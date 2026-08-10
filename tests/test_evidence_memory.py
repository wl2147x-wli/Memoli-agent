from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import memoli_agent.agent.memory.sqlite_store as sqlite_store_module
from memoli_agent.agent.memory.consolidator import (
    ConsolidationInput,
    MemoryConsolidator,
)
from memoli_agent.agent.memory.episodic import TrajectorySegmentIndexer
from memoli_agent.agent.memory.migration import LegacyMemoryMigrator
from memoli_agent.agent.memory.models import (
    ConsolidationCandidate,
    EvidenceRef,
    MemoryMutation,
    MemoryQuery,
    MemoryScope,
)
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore
from memoli_agent.agent.tools.builtin import MemoryManageTool
from memoli_agent.agent.tools.execution import ToolExecutionContext, tool_context
from memoli_agent.agent.trajectory import (
    NewTrajectoryEvent,
    SpanKind,
    SpanProjection,
    SQLiteTrajectoryStore,
    TraceProjection,
)
from memoli_agent.agent.working.models import CheckpointPatch
from memoli_agent.agent.working.repository import (
    RevisionConflictError,
    WorkingStateRepository,
)
from memoli_agent.bootstrap.config import MemoryConfig, WorkingMemoryConfig
from memoli_agent.bootstrap.memory import build_memory_runtime


def explicit_memory(content: str, **kwargs: object) -> MemoryMutation:
    return MemoryMutation(
        content=content,
        evidence=(EvidenceRef("message", "msg-1", content),),
        **kwargs,  # type: ignore[arg-type]
    )


def test_working_repository_revision_stale_and_restore(tmp_path: Path) -> None:
    repository = WorkingStateRepository(tmp_path / "working.db")
    first = repository.patch("task-a", CheckpointPatch(key_info="读取配置"))
    assert first.revision == 1
    with pytest.raises(RevisionConflictError):
        repository.patch(
            "task-a", CheckpointPatch(expected_revision=0, key_info="过期覆盖")
        )
    repository.patch("task-b", CheckpointPatch(key_info="独立任务"))
    repository.mark_stale_except("task-b")
    assert repository.get("task-a").stale is True  # type: ignore[union-attr]
    restored = repository.restore("task-a")
    assert restored is not None and restored.stale is False


def test_memory_config_validation_and_independent_disable(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        MemoryConfig(recall_limit=0)
    with pytest.raises(ValueError):
        WorkingMemoryConfig(max_chars=0)
    from memoli_agent.bootstrap.config import AppConfig

    config = AppConfig(memory=MemoryConfig(enabled=False))
    assert build_memory_runtime(config) is None
    repository = WorkingStateRepository(tmp_path / "working.db")
    assert repository.patch("task", CheckpointPatch(key_info="仍可工作")).revision == 1


def test_sqlite_claim_card_filters_and_deletion(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    with pytest.raises(PermissionError):
        store.append_claim(MemoryMutation("模型自己推断的偏好"))
    item = store.append_claim(explicit_memory("用户喜欢清华源下载依赖"))
    store.append_claim(
        explicit_memory(
            "过期的旧偏好",
            valid_to=datetime.now(UTC) - timedelta(days=1),
        )
    )
    card = store.create_card(
        title="开发偏好",
        content="安装 Python 包时使用清华源",
        claim_relations=((item.item_id, "supports"),),
    )
    store.revise_card(
        card.card_id,
        title="开发偏好",
        content="Python 依赖优先使用清华源",
        actor="human",
    )
    result = store.search(MemoryQuery("清华源", limit=5))
    assert {hit.item_type for hit in result.items} == {"card", "claim"}
    assert all(hit.recall_reason for hit in result.items)
    store.set_status("claim", item.item_id, "deleted", "human")
    recalled = store.search(MemoryQuery("用户喜欢清华源下载依赖"))
    assert all(hit.item_id != item.item_id for hit in recalled.items)


def test_soft_deleted_claim_can_be_remembered_again_per_scope(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    first = store.append_claim(explicit_memory("偏好中文注释"))
    store.set_status("claim", first.item_id, "deleted", "human")
    second = store.append_claim(explicit_memory("偏好中文注释"))
    other = store.append_claim(
        explicit_memory(
            "偏好中文注释", scope=MemoryScope("project", "another")
        )
    )

    assert len({first.item_id, second.item_id, other.item_id}) == 3
    assert store.find_exact_claim("偏好中文注释", MemoryScope()) == second.item_id
    assert (
        store.find_exact_claim("偏好中文注释", MemoryScope("project", "another"))
        == other.item_id
    )


def test_memory_store_enables_foreign_keys_and_is_idempotently_closeable(
    tmp_path: Path,
) -> None:
    with SQLiteMemoryStore(tmp_path / "memory.db") as store:
        assert store._connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert store._connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    store.close()


def test_two_connections_converge_on_one_live_claim(tmp_path: Path) -> None:
    database = tmp_path / "memory.db"
    first_store = SQLiteMemoryStore(database)
    second_store = SQLiteMemoryStore(database)
    first = first_store.append_claim(explicit_memory("双连接写入"))
    second = second_store.append_claim(explicit_memory("双连接写入"))
    assert first.item_id == second.item_id
    assert len(first_store.list_items(MemoryScope())) == 1


def test_approved_claim_is_current_and_export_includes_cards(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    claim = store.append_claim(explicit_memory("使用 SQLite", status="approved"))
    store.create_card(
        title="技术偏好",
        content="使用 SQLite",
        claim_relations=((claim.item_id, "supports"),),
    )
    recalled = store.search(MemoryQuery("SQLite"))
    approved = next(item for item in recalled.items if item.item_id == claim.item_id)
    exported = store.export_items(MemoryScope(), max_sensitivity="private")

    assert approved.current is True
    assert {item["type"] for item in exported} == {"claim", "card"}
    assert all("scope" in item and "created_at" in item for item in exported)


def test_frozen_memory_rejects_automated_mutation(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    claim = store.append_claim(explicit_memory("固定偏好"))
    store.set_status("claim", claim.item_id, "frozen", "automation")
    with pytest.raises(PermissionError):
        store.set_status("claim", claim.item_id, "deleted", "automation")
    store.set_status("claim", claim.item_id, "deleted", "user:msg-1")


def test_unknown_memory_schema_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "unknown.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA user_version = 99")
    connection.close()
    with pytest.raises(RuntimeError, match="schema"):
        SQLiteMemoryStore(database)


def _downgrade_fixture_to_v2(database: Path) -> None:
    """把测试库的 Claim 表改成 v2 的全局哈希唯一结构。"""

    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("CREATE TABLE claims_v2 AS SELECT * FROM claims")
    connection.execute(
        "CREATE UNIQUE INDEX claims_v2_id ON claims_v2(claim_id)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX claims_v2_content_hash ON claims_v2(content_hash)"
    )
    connection.execute("DROP TABLE claims")
    connection.execute("ALTER TABLE claims_v2 RENAME TO claims")
    connection.execute("PRAGMA user_version = 2")
    connection.commit()
    connection.close()


def test_v2_migration_removes_global_hash_uniqueness(tmp_path: Path) -> None:
    database = tmp_path / "v2.db"
    seed = SQLiteMemoryStore(database)
    seed.append_claim(explicit_memory("跨 scope 内容"))
    seed.close()
    _downgrade_fixture_to_v2(database)

    migrated = SQLiteMemoryStore(database)
    assert migrated._connection.execute("PRAGMA user_version").fetchone()[0] == 3
    other = migrated.append_claim(
        explicit_memory("跨 scope 内容", scope=MemoryScope("project", "other"))
    )
    assert other.item_id


def test_v2_migration_failure_rolls_back_and_can_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "interrupted-v2.db"
    seed = SQLiteMemoryStore(database)
    seed.append_claim(explicit_memory("迁移中断恢复"))
    seed.close()
    _downgrade_fixture_to_v2(database)

    original = sqlite_store_module._execute_sql_script

    def fail_after_first_statement(
        connection: sqlite3.Connection, script: str
    ) -> None:
        if "CREATE TABLE claims_v3" in script:
            connection.execute(
                "CREATE TABLE claims_v3 AS SELECT * FROM claims WHERE 0"
            )
            raise RuntimeError("injected migration failure")
        original(connection, script)

    monkeypatch.setattr(
        sqlite_store_module, "_execute_sql_script", fail_after_first_statement
    )
    with pytest.raises(RuntimeError, match="injected migration failure"):
        SQLiteMemoryStore(database)

    connection = sqlite3.connect(database)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='claims_v3'"
        ).fetchone()[0]
        == 0
    )
    connection.close()

    monkeypatch.setattr(sqlite_store_module, "_execute_sql_script", original)
    recovered = SQLiteMemoryStore(database)
    assert recovered._connection.execute("PRAGMA user_version").fetchone()[0] == 3
    assert recovered.find_exact_claim("迁移中断恢复", MemoryScope())


def test_episodic_index_resolves_original_trajectory_message(tmp_path: Path) -> None:
    trajectory = SQLiteTrajectoryStore(
        tmp_path / "trajectory.db",
        payload_directory=tmp_path / "payloads",
        capture_content="full-local",
    )
    memory = SQLiteMemoryStore(tmp_path / "memory.db")

    async def scenario() -> None:
        await trajectory.start()
        trace = TraceProjection("0" * 32, "session", "2026-01-01T00:00:00+00:00")
        span = SpanProjection(
            "1" * 16,
            trace.trace_id,
            None,
            SpanKind.AGENT,
            "agent-turn",
            trace.started_at,
            input_data={
                "messages": [{"role": "user", "content": "原始消息：请使用中文注释"}]
            },
        )
        await trajectory.record(
            NewTrajectoryEvent(
                trace.trace_id,
                "trace_started",
                {"session_id": "session"},
                span_id=span.span_id,
                trace=trace,
                span=span,
            )
        )
        indexer = TrajectorySegmentIndexer(trajectory, memory)
        segments = await indexer.rebuild_trace(trace.trace_id, MemoryScope())
        assert len(segments) == 1
        assert await indexer.resolve(segments[0]) == "原始消息：请使用中文注释"
        assert memory.search(MemoryQuery("中文注释")).items[0].item_type == "episode"
        await trajectory.close()

    asyncio.run(scenario())


def test_legacy_preview_backup_idempotence_and_rollback(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "MEMORY.md").write_text(
        "# 记忆\n- 喜欢简洁代码\n- 使用中文注释\n", encoding="utf-8"
    )
    (legacy / "HISTORY.md").write_text("不应提升\n", encoding="utf-8")
    (legacy / "RECENT_CONTEXT.md").write_text("也不应提升\n", encoding="utf-8")

    failed_store = SQLiteMemoryStore(tmp_path / "failed.db")
    failed = LegacyMemoryMigrator(legacy, failed_store)
    with pytest.raises(RuntimeError):
        failed.import_memory(fail_after=1)
    assert failed_store.list_items(MemoryScope()) == []

    store = SQLiteMemoryStore(tmp_path / "memory.db")
    migrator = LegacyMemoryMigrator(legacy, store)
    assert migrator.preview().parseable == 2
    first = migrator.import_memory()
    second = migrator.import_memory()
    assert (first.imported, second.imported, second.duplicate) == (2, 0, 2)
    backup = legacy / "legacy-backups" / first.manifest_hash[:16]
    assert all(
        (backup / name).exists()
        for name in ("MEMORY.md", "HISTORY.md", "RECENT_CONTEXT.md")
    )


def test_memory_manage_requires_current_user_basis(tmp_path: Path) -> None:
    from memoli_agent.agent.memory.retriever import SQLiteMemoryRetriever
    from memoli_agent.agent.memory.runtime import MemoryRuntime

    store = SQLiteMemoryStore(tmp_path / "memory.db")
    tool = MemoryManageTool(MemoryRuntime(store, SQLiteMemoryRetriever(store)))
    context = ToolExecutionContext(
        "trace", "session", "call", "msg-1", "请记住我喜欢中文注释"
    )

    async def scenario() -> None:
        with tool_context(context):
            rejected = await tool.run(
                {
                    "action": "remember",
                    "content": "喜欢中文注释",
                    "basis_quote": "不存在",
                }
            )
            assert rejected.success is False
            accepted = await tool.run(
                {
                    "action": "remember",
                    "content": "喜欢中文注释",
                    "basis_quote": "喜欢中文注释",
                }
            )
            assert accepted.success is True
            item_id = json.loads(accepted.content)["id"]
            frozen = await tool.run(
                {"action": "freeze", "entity_type": "claim", "entity_id": item_id}
            )
            assert frozen.success is True
            exported = await tool.run({"action": "export"})
            assert item_id in exported.content
            forgotten = await tool.run(
                {"action": "forget", "entity_type": "claim", "entity_id": item_id}
            )
            assert forgotten.success is True
            listed = await tool.run({"action": "list"})
            assert item_id not in listed.content

    asyncio.run(scenario())


def test_consolidation_is_candidate_only_and_idempotent(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")

    class Extractor:
        def extract(self, segment: str) -> list[ConsolidationCandidate]:
            return [
                ConsolidationCandidate(
                    content="用户偏好简洁代码",
                    source="offline",
                    scope=MemoryScope(),
                    evidence=(EvidenceRef("message", "msg-1", segment),),
                )
            ]

    consolidator = MemoryConsolidator(store, Extractor())
    input_data = ConsolidationInput("trace-1", "trace-2", ("我喜欢简洁代码",))
    first = consolidator.run(input_data)
    second = consolidator.run(input_data)
    assert first.status == "completed"
    assert second.status == "already-completed"
    assert (
        store.search(MemoryQuery("简洁代码", statuses=("candidate",))).items[0].status
        == "candidate"
    )


def test_consolidation_extraction_failure_writes_no_partial_candidates(
    tmp_path: Path,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")

    class Extractor:
        def extract(self, segment: str) -> list[ConsolidationCandidate]:
            if segment == "broken":
                raise RuntimeError("expected")
            return [
                ConsolidationCandidate(
                    "候选偏好",
                    "trace",
                    MemoryScope(),
                    (EvidenceRef("message", "msg-1"),),
                )
            ]

    with pytest.raises(RuntimeError):
        MemoryConsolidator(store, Extractor()).run(
            ConsolidationInput("a", "b", ("valid", "broken"), "failure")
        )
    assert store.list_items(MemoryScope()) == []


def test_wildcard_request_scope_matches_all_source_ids(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    store.append_claim(
        explicit_memory("项目甲使用 SQLite", scope=MemoryScope("project", "a"))
    )
    store.append_claim(
        explicit_memory("项目乙使用 SQLite", scope=MemoryScope("project", "b"))
    )
    result = store.search(
        MemoryQuery("SQLite", scope=MemoryScope("project", "*"), item_types=("claim",))
    )
    assert len(result.items) == 2
