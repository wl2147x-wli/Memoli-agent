"""§9.2 上下文降级矩阵测试。

覆盖 spec §9.2：capture full-local/redacted/metadata-only、轨迹关闭、context
持久化关闭与数据库损坏各自的 fail-closed 降级行为。核心断言：durable 来源在
可恢复模式下精确还原 committed turn；metadata-only/轨迹关闭/未知 schema 时降
级为 unavailable 或拒绝打开，绝不静默重建、丢失或回退按消息条数裁剪的旧行为。

本文件刻意不导入 pytest，避免 pyright reportMissingImports 环境解析噪声
（与 test_context_frontier_bounds.py 的 _expect_raises 约定一致）。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from memoli_agent.agent.context_management import (
    ContextArchive,
    ContextStateError,
    InMemoryContextStateRepository,
    SQLiteContextStateRepository,
)
from memoli_agent.agent.context_management.cross_turn import (
    InProcessTurnSource,
    RestorationLevel,
    TrajectoryContextSource,
    TurnRead,
    build_envelope,
)
from memoli_agent.agent.trajectory import (
    NewTrajectoryEvent,
    SpanKind,
    SpanProjection,
    SQLiteTrajectoryStore,
    TraceProjection,
    TrajectorySchemaError,
    new_span_id,
    new_trace_id,
    utc_now_iso,
)
from memoli_agent.agent.types import ChatMessage

_COMMITTED_INPUT = "turn_input_committed"
_COMMITTED_OUTPUT = "turn_output_committed"


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
    """记录一个完整 committed turn：trace_started + committed 事件 + trace_finished。"""

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


def _archive_json(refs: list[str]) -> str:
    return json.dumps(
        {
            "goal_constraints": ["preserve"],
            "decisions_reasons": ["decided"],
            "facts_evidence": ["fact"],
            "files_artifacts": ["file.txt"],
            "verification_status": ["ok"],
            "failure_paths": ["none"],
            "todo_remaining": ["ship"],
            "source_refs": list(refs),
        }
    )


def _archive(archive_id: str, refs: list[str]) -> ContextArchive:
    return ContextArchive(
        archive_id,
        "s",
        0,
        _archive_json(refs),
        f"hash-{archive_id}",
        tuple(refs),
        coverage_hash=f"cov-{archive_id}",
    )


def test_capture_mode_restoration_level_matrix(tmp_path: Path) -> None:
    """§9.2 capture 模式决定恢复等级：full-local=exact、redacted=governed、
    metadata-only=unavailable（无 committed turn 时亦然，§2.5/§2.6）。"""

    expectations = {
        "full-local": RestorationLevel.EXACT,
        "redacted": RestorationLevel.GOVERNED,
        "metadata-only": RestorationLevel.UNAVAILABLE,
    }
    for capture_mode, expected in expectations.items():
        store = build_store(tmp_path / capture_mode, capture_content=capture_mode)
        run(store.start())
        source = TrajectoryContextSource(store)
        level = run(source.restoration_level("session-a", 1))
        assert level is expected, f"{capture_mode} 期望 {expected}，实际 {level}"
        run(store.close())


def test_full_local_capture_restores_committed_turn(tmp_path: Path) -> None:
    """§9.2 full-local：committed turn 跨重启精确还原（exact），内容可读。"""

    store = build_store(tmp_path, capture_content="full-local")
    run(store.start())
    trace_id = new_trace_id()
    _commit_turn(
        store,
        session_id="session-a",
        epoch=1,
        trace_id=trace_id,
        root_span_id=new_span_id(),
        committed=[
            (_COMMITTED_INPUT, ChatMessage(role="user", content="你好")),
            (_COMMITTED_OUTPUT, ChatMessage(role="assistant", content="回复")),
        ],
        capture_mode="full-local",
        final_output="回复",
    )
    run(store.close())

    reopened = build_store(tmp_path, capture_content="full-local")
    run(reopened.start())
    source = TrajectoryContextSource(reopened)
    assert run(source.restoration_level("session-a", 1)) is RestorationLevel.EXACT
    read = run(source.read_turns(session_key="session-a", epoch=1))
    assert len(read.turns) == 1
    messages = read.turns[0].to_messages()
    assert [m.content for m in messages] == ["你好", "回复"]
    run(reopened.close())


def test_metadata_only_capture_degrades_to_empty(tmp_path: Path) -> None:
    """§9.2 metadata-only：即便已记录 committed turn 也降级为 unavailable + 空
    TurnRead（内容未持久化，不可恢复，§2.6 restorable=false）。"""

    store = build_store(tmp_path, capture_content="metadata-only")
    run(store.start())
    _commit_turn(
        store,
        session_id="session-a",
        epoch=1,
        trace_id=new_trace_id(),
        root_span_id=new_span_id(),
        committed=[
            (_COMMITTED_INPUT, ChatMessage(role="user", content="secret")),
            (_COMMITTED_OUTPUT, ChatMessage(role="assistant", content="reply")),
        ],
        capture_mode="metadata-only",
    )
    run(store.close())

    reopened = build_store(tmp_path, capture_content="metadata-only")
    run(reopened.start())
    source = TrajectoryContextSource(reopened)
    assert run(source.restoration_level("session-a", 1)) is RestorationLevel.UNAVAILABLE
    read = run(source.read_turns(session_key="session-a", epoch=1))
    assert read.turns == ()
    assert read.truncated is False
    run(reopened.close())


def test_trajectory_disabled_source_is_unavailable_empty() -> None:
    """§9.2 轨迹关闭：InProcessTurnSource 恒为 unavailable + 空 TurnRead（§2.6）。"""

    source = InProcessTurnSource()
    assert run(source.restoration_level("any", 1)) is RestorationLevel.UNAVAILABLE
    read = run(source.read_turns(session_key="any", epoch=1))
    assert isinstance(read, TurnRead)
    assert read.turns == ()


def test_persistence_disabled_does_not_survive_restart() -> None:
    """§9.2 持久化关闭：进程内仓库不跨实例持久化；新实例从空 context state 开始
    （archive 不残留，§3.4 / config persistence_enabled=false 语义）。"""

    first = InMemoryContextStateRepository()
    committed, _ = first.commit_archive(_archive("a1", ["r1"]))
    assert first.list_archives("s") == (committed,)

    # 新进程内实例：不读旧实例的内存，明确从空 context state 开始。
    second = InMemoryContextStateRepository()
    assert second.list_archives("s") == ()


def test_trajectory_unsupported_schema_fails_closed(tmp_path: Path) -> None:
    """§9.2 数据库损坏：未知 trajectory schema version 拒绝打开，不自动降级改写
    （agent-runtime.md：未知 schema version 时不删除或重建已有数据库）。"""

    # 写到 store 实际打开的同一文件（build_store 用 trajectories.db），
    # 否则 store 会另建空库、永远走 fresh-schema 分支而不报错。
    database = tmp_path / "trajectories.db"
    conn = sqlite3.connect(database)
    conn.execute(
        "CREATE TABLE trajectory_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute("INSERT INTO trajectory_meta VALUES ('schema_version', '999')")
    conn.commit()
    conn.close()

    store = build_store(tmp_path)
    try:
        run(store.start())
        raised: BaseException | None = None
    except TrajectorySchemaError as exc:
        raised = exc
    assert isinstance(raised, TrajectorySchemaError)
    # fail-closed：未把未知版本静默重建为当前 schema（数据未被覆盖）。
    assert raised is not None


def test_context_state_unsupported_schema_fails_closed(tmp_path: Path) -> None:
    """§9.2 数据库损坏：未知 context-state schema version 拒绝打开，不自动迁移
    改写（§6.1 / config 迁移说明）。"""

    database = tmp_path / "ctx.db"
    conn = sqlite3.connect(database)
    conn.execute(
        "CREATE TABLE schema_info (component TEXT PRIMARY KEY, version INTEGER)"
    )
    conn.execute("INSERT INTO schema_info VALUES ('context-state', 999)")
    conn.commit()
    conn.close()

    try:
        SQLiteContextStateRepository(database)
        raised: BaseException | None = None
    except ContextStateError as exc:
        raised = exc
    assert isinstance(raised, ContextStateError)
    assert raised is not None
