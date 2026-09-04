"""投影给终端的结构化、安全、非权威表现事件。"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import PureWindowsPath

from memoli_agent.agent.llm.contracts import ModelEvent, ModelEventKind
from memoli_agent.agent.trajectory import utc_now_iso


class PresentationEventKind(StrEnum):
    TURN_STARTED = "turn_started"
    MODEL_STARTED = "model_started"
    TEXT_DELTA = "text_delta"
    PROGRESS_UPDATE = "progress_update"
    REASONING_SUMMARY = "reasoning_summary"
    USAGE_UPDATED = "usage_updated"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    CHECKPOINT_CHANGED = "checkpoint_changed"
    TURN_COMPLETED = "turn_completed"
    TURN_FAILED = "turn_failed"
    TURN_CANCELLED = "turn_cancelled"
    # 兼容旧表现层名称；值等同于 model 完成通知。
    MODEL_COMPLETED = "model_completed"


_TERMINAL = {
    PresentationEventKind.TURN_COMPLETED,
    PresentationEventKind.TURN_FAILED,
    PresentationEventKind.TURN_CANCELLED,
}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x9b]")
_SECRET = re.compile(r"(?i)(bearer\s+|api[_-]?key\s*[:=]\s*|cookie\s*[:=]\s*)[^\s,;]+")
_WINDOWS_PATH = re.compile(r"(?i)\b[A-Z]:\\(?:[^\s\\]+\\)*[^\s]+")


@dataclass(frozen=True, slots=True)
class PresentationEvent:
    # 前四个字段保持旧位置参数兼容。
    kind: PresentationEventKind
    session_key: str
    trace_id: str
    text: str = ""
    turn_id: str = ""
    step_id: str = ""
    occurred_at: str = field(default_factory=utc_now_iso)
    status: str = ""
    elapsed_seconds: float | None = None
    usage: tuple[tuple[str, int], ...] = ()
    error_type: str = ""

    def sanitized(self, max_chars: int) -> PresentationEvent:
        return replace(
            self,
            session_key=_safe(self.session_key, 256),
            trace_id=_safe(self.trace_id, 128),
            turn_id=_safe(self.turn_id or self.trace_id, 128),
            step_id=_safe(self.step_id, 128),
            text=_safe(self.text, max_chars),
            status=_safe(self.status, 64),
            error_type=_safe(self.error_type, 128),
        )


@dataclass(slots=True)
class PresentationEventHub:
    """有界 Observer 队列；拥塞或消费者故障不改变 Agent 行为。"""

    max_events: int = 256
    max_text_chars: int = 2_000
    _queue: asyncio.Queue[PresentationEvent] = field(init=False)

    def __post_init__(self) -> None:
        if self.max_events < 2:
            raise ValueError("表现事件队列至少需要两个槽位。")
        self._queue = asyncio.Queue(maxsize=self.max_events)

    async def publish(self, event: PresentationEvent) -> None:
        projected = event.sanitized(self.max_text_chars)
        try:
            self._queue.put_nowait(projected)
            return
        except asyncio.QueueFull:
            pass
        items: list[PresentationEvent] = []
        try:
            while True:
                items.append(self._queue.get_nowait())
        except asyncio.QueueEmpty:
            ...

        merged = False
        if projected.kind == PresentationEventKind.TEXT_DELTA and items:
            previous = items[-1]
            if (
                previous.kind == PresentationEventKind.TEXT_DELTA
                and previous.session_key == projected.session_key
                and previous.trace_id == projected.trace_id
                and previous.step_id == projected.step_id
            ):
                items[-1] = replace(
                    previous,
                    text=(previous.text + projected.text)[: self.max_text_chars],
                )
                merged = True
        elif projected.kind in {
            PresentationEventKind.USAGE_UPDATED,
            PresentationEventKind.CHECKPOINT_CHANGED,
        }:
            for index in range(len(items) - 1, -1, -1):
                previous = items[index]
                if (
                    previous.kind == projected.kind
                    and previous.session_key == projected.session_key
                    and previous.trace_id == projected.trace_id
                    and previous.step_id == projected.step_id
                ):
                    items[index] = projected
                    merged = True
                    break
        if not merged and projected.kind in _TERMINAL:
            # 最终事件优先：丢弃最早一个可降级事件。
            if items:
                items.pop(0)
            items.append(projected)
        elif not merged and len(items) < self.max_events:
            items.append(projected)
        for item in items[-self.max_events :]:
            self._queue.put_nowait(item)

    async def publish_model_event(
        self,
        session_key: str,
        trace_id: str,
        event: ModelEvent,
    ) -> None:
        projected: PresentationEvent | None = None
        if event.kind == ModelEventKind.TEXT_DELTA and event.text:
            projected = PresentationEvent(
                PresentationEventKind.TEXT_DELTA,
                session_key,
                trace_id,
                event.text,
                turn_id=trace_id,
                step_id="model",
            )
        elif event.kind == ModelEventKind.PROGRESS_UPDATE and event.text:
            projected = PresentationEvent(
                PresentationEventKind.PROGRESS_UPDATE,
                session_key,
                trace_id,
                event.text,
                turn_id=trace_id,
                step_id="agent-progress",
            )
        elif event.kind == ModelEventKind.REASONING_SUMMARY_DELTA and event.text:
            projected = PresentationEvent(
                PresentationEventKind.REASONING_SUMMARY,
                session_key,
                trace_id,
                event.text,
                turn_id=trace_id,
                step_id="reasoning-summary",
            )
        elif event.kind == ModelEventKind.TOOL_CALL_DELTA and event.tool_name:
            # 原始 arguments_delta 永远不进入表现合同。
            projected = PresentationEvent(
                PresentationEventKind.TOOL_STARTED,
                session_key,
                trace_id,
                _tool_name(event.tool_name),
                turn_id=trace_id,
                step_id=_safe(event.tool_call_id, 128),
                status="running",
            )
        elif event.kind == ModelEventKind.USAGE and event.usage is not None:
            projected = PresentationEvent(
                PresentationEventKind.USAGE_UPDATED,
                session_key,
                trace_id,
                turn_id=trace_id,
                step_id="model",
                usage=tuple(sorted(event.usage.to_dict().items())),
            )
        elif event.kind == ModelEventKind.COMPLETED:
            projected = PresentationEvent(
                PresentationEventKind.MODEL_COMPLETED,
                session_key,
                trace_id,
                turn_id=trace_id,
                step_id="model",
                status="completed",
            )
        if projected is not None:
            await self.publish(projected)

    async def consume(self) -> PresentationEvent:
        return await self._queue.get()


def _safe(value: str, limit: int) -> str:
    text = _CONTROL.sub("", str(value))
    text = _SECRET.sub(lambda match: match.group(1) + "[REDACTED]", text)
    if _WINDOWS_PATH.search(text):
        text = _WINDOWS_PATH.sub("[HOST_PATH]", text)
    # 过滤 OSC/DCS/CSI 的 ESC 起始符，换行和制表符保留。
    text = text.replace("\x1b", "")
    return text[:limit]


def _tool_name(value: str) -> str:
    name = PureWindowsPath(value).name
    return re.sub(r"[^A-Za-z0-9_.:-]", "_", name)[:128]
