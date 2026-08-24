"""Persistent, non-blocking trigger coordination for offline memory learning."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from memoli_agent.agent.memory.models import (
    MemoryScope,
    TurnClassification,
)
from memoli_agent.agent.memory.source import TrajectorySourceReader
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore
from memoli_agent.agent.tools.registry import tool_purpose


@dataclass(frozen=True, slots=True)
class LongTaskCompletionClassifier:
    source_reader: TrajectorySourceReader
    min_business_tool_calls: int = 10
    min_distinct_business_tools: int = 2
    min_elapsed_seconds: int = 60

    async def classify(self, trace_id: str) -> TurnClassification:
        bundle = await self.source_reader.trajectory.get_trace(trace_id)
        if bundle is None:
            return TurnClassification(
                trace_id, "", "ineligible", False, reason="missing"
            )
        trace = bundle["trace"]
        session_id = str(trace.get("session_id") or "")
        completed = bool(
            trace.get("status") == "completed"
            and trace.get("termination_reason") == "completed"
            and trace.get("ended_at")
            and any(
                event.get("event_type") == "trace_finished"
                for event in bundle["events"]
            )
        )
        if not completed:
            return TurnClassification(
                trace_id, session_id, "ineligible", False, reason="not-completed"
            )
        elapsed = max(
            0.0,
            (
                datetime.fromisoformat(str(trace["ended_at"]))
                - datetime.fromisoformat(str(trace["started_at"]))
            ).total_seconds(),
        )
        successful: dict[str, str] = {}
        for event in bundle["events"]:
            if event.get("event_type") != "tool_finished":
                continue
            payload = await self._payload(event.get("payload_id"))
            if not isinstance(payload, dict):
                continue
            call_id = str(payload.get("tool_call_id") or "")
            name = str(payload.get("name") or "")
            status = str(payload.get("status") or "")
            if (
                not call_id
                or not name
                or payload.get("success") is not True
                or status in {"error", "failed", "cancelled", "confirmation_required"}
                or tool_purpose(name) != "business"
            ):
                continue
            successful.setdefault(call_id, name)
        calls = len(successful)
        kinds = len(set(successful.values()))
        long_task = calls >= self.min_business_tool_calls and (
            kinds >= self.min_distinct_business_tools
            or elapsed >= self.min_elapsed_seconds
        )
        return TurnClassification(
            trace_id,
            session_id,
            "long-task" if long_task else "chat",
            True,
            successful_business_tool_calls=calls,
            distinct_business_tool_kinds=kinds,
            elapsed_seconds=elapsed,
            reason="threshold-met" if long_task else "ordinary-completed-turn",
        )

    async def _payload(self, payload_id: Any) -> Any:
        if payload_id is None:
            return {}
        return await self.source_reader.trajectory.read_payload_json(int(payload_id))


@dataclass(slots=True)
class TriggerCoordinator:
    store: SQLiteMemoryStore
    source_reader: TrajectorySourceReader
    version_fingerprint: str
    chat_turn_threshold: int = 20
    long_task_min_business_tool_calls: int = 10
    long_task_min_distinct_business_tools: int = 2
    long_task_min_elapsed_seconds: int = 60
    max_attempts: int = 5
    consumer: str = "offline-memory-v2"

    async def tick(self) -> dict[str, Any]:
        scope = MemoryScope()
        baseline = self.store.get_offline_checkpoint(
            scope, consumer="trace-consumption-baseline"
        )
        traces = await self.source_reader.trajectory.query_traces(
            termination_reason="completed"
        )
        eligible = sorted(
            (
                trace
                for trace in traces
                if _trace_cursor(trace) > baseline
                and str(trace.get("session_id") or "").startswith("cli:")
            ),
            key=_trace_cursor,
        )
        classifier = LongTaskCompletionClassifier(
            self.source_reader,
            self.long_task_min_business_tool_calls,
            self.long_task_min_distinct_business_tools,
            self.long_task_min_elapsed_seconds,
        )
        observed = long_task_enqueued = chat_windows_enqueued = 0
        sessions: set[str] = set()
        recent_trigger_kind: str | None = None
        for trace in eligible:
            trace_id = str(trace["trace_id"])
            classification = await classifier.classify(trace_id)
            if not classification.completed or classification.kind == "ineligible":
                continue
            started_at = datetime.fromisoformat(str(trace["started_at"]))
            before = self.store.get_trace_consumption(trace_id, consumer=self.consumer)
            consumption = self.store.observe_completed_trace(
                classification,
                scope,
                trace_started_at=started_at,
                consumer=self.consumer,
            )
            if before is None and consumption is not None:
                observed += 1
            sessions.add(classification.session_id)
            if classification.kind == "long-task":
                request = self.store.reserve_trigger_request(
                    trigger_kind="long-task",
                    scope=scope,
                    session_id=classification.session_id,
                    trace_ids=(trace_id,),
                    version_fingerprint=self.version_fingerprint,
                    idempotency_key=f"long-task:{self.consumer}:{trace_id}",
                    priority=100,
                    max_attempts=self.max_attempts,
                    consumer=self.consumer,
                )
                if request is not None and before is None:
                    long_task_enqueued += 1
                    recent_trigger_kind = "long-task"
                    self.store.satisfy_update_intents(
                        scope, classification.session_id
                    )
        for session_id in sorted(sessions):
            while True:
                pending = self.store.pending_chat_consumptions(
                    scope,
                    session_id,
                    limit=self.chat_turn_threshold,
                    consumer=self.consumer,
                )
                if len(pending) < self.chat_turn_threshold:
                    break
                trace_ids = tuple(item.trace_id for item in pending)
                identity = hashlib.sha256("\0".join(trace_ids).encode()).hexdigest()
                request = self.store.reserve_trigger_request(
                    trigger_kind="chat-window",
                    scope=scope,
                    session_id=session_id,
                    trace_ids=trace_ids,
                    version_fingerprint=self.version_fingerprint,
                    idempotency_key=f"chat-window:{self.consumer}:{session_id}:{identity}",
                    max_attempts=self.max_attempts,
                    consumer=self.consumer,
                )
                if request is None:
                    break
                chat_windows_enqueued += 1
                recent_trigger_kind = "chat-window"
                self.store.satisfy_update_intents(scope, session_id)
        return {
            "observed": observed,
            "long_task_enqueued": long_task_enqueued,
            "chat_windows_enqueued": chat_windows_enqueued,
            "recent_trigger_kind": recent_trigger_kind,
            "sessions": {
                session_id: self.store.pending_chat_count(
                    scope, session_id, consumer=self.consumer
                )
                for session_id in sorted(sessions)
            },
        }


def _trace_cursor(trace: dict[str, Any]) -> str:
    return f"{str(trace.get('started_at') or '')}|{str(trace.get('trace_id') or '')}"
