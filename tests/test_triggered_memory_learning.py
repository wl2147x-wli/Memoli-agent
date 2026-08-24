from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from memoli_agent.agent.memory.extraction import DeterministicCandidateExtractor
from memoli_agent.agent.memory.models import MemoryScope, TurnClassification
from memoli_agent.agent.memory.source import TrajectorySourceReader
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore
from memoli_agent.agent.memory.triggers import (
    LongTaskCompletionClassifier,
    TriggerCoordinator,
)
from memoli_agent.agent.trajectory import (
    NewTrajectoryEvent,
    SpanKind,
    SpanProjection,
    SQLiteTrajectoryStore,
    TraceProjection,
)
from memoli_agent.bootstrap.config import MemoryOfflineConfig


async def _trajectory_store(tmp_path: Path) -> SQLiteTrajectoryStore:
    store = SQLiteTrajectoryStore(
        tmp_path / "trajectories.db",
        payload_directory=tmp_path / "payloads",
        capture_content="redacted",
    )
    await store.start()
    return store


async def _record_trace(
    store: SQLiteTrajectoryStore,
    trace_id: str,
    *,
    session_id: str = "cli:local",
    current: str = "普通问题",
    history: tuple[str, ...] = (),
    tools: tuple[tuple[str, str, bool], ...] = (),
    elapsed_seconds: int = 1,
) -> None:
    started_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(
        seconds=int(trace_id[-6:], 16)
    )
    ended_at = started_at + timedelta(seconds=elapsed_seconds)
    span_id = f"s{trace_id:0>15}"[-16:]
    messages = [
        {"role": "user", "content": content} for content in (*history, current)
    ]
    message_index = len(messages) - 1
    message_id = f"msg-{trace_id}"
    await store.record(
        NewTrajectoryEvent(
            trace_id,
            "trace_started",
            {
                "session_id": session_id,
                "current_user_message_id": message_id,
                "current_user_message_index": message_index,
            },
            span_id=span_id,
            trace=TraceProjection(trace_id, session_id, started_at.isoformat()),
            span=SpanProjection(
                span_id,
                trace_id,
                None,
                SpanKind.AGENT,
                "turn",
                started_at.isoformat(),
                input_data={
                    "messages": messages,
                    "current_user_message_id": message_id,
                    "current_user_message_index": message_index,
                },
            ),
        )
    )
    for call_id, name, success in tools:
        await store.record(
            NewTrajectoryEvent(
                trace_id,
                "tool_finished",
                {
                    "tool_call_id": call_id,
                    "name": name,
                    "success": success,
                    "status": "success" if success else "error",
                },
                span_id=span_id,
            )
        )
    await store.record(
        NewTrajectoryEvent(
            trace_id,
            "trace_finished",
            {"status": "completed"},
            span_id=span_id,
            trace=TraceProjection(
                trace_id,
                session_id,
                started_at.isoformat(),
                status="completed",
                ended_at=ended_at.isoformat(),
                termination_reason="completed",
            ),
            span=SpanProjection(
                span_id,
                trace_id,
                None,
                SpanKind.AGENT,
                "turn",
                started_at.isoformat(),
                status="completed",
                ended_at=ended_at.isoformat(),
            ),
        )
    )


def test_offline_trigger_config_defaults_and_positive_validation() -> None:
    config = MemoryOfflineConfig()
    assert config.chat_turn_threshold == 20
    assert config.long_task_min_business_tool_calls == 10
    assert config.long_task_min_distinct_business_tools == 2
    assert config.long_task_min_elapsed_seconds == 60
    assert config.dead_letter_stale_after_seconds == 86_400
    with pytest.raises(ValueError):
        MemoryOfflineConfig(long_task_min_business_tool_calls=0)


def test_schema_migrates_checkpoint_to_non_replay_baseline(tmp_path: Path) -> None:
    database = tmp_path / "memory.db"
    store = SQLiteMemoryStore(database)
    store._connection.execute(  # noqa: SLF001
        "INSERT INTO offline_memory_checkpoints VALUES "
        "('user','default','trajectory-auto-scan','2026|trace','2026')"
    )
    store._connection.execute("PRAGMA user_version = 4")  # noqa: SLF001
    store._connection.commit()  # noqa: SLF001
    store.close()

    migrated = SQLiteMemoryStore(database)
    try:
        assert migrated._connection.execute(  # noqa: SLF001
            "PRAGMA user_version"
        ).fetchone()[0] == 7
        assert (
            migrated.get_offline_checkpoint(
                MemoryScope(), consumer="trace-consumption-baseline"
            )
            == "2026|trace"
        )
    finally:
        migrated.close()


def test_current_user_source_and_deterministic_atomic_extraction(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        trajectory = await _trajectory_store(tmp_path)
        try:
            current = (
                "请记住：我对花生过敏。\n"
                "remember: I use Go.\n"
                "记住：我的目标是学习 Rust。\n"
                "remember: I prefer a dark editor.\n"
                "普通问题？"
            )
            await _record_trace(
                trajectory,
                "1" * 32,
                history=("记住：这条历史不应重复",),
                current=current,
            )
            source = await TrajectorySourceReader(trajectory).read_current_user_turn(
                "1" * 32, MemoryScope(), expected_session_id="cli:local"
            )
            assert source.content == current
            assert source.message_id == "msg-" + "1" * 32
            drafts = await DeterministicCandidateExtractor().extract((source,))
            assert [item.content for item in drafts] == [
                "我对花生过敏。",
                "I use Go.",
                "我的目标是学习 Rust。",
                "I prefer a dark editor.",
            ]
            for draft in drafts:
                locator = draft.evidence[0]
                assert source.content[locator.start_offset : locator.end_offset] == (
                    locator.quote
                )
            ordinary = source.__class__(
                **{
                    name: getattr(source, name)
                    for name in source.__dataclass_fields__
                    if name != "content"
                },
                content="你能帮我吗？",
            )
            assert await DeterministicCandidateExtractor().extract((ordinary,)) == ()
        finally:
            await trajectory.close()

    asyncio.run(scenario())


def test_long_task_classifier_counts_unique_successful_business_tools(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        trajectory = await _trajectory_store(tmp_path)
        try:
            business = tuple(
                (f"call-{index}", "file_read" if index < 5 else "code_run", True)
                for index in range(10)
            )
            await _record_trace(trajectory, "2" * 32, tools=business)
            await _record_trace(trajectory, "3" * 32, tools=business[:9])
            one_kind = tuple((f"one-{index}", "file_read", True) for index in range(10))
            await _record_trace(trajectory, "4" * 32, tools=one_kind)
            await _record_trace(
                trajectory, "5" * 32, tools=one_kind, elapsed_seconds=60
            )
            noisy = business + (
                ("call-0", "file_read", True),
                ("internal", "memory_manage", True),
                ("failed", "code_run", False),
            )
            await _record_trace(trajectory, "6" * 32, tools=noisy)
            classifier = LongTaskCompletionClassifier(
                TrajectorySourceReader(trajectory)
            )
            assert (await classifier.classify("2" * 32)).kind == "long-task"
            assert (await classifier.classify("3" * 32)).kind == "chat"
            assert (await classifier.classify("4" * 32)).kind == "chat"
            assert (await classifier.classify("5" * 32)).kind == "long-task"
            classified = await classifier.classify("6" * 32)
            assert classified.successful_business_tool_calls == 10
        finally:
            await trajectory.close()

    asyncio.run(scenario())


def test_trigger_coordinator_uses_fixed_window_and_long_task_priority(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        trajectory = await _trajectory_store(tmp_path)
        memory = SQLiteMemoryStore(tmp_path / "memory.db")
        try:
            for index in range(1, 20):
                await _record_trace(trajectory, f"{index:032x}")
            coordinator = TriggerCoordinator(
                memory,
                TrajectorySourceReader(trajectory),
                "extractor-v2",
            )
            first = await coordinator.tick()
            assert first["chat_windows_enqueued"] == 0
            assert memory.pending_chat_count(MemoryScope(), "cli:local") == 19

            tools = tuple(
                (f"call-{index}", "file_read" if index < 5 else "code_run", True)
                for index in range(10)
            )
            await _record_trace(trajectory, f"{20:032x}", tools=tools)
            second = await coordinator.tick()
            assert second["long_task_enqueued"] == 1
            requests = memory.list_long_term_update_requests(MemoryScope())
            assert [item.source_type for item in requests] == ["long-task"]
            assert memory.pending_chat_count(MemoryScope(), "cli:local") == 19

            await _record_trace(trajectory, f"{21:032x}")
            third = await coordinator.tick()
            assert third["chat_windows_enqueued"] == 1
            requests = memory.list_long_term_update_requests(MemoryScope())
            assert {item.source_type for item in requests} == {
                "long-task",
                "chat-window",
            }
            chat = next(item for item in requests if item.source_type == "chat-window")
            assert len(chat.trace_ids) == 20
            for index in range(22, 42):
                await _record_trace(trajectory, f"{index:032x}")
            fourth = await coordinator.tick()
            assert fourth["chat_windows_enqueued"] == 1
            assert sum(
                item.source_type == "chat-window"
                for item in memory.list_long_term_update_requests(MemoryScope())
            ) == 2
        finally:
            memory.close()
            await trajectory.close()

    asyncio.run(scenario())


def test_reservation_quarantine_suppress_and_force_release_are_audited(
    tmp_path: Path,
) -> None:
    memory = SQLiteMemoryStore(tmp_path / "memory.db")
    try:
        classification = TurnClassification(
            "a" * 32, "cli:local", "chat", True
        )
        memory.observe_completed_trace(
            classification,
            MemoryScope(),
            trace_started_at=datetime.now(UTC),
        )
        first_hint = memory.create_update_intent(
            MemoryScope(), "cli:local", "same-boundary"
        )
        repeated_hint = memory.create_update_intent(
            MemoryScope(), "cli:local", "same-boundary"
        )
        assert repeated_hint.hint_id == first_hint.hint_id
        request = memory.reserve_trigger_request(
            trigger_kind="chat-window",
            scope=MemoryScope(),
            session_id="cli:local",
            trace_ids=("a" * 32,),
            version_fingerprint="v2",
            idempotency_key="window-one",
            max_attempts=1,
        )
        assert request is not None
        claimed = memory.claim_long_term_update_requests(
            worker_id="worker", limit=1, lease_seconds=30
        )[0]
        assert (
            memory.fail_long_term_update_request(
                claimed.request_id,
                worker_id="worker",
                error_type="TrajectorySourceError",
                permanent=True,
            )
            == "quarantined"
        )
        assert memory.get_trace_consumption("a" * 32).state == "quarantined"  # type: ignore[union-attr]
        memory._connection.execute(  # noqa: SLF001
            "UPDATE long_term_update_requests SET updated_at=? WHERE request_id=?",
            ((datetime.now(UTC) - timedelta(days=2)).isoformat(), claimed.request_id),
        )
        memory._connection.commit()  # noqa: SLF001
        assert memory.offline_diagnostics()["stale_dead_letter"] == 1
        assert memory.get_trace_consumption("a" * 32).state == "quarantined"  # type: ignore[union-attr]
        assert memory.retry_long_term_update_request(
            claimed.request_id, MemoryScope()
        )
        assert memory.get_trace_consumption("a" * 32).state == "reserved"  # type: ignore[union-attr]
        retried = memory.claim_long_term_update_requests(
            worker_id="worker-2", limit=1, lease_seconds=30
        )[0]
        memory.fail_long_term_update_request(
            retried.request_id,
            worker_id="worker-2",
            error_type="TrajectorySourceError",
            permanent=True,
        )
        assert memory.cancel_long_term_update_request(claimed.request_id, MemoryScope())
        assert memory.get_trace_consumption("a" * 32).state == "suppressed"  # type: ignore[union-attr]
        with pytest.raises(ValueError):
            memory.force_release_long_term_update_request(
                claimed.request_id, MemoryScope(), actor="", reason=""
            )
        assert memory.force_release_long_term_update_request(
            claimed.request_id,
            MemoryScope(),
            actor="operator:test",
            reason="manual-recovery",
        )
        assert memory.get_trace_consumption("a" * 32).state == "released"  # type: ignore[union-attr]
        assert memory._connection.execute(  # noqa: SLF001
            "SELECT 1 FROM memory_revisions WHERE entity_id=? "
            "AND action='force-release'",
            (claimed.request_id,),
        ).fetchone()
    finally:
        memory.close()
