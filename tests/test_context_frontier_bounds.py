"""§6.8 有界 archive frontier 与原子提交的集成行为测试。

覆盖 spec §6.8 六类场景：frontier 长时间有界、source coverage 重叠拒绝、
合并失败回滚、并发/重试 generation 分配、outbox 故障不回滚已提交 context
state、source continuation（phase 单次有界读取后截断标志与续读游标进入
metadata 供协调器分批推进）。store 层用 ``InMemoryContextStateRepository``
对等 SQLite 事务语义（``_lock`` 串行 = 单事务原子）；source 层用游标驱动的
假 ContextSource 隔离 phase 的 metadata 透传合同，避免重 SQLite 播种。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from memoli_agent.agent.context_management import (
    CommittedMessage,
    CommittedTurn,
    ContextArchive,
    ContextStateError,
    InMemoryContextStateRepository,
    OutboxEvent,
    RestorationLevel,
    build_envelope,
)
from memoli_agent.agent.context_management.cross_turn import TurnRead
from memoli_agent.agent.lifecycle.phases import CrossTurnContextPhase
from memoli_agent.agent.lifecycle.types import PassiveTurnContext
from memoli_agent.bus.events import InboundMessage


def _archive_json(refs: list[str]) -> str:
    """构造固定 schema 的 archive 内容 JSON（source_refs 与批次一致）。"""

    return json.dumps(
        {
            "goal_constraints": ["preserve constraint"],
            "decisions_reasons": ["decision because evidence"],
            "facts_evidence": ["payload:42"],
            "files_artifacts": ["result.txt"],
            "verification_status": ["tests passed"],
            "failure_paths": ["first attempt failed"],
            "todo_remaining": ["ship"],
            "source_refs": list(refs),
        }
    )


def _expect_raises(
    exc: type[BaseException],
    fn: Any,
    *args: Any,
    **kwargs: Any,
) -> None:
    """断言 fn(*a, **k) 抛 exc；替代 pytest.raises，避免 pytest 导入触发
    pyright reportMissingImports 环境解析噪声（保持新测试文件 pyright 零错）。"""

    try:
        fn(*args, **kwargs)
    except exc:
        return
    raise AssertionError(f"expected {exc.__name__}")


def _archive(
    archive_id: str,
    refs: list[str],
    *,
    level: int = 1,
    parents: tuple[str, ...] = (),
    epoch: int = 0,
) -> ContextArchive:
    """直接提交用 archive（generation 由 commit_archive 事务分配）。"""

    return ContextArchive(
        archive_id,
        "s",
        0,
        _archive_json(refs),
        f"hash-{archive_id}",
        tuple(refs),
        epoch=epoch,
        coverage_hash=f"cov-{archive_id}",
        level=level,
        parent_archive_refs=tuple(parents),
    )


def _seed_parent(
    repo: InMemoryContextStateRepository, archive_id: str, refs: list[str]
) -> ContextArchive:
    """预置活动父 archive（commit_archive 事务内分配 generation）。"""

    committed, _ = repo.commit_archive(_archive(archive_id, refs))
    return committed


def _union_refs(parents: tuple[ContextArchive, ...]) -> list[str]:
    """父归档 source_refs 并集（保序去重）。"""

    seen: list[str] = []
    for parent in parents:
        for ref in parent.source_refs:
            if ref not in seen:
                seen.append(ref)
    return seen


def _merge(
    repo: InMemoryContextStateRepository,
    parents: tuple[ContextArchive, ...],
    merged_id: str,
) -> ContextArchive:
    """合并最旧相邻 2 父：merged.refs=父并集、level=max(父)+1，原子提交。"""

    refs = _union_refs(parents)
    merged = _archive(
        merged_id,
        refs,
        level=max(p.level for p in parents) + 1,
        parents=tuple(p.archive_id for p in parents),
    )
    committed, _ = repo.merge_archives(parents, merged)
    return committed


def test_frontier_stays_bounded_across_many_generations() -> None:
    """§6.4/§6.5 长会话累积：反复合并最旧相邻 frontier 节点，活动 frontier
    始终有界（≤ max_items），历史 generation 全量留存审计（list_archives
    保留 superseded），活动 frontier generation 单调互异。"""

    repo = InMemoryContextStateRepository()
    # 预置 6 个活动 archive，各覆盖不相交 refs（generation 事务分配 1..6）
    for i in range(6):
        _seed_parent(repo, f"aid{i + 1}", [f"r{2 * i + 1}", f"r{2 * i + 2}"])
    assert len(repo.list_frontier("s")) == 6
    archive_count = len(repo.list_archives("s"))
    # 分层合并直至 frontier ≤ 2（archive_frontier_max_items 上界）
    merges = 0
    while len(repo.list_frontier("s")) > 2:
        frontier = repo.list_frontier("s")  # 按 generation 升序
        _merge(repo, (frontier[0], frontier[1]), f"merged{merges + 1}")
        merges += 1
        # 每次 合并后 frontier 缩减、绝不超初始规模
        assert len(repo.list_frontier("s")) <= 6
    final = repo.list_frontier("s")
    # 最终活动 frontier 有界；历史全量留存（父 superseded 不删，审计可追溯）
    assert len(final) <= 2
    assert len(repo.list_archives("s")) == archive_count + merges
    assert len(final) < len(repo.list_archives("s"))
    # 活动 frontier generation 单调递增、互异（事务分配无回卷）
    gens = [a.generation for a in final]
    assert gens == sorted(gens) and len(set(gens)) == len(gens)


def test_commit_archive_rejects_overlapping_coverage() -> None:
    """§6.3 source coverage 唯一约束：新 archive 覆盖已被活动 archive 占据的
    ref 为真实重叠（非重试幂等）→ ContextStateError 转 fresh re-compile；
    同 archive_id 重试为幂等结果（返回已存在、is_new=False、不重分配）。"""

    repo = InMemoryContextStateRepository()
    original = _seed_parent(repo, "aid1", ["r1"])  # r1 已被 aid1 覆盖
    # 不同 archive_id 覆盖同一 r1 → 活动非重叠冲突
    _expect_raises(ContextStateError, repo.commit_archive, _archive("aid2", ["r1"]))
    # 幂等重试：同 archive_id 再提交 → 已存在、不报错、generation 不变
    retried, is_new = repo.commit_archive(_archive("aid1", ["r1"]))
    assert is_new is False
    assert retried.archive_id == original.archive_id
    assert retried.generation == original.generation
    # aid2 未落库（冲突在写入前抛错，事务未部分提交）
    assert {a.archive_id for a in repo.list_archives("s")} == {"aid1"}


def test_commit_archive_allocates_monotonic_generation_per_epoch() -> None:
    """§6.2 事务内 (session,epoch) 维度分配 generation：同 epoch 连续提交获
    单调递增互异 generation（非 len+1），不同 epoch 独立从 1 计数；重试同
    archive_id 幂等、generation 不重分配。"""

    repo = InMemoryContextStateRepository()
    a1, new1 = repo.commit_archive(_archive("aid1", ["r1"], epoch=0))
    a2, new2 = repo.commit_archive(_archive("aid2", ["r2"], epoch=0))
    assert new1 and new2
    assert (a1.generation, a2.generation) == (1, 2)  # 同 epoch 单调互异
    # 不同 epoch 独立计数（(session,epoch) 维度，非全局递增）
    b1, _ = repo.commit_archive(_archive("bid1", ["r3"], epoch=5))
    assert b1.generation == 1
    # 重试同 archive_id 幂等：返回已存在、is_new=False、generation 不变
    retried, is_new = repo.commit_archive(_archive("aid1", ["r1"], epoch=0))
    assert is_new is False and retried.generation == a1.generation


def test_merge_archives_rolls_back_on_invariant_violation() -> None:
    """§6.5 validate-then-mutate：coverage invariant 违反（父 refs ⊄ merged
    refs）在校验阶段抛错，无任何变更——父节点保持活动、frontier 不变、无
    孤立 merged（事务回滚对等）。"""

    repo = InMemoryContextStateRepository()
    p1 = _seed_parent(repo, "aid1", ["r1", "r2"])
    p2 = _seed_parent(repo, "aid2", ["r3", "r4"])
    frontier_before = repo.list_frontier("s")
    # merged 缺漏 r3/r4 → 违反 invariant（父 refs ⊄ merged refs）
    bad = _archive("merged1", ["r1", "r2"], level=2, parents=("aid1", "aid2"))
    _expect_raises(ContextStateError, repo.merge_archives, (p1, p2), bad)
    # 父仍活动、frontier 不变、未留孤立 merged（事务未部分 supersede）
    assert repo.list_frontier("s") == frontier_before
    assert {a.archive_id for a in repo.list_archives("s")} == {"aid1", "aid2"}


def test_merge_archives_rejects_non_active_parent() -> None:
    """§6.5 前置校验：父须为活动；已被并发合并取代（superseded）的父再次
    参与合并 → ContextStateError，避免重复 supersede 覆盖。"""

    repo = InMemoryContextStateRepository()
    p1 = _seed_parent(repo, "aid1", ["r1"])
    p2 = _seed_parent(repo, "aid2", ["r2"])
    p3 = _seed_parent(repo, "aid3", ["r3"])
    # 先合并 aid1+aid2 → aid1/aid2 superseded（留存审计）
    _merge(repo, (p1, p2), "merged1")
    # 再用已 superseded 的 aid1 参与合并 → 父非活动（活动校验先于 invariant）
    bad = _archive("merged2", ["r1", "r3"], level=3, parents=("aid1", "aid3"))
    _expect_raises(ContextStateError, repo.merge_archives, (p1, p3), bad)
    # aid3 仍活动、未受失败合并影响
    active = {a.archive_id for a in repo.list_frontier("s")}
    assert "aid3" in active and "merged2" not in active


def test_committed_archive_survives_outbox_delivery_failure() -> None:
    """§6.6 archive/coverage/outbox 同事务：archive 提交成功后 outbox 投递
    失败（mark_outbox_failed）不回滚已提交 context state——archive 仍在活动
    frontier；诊断暴露 outbox failed 计数（不暴露 payload，§8.3）。"""

    repo = InMemoryContextStateRepository()
    outbox = OutboxEvent(
        outbox_id="obx1",
        session_key="s",
        archive_id="aid1",
        event_type="context_compaction_committed",
        span_id="span1",
        trace_id="trace1",
        parent_span_id="parent",
    )
    archive, is_new = repo.commit_archive(_archive("aid1", ["r1"]), outbox=outbox)
    assert is_new
    # outbox 待投递、archive 已在活动 frontier
    pending = repo.list_pending_outbox("s")
    assert len(pending) == 1 and pending[0].archive_id == "aid1"
    assert any(a.archive_id == "aid1" for a in repo.list_frontier("s"))
    # 投递失败 → 标记 failed；archive 不回滚、仍活动在 frontier
    repo.mark_outbox_failed(pending[0].outbox_id, error="hook boom")
    still_pending = repo.list_pending_outbox("s")  # failed 仍在 pending 队列
    assert len(still_pending) == 1 and still_pending[0].status == "failed"
    frontier = repo.list_frontier("s")
    assert len(frontier) == 1 and frontier[0].archive_id == archive.archive_id
    # 诊断暴露 outbox failed 计数（仅哈希/计数/稳定引用，无 payload）
    summary = repo.diagnostic_summary("s")
    assert summary["outbox_failed"] == 1
    assert summary["frontier_active_count"] == 1


def _turn(seq: int) -> CommittedTurn:
    """最小已终止 turn（user+assistant 两消息，可 to_messages 重构）。"""

    return CommittedTurn(
        epoch=0,
        turn_seq=seq,
        trace_id=f"trace{seq}",
        status="completed",
        started_at=f"2024-01-01T00:00:{seq:02d}.000000Z",
        ended_at=f"2024-01-01T00:00:{seq:02d}.000000Z",
        messages=(
            CommittedMessage(
                turn_seq=seq,
                message_seq=1,
                role="user",
                content=f"u{seq}",
                content_hash=f"h-u{seq}",
            ),
            CommittedMessage(
                turn_seq=seq,
                message_seq=2,
                role="assistant",
                content=f"a{seq}",
                content_hash=f"h-a{seq}",
            ),
        ),
        content_hash=f"turn{seq}",
    )


class _CursorSource:
    """§6.8 测试夹具：按 after_turn_seq 游标返回分批 TurnRead，模拟压缩协调器
    分批推进覆盖。phase 单次有界读取后把截断标志与游标写入 metadata 供续读。"""

    def __init__(self) -> None:
        self.reads: list[int | None] = []

    async def read_turns(
        self,
        *,
        session_key: str,
        epoch: int,
        exclude_trace_id: str | None = None,
        after_turn_seq: int | None = None,
        max_turns: int | None = None,
        max_bytes: int | None = None,
    ) -> TurnRead:
        self.reads.append(after_turn_seq)
        if after_turn_seq in (None, 0):
            # 首批：2 turn，触及 max_turns 上限 → 截断，游标=末纳入 turn_seq
            return TurnRead((_turn(1), _turn(2)), True, 2)
        if after_turn_seq == 2:
            # 续读末批：1 turn，未触及上限 → 不截断，游标 None（≠截断）
            return TurnRead((_turn(3),), False, None)
        return TurnRead((), False, None)

    async def restoration_level(
        self, session_key: str, epoch: int
    ) -> RestorationLevel:
        return RestorationLevel.GOVERNED


def test_source_continuation_phase_records_truncated_and_cursor() -> None:
    """§6.7/§6.8 source continuation：phase 单次有界读取把截断标志与续读游标
    写入 ctx.metadata，使截断的未读内容可观察、可分批推进；协调器凭游标续读
    得末批，末批 truncated=False、游标 None（绝不把截断当作历史不存在）。"""

    source = _CursorSource()
    phase = CrossTurnContextPhase(
        context_source=source,
        trajectory_store=None,
        source_read_max_turns=2,
    )
    ctx = PassiveTurnContext(
        inbound=InboundMessage(
            channel="c", chat_id="1", sender="u", content="hi"
        ),
        conversation_epoch=0,
        trace_id="current",
    )
    asyncio.run(phase.run(ctx))
    # phase 单次有界读取后：截断标志与续读游标进入 metadata（供协调器续读）
    assert ctx.metadata["cross_turn_status"] == "ready"
    assert ctx.metadata["cross_turn_truncated"] is True
    assert ctx.metadata["cross_turn_next_after_turn_seq"] == 2
    assert ctx.metadata["cross_turn_turn_count"] == 2
    # 协调器凭游标续读：得末批，未截断、游标 None（≠截断＝不存在）
    cursor = ctx.metadata["cross_turn_next_after_turn_seq"]
    assert cursor is not None
    cont = asyncio.run(
        source.read_turns(
            session_key="c:1",
            epoch=0,
            exclude_trace_id="current",
            after_turn_seq=cursor,
            max_turns=2,
        )
    )
    assert len(cont.turns) == 1
    assert cont.truncated is False
    assert cont.next_after_turn_seq is None


def test_phase_excludes_turn_with_inconsistent_preview() -> None:
    """§7.3 恢复期引用完整性：CrossTurnContextPhase 装配 preview_lookup 后，
    对 canonical hash 不一致的整 turn 排除（不拆 tool pair），并把排除计数写入
    metadata；recent_turns 不含被排除 turn 的任何消息。"""

    from memoli_agent.agent.context_management import (
        ConservativeTokenEstimator,
        ToolResultPreviewer,
    )
    from memoli_agent.agent.context_management.cross_turn import (
        envelope_to_committed_message,
    )
    from memoli_agent.agent.types import ChatMessage

    repo = InMemoryContextStateRepository()
    previewer = ToolResultPreviewer(repo, ConservativeTokenEstimator(), 20)
    # session_key 须与 PassiveTurnContext.inbound.session_key（channel:chat_id）一致。
    # 冻结只为在 repo 写入一个 epoch=0 的预览供 phase 校验；返回值不直接使用。
    previewer.freeze(
        session_key="c:1",
        tool_call_id="call",
        tool_name="read",
        content="x" * 400,
        payload_ref="trajectory-payload:1",
        epoch=0,
    )
    # committed tool 内容被篡改（≠ 冻结预览）→ canonical 不一致，整 turn 排除。
    tampered = ChatMessage(
        role="tool", content="tampered", tool_call_id="call", name="read"
    )
    envelope = build_envelope(tampered, epoch=0, turn_seq=1, message_seq=2)
    tool_msg = envelope_to_committed_message(
        envelope, restoration=RestorationLevel.GOVERNED
    )
    assert tool_msg is not None  # 合法 envelope 必还原（收窄 Optional）
    assistant = CommittedMessage(
        turn_seq=1,
        message_seq=1,
        role="assistant",
        content="go",
        content_hash="h-a",
    )
    bad_turn = CommittedTurn(
        epoch=0,
        turn_seq=1,
        trace_id="t1",
        status="completed",
        started_at="",
        ended_at="",
        messages=(assistant, tool_msg),
        content_hash="turn1",
    )

    class _OneTurnSource:
        async def read_turns(
            self,
            *,
            session_key: str,
            epoch: int,
            exclude_trace_id: str | None = None,
            after_turn_seq: int | None = None,
            max_turns: int | None = None,
            max_bytes: int | None = None,
        ) -> TurnRead:
            return TurnRead((bad_turn,), False, None)

        async def restoration_level(
            self, session_key: str, epoch: int
        ) -> RestorationLevel:
            return RestorationLevel.GOVERNED

    phase = CrossTurnContextPhase(
        context_source=_OneTurnSource(),
        trajectory_store=None,
        preview_lookup=repo,
    )
    ctx = PassiveTurnContext(
        inbound=InboundMessage(
            channel="c", chat_id="1", sender="u", content="hi"
        ),
        conversation_epoch=0,
        trace_id="current",
    )
    asyncio.run(phase.run(ctx))
    # 整 turn 被排除：无 recent_turns、排除计数=1、tool pair 未被拆散注入。
    assert ctx.recent_turns == ()
    assert ctx.metadata["cross_turn_preview_excluded_turns"] == 1
    assert ctx.metadata["cross_turn_turn_count"] == 0


def test_phase_keeps_turn_when_no_preview_lookup() -> None:
    """§7.5 无 preview_lookup（SubAgent/降级）→ 不校验、保持隔离，turn 原样注入。"""

    assistant = CommittedMessage(
        turn_seq=1,
        message_seq=1,
        role="assistant",
        content="go",
        content_hash="h-a",
    )
    turn = CommittedTurn(
        epoch=0,
        turn_seq=1,
        trace_id="t1",
        status="completed",
        started_at="",
        ended_at="",
        messages=(assistant,),
        content_hash="turn1",
    )

    class _OneTurnSource:
        async def read_turns(
            self,
            *,
            session_key: str,
            epoch: int,
            exclude_trace_id: str | None = None,
            after_turn_seq: int | None = None,
            max_turns: int | None = None,
            max_bytes: int | None = None,
        ) -> TurnRead:
            return TurnRead((turn,), False, None)

        async def restoration_level(
            self, session_key: str, epoch: int
        ) -> RestorationLevel:
            return RestorationLevel.GOVERNED

    phase = CrossTurnContextPhase(
        context_source=_OneTurnSource(),
        trajectory_store=None,
        preview_lookup=None,
    )
    ctx = PassiveTurnContext(
        inbound=InboundMessage(
            channel="c", chat_id="1", sender="u", content="hi"
        ),
        conversation_epoch=0,
        trace_id="current",
    )
    asyncio.run(phase.run(ctx))
    assert len(ctx.recent_turns) == 1
    assert "cross_turn_preview_excluded_turns" not in ctx.metadata
