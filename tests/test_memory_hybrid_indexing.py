from __future__ import annotations

import asyncio
import math
import os
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import replace as dc_replace
from pathlib import Path

import pytest

from memoli_agent.agent.memory.cards import (
    CardBuilder,
    CardGenerationError,
    CardTextGenerator,
)
from memoli_agent.agent.memory.episodic import TrajectorySegmentIndexer
from memoli_agent.agent.memory.hybrid import (
    HybridMemoryRetriever,
    KeywordSearchLane,
    MetadataSearchLane,
    SemanticSearchLane,
)
from memoli_agent.agent.memory.models import (
    CardDraft,
    CardDraftStatement,
    CardProjectionKey,
    EvidenceRef,
    MemoryMutation,
    MemoryQuery,
    MemoryScope,
)
from memoli_agent.agent.memory.semantic import (
    DeterministicEmbedder,
    EmbeddingError,
    MemoryIndexWorker,
    OpenAICompatibleEmbedder,
    cosine_similarity,
    decode_vector,
    encode_vector,
)
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore
from memoli_agent.agent.trajectory import (
    NewTrajectoryEvent,
    SpanKind,
    SpanProjection,
    SQLiteTrajectoryStore,
    TraceProjection,
    TrajectoryError,
)
from memoli_agent.bootstrap.config import (
    AppConfig,
    MemoryConfig,
    MemoryEmbeddingConfig,
    load_config,
)
from memoli_agent.bootstrap.memory import build_memory_runtime


def _claim(
    content: str,
    *,
    status: str = "active",
    subject: str = "general",
    card_kind: str = "profile",
    scope: MemoryScope | None = None,
) -> MemoryMutation:
    return MemoryMutation(
        content,
        scope=scope or MemoryScope(),
        status=status,  # type: ignore[arg-type]
        subject=subject,
        card_kind=card_kind,
        evidence=(EvidenceRef("message", f"msg-{content}", content),),
    )


def test_vector_codec_validation_and_cosine() -> None:
    vector = (0.25, -0.5, 1.0)
    assert decode_vector(encode_vector(vector, 3), 3) == pytest.approx(vector)
    assert cosine_similarity(vector, vector) == pytest.approx(1.0)
    with pytest.raises(EmbeddingError):
        encode_vector((1.0, math.nan), 2)
    with pytest.raises(EmbeddingError):
        decode_vector(b"short", 3)


def test_index_worker_is_idempotent_and_versioned(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    item = store.append_claim(_claim("项目使用 SQLite 保存长期记忆"))
    embedder = DeterministicEmbedder(dimensions=8)
    worker = MemoryIndexWorker(store, embedder, batch_size=4)

    async def scenario() -> None:
        first = await worker.tick()
        assert (first.processed, first.succeeded, first.failed) == (1, 1, 0)
        assert (await worker.tick()).processed == 0
        ready = store.ready_semantic_rows(
            MemoryQuery("SQLite"),
            model=embedder.model,
            version=embedder.version,
            dimensions=embedder.dimensions,
            limit=10,
        )
        assert [row[0].item_id for row in ready] == [item.item_id]
        assert (
            store.ready_semantic_rows(
                MemoryQuery("SQLite"),
                model=embedder.model,
                version="future",
                dimensions=embedder.dimensions,
                limit=10,
            )
            == []
        )
        assert worker.rebuild("claim") == 1
        assert (await worker.tick()).succeeded == 1

    asyncio.run(scenario())


@dataclass(frozen=True)
class _FailingEmbedder:
    model: str = "failed"
    version: str = "1"
    dimensions: int = 4
    enabled: bool = True

    async def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        raise TimeoutError("secret provider response")


def test_index_failure_keeps_source_and_records_safe_retry(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    item = store.append_claim(_claim("即使向量失败也能关键词检索"))

    async def scenario() -> None:
        result = await MemoryIndexWorker(store, _FailingEmbedder()).tick()
        assert (result.processed, result.failed) == (1, 1)
        assert store.search(MemoryQuery("关键词检索")).items[0].item_id == item.item_id

    asyncio.run(scenario())
    row = store._connection.execute(  # noqa: SLF001
        "SELECT state, last_error FROM memory_index_jobs WHERE memory_id=?",
        (item.item_id,),
    ).fetchone()
    assert (row["state"], row["last_error"]) == ("retry", "TimeoutError")


def test_openai_embedder_requires_environment_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MEMOLI_TEST_EMBEDDING_KEY", raising=False)
    embedder = OpenAICompatibleEmbedder(
        model="embedding-test",
        api_key_env="MEMOLI_TEST_EMBEDDING_KEY",
        dimensions=4,
    )
    with pytest.raises(EmbeddingError, match="环境变量"):
        asyncio.run(embedder.embed(("text",)))
    assert "MEMOLI_TEST_EMBEDDING_KEY" not in os.environ


def test_hybrid_rrf_deduplicates_budgets_and_is_deterministic(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    first = store.append_claim(_claim("Python 项目使用清华源下载依赖"))
    store.append_claim(_claim("Python 代码保持中文注释"))
    store.create_card(
        title="开发偏好",
        content="Python 使用清华源",
        claim_relations=((first.item_id, "supports"),),
    )
    embedder = DeterministicEmbedder(dimensions=12)
    worker = MemoryIndexWorker(store, embedder, batch_size=10)
    retriever = HybridMemoryRetriever(
        store,
        KeywordSearchLane(store),
        MetadataSearchLane(store),
        SemanticSearchLane(store, embedder),
        candidate_limit=20,
    )

    async def scenario() -> None:
        await worker.tick()
        request = MemoryQuery(
            "Python 清华源",
            limit=2,
            card_limit=1,
            claim_limit=1,
            episode_limit=0,
            max_chars=100,
        )
        first_result = await retriever.query(request)
        second_result = await retriever.query(request)
        assert [item.item_id for item in first_result.items] == [
            item.item_id for item in second_result.items
        ]
        assert len({item.item_id for item in first_result.items}) == len(
            first_result.items
        )
        assert {item.item_type for item in first_result.items} == {"card", "claim"}
        assert "semantic" in first_result.active_lanes
        assert first_result.query_context_fields == ("query",)
        assert first_result.injected_chars <= 100
        assert sum(item.item_type == "claim" for item in first_result.items) == 1

    asyncio.run(scenario())


def test_hybrid_semantic_failure_and_spillover_are_bounded(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    item = store.append_claim(_claim("关键词通道保持可用"))
    retriever = HybridMemoryRetriever(
        store,
        KeywordSearchLane(store),
        MetadataSearchLane(store),
        SemanticSearchLane(store, _FailingEmbedder()),
    )

    async def scenario() -> None:
        result = await retriever.query(
            MemoryQuery(
                "关键词通道",
                limit=1,
                card_limit=0,
                claim_limit=0,
                episode_limit=0,
                spillover_order=("claim", "card", "episode"),
            )
        )
        assert [candidate.item_id for candidate in result.items] == [item.item_id]
        assert "semantic:error" in result.degraded_lanes
        assert result.lane_candidate_counts["semantic"] == 0
        empty = await retriever.query(MemoryQuery("", limit=1))
        assert empty.items == []

    asyncio.run(scenario())


def test_card_builder_governance_versions_and_freeze(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    active = store.append_claim(_claim("偏好简洁代码", subject="开发偏好"))
    store.append_claim(
        _claim("未经批准的推断", status="candidate", subject="开发偏好")
    )
    builder = CardBuilder(store)
    first = builder.tick()[0]
    assert first.status == "created"
    assert first.claim_ids == (active.item_id,)
    key = CardProjectionKey(MemoryScope(), "开发偏好", "profile")
    assert builder.build(key).status == "unchanged"

    store.append_claim(_claim("核心模块使用中文注释", subject="开发偏好"))
    revised = builder.tick()[0]
    assert revised.status == "revised"
    card = store.find_card_by_projection_key(key.value)
    assert card is not None and card["current_version"] == 2
    store.set_status("card", str(card["card_id"]), "frozen", "human")
    store.append_claim(_claim("新增偏好不应覆盖冻结卡片", subject="开发偏好"))
    assert builder.tick()[0].status == "frozen"
    frozen_card = store.find_card_by_projection_key(key.value)
    assert frozen_card is not None and frozen_card["current_version"] == 2


def test_card_builder_rejects_unsupported_generation(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    store.append_claim(_claim("只支持 SQLite", subject="架构"))

    class UnsupportedGenerator(CardTextGenerator):
        def generate(
            self, key: CardProjectionKey, claims: Sequence[tuple[str, str]]
        ) -> CardDraft:
            return CardDraft(
                key,
                "架构",
                (CardDraftStatement("项目使用外部向量数据库", (claims[0][0],)),),
            )

    builder = CardBuilder(store, generator=UnsupportedGenerator())
    with pytest.raises(CardGenerationError):
        builder.build(CardProjectionKey(MemoryScope(), "架构", "profile"))
    assert store.find_card_by_projection_key("user:default:架构:profile") is None


def test_episode_complete_projection_context_idempotence_and_rebuild(
    tmp_path: Path,
) -> None:
    trajectory = SQLiteTrajectoryStore(
        tmp_path / "trajectory.db",
        payload_directory=tmp_path / "payloads",
        capture_content="full-local",
    )
    memory = SQLiteMemoryStore(tmp_path / "memory.db")

    async def scenario() -> None:
        await trajectory.start()
        trace = TraceProjection("a" * 32, "session-a", "2026-01-01T00:00:00+00:00")
        span = SpanProjection(
            "b" * 16,
            trace.trace_id,
            None,
            SpanKind.AGENT,
            "agent-turn",
            trace.started_at,
            input_data={"messages": [{"role": "user", "content": "继续实现记忆"}]},
        )
        await trajectory.record(
            NewTrajectoryEvent(
                trace.trace_id,
                "trace_started",
                trace=trace,
                span=span,
            )
        )
        indexer = TrajectorySegmentIndexer(trajectory, memory)
        assert await indexer.project_trace(trace.trace_id, MemoryScope()) == ()
        ended = dc_replace(
            trace,
            ended_at="2026-01-01T00:01:00+00:00",
            status="completed",
            termination_reason="completed",
            final_output="记忆功能已完成",
        )
        finished_span = dc_replace(
            span,
            ended_at=ended.ended_at,
            status="completed",
            output_data={"content": "记忆功能已完成"},
        )
        await trajectory.record(
            NewTrajectoryEvent(
                trace.trace_id,
                "trace_finished",
                {"termination_reason": "completed"},
                span_id=span.span_id,
                trace=ended,
                span=finished_span,
            )
        )
        segments = await indexer.project_trace(
            trace.trace_id,
            MemoryScope(),
            objective="构建长期助手",
            current_step="完成 Episode",
        )
        assert len(segments) == 1
        assert "工作目标: 构建长期助手" in segments[0].search_text
        assert "工作目标" not in await indexer.resolve(segments[0])
        repeated = await indexer.project_trace(
            trace.trace_id,
            MemoryScope(),
            objective="构建长期助手",
            current_step="完成 Episode",
        )
        assert [item.segment_id for item in repeated] == [segments[0].segment_id]
        assert memory.search(MemoryQuery("构建长期助手")).items

        upgraded = TrajectorySegmentIndexer(
            trajectory, memory, segmenter_version="3"
        )
        rebuilt = await upgraded.project_trace(trace.trace_id, MemoryScope())
        assert rebuilt[0].segment_id != segments[0].segment_id

        split = TrajectorySegmentIndexer(
            trajectory,
            memory,
            segmenter_version="split",
            max_segment_chars=8,
        )
        assert len(await split.project_trace(trace.trace_id, MemoryScope())) > 1
        await trajectory.close()
        with pytest.raises(TrajectoryError):
            await split.project_trace(trace.trace_id, MemoryScope())

    asyncio.run(scenario())


def test_v1_database_migrates_and_backfills_without_fact_changes(
    tmp_path: Path,
) -> None:
    database = tmp_path / "v1.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE claims (
          claim_id TEXT PRIMARY KEY, content TEXT NOT NULL,
          normalized_content TEXT NOT NULL, content_hash TEXT NOT NULL UNIQUE,
          source TEXT NOT NULL, explicitness TEXT NOT NULL,
          scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL,
          sensitivity TEXT NOT NULL, status TEXT NOT NULL,
          valid_from TEXT, valid_to TEXT, created_at TEXT NOT NULL
        );
        CREATE TABLE cards (
          card_id TEXT PRIMARY KEY, scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL,
          status TEXT NOT NULL, sensitivity TEXT NOT NULL,
          current_version INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE trajectory_segments (
          segment_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL,
          start_event_id INTEGER NOT NULL, end_event_id INTEGER NOT NULL,
          content TEXT NOT NULL, scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL,
          occurred_at TEXT NOT NULL, UNIQUE(trace_id, start_event_id, end_event_id)
        );
        PRAGMA user_version = 1;
        """
    )
    connection.commit()
    connection.close()
    store = SQLiteMemoryStore(database)
    assert store.index_diagnostics()["schema_version"] == 3
    version = store._connection.execute("PRAGMA user_version").fetchone()[0]  # noqa: SLF001
    assert version == 3


def test_nested_memory_config_parsing(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
        [memory]
        engine = "sqlite"
        card_builder_enabled = false
        episode_projection_enabled = true

        [memory.embedding]
        enabled = true
        provider = "deterministic"
        model = "local-test"
        dimensions = 8

        [memory.hybrid]
        rrf_k = 30
        card_limit = 1
        claim_limit = 3
        episode_limit = 1
        spillover_order = ["claim", "card", "episode"]
        """,
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.memory.embedding.model == "local-test"
    assert config.memory.embedding.dimensions == 8
    assert config.memory.hybrid.rrf_k == 30
    assert config.memory.card_builder_enabled is False


def test_bootstrap_disabled_enabled_and_rebuild_end_to_end(tmp_path: Path) -> None:
    disabled = build_memory_runtime(
        AppConfig(
            memory=MemoryConfig(
                database=str(tmp_path / "disabled.db"),
                path=str(tmp_path / "legacy-disabled"),
                legacy_import="off",
                embedding=MemoryEmbeddingConfig(enabled=False),
            )
        )
    )
    assert disabled is not None and disabled.index_worker is None

    enabled = build_memory_runtime(
        AppConfig(
            memory=MemoryConfig(
                database=str(tmp_path / "enabled.db"),
                path=str(tmp_path / "legacy-enabled"),
                legacy_import="off",
                embedding=MemoryEmbeddingConfig(
                    enabled=True,
                    provider="deterministic",
                    model="local-test",
                    dimensions=8,
                ),
            )
        )
    )
    assert enabled is not None and enabled.index_worker is not None

    async def scenario() -> None:
        disabled_item = await disabled.mutate(_claim("关闭向量仍可关键词召回"))
        disabled_result = await disabled.pre_recall(user_message="关键词召回")
        assert disabled_item.item_id in {
            item.item_id for item in disabled_result.items
        }
        assert disabled.diagnostics()["semantic_entries"] == 0

        enabled_item = await enabled.mutate(_claim("启用确定性语义索引"))
        await enabled.maintenance_tick()
        assert enabled.diagnostics()["semantic_entries"] >= 1
        result = await enabled.pre_recall(user_message="语义索引")
        assert enabled_item.item_id in {item.item_id for item in result.items}
        assert "semantic" in result.active_lanes
        before = enabled.store.list_items(MemoryScope())
        assert enabled.index_worker.rebuild() >= 1
        await enabled.maintenance_tick()
        after = enabled.store.list_items(MemoryScope())
        assert [item.item_id for item in before] == [item.item_id for item in after]

    asyncio.run(scenario())
    disabled.close()
    enabled.close()
