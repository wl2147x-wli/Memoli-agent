"""§6.6 context audit outbox 幂等投递/重放/诊断测试。

覆盖 spec「Archive transaction commits but audit delivery is delayed」与
「Compiled context is sent」两场景的 outbox 重放侧：

- trajectory 审计事件去重（partial UNIQUE ``events_audit_dedup`` + record 预检）；
- repository ``list_pending_outbox`` / ``diagnostic_summary`` outbox 计数；
- ``TaskAwareCompactor.replay_outbox`` 幂等重放（不触碰 generation/coverage）；
- Reasoner turn-start 触发重放（best-effort，不阻塞主控制流）。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from memoli_agent.agent.context_management import (
    ConservativeTokenEstimator,
    ContextArchive,
    InMemoryContextStateRepository,
    OutboxEvent,
    SQLiteContextStateRepository,
    TaskAwareCompactor,
)
from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.core.results import TerminationReason
from memoli_agent.agent.provider import EchoProvider, LLMResponse, ScriptedProvider
from memoli_agent.agent.trajectory import (
    InMemoryTrajectoryStore,
    NewTrajectoryEvent,
    SpanKind,
    SpanProjection,
    SQLiteTrajectoryStore,
    TraceProjection,
    new_span_id,
    new_trace_id,
    utc_now_iso,
)
from memoli_agent.agent.types import ChatMessage


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


def _make_repo(
    tmp_path: Path, persistent: bool
) -> InMemoryContextStateRepository | SQLiteContextStateRepository:
    """§6.6 内存版与持久版对等覆盖同一 outbox 重放合同。"""
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
    coverage_hash: str,
    session_key: str = "s",
    epoch: int = 0,
) -> ContextArchive:
    """generation=0 占位活动 archive——generation 由 commit_archive 事务内分配。"""
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


def _outbox(
    outbox_id: str,
    archive_id: str,
    span_id: str,
    trace_id: str,
    *,
    session_key: str = "s",
    event_type: str = "context_compaction_committed",
) -> OutboxEvent:
    # span_projection 复刻 compact() 的 _span_to_json(completed_span)：经
    # _span_projection_from_json 可重建完整 SpanProjection（空值会缺必填字段
    # 致 _deliver_committed 误标 failed）。committed 事件复用 requested 同 span。
    span_projection = json.dumps(
        {
            "span_id": span_id,
            "trace_id": trace_id,
            "parent_span_id": None,
            "kind": "llm",
            "name": "compact",
            "started_at": "now",
            "status": "completed",
            "ended_at": "now",
            "output_data": {"archive_id": archive_id},
        }
    )
    return OutboxEvent(
        outbox_id=outbox_id,
        session_key=session_key,
        archive_id=archive_id,
        event_type=event_type,
        span_id=span_id,
        trace_id=trace_id,
        span_projection=span_projection,
        created_at="now",
    )


@pytest.mark.parametrize("persistent", [False, True])
def test_audit_committed_event_record_is_idempotent(
    tmp_path: Path, persistent: bool
) -> None:
    """§6.6 审计事件幂等：同 (trace_id, span_id, context_compaction_committed)
    二次 record 返回已存事件、不新增 events 行（partial UNIQUE
    events_audit_dedup + record 预检兜底；InMemory 与 SQLite 对等）。"""

    async def scenario():
        # 建立 trace + span（模拟 turn 中 trace_started 已落盘；SQLite events
        # 对 trace_id/span_id 有 FK，traces 表 CHECK length(trace_id)=32，故用
        # 生成器）。committed 复用同 span。
        tid = new_trace_id()
        sid = new_span_id()
        await store.record(
            NewTrajectoryEvent(
                trace_id=tid,
                event_type="trace_started",
                payload={},
                span_id=sid,
                trace=TraceProjection(
                    trace_id=tid, session_id="s", started_at=utc_now_iso(),
                    provider="fake",
                ),
                span=SpanProjection(
                    span_id=sid, trace_id=tid, parent_span_id=None,
                    kind=SpanKind.AGENT, name="turn", started_at=utc_now_iso(),
                ),
            )
        )
        first = await store.record(
            NewTrajectoryEvent(
                trace_id=tid,
                event_type="context_compaction_committed",
                payload={"archive_id": "a1", "generation": 1},
                span_id=sid,
            )
        )
        # 重放/重试同一逻辑提交：幂等返回已存事件（同 sequence、不新增行）
        second = await store.record(
            NewTrajectoryEvent(
                trace_id=tid,
                event_type="context_compaction_committed",
                payload={"archive_id": "a1", "generation": 1},
                span_id=sid,
            )
        )
        return first, second

    if persistent:
        store = SQLiteTrajectoryStore(
            tmp_path / "traj.db", payload_directory=tmp_path / "payloads"
        )
        run(store.start())
        first, second = run(scenario())
        assert first.sequence == second.sequence
        with sqlite3.connect(tmp_path / "traj.db") as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM events "
                "WHERE event_type='context_compaction_committed'"
            ).fetchone()[0]
        assert count == 1
        run(store.close())
    else:
        store = InMemoryTrajectoryStore()
        first, second = run(scenario())
        assert first.sequence == second.sequence
        committed = [
            e for e in store.events if e.event_type == "context_compaction_committed"
        ]
        assert len(committed) == 1


def test_audit_dedup_is_scoped_per_span_not_blanket() -> None:
    """§6.6 去重按 (trace_id, span_id, event_type) 精确作用：不同 span_id 的
    committed 事件各自独立记录——证明去重不是 blanket UNIQUE，不会误丢多工具
    轮内共用 root span 的合法多次 committed 消息事件（correction 6 安全边界）。"""
    store = InMemoryTrajectoryStore()

    async def scenario() -> None:
        await store.record(
            NewTrajectoryEvent(
                trace_id="t1",
                event_type="context_compaction_committed",
                payload={},
                span_id="s1",
            )
        )
        await store.record(
            NewTrajectoryEvent(
                trace_id="t1",
                event_type="context_compaction_committed",
                payload={},
                span_id="s2",
            )
        )

    run(scenario())
    committed = [
        e for e in store.events if e.event_type == "context_compaction_committed"
    ]
    assert [e.span_id for e in committed] == ["s1", "s2"]
    assert len(committed) == 2


@pytest.mark.parametrize("persistent", [False, True])
def test_list_pending_outbox_returns_pending_and_failed_not_delivered(
    tmp_path: Path, persistent: bool
) -> None:
    """§6.6 list_pending_outbox：返回 pending/failed 行（供重放），delivered 不返回。"""
    repo = _make_repo(tmp_path, persistent)
    # pending：commit_archive 事务内写入 outbox（未投递）
    repo.commit_archive(
        _active_archive(
            "aid1", content="c1", content_hash="h1",
            source_refs=("r1",), coverage_hash="cv1",
        ),
        outbox=_outbox("oid1", "aid1", "span1", "t1"),
    )
    # delivered：投递成功
    repo.commit_archive(
        _active_archive(
            "aid2", content="c2", content_hash="h2",
            source_refs=("r2",), coverage_hash="cv2",
        ),
        outbox=_outbox("oid2", "aid2", "span2", "t2"),
    )
    repo.mark_outbox_delivered("oid2", delivered_at="now")
    # failed：投递失败
    repo.commit_archive(
        _active_archive(
            "aid3", content="c3", content_hash="h3",
            source_refs=("r3",), coverage_hash="cv3",
        ),
        outbox=_outbox("oid3", "aid3", "span3", "t3"),
    )
    repo.mark_outbox_failed("oid3", error="boom")

    pending = {e.outbox_id for e in repo.list_pending_outbox("s")}
    assert pending == {"oid1", "oid3"}  # pending + failed；delivered 不返回
    if persistent:
        repo.close()


@pytest.mark.parametrize("persistent", [False, True])
def test_diagnostic_summary_reports_outbox_pending_and_failed_counts(
    tmp_path: Path, persistent: bool
) -> None:
    """§6.6 diagnostic_summary：暴露 outbox_pending/outbox_failed 计数供运维定位
    延迟投递（仅计数，不暴露 payload/span——§8.3 安全）。"""
    repo = _make_repo(tmp_path, persistent)
    repo.commit_archive(
        _active_archive(
            "aid1", content="c1", content_hash="h1",
            source_refs=("r1",), coverage_hash="cv1",
        ),
        outbox=_outbox("oid1", "aid1", "span1", "t1"),
    )  # pending
    repo.commit_archive(
        _active_archive(
            "aid2", content="c2", content_hash="h2",
            source_refs=("r2",), coverage_hash="cv2",
        ),
        outbox=_outbox("oid2", "aid2", "span2", "t2"),
    )
    repo.mark_outbox_failed("oid2", error="boom")  # failed
    repo.commit_archive(
        _active_archive(
            "aid3", content="c3", content_hash="h3",
            source_refs=("r3",), coverage_hash="cv3",
        ),
        outbox=_outbox("oid3", "aid3", "span3", "t3"),
    )
    repo.mark_outbox_delivered("oid3", delivered_at="now")  # delivered

    summary = repo.diagnostic_summary("s")
    assert summary["outbox_pending"] == 1  # oid1
    assert summary["outbox_failed"] == 1  # oid2
    if persistent:
        repo.close()


def test_replay_outbox_delivers_pending_and_is_idempotent() -> None:
    """§6.6 replay_outbox：pending outbox 经重放投递 committed 轨迹事件（窄
    payload archive_id/generation/source_refs）；二次重放幂等（已 delivered
    不返回→0、无新事件）；重放只记轨迹、不调 commit/merge，archive 数不变
    （spec「重放 SHALL 幂等且不得再次创建 archive generation 或重复 source
    coverage」）。"""
    repo = InMemoryContextStateRepository()
    store = InMemoryTrajectoryStore()
    repo.commit_archive(
        _active_archive(
            "aid1", content="summary", content_hash="h1",
            source_refs=("r1",), coverage_hash="cv1",
        ),
        outbox=_outbox("oid1", "aid1", "span1", "t1"),
    )
    assert len(repo.list_pending_outbox("s")) == 1
    assert len(repo.list_archives("s")) == 1
    compactor = TaskAwareCompactor(
        EchoProvider(), repo, ConservativeTokenEstimator(), archive_tokens=100,
    )

    delivered = run(compactor.replay_outbox(session_key="s", trajectory_store=store))
    assert delivered == 1
    # trajectory 记录了被重放的 committed 事件
    committed = [
        e for e in store.events if e.event_type == "context_compaction_committed"
    ]
    assert len(committed) == 1
    # outbox 已 delivered，不再 pending
    assert repo.list_pending_outbox("s") == ()
    # archive 数不变（重放未重新提交）
    assert len(repo.list_archives("s")) == 1

    # 二次重放幂等：无 pending/failed → 0、无新事件
    again = run(compactor.replay_outbox(session_key="s", trajectory_store=store))
    assert again == 0
    assert len(committed) == 1


def test_replay_outbox_redelivers_failed_outbox() -> None:
    """§6.6 spec 场景「audit delivery is delayed」：outbox 投递临时失败留 failed
    行，下一轮重放用可用 trajectory store 成功补投递、标记 delivered（context-state
    事务已提交、压缩决定已生效，重放只补审计投递，不回滚也不重做压缩）。"""
    repo = InMemoryContextStateRepository()
    store = InMemoryTrajectoryStore()
    repo.commit_archive(
        _active_archive(
            "aid1", content="summary", content_hash="h1",
            source_refs=("r1",), coverage_hash="cv1",
        ),
        outbox=_outbox("oid1", "aid1", "span1", "t1"),
    )
    # 模拟上一轮投递失败（如 _deliver_committed 在 trajectory 不可用时标记 failed）
    repo.mark_outbox_failed("oid1", error="trajectory unavailable")
    assert {e.outbox_id for e in repo.list_pending_outbox("s")} == {"oid1"}

    compactor = TaskAwareCompactor(
        EchoProvider(), repo, ConservativeTokenEstimator(), archive_tokens=100,
    )
    delivered = run(compactor.replay_outbox(session_key="s", trajectory_store=store))
    assert delivered == 1
    assert repo.list_pending_outbox("s") == ()  # 补投递成功→delivered
    assert any(
        e.event_type == "context_compaction_committed" for e in store.events
    )


def test_replay_outbox_marks_invalid_payload_failed_and_continues() -> None:
    """§6.6 outbox payload 非合法 archive JSON（落盘损坏，正常路径不会产生）→
    标记 failed 跳过、重放流程继续后续事件，不抛异常（best-effort 不阻塞）。"""
    repo = InMemoryContextStateRepository()
    store = InMemoryTrajectoryStore()
    repo.commit_archive(
        _active_archive(
            "aid1", content="c1", content_hash="h1",
            source_refs=("r1",), coverage_hash="cv1",
        ),
        outbox=_outbox("oid1", "aid1", "span1", "t1"),
    )
    repo.commit_archive(
        _active_archive(
            "aid2", content="c2", content_hash="h2",
            source_refs=("r2",), coverage_hash="cv2",
        ),
        outbox=_outbox("oid2", "aid2", "span2", "t2"),
    )
    # 损坏 oid2 的 payload（模拟落盘损坏）
    repo.outbox["s"][1]["payload"] = "not-valid-json"
    compactor = TaskAwareCompactor(
        EchoProvider(), repo, ConservativeTokenEstimator(), archive_tokens=100,
    )

    delivered = run(compactor.replay_outbox(session_key="s", trajectory_store=store))
    # oid1 投递成功、oid2 标记 failed；返回本次尝试重放数=2
    assert delivered == 2
    summary = repo.diagnostic_summary("s")
    assert summary["outbox_failed"] == 1  # oid2
    # oid1 的 committed 事件已记录
    assert any(
        e.event_type == "context_compaction_committed" for e in store.events
    )


def test_run_turn_replays_pending_outbox_at_turn_start() -> None:
    """§6.6 Reasoner turn-start 触发：task_compactor 在场且 outbox 有 pending 行时，
    run_turn 起始（trace 落盘后、model 循环前）重放未投递审计事件。"""
    repo = InMemoryContextStateRepository()
    store = InMemoryTrajectoryStore()
    repo.commit_archive(
        _active_archive(
            "aid1", content="summary", content_hash="h1",
            source_refs=("r1",), coverage_hash="cv1",
        ),
        outbox=_outbox("oid1", "aid1", "span1", "t1"),
    )
    assert len(repo.list_pending_outbox("s")) == 1
    compactor = TaskAwareCompactor(
        EchoProvider(), repo, ConservativeTokenEstimator(), archive_tokens=100,
    )
    provider = ScriptedProvider([LLMResponse("done", provider="scripted")])
    reasoner = Reasoner(provider, trajectory_store=store, task_compactor=compactor)

    result = run(reasoner.run_turn([ChatMessage("user", "go")], session_key="s"))

    assert result.termination_reason is TerminationReason.COMPLETED
    # turn-start 重放已投递 pending outbox
    assert repo.list_pending_outbox("s") == ()
    # trajectory 记录了被重放的 committed 事件
    assert any(
        e.event_type == "context_compaction_committed" for e in store.events
    )


def test_run_turn_swallows_replay_failure_without_blocking_turn() -> None:
    """§6.6 best-effort：replay_outbox 抛异常时不得阻塞主 turn——except 吞掉、
    turn 正常完成（审计重放是派生投递，不得影响已提交 context state / 主控制流）。"""

    class _RaisingCompactor(TaskAwareCompactor):
        async def replay_outbox(  # type: ignore[no-untyped-def]
            self, *, session_key: str, trajectory_store
        ) -> int:
            raise RuntimeError("replay exploded")

    compactor = _RaisingCompactor(
        EchoProvider(),
        InMemoryContextStateRepository(),
        ConservativeTokenEstimator(),
        archive_tokens=100,
    )
    provider = ScriptedProvider([LLMResponse("done", provider="scripted")])
    reasoner = Reasoner(provider, task_compactor=compactor)

    result = run(reasoner.run_turn([ChatMessage("user", "go")], session_key="s"))

    # replay 抛异常被吞掉，turn 仍正常完成
    assert result.termination_reason is TerminationReason.COMPLETED


def test_run_turn_skips_replay_when_no_compactor() -> None:
    """§6.6 task_compactor=None（未配置压缩协调器）时 turn-start 跳过重放、不报错。"""
    provider = ScriptedProvider([LLMResponse("done", provider="scripted")])
    reasoner = Reasoner(provider)  # task_compactor 默认 None

    result = run(reasoner.run_turn([ChatMessage("user", "go")], session_key="s"))

    assert result.termination_reason is TerminationReason.COMPLETED
