"""从已提交 trajectory 构建可重建、带上下文的 Episode 索引。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from memoli_agent.agent.memory.models import MemoryScope
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore
from memoli_agent.agent.trajectory import SQLiteTrajectoryStore


@dataclass(frozen=True, slots=True)
class EpisodicSegment:
    segment_id: str
    trace_id: str
    start_event_id: int
    end_event_id: int
    role: str
    content: str
    occurred_at: str
    context_prefix: str = ""
    search_text: str = ""
    segmenter_version: str = "2"
    content_hash: str = ""
    source_refs: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class _Fragment:
    role: str
    content: str
    reference: dict[str, Any]
    event_id: int


@dataclass(frozen=True, slots=True)
class TrajectorySegmentIndexer:
    trajectory: SQLiteTrajectoryStore
    memory: SQLiteMemoryStore
    segmenter_version: str = "2"
    max_segment_chars: int = 4_000
    max_prefix_chars: int = 1_000

    async def project_trace(
        self,
        trace_id: str,
        scope: MemoryScope,
        *,
        objective: str = "",
        current_step: str = "",
    ) -> tuple[EpisodicSegment, ...]:
        return await self.rebuild_trace(
            trace_id,
            scope,
            objective=objective,
            current_step=current_step,
            require_complete=True,
        )

    async def rebuild_trace(
        self,
        trace_id: str,
        scope: MemoryScope,
        *,
        objective: str = "",
        current_step: str = "",
        require_complete: bool = False,
    ) -> tuple[EpisodicSegment, ...]:
        bundle = await self.trajectory.get_trace(trace_id)
        if bundle is None:
            raise KeyError(trace_id)
        if require_complete and not _is_complete(bundle):
            return ()
        fragments = await self._fragments(bundle)
        if not fragments:
            return ()
        trace = bundle["trace"]
        user_request = next(
            (item.content for item in fragments if item.role == "user"), ""
        )
        prefix = _context_prefix(
            session_id=str(trace.get("session_id") or ""),
            user_request=user_request,
            objective=objective,
            current_step=current_step,
            outcome=str(trace.get("termination_reason") or trace.get("status") or ""),
            max_chars=self.max_prefix_chars,
        )
        chunks = _pack_fragments(fragments, self.max_segment_chars)
        segments: list[EpisodicSegment] = []
        rows: list[dict[str, Any]] = []
        occurred_at = str(trace.get("started_at") or "")
        for ordinal, chunk in enumerate(chunks):
            content = "\n".join(item.content for item in chunk).strip()
            search_text = "\n".join(part for part in (prefix, content) if part)
            content_hash = hashlib.sha256(
                " ".join(search_text.casefold().split()).encode("utf-8")
            ).hexdigest()
            segment_id = "seg_" + hashlib.sha256(
                f"{trace_id}:{ordinal}:{self.segmenter_version}".encode()
            ).hexdigest()[:24]
            source_refs = tuple(item.reference for item in chunk)
            segment = EpisodicSegment(
                segment_id=segment_id,
                trace_id=trace_id,
                start_event_id=min(item.event_id for item in chunk),
                end_event_id=max(item.event_id for item in chunk),
                role=chunk[0].role if len(chunk) == 1 else "mixed",
                content=content,
                occurred_at=occurred_at,
                context_prefix=prefix,
                search_text=search_text,
                segmenter_version=self.segmenter_version,
                content_hash=content_hash,
                source_refs=source_refs,
            )
            segments.append(segment)
            rows.append(
                {
                    "segment_id": segment.segment_id,
                    "start_event_id": segment.start_event_id,
                    "end_event_id": segment.end_event_id,
                    "content": segment.content,
                    "scope": scope,
                    "occurred_at": occurred_at,
                    "context_prefix": prefix,
                    "search_text": search_text,
                    "segmenter_version": self.segmenter_version,
                    "content_hash": content_hash,
                    "source_refs_json": json.dumps(
                        source_refs, ensure_ascii=False, sort_keys=True
                    ),
                }
            )
        self.memory.replace_trajectory_segments(trace_id, rows)
        return tuple(segments)

    async def resolve(self, segment: EpisodicSegment) -> str:
        """从权威轨迹读取原始片段，不把 context prefix 当作证据。"""

        bundle = await self.trajectory.get_trace(segment.trace_id)
        if bundle is None:
            raise KeyError(segment.trace_id)
        resolved: list[str] = []
        for reference in segment.source_refs:
            value = await self._resolve_reference(bundle, reference)
            if value:
                resolved.append(value)
        if resolved:
            return "\n".join(resolved)
        # 兼容 v1 显式索引对象。
        root = next(span for span in bundle["spans"] if span["kind"] == "agent")
        data = await self._payload(bundle, root.get("input_payload_id"))
        messages = data.get("messages", []) if isinstance(data, dict) else []
        return str(messages[segment.start_event_id]["content"])

    async def backfill(
        self, scope: MemoryScope, *, limit: int = 100
    ) -> dict[str, int]:
        traces = await self.trajectory.query_traces()
        completed = projected = 0
        for trace in traces[:limit]:
            if not trace.get("ended_at"):
                continue
            completed += 1
            segments = await self.project_trace(str(trace["trace_id"]), scope)
            projected += len(segments)
        return {"completed_traces": completed, "segments": projected}

    async def _fragments(self, bundle: dict[str, Any]) -> list[_Fragment]:
        fragments: list[_Fragment] = []
        root = next(
            (span for span in bundle["spans"] if span["kind"] == "agent"), None
        )
        if root is not None:
            data = await self._payload(bundle, root.get("input_payload_id"))
            if isinstance(data, dict):
                messages = data.get("messages")
                if isinstance(messages, list):
                    for index, message in enumerate(messages):
                        if not isinstance(message, dict):
                            continue
                        content = str(message.get("content") or "").strip()
                        if content:
                            fragments.append(
                                _Fragment(
                                    str(message.get("role") or "unknown"),
                                    content,
                                    {"kind": "message", "index": index},
                                    index,
                                )
                            )
                elif str(data.get("content") or "").strip():
                    fragments.append(
                        _Fragment(
                            "user",
                            str(data["content"]).strip(),
                            {"kind": "root-content"},
                            0,
                        )
                    )
        for event in bundle["events"]:
            if event["event_type"] != "tool_finished":
                continue
            payload = await self._payload(bundle, event.get("payload_id"))
            if not isinstance(payload, dict):
                continue
            content = str(
                payload.get("raw_content") or payload.get("model_content") or ""
            ).strip()
            if content:
                sequence = int(event["sequence"])
                fragments.append(
                    _Fragment(
                        "tool",
                        content,
                        {"kind": "event", "sequence": sequence},
                        sequence,
                    )
                )
        trace = bundle["trace"]
        if trace.get("final_output_payload_id") is not None:
            final = await self._payload(bundle, trace["final_output_payload_id"])
            content = str(final or "").strip()
            if content:
                sequence = max(
                    (int(event["sequence"]) for event in bundle["events"]),
                    default=len(fragments),
                )
                fragments.append(
                    _Fragment(
                        "assistant",
                        content,
                        {"kind": "trace-final"},
                        sequence,
                    )
                )
        return fragments

    async def _payload(self, bundle: dict[str, Any], payload_id: Any) -> Any:
        if payload_id is None:
            return {}
        if hasattr(self.trajectory, "read_payload_json"):
            return await self.trajectory.read_payload_json(int(payload_id))
        payloads = {
            int(payload["payload_id"]): payload for payload in bundle["payloads"]
        }
        return _payload_json(payloads.get(int(payload_id)))

    async def _resolve_reference(
        self, bundle: dict[str, Any], reference: dict[str, Any]
    ) -> str:
        kind = reference.get("kind")
        if kind in {"message", "root-content"}:
            root = next(span for span in bundle["spans"] if span["kind"] == "agent")
            data = await self._payload(bundle, root.get("input_payload_id"))
            if kind == "root-content":
                return str(data.get("content") or "") if isinstance(data, dict) else ""
            return str(data["messages"][int(reference["index"])]["content"])
        if kind == "event":
            event = next(
                item
                for item in bundle["events"]
                if int(item["sequence"]) == int(reference["sequence"])
            )
            payload = await self._payload(bundle, event.get("payload_id"))
            return str(
                payload.get("raw_content") or payload.get("model_content") or ""
            )
        if kind == "trace-final":
            return str(
                await self._payload(
                    bundle, bundle["trace"].get("final_output_payload_id")
                )
                or ""
            )
        return ""


def _is_complete(bundle: dict[str, Any]) -> bool:
    trace = bundle["trace"]
    return bool(trace.get("ended_at")) and any(
        event["event_type"] == "trace_finished" for event in bundle["events"]
    )


def _context_prefix(
    *,
    session_id: str,
    user_request: str,
    objective: str,
    current_step: str,
    outcome: str,
    max_chars: int,
) -> str:
    fields = (
        ("会话", session_id),
        ("用户请求", user_request),
        ("工作目标", objective),
        ("当前步骤", current_step),
        ("结果", outcome),
    )
    text = "\n".join(
        f"{name}: {value.strip()}" for name, value in fields if value.strip()
    )
    return text[:max_chars]


def _pack_fragments(
    fragments: list[_Fragment], max_chars: int
) -> list[list[_Fragment]]:
    chunks: list[list[_Fragment]] = []
    current: list[_Fragment] = []
    used = 0
    for fragment in fragments:
        pieces = [
            fragment.content[index : index + max_chars]
            for index in range(0, len(fragment.content), max_chars)
        ] or [""]
        for piece in pieces:
            item = _Fragment(
                fragment.role, piece, fragment.reference, fragment.event_id
            )
            if current and used + len(piece) + 1 > max_chars:
                chunks.append(current)
                current = []
                used = 0
            current.append(item)
            used += len(piece) + (1 if used else 0)
    if current:
        chunks.append(current)
    return chunks


def _payload_json(payload: dict[str, Any] | None) -> Any:
    if payload is None or payload.get("inline_text") is None:
        return {}
    try:
        return json.loads(str(payload["inline_text"]))
    except json.JSONDecodeError:
        return {}


async def export_trace_markdown(
    trajectory: SQLiteTrajectoryStore, trace_id: str
) -> str:
    """从权威轨迹确定性生成只读 Markdown，不回写 HISTORY.md。"""

    bundle = await trajectory.get_trace(trace_id)
    if bundle is None:
        raise KeyError(trace_id)
    root = next(span for span in bundle["spans"] if span["kind"] == "agent")
    data = await trajectory.read_payload_json(int(root["input_payload_id"]))
    messages = data.get("messages", []) if isinstance(data, dict) else []
    lines = [f"# Trace {trace_id}", ""]
    for message in messages:
        lines.extend(
            [
                f"## {str(message.get('role') or 'unknown').title()}",
                "",
                str(message.get("content") or ""),
                "",
            ]
        )
    return "\n".join(lines)
