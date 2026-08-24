"""§6.7 source reader 有界读取测试。

覆盖 spec scenario「Source reader reaches an I/O bound」：当可用 turn 超过单次
turn/byte 读取上限时，reader 返回稳定续读游标 + source-truncated 信号，
coordinator 可分批推进覆盖；且读取截断（``truncated=True``）绝不等于历史
不存在——截断表示「触及 I/O 上限尚有未读」，``truncated=False`` 才表示
「确无更多历史」。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from memoli_agent.agent.context_management.cross_turn import (
    InProcessTurnSource,
    LegacyTurnSource,
    RestorationLevel,
    TrajectoryContextSource,
    TurnRead,
    _turn_byte_size,
    build_envelope,
)
from memoli_agent.agent.trajectory import (
    NewTrajectoryEvent,
    SpanKind,
    SpanProjection,
    SQLiteTrajectoryStore,
    TraceProjection,
    new_span_id,
    new_trace_id,
)
from memoli_agent.agent.types import ChatMessage

COMMITTED_INPUT = "turn_input_committed"
COMMITTED_OUTPUT = "turn_output_committed"


def run(coroutine: Any) -> Any:  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


def build_store(tmp_path: Path, **kwargs: Any) -> SQLiteTrajectoryStore:
    return SQLiteTrajectoryStore(
        tmp_path / "trajectories.db",
        payload_directory=tmp_path / "payloads",
        **kwargs,
    )


def _ts(n: int) -> str:
    # 固定格式、严格递增，使 (started_at, trace_id) 全序确定、turn_seq 与插入序一致。
    return f"2024-01-01T00:00:{n:02d}.000000Z"


# 所有 turn 共用的合法收尾时间（晚于任一 started_at；仅用于 ended_at IS NOT NULL）。
_FINISHED_AT = "2024-01-01T00:00:10.000000Z"


def _commit_turn(  # type: ignore[no-untyped-def]
    store: SQLiteTrajectoryStore,
    *,
    session_id: str,
    epoch: int,
    trace_id: str,
    root_span_id: str,
    committed: list[tuple[str, ChatMessage]],
    started: str,
    capture_mode: str = "full-local",
    turn_seq: int = 1,
    status: str = "completed",
    final_output: str | None = None,
) -> None:
    """记录一个完整 committed turn（镜像 runtime 记录点，注入 started_at 控制序）。"""

    trace = TraceProjection(
        trace_id, session_id, started, context_epoch=epoch, provider="fake"
    )
    root = SpanProjection(
        root_span_id, trace_id, None, SpanKind.AGENT, "turn", started
    )
    run(
        store.record(
            NewTrajectoryEvent(
                trace_id=trace_id,
                span_id=root_span_id,
                event_type="trace_started",
                payload={"content": "turn"},
                trace=trace,
                span=root,
            )
        )
    )
    for sequence, (event_type, message) in enumerate(committed, start=1):
        envelope = build_envelope(
            message,
            epoch=epoch,
            turn_seq=turn_seq,
            message_seq=sequence,
            capture_mode=capture_mode,
        )
        run(
            store.record(
                NewTrajectoryEvent(
                    trace_id=trace_id,
                    span_id=root_span_id,
                    event_type=event_type,
                    payload=envelope,
                )
            )
        )
    finished = TraceProjection(
        trace_id,
        session_id,
        started,
        context_epoch=epoch,
        status=status,
        ended_at=_FINISHED_AT,
        termination_reason=status,
        final_output=final_output if final_output is not None else "",
        provider="fake",
        iteration_count=1,
    )
    run(
        store.record(
            NewTrajectoryEvent(
                trace_id=trace_id,
                span_id=root_span_id,
                event_type="trace_finished",
                payload={"final_output": final_output or ""},
                trace=finished,
            )
        )
    )


def _commit_legacy_turn(  # type: ignore[no-untyped-def]
    store: SQLiteTrajectoryStore,
    *,
    session_id: str,
    epoch: int,
    trace_id: str,
    root_span_id: str,
    started: str,
    user_content: str,
    assistant_content: str,
) -> None:
    """记录一个无 committed 事件的旧 trace（user→assistant），供 legacy 分页。"""

    trace = TraceProjection(
        trace_id, session_id, started, context_epoch=epoch, provider="fake"
    )
    root = SpanProjection(
        root_span_id, trace_id, None, SpanKind.AGENT, "turn", started
    )
    run(
        store.record(
            NewTrajectoryEvent(
                trace_id=trace_id,
                span_id=root_span_id,
                event_type="trace_started",
                payload={"content": "turn"},
                trace=trace,
                span=root,
            )
        )
    )
    run(
        store.record(
            NewTrajectoryEvent(
                trace_id=trace_id,
                span_id=root_span_id,
                event_type="model_requested",
                payload={"messages": [{"role": "user", "content": user_content}]},
            )
        )
    )
    run(
        store.record(
            NewTrajectoryEvent(
                trace_id=trace_id,
                span_id=root_span_id,
                event_type="model_responded",
                payload={"content": assistant_content},
            )
        )
    )
    finished = TraceProjection(
        trace_id,
        session_id,
        started,
        context_epoch=epoch,
        status="completed",
        ended_at=_FINISHED_AT,
        termination_reason="completed",
        final_output=assistant_content,
        provider="fake",
        iteration_count=1,
    )
    run(
        store.record(
            NewTrajectoryEvent(
                trace_id=trace_id,
                span_id=root_span_id,
                event_type="trace_finished",
                payload={"final_output": assistant_content},
                trace=finished,
            )
        )
    )


def _seed_turns(
    store: SQLiteTrajectoryStore, *, session_id: str, epoch: int, count: int
) -> list[str]:
    """提交 count 个 committed turn（content 形如 turn-1..turn-N）。

    返回 trace_id 列表（按提交序）。started_at 注入保证 turn_seq 与插入序一致。
    """

    trace_ids: list[str] = []
    for index in range(1, count + 1):
        trace_id = new_trace_id()
        root = new_span_id()
        _commit_turn(
            store,
            session_id=session_id,
            epoch=epoch,
            trace_id=trace_id,
            root_span_id=root,
            started=_ts(index),
            committed=[
                (COMMITTED_INPUT, ChatMessage(role="user", content=f"问题-{index}")),
                (
                    COMMITTED_OUTPUT,
                    ChatMessage(role="assistant", content=f"回复-{index}"),
                ),
            ],
            final_output=f"回复-{index}",
        )
        trace_ids.append(trace_id)
    return trace_ids


def test_max_turns_bound_pages_via_stable_cursor(tmp_path: Path) -> None:
    # 5 个 committed turn；max_turns=2 分页：满页 2 条、truncated=True、cursor
    # 推进；末页 1 条 truncated=False cursor=None（确无更多）；越过末序号续读
    # → 空 + truncated=False + cursor=None（再次确认确无更多，≠截断）。
    store = build_store(tmp_path, capture_content="full-local")
    run(store.start())
    _seed_turns(store, session_id="bounds-a", epoch=1, count=5)

    source = TrajectoryContextSource(store)
    assert run(source.restoration_level("bounds-a", 1)) is RestorationLevel.EXACT

    all_read = run(source.read_turns(session_key="bounds-a", epoch=1))
    assert len(all_read.turns) == 5
    assert all_read.truncated is False
    assert all_read.next_after_turn_seq is None
    # 稳定序号 1..5 与内容一一对应（started_at 注入序）。
    assert [t.turn_seq for t in all_read.turns] == [1, 2, 3, 4, 5]

    page1 = run(source.read_turns(session_key="bounds-a", epoch=1, max_turns=2))
    assert [t.turn_seq for t in page1.turns] == [1, 2]
    assert page1.truncated is True
    assert page1.next_after_turn_seq == 2

    page2 = run(
        source.read_turns(
            session_key="bounds-a", epoch=1, max_turns=2, after_turn_seq=2
        )
    )
    assert [t.turn_seq for t in page2.turns] == [3, 4]
    assert page2.truncated is True
    assert page2.next_after_turn_seq == 4

    page3 = run(
        source.read_turns(
            session_key="bounds-a", epoch=1, max_turns=2, after_turn_seq=4
        )
    )
    assert [t.turn_seq for t in page3.turns] == [5]
    assert page3.truncated is False
    assert page3.next_after_turn_seq is None  # 末页：读到末条、未截断 → cursor=None

    # 越过末序号：空 + truncated=False + cursor=None ——「确无更多历史」，
    # 不得与「触及上限尚有未读」（truncated=True）混淆。
    page4 = run(
        source.read_turns(
            session_key="bounds-a", epoch=1, max_turns=2, after_turn_seq=5
        )
    )
    assert page4.turns == ()
    assert page4.truncated is False
    assert page4.next_after_turn_seq is None

    # 分页覆盖完整、无重叠：三页并集 == 全量，trace_id 不重复。
    seen: set[str] = set()
    for page in (page1, page2, page3):
        for turn in page.turns:
            assert turn.trace_id not in seen
            seen.add(turn.trace_id)
    assert seen == {t.trace_id for t in all_read.turns}
    run(store.close())


def test_max_bytes_bound_truncates_and_resumes(tmp_path: Path) -> None:
    # byte 上限：恰好容纳前 2 个 turn 的 max_bytes → 保留 2 条、byte_stopped、
    # truncated=True、cursor=2；放宽上限续读 → 第 3 条 truncated=False cursor=3；
    # 越过 → 空 truncated=False cursor=None。
    store = build_store(tmp_path, capture_content="full-local")
    run(store.start())
    _seed_turns(store, session_id="bounds-b", epoch=1, count=3)

    source = TrajectoryContextSource(store)
    all_read = run(source.read_turns(session_key="bounds-b", epoch=1))
    s0 = _turn_byte_size(all_read.turns[0])
    s1 = _turn_byte_size(all_read.turns[1])
    two_turn_bytes = s0 + s1

    page1 = run(
        source.read_turns(
            session_key="bounds-b", epoch=1, max_bytes=two_turn_bytes
        )
    )
    assert [t.turn_seq for t in page1.turns] == [1, 2]
    assert page1.truncated is True  # byte_stopped（第 3 turn 超余量）
    assert page1.next_after_turn_seq == 2

    page2 = run(
        source.read_turns(
            session_key="bounds-b",
            epoch=1,
            max_bytes=two_turn_bytes * 100,  # 放宽上限，足以容纳剩余 1 turn
            after_turn_seq=2,
        )
    )
    assert [t.turn_seq for t in page2.turns] == [3]
    assert page2.truncated is False
    assert page2.next_after_turn_seq is None  # 读到末条、未截断 → cursor=None

    page3 = run(
        source.read_turns(
            session_key="bounds-b",
            epoch=1,
            max_bytes=two_turn_bytes * 100,
            after_turn_seq=3,
        )
    )
    assert page3.turns == ()
    assert page3.truncated is False
    assert page3.next_after_turn_seq is None
    run(store.close())


def test_bound_too_small_to_advance_preserves_cursor(tmp_path: Path) -> None:
    # 第 3 turn 远大于 max_bytes：续读至该 turn 时一条也纳入不了，但 truncated
    # 仍为 True、cursor 保持在 after_turn_seq（未推进）。此为「bound 过小无法
    # 推进」信号——coordinator 须放大 bound 或硬停，绝不得把该 turn 当作
    # 不存在/已归档（§6.7：读取截断 ≠ 历史不存在）。
    store = build_store(tmp_path, capture_content="full-local")
    run(store.start())
    # 前 2 个 turn 常规大小；第 3 个 turn 巨大（远超任何小 bound）。
    for index in (1, 2):
        trace_id = new_trace_id()
        root = new_span_id()
        _commit_turn(
            store,
            session_id="bounds-c",
            epoch=1,
            trace_id=trace_id,
            root_span_id=root,
            started=_ts(index),
            committed=[
                (COMMITTED_INPUT, ChatMessage(role="user", content=f"问题-{index}")),
                (
                    COMMITTED_OUTPUT,
                    ChatMessage(role="assistant", content=f"回复-{index}"),
                ),
            ],
            final_output=f"回复-{index}",
        )
    big_trace = new_trace_id()
    big_root = new_span_id()
    huge_content = "巨" * 5000
    _commit_turn(
        store,
        session_id="bounds-c",
        epoch=1,
        trace_id=big_trace,
        root_span_id=big_root,
        started=_ts(3),
        committed=[
            (COMMITTED_INPUT, ChatMessage(role="user", content="巨问题")),
            (COMMITTED_OUTPUT, ChatMessage(role="assistant", content=huge_content)),
        ],
        final_output=huge_content,
    )

    source = TrajectoryContextSource(store)
    # 先用 max_turns=2 读到前 2 个 turn，cursor=2、truncated=True（尚有第 3 个）。
    page1 = run(source.read_turns(session_key="bounds-c", epoch=1, max_turns=2))
    assert [t.turn_seq for t in page1.turns] == [1, 2]
    assert page1.truncated is True
    assert page1.next_after_turn_seq == 2

    # 续读第 3 turn：max_bytes=10 远小于该 turn；纳入侧 0 + 巨量 > 10 → byte_stopped。
    page2 = run(
        source.read_turns(
            session_key="bounds-c", epoch=1, max_bytes=10, after_turn_seq=2
        )
    )
    assert page2.turns == ()
    assert page2.truncated is True  # 截断：触及 byte 上限，第 3 turn 尚未读
    # cursor 保持在 2（未推进）——与「确无更多」（cursor=None）严格区分。
    assert page2.next_after_turn_seq == 2
    run(store.close())


def test_legacy_source_pages_via_cursor(tmp_path: Path) -> None:
    # 3 个旧 trace（无 committed 事件）：LegacyTurnSource 以 max_turns=1 分页，
    # 游标随产出 turn 稳定推进；末页 truncated=False cursor=末序号；越过 → 空。
    store = build_store(tmp_path)  # redacted：legacy 不依赖可见内容 capture
    run(store.start())
    for index in range(1, 4):
        trace_id = new_trace_id()
        root = new_span_id()
        _commit_legacy_turn(
            store,
            session_id="bounds-legacy",
            epoch=1,
            trace_id=trace_id,
            root_span_id=root,
            started=_ts(index),
            user_content=f"旧问-{index}",
            assistant_content=f"旧答-{index}",
        )
    run(store.close())

    reopened = build_store(tmp_path)
    run(reopened.start())
    legacy = LegacyTurnSource(reopened)
    level = run(legacy.restoration_level("bounds-legacy", 1))
    assert level is RestorationLevel.LEGACY_INFERRED

    all_read = run(legacy.read_turns(session_key="bounds-legacy", epoch=1))
    assert len(all_read.turns) == 3
    assert all_read.truncated is False
    assert all_read.next_after_turn_seq is None
    assert [t.turn_seq for t in all_read.turns] == [1, 2, 3]

    page1 = run(legacy.read_turns(session_key="bounds-legacy", epoch=1, max_turns=1))
    assert [t.turn_seq for t in page1.turns] == [1]
    assert page1.truncated is True
    assert page1.next_after_turn_seq == 1

    page2 = run(
        legacy.read_turns(
            session_key="bounds-legacy", epoch=1, max_turns=1, after_turn_seq=1
        )
    )
    assert [t.turn_seq for t in page2.turns] == [2]
    assert page2.truncated is True
    assert page2.next_after_turn_seq == 2

    page3 = run(
        legacy.read_turns(
            session_key="bounds-legacy", epoch=1, max_turns=1, after_turn_seq=2
        )
    )
    assert [t.turn_seq for t in page3.turns] == [3]
    assert page3.truncated is False
    assert page3.next_after_turn_seq is None  # 末页：未截断 → cursor=None

    page4 = run(
        legacy.read_turns(
            session_key="bounds-legacy", epoch=1, max_turns=1, after_turn_seq=3
        )
    )
    assert page4.turns == ()
    assert page4.truncated is False
    assert page4.next_after_turn_seq is None

    seen: set[str] = set()
    for page in (page1, page2, page3):
        for turn in page.turns:
            assert turn.trace_id not in seen
            seen.add(turn.trace_id)
    assert seen == {t.trace_id for t in all_read.turns}
    run(reopened.close())


def test_in_process_source_bounds_do_not_signal_truncation() -> None:
    # 隔离来源无可读历史：即便施加 max_turns/max_bytes 也返回空 + 不截断 +
    # 无续读——这是「确无更多」（genuine empty），而非 I/O 上限命中。
    fallback = InProcessTurnSource()
    read = run(
        fallback.read_turns(
            session_key="any", epoch=1, max_turns=5, max_bytes=100
        )
    )
    assert isinstance(read, TurnRead)
    assert read.turns == ()
    assert read.truncated is False
    assert read.next_after_turn_seq is None
