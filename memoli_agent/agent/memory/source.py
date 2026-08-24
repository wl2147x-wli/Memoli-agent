"""从已提交 SQLite trajectory 构造只读、可验证的离线学习输入。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from memoli_agent.agent.memory.models import (
    CandidateDraft,
    EvidenceRef,
    MemoryScope,
    SourceSegment,
)
from memoli_agent.agent.trajectory import SQLiteTrajectoryStore


class TrajectorySourceError(RuntimeError):
    """轨迹不存在、不完整、越权或无法安全解析。"""


class EvidenceVerificationError(ValueError):
    """Extractor 给出的定位器无法由权威轨迹证明。"""


_SENSITIVE_PATTERN = re.compile(
    r"(?i)(password|api[_ -]?key|authorization|身份证|银行卡|密码|令牌|"
    r"医疗|诊断|法律意见|精确地址)"
)


@dataclass(frozen=True, slots=True)
class MemoryContentPolicy:
    """分别决定 prompt 与 embedding 的最小本地策略。"""

    prompt_max_sensitivity: str = "private"
    embedding_max_sensitivity: str = "private"

    def classify(self, content: str) -> str:
        if "REDACTED" in content or _SENSITIVE_PATTERN.search(content):
            return "sensitive"
        return "private"

    def prompt_allowed(self, sensitivity: str) -> bool:
        return _level(sensitivity) <= _level(self.prompt_max_sensitivity)

    def embedding_allowed(self, sensitivity: str) -> bool:
        return _level(sensitivity) <= _level(self.embedding_max_sensitivity)


@dataclass(frozen=True, slots=True)
class TrajectorySourceReader:
    trajectory: SQLiteTrajectoryStore
    policy: MemoryContentPolicy = MemoryContentPolicy()

    async def read_traces(
        self,
        trace_ids: tuple[str, ...],
        scope: MemoryScope,
        *,
        expected_session_id: str = "",
    ) -> tuple[SourceSegment, ...]:
        segments: list[SourceSegment] = []
        for trace_id in tuple(dict.fromkeys(trace_ids)):
            segments.extend(
                await self.read_trace(
                    trace_id,
                    scope,
                    expected_session_id=expected_session_id,
                )
            )
        return tuple(segments)

    async def read_current_user_turns(
        self,
        trace_ids: tuple[str, ...],
        scope: MemoryScope,
        *,
        expected_session_id: str = "",
    ) -> tuple[SourceSegment, ...]:
        segments: list[SourceSegment] = []
        for trace_id in tuple(dict.fromkeys(trace_ids)):
            segments.append(
                await self.read_current_user_turn(
                    trace_id, scope, expected_session_id=expected_session_id
                )
            )
        return tuple(segments)

    async def read_current_user_turn(
        self,
        trace_id: str,
        scope: MemoryScope,
        *,
        expected_session_id: str = "",
    ) -> SourceSegment:
        bundle = await self.trajectory.get_trace(trace_id)
        if bundle is None:
            raise TrajectorySourceError("trajectory-not-found")
        trace = bundle["trace"]
        if not _is_complete(bundle):
            raise TrajectorySourceError("trajectory-incomplete")
        session_id = str(trace.get("session_id") or "")
        if expected_session_id and session_id != expected_session_id:
            raise TrajectorySourceError("trajectory-session-mismatch")
        if not _scope_allows(scope, session_id):
            raise TrajectorySourceError("trajectory-scope-forbidden")
        root = next(
            (span for span in bundle["spans"] if span.get("kind") == "agent"), None
        )
        if root is None:
            raise TrajectorySourceError("current-user-message-not-found")
        data = await self._payload(root.get("input_payload_id"))
        if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
            raise TrajectorySourceError("current-user-message-not-found")
        messages = data["messages"]
        index_value = data.get("current_user_message_index")
        message_id = str(data.get("current_user_message_id") or "")
        selection = "envelope"
        index: int | None = None
        if isinstance(index_value, int) and 0 <= index_value < len(messages):
            candidate = messages[index_value]
            if isinstance(candidate, dict) and candidate.get("role") == "user":
                index = index_value
        if index is None:
            index = next(
                (
                    item
                    for item in range(len(messages) - 1, -1, -1)
                    if isinstance(messages[item], dict)
                    and messages[item].get("role") == "user"
                ),
                None,
            )
            selection = "legacy-last-user"
        if index is None:
            raise TrajectorySourceError("current-user-message-not-found")
        content = str(messages[index].get("content") or "").strip()
        if not content:
            raise TrajectorySourceError("current-user-message-empty")
        message_id = message_id or f"{trace_id}:message:{index}"
        sensitivity = self.policy.classify(content)
        return SourceSegment(
            trace_id=trace_id,
            session_id=session_id,
            message_id=message_id,
            role="user",
            sequence=index,
            occurred_at=_parse_time(str(trace.get("started_at") or "")),
            content=content,
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            scope=scope,
            sensitivity=sensitivity,
            prompt_allowed=self.policy.prompt_allowed(sensitivity),
            embedding_allowed=self.policy.embedding_allowed(sensitivity),
            selection=selection,
        )

    async def read_trace(
        self,
        trace_id: str,
        scope: MemoryScope,
        *,
        expected_session_id: str = "",
    ) -> tuple[SourceSegment, ...]:
        bundle = await self.trajectory.get_trace(trace_id)
        if bundle is None:
            raise TrajectorySourceError("trajectory-not-found")
        trace = bundle["trace"]
        if not _is_complete(bundle):
            raise TrajectorySourceError("trajectory-incomplete")
        session_id = str(trace.get("session_id") or "")
        if expected_session_id and session_id != expected_session_id:
            raise TrajectorySourceError("trajectory-session-mismatch")
        if not _scope_allows(scope, session_id):
            raise TrajectorySourceError("trajectory-scope-forbidden")

        occurred_at = str(trace.get("started_at") or "")
        root = next(
            (span for span in bundle["spans"] if span.get("kind") == "agent"), None
        )
        raw: list[tuple[str, str, str, int]] = []
        if root is not None:
            data = await self._payload(root.get("input_payload_id"))
            if isinstance(data, dict) and isinstance(data.get("messages"), list):
                for index, message in enumerate(data["messages"]):
                    if not isinstance(message, dict):
                        continue
                    content = str(message.get("content") or "").strip()
                    if content:
                        raw.append(
                            (
                                f"{trace_id}:message:{index}",
                                str(message.get("role") or "unknown"),
                                content,
                                index,
                            )
                        )
            elif isinstance(data, dict) and str(data.get("content") or "").strip():
                raw.append(
                    (
                        f"{trace_id}:root-content",
                        "user",
                        str(data["content"]).strip(),
                        0,
                    )
                )
        for event in bundle["events"]:
            if event.get("event_type") != "tool_finished":
                continue
            payload = await self._payload(event.get("payload_id"))
            if not isinstance(payload, dict):
                continue
            content = str(
                payload.get("raw_content") or payload.get("model_content") or ""
            ).strip()
            if content:
                sequence = int(event["sequence"])
                raw.append((f"{trace_id}:event:{sequence}", "tool", content, sequence))
        final_payload = trace.get("final_output_payload_id")
        if final_payload is not None:
            content = str(await self._payload(final_payload) or "").strip()
            if content:
                sequence = max(
                    (int(event["sequence"]) for event in bundle["events"]),
                    default=len(raw),
                )
                raw.append((f"{trace_id}:final", "assistant", content, sequence))

        segments: list[SourceSegment] = []
        for message_id, role, content, sequence in raw:
            sensitivity = self.policy.classify(content)
            segments.append(
                SourceSegment(
                    trace_id=trace_id,
                    session_id=session_id,
                    message_id=message_id,
                    role=role,
                    sequence=sequence,
                    occurred_at=_parse_time(occurred_at),
                    content=content,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(),
                    scope=scope,
                    sensitivity=sensitivity,
                    prompt_allowed=self.policy.prompt_allowed(sensitivity),
                    embedding_allowed=self.policy.embedding_allowed(sensitivity),
                )
            )
        return tuple(
            sorted(segments, key=lambda item: (item.sequence, item.message_id))
        )

    async def _payload(self, payload_id: Any) -> Any:
        return (
            {}
            if payload_id is None
            else await self.trajectory.read_payload_json(int(payload_id))
        )


@dataclass(frozen=True, slots=True)
class EvidenceVerifier:
    """在提交 Candidate 前逐项回查不可变 Source Segment。"""

    def verify(
        self,
        candidate: CandidateDraft,
        sources: tuple[SourceSegment, ...],
        scope: MemoryScope,
    ) -> tuple[EvidenceRef, ...]:
        if not candidate.evidence:
            raise EvidenceVerificationError("evidence-required")
        source_map = {(item.trace_id, item.message_id): item for item in sources}
        verified: list[EvidenceRef] = []
        user_evidence = 0
        for locator in candidate.evidence:
            source = source_map.get((locator.trace_id, locator.message_id))
            if source is None:
                raise EvidenceVerificationError("evidence-source-not-found")
            if source.scope != scope:
                raise EvidenceVerificationError("evidence-scope-mismatch")
            if source.role != locator.role:
                raise EvidenceVerificationError("evidence-role-mismatch")
            if source.content_hash != locator.content_hash:
                raise EvidenceVerificationError("evidence-hash-mismatch")
            quote = locator.quote
            if locator.start_offset is not None or locator.end_offset is not None:
                if locator.start_offset is None or locator.end_offset is None:
                    raise EvidenceVerificationError("evidence-offset-incomplete")
                if (
                    not 0
                    <= locator.start_offset
                    <= locator.end_offset
                    <= len(source.content)
                ):
                    raise EvidenceVerificationError("evidence-offset-invalid")
                if source.content[locator.start_offset : locator.end_offset] != quote:
                    raise EvidenceVerificationError("evidence-offset-mismatch")
            elif not quote or quote not in source.content:
                raise EvidenceVerificationError("evidence-quote-mismatch")
            if source.role == "user":
                user_evidence += 1
            verified.append(
                EvidenceRef(
                    "message",
                    source.message_id,
                    quote,
                    {
                        "verified": True,
                        "trace_id": source.trace_id,
                        "role": source.role,
                        "content_hash": source.content_hash,
                        "locator": {
                            "start": locator.start_offset,
                            "end": locator.end_offset,
                        },
                        "prompt_allowed": source.prompt_allowed,
                        "embedding_allowed": source.embedding_allowed,
                        "sensitivity": source.sensitivity,
                    },
                )
            )
        if candidate.explicitness == "explicit-user" and user_evidence == 0:
            raise EvidenceVerificationError("explicit-user-evidence-required")
        if candidate.fact_type in {"preference", "relationship"} and user_evidence == 0:
            raise EvidenceVerificationError("user-fact-cannot-use-assistant-only")
        return tuple(verified)


def _is_complete(bundle: dict[str, Any]) -> bool:
    trace = bundle["trace"]
    return bool(
        trace.get("ended_at")
        and trace.get("status") == "completed"
        and any(item.get("event_type") == "trace_finished" for item in bundle["events"])
    )


def _scope_allows(scope: MemoryScope, session_id: str) -> bool:
    if scope.kind == "user" and scope.identifier in {"default", "*"}:
        return True
    return bool(session_id and session_id == scope.identifier)


def _level(value: str) -> int:
    return {"public": 0, "private": 1, "sensitive": 2}.get(value, 2)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value) if value else datetime.now(UTC)
