"""§2.8 跨轮 committed turn reader 测试。

覆盖：重启恢复、最终响应 transform、provider blocks 排除、tool name/id/arguments/
result 相关性、损坏 payload 的 fail-closed 排除，以及 legacy-inferred 有界兼容读取。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from memoli_agent.agent.context_management.cross_turn import (
    LegacyTurnSource,
    RestorationLevel,
    TrajectoryContextSource,
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
    utc_now_iso,
)
from memoli_agent.agent.types import ChatMessage

COMMITTED_INPUT = "turn_input_committed"
COMMITTED_ASSISTANT = "assistant_message_committed"
COMMITTED_TOOL = "tool_message_committed"
COMMITTED_OUTPUT = "turn_output_committed"


def run(coroutine: Any) -> Any:  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


def build_store(  # type: ignore[no-untyped-def]
    tmp_path: Path, **kwargs: Any
) -> SQLiteTrajectoryStore:
    return SQLiteTrajectoryStore(
        tmp_path / "trajectories.db",
        payload_directory=tmp_path / "payloads",
        **kwargs,
    )


def _commit_turn(  # type: ignore[no-untyped-def]
    store: SQLiteTrajectoryStore,
    *,
    session_id: str,
    epoch: int,
    trace_id: str,
    root_span_id: str,
    committed: list[tuple[str, ChatMessage]],
    capture_mode: str = "",
    turn_seq: int = 1,
    status: str = "completed",
    final_output: str | None = None,
) -> None:
    """记录一个完整 committed turn：trace_started + committed 事件 + trace_finished。

    镜像 runtime 记录点：message_seq 按 1..N 顺序分配，turn_seq 取传入值（reader 会
    按 started_at 重新编号，存储值仅作 CommittedMessage 信息字段）。
    """

    started = utc_now_iso()
    trace = TraceProjection(
        trace_id,
        session_id,
        started,
        context_epoch=epoch,
        provider="fake",
    )
    root = SpanProjection(
        root_span_id,
        trace_id,
        None,
        SpanKind.AGENT,
        "turn",
        started,
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
        ended_at=utc_now_iso(),
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


def _finish_legacy_trace(  # type: ignore[no-untyped-def]
    store: SQLiteTrajectoryStore,
    *,
    session_id: str,
    epoch: int,
    trace_id: str,
    root_span_id: str,
    final_output: str = "",
) -> None:
    """收尾一个旧式 trace（无 committed 事件，供 legacy reader 重构）。"""

    started = utc_now_iso()
    finished = TraceProjection(
        trace_id,
        session_id,
        started,
        context_epoch=epoch,
        status="completed",
        ended_at=utc_now_iso(),
        termination_reason="completed",
        final_output=final_output,
        provider="fake",
        iteration_count=1,
    )
    run(
        store.record(
            NewTrajectoryEvent(
                trace_id=trace_id,
                span_id=root_span_id,
                event_type="trace_finished",
                payload={"final_output": final_output},
                trace=finished,
            )
        )
    )


def test_restart_recovery_restores_committed_turn(tmp_path: Path) -> None:
    # full-local capture → 恢复等级 exact；committed turn 跨重启可读、当前 trace 排除。
    store = build_store(tmp_path, capture_content="full-local")
    run(store.start())
    trace_id = new_trace_id()
    root = new_span_id()
    _commit_turn(
        store,
        session_id="session-a",
        epoch=1,
        trace_id=trace_id,
        root_span_id=root,
        committed=[
            (COMMITTED_INPUT, ChatMessage(role="user", content="你好")),
            (COMMITTED_OUTPUT, ChatMessage(role="assistant", content="回复")),
        ],
        capture_mode="full-local",
        final_output="回复",
    )
    run(store.close())

    reopened = build_store(tmp_path, capture_content="full-local")
    run(reopened.start())
    source = TrajectoryContextSource(reopened)

    level = run(source.restoration_level("session-a", 1))
    assert level is RestorationLevel.EXACT

    read = run(
        source.read_turns(session_key="session-a", epoch=1, exclude_trace_id=None)
    )
    turns = read.turns
    assert len(turns) == 1
    turn = turns[0]
    assert turn.epoch == 1
    assert turn.turn_seq == 1
    assert turn.status == "completed"
    assert turn.restoration is RestorationLevel.EXACT
    assert len(turn.messages) == 2
    messages = turn.to_messages()
    assert messages[0].role == "user"
    assert messages[0].content == "你好"
    assert messages[1].role == "assistant"
    assert messages[1].content == "回复"

    # 排除当前 trace（reader 不得把进行中的 turn 当作历史）。
    excluded = run(
        source.read_turns(
            session_key="session-a", epoch=1, exclude_trace_id=trace_id
        )
    )
    assert excluded.turns == ()
    assert excluded.truncated is False
    run(reopened.close())


def test_turn_output_reflects_transformed_content(tmp_path: Path) -> None:
    # turn_output_committed 记录变换后（post-RESPONSE_TRANSFORM）的用户可见输出，
    # 而非变换前的中间 assistant 文本。
    store = build_store(tmp_path)  # 默认 redacted
    run(store.start())
    trace_id = new_trace_id()
    root = new_span_id()
    _commit_turn(
        store,
        session_id="session-b",
        epoch=1,
        trace_id=trace_id,
        root_span_id=root,
        committed=[
            (COMMITTED_INPUT, ChatMessage(role="user", content="原始问题")),
            (COMMITTED_OUTPUT, ChatMessage(role="assistant", content="已变换回复")),
        ],
        final_output="已变换回复",
    )
    run(store.close())

    reopened = build_store(tmp_path)
    run(reopened.start())
    source = TrajectoryContextSource(reopened)
    turns = run(source.read_turns(session_key="session-b", epoch=1)).turns
    assert len(turns) == 1
    messages = turns[0].messages
    # 稳定序号：input=1，output=2，且 output 内容是变换后版本。
    assert messages[0].message_seq == 1
    assert messages[0].content == "原始问题"
    assert messages[1].message_seq == 2
    assert messages[1].content == "已变换回复"
    run(reopened.close())


def test_provider_blocks_excluded_from_envelope(tmp_path: Path) -> None:
    # 携带 provider blocks（含隐藏推理）的 ChatMessage：envelope 仅取 to_dict()，
    # blocks / 隐藏 reasoning 不得落盘或回放（§2.4）。
    blocked = ChatMessage(
        role="assistant",
        content="可见回复",
        blocks=(
            {"type": "reasoning", "text": "隐藏推理"},
            {"type": "text", "text": "可见回复"},
        ),
    )
    envelope = build_envelope(
        blocked, epoch=1, turn_seq=1, message_seq=1, capture_mode="full-local"
    )
    assert "blocks" not in envelope
    assert "reasoning" not in envelope
    assert envelope["content"] == "可见回复"

    # 落盘再读回：重构的 ChatMessage 不含 blocks，可见内容保留。
    store = build_store(tmp_path, capture_content="full-local")
    run(store.start())
    trace_id = new_trace_id()
    root = new_span_id()
    _commit_turn(
        store,
        session_id="session-c",
        epoch=1,
        trace_id=trace_id,
        root_span_id=root,
        committed=[
            (COMMITTED_INPUT, ChatMessage(role="user", content="问题")),
            (COMMITTED_OUTPUT, blocked),
        ],
        capture_mode="full-local",
        final_output="可见回复",
    )
    run(store.close())

    reopened = build_store(tmp_path, capture_content="full-local")
    run(reopened.start())
    source = TrajectoryContextSource(reopened)
    turns = run(source.read_turns(session_key="session-c", epoch=1)).turns
    assert len(turns) == 1
    output_message = turns[0].messages[-1]
    assert output_message.role == "assistant"
    assert output_message.content == "可见回复"
    rebuilt = output_message.to_chat_message()
    assert rebuilt.blocks is None
    assert "隐藏推理" not in (rebuilt.content or "")
    run(reopened.close())


def test_tool_name_id_arguments_result_round_trip(tmp_path: Path) -> None:
    # assistant tool-call 与 tool result 经 committed envelope 落盘后，name/id/
    # arguments/result 与 tool_call_id 相关性必须完整保留。
    store = build_store(tmp_path)  # redacted：常规内容不脱敏，保留工具结构
    run(store.start())
    trace_id = new_trace_id()
    root = new_span_id()
    assistant_call = ChatMessage(
        role="assistant",
        content="正在查询",
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "search",
                    "arguments": '{"query":"cat"}',
                },
            }
        ],
    )
    tool_result = ChatMessage(
        role="tool",
        content="结果: 猫",
        tool_call_id="call_1",
        name="search",
    )
    _commit_turn(
        store,
        session_id="session-d",
        epoch=1,
        trace_id=trace_id,
        root_span_id=root,
        committed=[
            (COMMITTED_INPUT, ChatMessage(role="user", content="查一下猫")),
            (COMMITTED_ASSISTANT, assistant_call),
            (COMMITTED_TOOL, tool_result),
            (COMMITTED_OUTPUT, ChatMessage(role="assistant", content="找到猫了")),
        ],
        final_output="找到猫了",
    )
    run(store.close())

    reopened = build_store(tmp_path)
    run(reopened.start())
    source = TrajectoryContextSource(reopened)
    turns = run(source.read_turns(session_key="session-d", epoch=1)).turns
    assert len(turns) == 1
    messages = turns[0].messages
    assert len(messages) == 4

    assistant = messages[1]
    assert assistant.role == "assistant"
    assert assistant.tool_calls
    call = assistant.tool_calls[0]
    assert call["id"] == "call_1"
    assert call["function"]["name"] == "search"
    assert "query" in call["function"]["arguments"]

    tool = messages[2]
    assert tool.role == "tool"
    assert tool.tool_call_id == "call_1"
    assert tool.tool_name == "search"
    assert tool.content == "结果: 猫"

    # tool-call 与 tool result 通过 tool_call_id 相关。
    assert call["id"] == tool.tool_call_id
    run(reopened.close())


def test_corrupt_payload_excludes_turn_and_degrades(tmp_path: Path) -> None:
    # 外置 payload 文件丢失 → committed envelope 不可读 → turn 标 corrupt 被
    # fail-closed 排除，恢复等级降级为 legacy-inferred（§2.5/§2.6）。
    store = build_store(
        tmp_path, capture_content="full-local", max_inline_bytes=1, max_payload_bytes=1
    )
    run(store.start())
    trace_id = new_trace_id()
    root = new_span_id()
    _commit_turn(
        store,
        session_id="session-e",
        epoch=1,
        trace_id=trace_id,
        root_span_id=root,
        committed=[
            (COMMITTED_INPUT, ChatMessage(role="user", content="会损坏的问题")),
            (COMMITTED_OUTPUT, ChatMessage(role="assistant", content="会损坏的回复")),
        ],
        capture_mode="full-local",
        final_output="会损坏的回复",
    )
    run(store.close())

    # 删除外置 payload 文件，模拟磁盘损坏。
    payloads_dir = tmp_path / "payloads"
    for path in payloads_dir.glob("*.json.zlib"):
        path.unlink()

    reopened = build_store(
        tmp_path, capture_content="full-local", max_inline_bytes=1, max_payload_bytes=1
    )
    run(reopened.start())
    source = TrajectoryContextSource(reopened)

    level = run(source.restoration_level("session-e", 1))
    assert level is RestorationLevel.LEGACY_INFERRED

    read = run(source.read_turns(session_key="session-e", epoch=1))
    assert read.turns == ()
    assert read.truncated is False
    run(reopened.close())


def test_legacy_inferred_reconstructs_old_turn(tmp_path: Path) -> None:
    # 无 committed 事件的旧 trace：LegacyTurnSource 从 model_requested/model_responded/
    # tool_finished/trace_finished 有界重构，标记 legacy-inferred，保留 tool 相关性。
    store = build_store(tmp_path)  # redacted
    run(store.start())
    trace_id = new_trace_id()
    root = new_span_id()
    started = utc_now_iso()
    trace = TraceProjection(trace_id, "session-f", started, provider="fake")
    root_span = SpanProjection(root, trace_id, None, SpanKind.AGENT, "turn", started)
    run(
        store.record(
            NewTrajectoryEvent(
                trace_id=trace_id,
                span_id=root,
                event_type="trace_started",
                payload={"content": "turn"},
                trace=trace,
                span=root_span,
            )
        )
    )
    run(
        store.record(
            NewTrajectoryEvent(
                trace_id=trace_id,
                span_id=root,
                event_type="model_requested",
                payload={
                    "messages": [{"role": "user", "content": "查猫"}]
                },
            )
        )
    )
    run(
        store.record(
            NewTrajectoryEvent(
                trace_id=trace_id,
                span_id=root,
                event_type="model_responded",
                payload={
                    "content": "正在查",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "search",
                                "arguments": '{"query":"cat"}',
                            },
                        }
                    ],
                },
            )
        )
    )
    run(
        store.record(
            NewTrajectoryEvent(
                trace_id=trace_id,
                span_id=root,
                event_type="tool_finished",
                payload={
                    "tool_call_id": "call_1",
                    "name": "search",
                    "model_content": "结果: 猫",
                },
            )
        )
    )
    _finish_legacy_trace(
        store,
        session_id="session-f",
        epoch=1,
        trace_id=trace_id,
        root_span_id=root,
        final_output="找到猫了",
    )
    run(store.close())

    reopened = build_store(tmp_path)
    run(reopened.start())
    legacy = LegacyTurnSource(reopened)

    level = run(legacy.restoration_level("session-f", 1))
    assert level is RestorationLevel.LEGACY_INFERRED

    turns = run(legacy.read_turns(session_key="session-f", epoch=1)).turns
    assert len(turns) == 1
    turn = turns[0]
    assert turn.restoration is RestorationLevel.LEGACY_INFERRED
    assert turn.degradation_reason == "legacy-inferred"
    messages = turn.messages
    # user → assistant(tool_calls) → tool(result) → assistant(final_output)
    assert messages[0].role == "user"
    assert messages[0].content == "查猫"
    assert messages[1].role == "assistant"
    assert messages[1].tool_calls
    assert messages[1].tool_calls[0]["id"] == "call_1"
    assert messages[1].tool_calls[0]["function"]["name"] == "search"
    assert messages[2].role == "tool"
    assert messages[2].tool_call_id == "call_1"
    assert messages[2].tool_name == "search"
    assert messages[2].content == "结果: 猫"
    assert messages[3].role == "assistant"
    assert messages[3].content == "找到猫了"
    run(reopened.close())


def test_in_process_source_is_unavailable() -> None:
    # 隔离的进程内来源：restorable=false，不返回跨轮历史（SubAgent 隔离，§2.6）。
    from memoli_agent.agent.context_management.cross_turn import InProcessTurnSource

    fallback = InProcessTurnSource()
    level = run(fallback.restoration_level("any", 1))
    assert level is RestorationLevel.UNAVAILABLE
    read = run(fallback.read_turns(session_key="any", epoch=1))
    assert read.turns == ()
    assert read.truncated is False
    assert read.next_after_turn_seq is None


# --------------------------------------------------------------------------- #
# §7.3 FrozenToolPreview 引用完整性恢复期校验
# --------------------------------------------------------------------------- #


def _tool_result_turn(
    *,
    tool_call_id: str = "call",
    tool_name: str = "read",
    tool_content: str = "x" * 400,
    epoch: int = 0,
) -> Any:
    """构造含 assistant tool_call + tool result 的 CommittedTurn。

    tool result 的 committed ``content_hash`` 由 ``build_envelope`` 对
    ``tool_content``（模型所见内容）计算——与冻结预览的 canonical_message_hash
    同构，故一致时二者相等、被篡改/漂移时不等。
    """

    from memoli_agent.agent.context_management.cross_turn import (
        CommittedMessage,
        CommittedTurn,
        envelope_to_committed_message,
    )

    tool_msg = ChatMessage(
        role="tool",
        content=tool_content,
        tool_call_id=tool_call_id,
        name=tool_name,
    )
    envelope = build_envelope(
        tool_msg, epoch=epoch, turn_seq=1, message_seq=2
    )
    tool_committed = envelope_to_committed_message(
        envelope, restoration=RestorationLevel.GOVERNED
    )
    assert tool_committed is not None  # 合法 envelope 必还原（收窄 Optional）
    assistant = CommittedMessage(
        turn_seq=1,
        message_seq=1,
        role="assistant",
        content="go",
        tool_calls=(
            {
                "id": tool_call_id,
                "type": "function",
                "function": {"name": tool_name, "arguments": "{}"},
            },
        ),
    )
    return CommittedTurn(
        epoch=epoch,
        turn_seq=1,
        trace_id="t1",
        status="completed",
        started_at="",
        ended_at="",
        messages=(assistant, tool_committed),
    )


def _real_preview_lookup(
    *, session_key: str = "s", tool_call_id: str = "call", epoch: int = 0
) -> Any:
    """冻结一个真实大结果预览，返回 (repo, previewer, preview)。"""

    from memoli_agent.agent.context_management import (
        ConservativeTokenEstimator,
        InMemoryContextStateRepository,
        ToolResultPreviewer,
    )

    repo = InMemoryContextStateRepository()
    previewer = ToolResultPreviewer(repo, ConservativeTokenEstimator(), 20)
    preview = previewer.freeze(
        session_key=session_key,
        tool_call_id=tool_call_id,
        tool_name="read",
        content="x" * 400,
        payload_ref="trajectory-payload:1",
        epoch=epoch,
    )
    return repo, preview


def test_verify_keeps_turn_when_preview_is_consistent() -> None:
    # §7.3 一致：committed 内容 == 冻结预览（模型所见），canonical hash 相等、
    # epoch/tool_call_id/payload_ref 一致 → 保留整 turn（含 assistant + tool pair）。
    from memoli_agent.agent.context_management.cross_turn import verify_turn_previews

    repo, preview = _real_preview_lookup()
    turn = _tool_result_turn(tool_content=preview.preview, epoch=0)
    kept = verify_turn_previews(
        turn, session_key="s", preview_lookup=repo
    )
    assert kept is not None
    assert len(kept.messages) == 2  # tool pair 未被拆散


def test_verify_excludes_whole_turn_on_canonical_hash_mismatch() -> None:
    # §7.3 canonical 不一致：committed 内容被篡改为 "tampered"（≠ 冻结预览），
    # canonical hash 不等 → 排除整个 turn（不拆 tool pair、不重生成预览）。
    from memoli_agent.agent.context_management.cross_turn import verify_turn_previews

    repo, _preview = _real_preview_lookup()
    turn = _tool_result_turn(tool_content="tampered", epoch=0)
    excluded = verify_turn_previews(
        turn, session_key="s", preview_lookup=repo
    )
    assert excluded is None  # 整 turn 排除，assistant 与 tool result 一起丢


def test_verify_skips_when_no_frozen_preview() -> None:
    # §7.3 无冻结预览（小结果未超预算，或该 tool_call_id 从未冻结）→ 跳过校验、
    # 保留 turn（不视为不一致）。
    from memoli_agent.agent.context_management.cross_turn import verify_turn_previews

    repo, _preview = _real_preview_lookup()
    # 用一个从未冻结的 tool_call_id：repo 找不到预览 → 跳过。
    turn = _tool_result_turn(
        tool_call_id="never-frozen", tool_content="raw"
    )
    kept = verify_turn_previews(
        turn, session_key="s", preview_lookup=repo
    )
    assert kept is not None


def test_verify_skips_small_untransformed_preview() -> None:
    # §7.3 小结果（transformed=False）：模型见原始内容而非预览 envelope，预览非
    # 绑定锚点 → 跳过 canonical 校验、保留 turn。
    from memoli_agent.agent.context_management import (
        ConservativeTokenEstimator,
        InMemoryContextStateRepository,
        ToolResultPreviewer,
    )
    from memoli_agent.agent.context_management.cross_turn import verify_turn_previews

    repo = InMemoryContextStateRepository()
    previewer = ToolResultPreviewer(repo, ConservativeTokenEstimator(), 20)
    preview = previewer.freeze(
        session_key="s",
        tool_call_id="call",
        tool_name="read",
        content="short",
        payload_ref="trajectory-payload:1",
        epoch=0,
    )
    assert preview.transformed is False
    turn = _tool_result_turn(tool_content="short", epoch=0)
    kept = verify_turn_previews(
        turn, session_key="s", preview_lookup=repo
    )
    assert kept is not None


def test_verify_skips_when_no_preview_lookup() -> None:
    # §7.5 无 preview_lookup（SubAgent/降级来源）→ 不校验、保持隔离，原样返回。
    from memoli_agent.agent.context_management.cross_turn import verify_turn_previews

    turn = _tool_result_turn(tool_content="anything", epoch=0)
    kept = verify_turn_previews(
        turn, session_key="s", preview_lookup=None
    )
    assert kept is turn


def test_verify_excludes_turn_on_epoch_mismatch() -> None:
    # §7.3 epoch 不一致：冻结预览 epoch=0，但 turn 处于 epoch=1（跨 epoch 泄漏
    # 场景）→ 排除整 turn。用 stub lookup 绕过 epoch 过滤以触发 epoch 校验。
    from memoli_agent.agent.context_management.cross_turn import (
        PreviewIntegrityLookup,
        verify_turn_previews,
    )

    _repo, preview = _real_preview_lookup(epoch=0)

    class _StubLookup:
        def get_preview_by_ref(
            self, session_key: str, epoch: int, tool_call_id: str
        ) -> Any:
            return preview  # 忽略查询 epoch，返回 epoch=0 预览以触发校验

    stub: PreviewIntegrityLookup = _StubLookup()  # type: ignore[assignment]
    # turn 在 epoch=1，内容与预览一致（canonical 相等）但预览 epoch=0 → 排除。
    turn = _tool_result_turn(tool_content=preview.preview, epoch=1)
    assert verify_turn_previews(
        turn, session_key="s", preview_lookup=stub
    ) is None


def test_verify_excludes_turn_on_missing_payload_ref() -> None:
    # §7.3 payload reference 缺失：预览 payload_ref 为空 → 排除整 turn
    # （canonical/epoch/tool_call_id 均一致，仅 payload_ref 失败）。
    from dataclasses import replace

    from memoli_agent.agent.context_management.cross_turn import (
        PreviewIntegrityLookup,
        verify_turn_previews,
    )

    _repo, preview = _real_preview_lookup(epoch=0)
    tampered = replace(preview, payload_ref="")

    class _StubLookup:
        def get_preview_by_ref(
            self, session_key: str, epoch: int, tool_call_id: str
        ) -> Any:
            return tampered

    stub: PreviewIntegrityLookup = _StubLookup()  # type: ignore[assignment]
    turn = _tool_result_turn(tool_content=preview.preview, epoch=0)
    assert verify_turn_previews(
        turn, session_key="s", preview_lookup=stub
    ) is None
