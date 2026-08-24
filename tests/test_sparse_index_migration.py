"""Sparse 索引与 schema 6→7 迁移测试：空库初始化、升级与回填、重复升级、
迁移失败回滚、显式重建、stable ID 保持与 trigram 不可用降级。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from memoli_agent.agent.memory.models import (
    CardDraftStatement,
    EvidenceRef,
    MemoryMutation,
    MemoryQuery,
    MemoryScope,
)
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore


def _claim(content: str) -> MemoryMutation:
    return MemoryMutation(
        content,
        scope=MemoryScope(),
        status="active",
        subject="general",
        card_kind="profile",
        evidence=(EvidenceRef("message", f"msg-{content}", content),),
    )


def _downgrade_to_v6(database: Path) -> None:
    """把 v7 数据库降级回 v6 派生索引状态：删除 sparse 表并重建旧 claim/card_search。"""

    con = sqlite3.connect(database)
    con.execute("PRAGMA user_version = 6")
    con.execute("DROP TABLE IF EXISTS memory_search")
    con.execute("DROP TABLE IF EXISTS memory_index_meta")
    con.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS claim_search USING fts5("
        "claim_id UNINDEXED, content, search_text, tokenize='unicode61')"
    )
    con.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS card_search USING fts5("
        "card_id UNINDEXED, title, content, search_text, tokenize='unicode61')"
    )
    con.commit()
    con.close()


def _seed_authority(store: SQLiteMemoryStore) -> tuple[str, str, str]:
    """写入一条 Claim、一张带 statement 的 Card 与一段 Episode，返回各自 stable ID。"""

    claim = store.append_claim(_claim("项目使用清华源下载依赖"))
    card = store.create_card(
        title="开发偏好",
        content="Python 使用清华源",
        statements=(CardDraftStatement("项目使用清华源", (claim.item_id,)),),
    )
    statement_id = store._connection.execute(  # noqa: SLF001
        "SELECT statement_id FROM card_statements WHERE card_id=?", (card.card_id,)
    ).fetchone()[0]
    store.add_trajectory_segment(
        segment_id="seg_one",
        trace_id="trace_one",
        start_event_id=0,
        end_event_id=1,
        content="episode 使用清华镜像源",
        scope=MemoryScope(),
        occurred_at="2026-01-01T00:00:00+00:00",
    )
    return claim.item_id, str(statement_id), "seg_one"


def test_empty_db_initializes_schema_7_with_sparse_index(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "empty.db")
    assert store.index_diagnostics()["schema_version"] == 7
    assert store.fts_available is True
    meta = store._connection.execute(  # noqa: SLF001
        "SELECT value FROM memory_index_meta WHERE key='sparse_format'"
    ).fetchone()
    assert meta is not None and meta[0] == "trigram-v1"
    # 统一 sparse 表存在，旧派生搜索表不存在。
    names = {
        row[0]
        for row in store._connection.execute(  # noqa: SLF001
            "SELECT name FROM sqlite_master WHERE name IN "
            "('memory_search','claim_search','card_search')"
        )
    }
    assert names == {"memory_search"}
    store.close()


def test_schema_6_upgrades_and_backfills_preserving_stable_ids(tmp_path: Path) -> None:
    database = tmp_path / "v6.db"
    store = SQLiteMemoryStore(database)
    claim_id, statement_id, segment_id = _seed_authority(store)
    store.close()
    _downgrade_to_v6(database)

    migrated = SQLiteMemoryStore(database)
    assert migrated._connection.execute(  # noqa: SLF001
        "PRAGMA user_version"
    ).fetchone()[0] == 7
    # stable identity 集合从权威表回填，ID 不变。
    claim_rows = migrated._connection.execute(  # noqa: SLF001
        "SELECT memory_id FROM memory_search WHERE memory_type='claim'"
    ).fetchall()
    assert [r[0] for r in claim_rows] == [claim_id]
    card_rows = migrated._connection.execute(  # noqa: SLF001
        "SELECT memory_id FROM memory_search WHERE memory_type='card'"
    ).fetchall()
    assert [r[0] for r in card_rows] == [statement_id]
    episode_rows = migrated._connection.execute(  # noqa: SLF001
        "SELECT memory_id FROM memory_search WHERE memory_type='episode'"
    ).fetchall()
    assert [r[0] for r in episode_rows] == [segment_id]
    # 旧派生搜索表仅在迁移成功后移除。
    names = {
        row[0]
        for row in migrated._connection.execute(  # noqa: SLF001
            "SELECT name FROM sqlite_master WHERE name IN "
            "('claim_search','card_search')"
        )
    }
    assert names == set()
    migrated.close()


def test_repeat_upgrade_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "repeat.db"
    store = SQLiteMemoryStore(database)
    _seed_authority(store)
    before = store._connection.execute(  # noqa: SLF001
        "SELECT memory_type, memory_id FROM memory_search ORDER BY 1, 2"
    ).fetchall()
    store.close()

    # 再次打开已为 v7 的库：不应报错、不应改写 stable identity 集合。
    reopened = SQLiteMemoryStore(database)
    assert reopened._connection.execute(  # noqa: SLF001
        "PRAGMA user_version"
    ).fetchone()[0] == 7
    after = reopened._connection.execute(  # noqa: SLF001
        "SELECT memory_type, memory_id FROM memory_search ORDER BY 1, 2"
    ).fetchall()
    assert after == before
    reopened.close()


def test_migration_failure_rolls_back_keeping_authority_and_old_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "fail.db"
    store = SQLiteMemoryStore(database)
    claim_id, _statement_id, _segment_id = _seed_authority(store)
    store.close()
    _downgrade_to_v6(database)

    def fail_backfill(self: SQLiteMemoryStore) -> None:
        raise RuntimeError("injected backfill failure")

    monkeypatch.setattr(SQLiteMemoryStore, "_backfill_memory_search", fail_backfill)
    with pytest.raises(RuntimeError, match="injected backfill failure"):
        SQLiteMemoryStore(database)

    con = sqlite3.connect(database)
    # 失败回滚：版本不发布、权威记忆与旧派生表保留、sparse 表未发布。
    assert con.execute("PRAGMA user_version").fetchone()[0] == 6
    assert con.execute(
        "SELECT COUNT(*) FROM claims WHERE claim_id=?", (claim_id,)
    ).fetchone()[0] == 1
    assert con.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='memory_search'"
    ).fetchone()[0] == 0
    assert con.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='claim_search'"
    ).fetchone()[0] == 1
    con.close()

    monkeypatch.undo()
    # 恢复后可正常迁移。
    recovered = SQLiteMemoryStore(database)
    assert recovered._connection.execute(  # noqa: SLF001
        "PRAGMA user_version"
    ).fetchone()[0] == 7
    recovered.close()


def test_explicit_rebuild_regenerates_sparse_index_without_governance(
    tmp_path: Path,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "rebuild.db")
    claim_id, statement_id, segment_id = _seed_authority(store)
    # 记录治理任务与权威记录数，重建不得触发治理或新增事实。
    jobs_before = store._connection.execute(  # noqa: SLF001
        "SELECT COUNT(*) FROM memory_index_jobs"
    ).fetchone()[0]
    claims_before = store._connection.execute(  # noqa: SLF001
        "SELECT COUNT(*) FROM claims"
    ).fetchone()[0]

    store.rebuild_sparse_index()

    ids = {
        (r[0], r[1])
        for r in store._connection.execute(  # noqa: SLF001
            "SELECT memory_type, memory_id FROM memory_search"
        )
    }
    assert {("claim", claim_id), ("card", statement_id), ("episode", segment_id)} <= ids
    jobs_after = store._connection.execute(  # noqa: SLF001
        "SELECT COUNT(*) FROM memory_index_jobs"
    ).fetchone()[0]
    claims_after = store._connection.execute(  # noqa: SLF001
        "SELECT COUNT(*) FROM claims"
    ).fetchone()[0]
    assert jobs_after == jobs_before
    assert claims_after == claims_before
    store.close()


def test_trigram_unavailable_degrades_fts_but_pattern_still_recalls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(SQLiteMemoryStore, "_probe_trigram_bm25", lambda self: False)
    store = SQLiteMemoryStore(tmp_path / "nofts.db")
    # 数据库仍可打开，FTS 标记 unavailable，sparse 表未创建。
    assert store.fts_available is False
    assert store._connection.execute(  # noqa: SLF001
        "SELECT COUNT(*) FROM sqlite_master WHERE name='memory_search'"
    ).fetchone()[0] == 0

    store.append_claim(_claim("项目使用清华源下载依赖"))
    result = store.search(
        MemoryQuery(
            "清华源",
            limit=2,
            claim_limit=2,
            card_limit=0,
            episode_limit=0,
        )
    )
    # FTS 不可用时 Pattern lane 继续工作，返回相关 Claim。
    assert any(item.item_type == "claim" for item in result.items)
    assert result.degraded is True
    # trigram 不可用时显式重建应明确报错而非以空索引替代。
    with pytest.raises(RuntimeError, match="trigram"):
        store.rebuild_sparse_index()
    store.close()
