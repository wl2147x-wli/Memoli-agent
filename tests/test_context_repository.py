from __future__ import annotations

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from memoli_agent.agent.context_management import (
    ContextArchive,
    ContextSnapshot,
    ContextStateError,
    FrozenToolPreview,
    InMemoryContextStateRepository,
    OutboxEvent,
    SQLiteContextStateRepository,
    ToolDisclosure,
)


def _make_repo(
    tmp_path: Path, persistent: bool
) -> InMemoryContextStateRepository | SQLiteContextStateRepository:
    """§6.3 测试参数化：内存版与持久版对等覆盖同一冲突/幂等合同。"""
    return (
        SQLiteContextStateRepository(tmp_path / "context.db")
        if persistent
        else InMemoryContextStateRepository()
    )


def _active_archive(
    archive_id: str,
    *,
    content: str,
    content_hash: str,
    source_refs: tuple[str, ...],
    coverage_hash: str = "",
    session_key: str = "s",
    epoch: int = 0,
) -> ContextArchive:
    """构造 generation=0 占位的活动 archive——generation 由 ``commit_archive``
    事务内按 (session,epoch) max+1 分配，调用方不预填。"""
    return ContextArchive(
        archive_id,
        session_key,
        0,
        content,
        content_hash,
        source_refs,
        epoch=epoch,
        coverage_hash=coverage_hash,
    )


def _snapshot(session_key: str = "s") -> ContextSnapshot:
    return ContextSnapshot(
        session_key=session_key,
        session_instance_id="instance",
        layout_version=1,
        system_prompt="system",
        skill_catalog="skills",
        tool_schemas_json="[]",
        system_prompt_hash="a",
        skill_catalog_hash="b",
        tool_schema_hash="c",
        stable_prefix_hash="d",
        created_at="now",
    )


def test_v4_repository_migrates_tool_disclosure_table(tmp_path: Path) -> None:
    database = tmp_path / "v4.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE schema_info "
        "(component TEXT PRIMARY KEY, version INTEGER NOT NULL)"
    )
    connection.execute("INSERT INTO schema_info VALUES ('context-state', 4)")
    connection.commit()
    connection.close()

    repo = SQLiteContextStateRepository(database)
    repo.close()

    connection = sqlite3.connect(database)
    version = connection.execute(
        "SELECT version FROM schema_info WHERE component='context-state'"
    ).fetchone()
    table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tool_disclosures'"
    ).fetchone()
    connection.close()
    assert version == (5,)
    assert table == ("tool_disclosures",)


@pytest.mark.parametrize("persistent", [False, True])
def test_repository_round_trip(tmp_path: Path, persistent: bool) -> None:
    repo = (
        SQLiteContextStateRepository(tmp_path / "context.db")
        if persistent
        else InMemoryContextStateRepository()
    )
    snapshot = _snapshot()
    archive = ContextArchive("a1", "s", 1, "summary", "hash", ("source:1",), 3)
    preview = FrozenToolPreview("p1", "s", "call", "tool", "hash", 99, 10, "x", "ref")
    repo.save_snapshot(snapshot)
    repo.save_snapshot(replace(snapshot, system_prompt="must-not-overwrite"))
    repo.append_archive(archive)
    repo.append_archive(archive)
    repo.save_preview(preview)
    disclosure = ToolDisclosure(
        "s",
        2,
        "deferred",
        "{}",
        hashlib.sha256(b"{}").hexdigest(),
        "call-search",
        "now",
    )
    committed_disclosure = repo.save_tool_disclosure(disclosure)
    assert repo.save_tool_disclosure(disclosure) == committed_disclosure
    repo.set_compaction_failures("s", 2)
    assert repo.get_snapshot("s") == snapshot
    assert repo.list_archives("s") == (archive,)
    assert repo.get_preview("p1") == preview
    assert repo.get_compaction_failures("s") == 2
    assert repo.list_tool_disclosures("s", 2) == (committed_disclosure,)
    assert repo.list_tool_disclosures("other", 2) == ()
    repo.close()


@pytest.mark.parametrize("persistent", [False, True])
def test_clear_epoch_previews_marks_old_invisible(
    tmp_path: Path, persistent: bool
) -> None:
    """§7.4 clear_epoch_previews 把早于 before_epoch 的派生预览索引标记不可见。

    - 旧 epoch 预览经 get_preview_by_ref 不再返回（避免注入新 epoch 上下文）；
    - 当前 epoch 预览保持可见；
    - get_preview(id) 仍可取回不可见预览（审计/可重建派生索引，未删行）；
    - 清理幂等（已不可见的预览不重复计数）。
    """
    repo = _make_repo(tmp_path, persistent)
    old = FrozenToolPreview(
        "p-old", "s", "call-old", "tool", "chash", 99, 10, "prev", "ref", epoch=0
    )
    current = FrozenToolPreview(
        "p-cur", "s", "call-cur", "tool", "chash2", 99, 10, "prev2", "ref2", epoch=2
    )
    repo.save_preview(old)
    repo.save_preview(current)
    # 推进到 epoch=2：清理早于 2 的可见派生索引
    assert repo.clear_epoch_previews("s", before_epoch=2) == 1
    # 旧 epoch 预览不可见 → ref 查不到
    assert repo.get_preview_by_ref("s", 0, "call-old") is None
    # 当前 epoch 预览仍可见
    assert repo.get_preview_by_ref("s", 2, "call-cur") == current
    # 审计：不可见预览仍可按 id 取回（行未删）
    assert repo.get_preview("p-old") == old
    # 幂等：再次清理早于 2 的可见预览，计数 0
    assert repo.clear_epoch_previews("s", before_epoch=2) == 0
    repo.close()


@pytest.mark.parametrize("persistent", [False, True])
def test_reset_session_preserves_previews_for_audit(
    tmp_path: Path, persistent: bool
) -> None:
    """§7.4 reset_session 不再硬删 previews：派生预览索引保留以供审计/重建。

    reset_session 只重置可重建派生状态（快照/frontier/覆盖/outbox/失败计数/诊断）；
    预览的 epoch 可见性清理由 clear_epoch_previews 单独负责。/clear 不隐式删
    payload（原始 payload 由 trajectory 独立保留，design line 91）。
    """
    repo = _make_repo(tmp_path, persistent)
    preview = FrozenToolPreview(
        "p1", "s", "call", "tool", "hash", 99, 10, "x", "ref", epoch=1
    )
    repo.save_preview(preview)
    repo.reset_session("s")
    # 预览行保留（审计），reset_session 未删 previews
    assert repo.get_preview("p1") == preview
    # 且仍可见（reset_session 不负责可见性清理）
    assert repo.get_preview_by_ref("s", 1, "call") == preview
    repo.close()



def test_sqlite_repository_persists_and_is_thread_safe(tmp_path: Path) -> None:
    database = tmp_path / "context.db"
    repo = SQLiteContextStateRepository(database)
    repo.save_snapshot(_snapshot())
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda value: repo.set_compaction_failures("s", value), range(8)))
    repo.close()
    reopened = SQLiteContextStateRepository(database)
    assert reopened.get_snapshot("s") == _snapshot()
    assert 0 <= reopened.get_compaction_failures("s") <= 7
    reopened.close()


def test_memory_repository_does_not_claim_restart_recovery() -> None:
    first = InMemoryContextStateRepository()
    first.save_snapshot(_snapshot())
    second = InMemoryContextStateRepository()
    assert second.get_snapshot("s") is None


def test_sqlite_rejects_unknown_schema_without_rebuilding(tmp_path: Path) -> None:
    database = tmp_path / "context.db"
    connection = sqlite3.connect(database)
    connection.execute(
        "CREATE TABLE schema_info "
        "(component TEXT PRIMARY KEY, version INTEGER NOT NULL)"
    )
    connection.execute("INSERT INTO schema_info VALUES ('context-state', 999)")
    connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
    connection.execute("INSERT INTO sentinel VALUES ('preserve')")
    connection.commit()
    connection.close()

    with pytest.raises(ContextStateError, match="not supported"):
        SQLiteContextStateRepository(database)

    reopened = sqlite3.connect(database)
    assert reopened.execute("SELECT value FROM sentinel").fetchone() == ("preserve",)
    reopened.close()


def test_failed_write_rolls_back_and_other_databases_are_untouched(
    tmp_path: Path,
) -> None:
    context_database = tmp_path / "context.db"
    other_databases = [
        tmp_path / name
        for name in ("trajectories.db", "memory.db", "working-state.db", "skills.db")
    ]
    repo = SQLiteContextStateRepository(context_database)
    repo.save_snapshot(_snapshot())
    with pytest.raises(ContextStateError):
        repo._execute("INSERT INTO missing_table VALUES (?)", "failure")
    assert repo.get_snapshot("s") == _snapshot()
    assert all(not path.exists() for path in other_databases)
    repo.close()


@pytest.mark.parametrize("persistent", [False, True])
def test_snapshot_invalidation_is_first_reason_wins(
    tmp_path: Path, persistent: bool
) -> None:
    repo = (
        SQLiteContextStateRepository(tmp_path / "context.db")
        if persistent
        else InMemoryContextStateRepository()
    )
    repo.save_snapshot(_snapshot())
    repo.invalidate_snapshot("s", "tool-revoked:read")
    repo.invalidate_snapshot("s", "must-not-overwrite")
    current = repo.get_snapshot("s")
    assert current is not None
    assert current.invalidated_reason == "tool-revoked:read"
    repo.close()


@pytest.mark.parametrize("persistent", [False, True])
def test_snapshot_keyed_by_session_key_and_epoch(
    tmp_path: Path, persistent: bool
) -> None:
    """§7.1 快照主键迁移为 (session_key, conversation_epoch)：不同 epoch 取独立
    快照行，新 epoch 不复用旧 epoch 的冻结内容；失效按 epoch 隔离。"""
    repo = (
        SQLiteContextStateRepository(tmp_path / "context.db")
        if persistent
        else InMemoryContextStateRepository()
    )
    epoch0 = _snapshot("s")  # conversation_epoch 默认 0
    epoch1 = replace(_snapshot("s"), conversation_epoch=1, system_prompt="system-v2")
    # 任一 epoch 未存时均查不到——主键含 epoch
    assert repo.get_snapshot("s", epoch=0) is None
    assert repo.get_snapshot("s", epoch=1) is None
    repo.save_snapshot(epoch0)
    assert repo.get_snapshot("s", epoch=0) == epoch0
    assert repo.get_snapshot("s", epoch=1) is None  # 新 epoch 不复用旧冻结
    # 新 epoch 重新冻结：写 epoch 1 快照，两 epoch 并存且互不覆盖
    repo.save_snapshot(epoch1)
    assert repo.get_snapshot("s", epoch=0) == epoch0
    assert repo.get_snapshot("s", epoch=1) == epoch1
    # 失效按 epoch 隔离：失效 epoch 0 不影响 epoch 1
    repo.invalidate_snapshot("s", "tool-revoked:read", epoch=0)
    invalidated0 = repo.get_snapshot("s", epoch=0)
    assert invalidated0 is not None
    assert invalidated0.invalidated_reason == "tool-revoked:read"
    survivor1 = repo.get_snapshot("s", epoch=1)
    assert survivor1 is not None  # get_snapshot 返回 Optional；收窄后访问属性
    assert survivor1 == epoch1
    assert survivor1.invalidated_reason == ""
    repo.close()


@pytest.mark.parametrize("persistent", [False, True])
def test_commit_archive_rejects_coverage_overlap_and_rolls_back(
    tmp_path: Path, persistent: bool
) -> None:
    """§6.3 唯一约束：活动 coverage 非重叠——新 archive 撞已活动 ref 则事务原子
    回滚，不留孤立 archive/coverage 行。InMemory ``active_refs`` 自检对等 SQLite
    partial UNIQUE ``coverage_active_unique``；冲突交由协调器 fresh re-compile
    （reasoner §6.3 ``except ContextStateError``）。"""
    repo = _make_repo(tmp_path, persistent)
    # 预置活动 archive A1 覆盖 r1/r2（generation 由事务分配为 1）
    a1 = _active_archive(
        "aid1", content="summary-a1", content_hash="hash-a1",
        source_refs=("r1", "r2"), coverage_hash="ch1",
    )
    committed1, is_new1 = repo.commit_archive(a1)
    assert is_new1 is True
    assert committed1.generation == 1  # 事务内 max(同 epoch 0)+1

    # A2 同 (session,epoch)，coverage 与 A1 在 r2 上重叠
    a2 = _active_archive(
        "aid2", content="summary-a2", content_hash="hash-a2",
        source_refs=("r2", "r3"), coverage_hash="ch2",
    )
    with pytest.raises(ContextStateError, match="overlap|UNIQUE constraint"):
        repo.commit_archive(a2)

    # 回滚：仅 A1 入档，A2 未留下孤立 archive；A1 仍为活动 frontier
    archives = repo.list_archives("s")
    assert len(archives) == 1
    assert archives[0].archive_id == "aid1"
    frontier = repo.list_frontier("s")
    assert len(frontier) == 1 and frontier[0].archive_id == "aid1"
    repo.close()


@pytest.mark.parametrize("persistent", [False, True])
def test_commit_archive_retry_with_same_id_is_idempotent(
    tmp_path: Path, persistent: bool
) -> None:
    """§6.3 重试幂等：同 archive_id 二次提交返回 ``is_new=False``，不重复入档/
    coverage/outbox（``UNIQUE(archive_id, event_type)`` + archive_id 主键查重）。
    保证协调器重试或 §6.6 outbox 重放不产生重复事件与重复 coverage 行。"""
    repo = _make_repo(tmp_path, persistent)
    a1 = _active_archive(
        "aid1", content="summary-a1", content_hash="hash-a1",
        source_refs=("r1",), coverage_hash="ch1",
    )
    outbox = OutboxEvent(
        outbox_id="oid1", session_key="s", archive_id="aid1",
        event_type="context_compaction_committed", span_id="span1",
        trace_id="t1", created_at="now",
    )
    committed1, is_new1 = repo.commit_archive(a1, outbox=outbox)
    # 重试：同 archive_id + 同 outbox（archive_id,event_type UNIQUE 幂等）
    committed2, is_new2 = repo.commit_archive(a1, outbox=outbox)

    assert is_new1 is True and is_new2 is False
    assert committed2 == committed1  # 返回已存档（同事务分配 generation）
    assert committed2.generation == 1
    assert len(repo.list_archives("s")) == 1  # 无重复 archive
    repo.close()


@pytest.mark.parametrize("persistent", [False, True])
def test_merge_archives_supersedes_parents_and_inserts_merged(
    tmp_path: Path, persistent: bool
) -> None:
    """§6.5 分层合并：最旧相邻父 archive 原子合并为更高层 archive（correction 3
    事务顺序：supersede 父 archive/coverage → INSERT merged coverage/archive/
    outbox）。父 status=superseded 留存审计，frontier 仅剩 merged 活动；merged
    generation 事务内分配=max+1，level=max(父 level)+1，source_refs=父并集
    （correction 4 invariant）。"""
    repo = _make_repo(tmp_path, persistent)
    # 预置 2 个活动父 archive（ref 不相交，generation 事务分配为 1/2）
    a1 = _active_archive(
        "aid1", content="summary-a1", content_hash="hash-a1",
        source_refs=("r1", "r2"), coverage_hash="ch1",
    )
    a2 = _active_archive(
        "aid2", content="summary-a2", content_hash="hash-a2",
        source_refs=("r3", "r4"), coverage_hash="ch2",
    )
    committed1, _ = repo.commit_archive(a1)
    committed2, _ = repo.commit_archive(a2)
    assert committed1.generation == 1 and committed2.generation == 2

    parents = (committed1, committed2)
    merged = ContextArchive(
        "am1", "s", 0, "merged-summary", "hash-m",
        ("r1", "r2", "r3", "r4"),  # source_refs = 父并集（correction 4）
        epoch=0, level=2,
        parent_archive_refs=("aid1", "aid2"),
        coverage_hash="chm",
    )
    outbox = OutboxEvent(
        outbox_id="oidm", session_key="s", archive_id="am1",
        event_type="context_compaction_committed", span_id="spanm",
        trace_id="tm", created_at="now",
    )
    committed_m, is_new = repo.merge_archives(parents, merged, outbox=outbox)

    assert is_new is True
    # merged generation 事务分配 = max(同 epoch)+1 = 3；level=max(父 level)+1=2
    assert committed_m.generation == 3
    assert committed_m.level == 2
    assert set(committed_m.source_refs) == {"r1", "r2", "r3", "r4"}
    assert committed_m.parent_archive_refs == ("aid1", "aid2")
    assert committed_m.status == "active"

    # 父节点 superseded 留存审计（不删除），frontier 仅 merged 活动
    all_archives = repo.list_archives("s")
    assert {a.archive_id for a in all_archives} == {"aid1", "aid2", "am1"}
    parent_status = {
        a.archive_id: a.status
        for a in all_archives
        if a.archive_id in ("aid1", "aid2")
    }
    assert parent_status == {"aid1": "superseded", "aid2": "superseded"}
    frontier = repo.list_frontier("s")
    assert len(frontier) == 1 and frontier[0].archive_id == "am1"

    # merged coverage 活动（父 coverage 已 superseded）：新 archive 撞 r1 → 重叠
    # 拒绝（overlap 来自 merged 而非父——父 coverage 不再活动）
    a3 = _active_archive(
        "aid3", content="summary-a3", content_hash="hash-a3",
        source_refs=("r1",), coverage_hash="ch3",
    )
    with pytest.raises(ContextStateError, match="overlap|UNIQUE constraint"):
        repo.commit_archive(a3)
    repo.close()


@pytest.mark.parametrize("persistent", [False, True])
def test_merge_archives_retry_with_same_id_is_idempotent(
    tmp_path: Path, persistent: bool
) -> None:
    """§6.5 重试幂等：同 merged.archive_id 二次合并返回 is_new=False，不重复
    supersede 父节点、不重复 coverage/outbox（父不二次 superseded、merged 不
    重复入档）。保证协调器重试或 §6.6 重放不产生重复事件与重复 coverage 行。"""
    repo = _make_repo(tmp_path, persistent)
    a1 = _active_archive(
        "aid1", content="s1", content_hash="h1",
        source_refs=("r1",), coverage_hash="c1",
    )
    a2 = _active_archive(
        "aid2", content="s2", content_hash="h2",
        source_refs=("r2",), coverage_hash="c2",
    )
    p1, _ = repo.commit_archive(a1)
    p2, _ = repo.commit_archive(a2)
    parents = (p1, p2)
    merged = ContextArchive(
        "am1", "s", 0, "m", "hm", ("r1", "r2"),
        epoch=0, level=2, parent_archive_refs=("aid1", "aid2"),
        coverage_hash="cm",
    )
    outbox = OutboxEvent(
        outbox_id="oidm", session_key="s", archive_id="am1",
        event_type="context_compaction_committed", span_id="sm",
        trace_id="tm", created_at="now",
    )
    committed1, is_new1 = repo.merge_archives(parents, merged, outbox=outbox)
    committed2, is_new2 = repo.merge_archives(parents, merged, outbox=outbox)

    assert is_new1 is True and is_new2 is False
    assert committed2 == committed1
    assert len(repo.list_archives("s")) == 3  # aid1, aid2, am1——无重复
    repo.close()


@pytest.mark.parametrize("persistent", [False, True])
def test_merge_archives_rejects_inactive_parent_and_keeps_frontier(
    tmp_path: Path, persistent: bool
) -> None:
    """§6.5 父非活动（并发合并已取代某父）→ ContextStateError，frontier 不变
    （spec「原有 frontier、coverage、源 turn 与当前视图保持不变」+ correction 3
    原子）。对等 InMemory validate-then-mutate / SQLite 事务回滚 + partial UNIQUE。"""
    repo = _make_repo(tmp_path, persistent)
    a1 = _active_archive(
        "aid1", content="s1", content_hash="h1",
        source_refs=("r1",), coverage_hash="c1",
    )
    a2 = _active_archive(
        "aid2", content="s2", content_hash="h2",
        source_refs=("r2",), coverage_hash="c2",
    )
    p1, _ = repo.commit_archive(a1)
    p2, _ = repo.commit_archive(a2)
    # 第一次合并：p1+p2 → m1（p1/p2 superseded、m1 活动、coverage 接管 r1/r2）
    m1 = ContextArchive(
        "am1", "s", 0, "m1", "hm1", ("r1", "r2"),
        epoch=0, level=2, parent_archive_refs=("aid1", "aid2"),
        coverage_hash="cm1",
    )
    repo.merge_archives((p1, p2), m1)
    # 第二次合并：复用已 superseded 的 p1/p2 + 新 merged_id → 父非活动 → 冲突
    m2 = ContextArchive(
        "am2", "s", 0, "m2", "hm2", ("r1", "r2"),
        epoch=0, level=2, parent_archive_refs=("aid1", "aid2"),
        coverage_hash="cm2",
    )
    with pytest.raises(ContextStateError, match="not active|merge conflict"):
        repo.merge_archives((p1, p2), m2)
    # frontier 不变：仅 m1 活动，无 m2 孤立 archive
    frontier = repo.list_frontier("s")
    assert len(frontier) == 1 and frontier[0].archive_id == "am1"
    assert not any(a.archive_id == "am2" for a in repo.list_archives("s"))
    repo.close()


@pytest.mark.parametrize("persistent", [False, True])
def test_merge_archives_rejects_coverage_invariant_violation(
    tmp_path: Path, persistent: bool
) -> None:
    """§6.5/correction 4 invariant：merged.source_refs 必须包含父并集——漏掉
    某父 ref 则 ContextStateError（``set(parents.refs) ⊄ set(merged.refs)``），
    frontier 不变。保证 ``_drop_covered_groups`` 合并后仍排除原 covered turn。"""
    repo = _make_repo(tmp_path, persistent)
    a1 = _active_archive(
        "aid1", content="s1", content_hash="h1",
        source_refs=("r1", "r2"), coverage_hash="c1",
    )
    a2 = _active_archive(
        "aid2", content="s2", content_hash="h2",
        source_refs=("r3",), coverage_hash="c2",
    )
    p1, _ = repo.commit_archive(a1)
    p2, _ = repo.commit_archive(a2)
    # invariant 违反：merged 漏掉 r2（父 a1 的 ref）→ set(parents.refs) ⊄ merged
    merged = ContextArchive(
        "am1", "s", 0, "m", "hm", ("r1", "r3"),
        epoch=0, level=2, parent_archive_refs=("aid1", "aid2"),
        coverage_hash="cm",
    )
    with pytest.raises(ContextStateError, match="invariant"):
        repo.merge_archives((p1, p2), merged)
    # frontier 不变：父仍活动、无 merged 孤立
    frontier = repo.list_frontier("s")
    assert {a.archive_id for a in frontier} == {"aid1", "aid2"}
    repo.close()
