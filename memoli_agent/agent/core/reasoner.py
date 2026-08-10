"""极简串行 Agent Loop。"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, cast

from memoli_agent.agent.core.results import (
    LoopOutcome,
    StepSummary,
    TerminationReason,
    TurnResult,
)
from memoli_agent.agent.llm.contracts import (
    EventCallback,
    ModelMessage,
    ToolUseBlock,
    model_message_to_chat,
)
from memoli_agent.agent.plugins.events import (
    HookName,
    ModelAfterEvent,
    ModelBeforeEvent,
)
from memoli_agent.agent.plugins.hooks import HookBus
from memoli_agent.agent.provider import (
    LLMResponse,
    ProviderError,
    ProviderLike,
    ToolCall,
    invoke_provider,
)
from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.control import WorkingStateStore
from memoli_agent.agent.tools.execution import ToolExecutionContext
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import (
    NewTrajectoryEvent,
    NullTrajectoryStore,
    SpanKind,
    SpanProjection,
    TraceProjection,
    TrajectoryError,
    TrajectoryStore,
    new_span_id,
    new_trace_id,
    utc_now_iso,
)
from memoli_agent.agent.types import ChatMessage


@dataclass(frozen=True, slots=True)
class Reasoner:
    """用一个顺序 while 循环驱动模型与工具。"""

    provider: ProviderLike
    fallback_provider: ProviderLike | None = None
    tool_registry: ToolRegistry | None = None
    trajectory_store: TrajectoryStore = field(default_factory=NullTrajectoryStore)
    max_iterations: int = 12
    max_elapsed_seconds: float = 300.0
    no_progress_limit: int = 3
    model_name: str = ""
    max_tool_rounds: int | None = None
    working_state: WorkingStateStore | None = None
    hook_bus: HookBus | None = None
    stream_model: bool = False
    model_event_callback: EventCallback | None = None

    def __post_init__(self) -> None:
        if self.max_iterations <= 0:
            raise ValueError("max_iterations 必须大于 0。")
        if self.max_elapsed_seconds <= 0:
            raise ValueError("max_elapsed_seconds 必须大于 0。")
        if self.no_progress_limit <= 0:
            raise ValueError("no_progress_limit 必须大于 0。")

    async def generate(self, messages: list[ChatMessage]) -> LLMResponse:
        """保留旧调用入口；SubAgent 可用零工具轮次直接请求模型。"""

        if self.max_tool_rounds == 0:
            # 零工具 SubAgent 仍复用完整的空响应恢复与轨迹边界，但不暴露工具。
            direct = replace(self, tool_registry=None, max_tool_rounds=None)
            return (await direct.run_turn(messages, session_key="direct")).response
        return (await self.run_turn(messages, session_key="direct")).response

    async def run_turn(
        self,
        messages: list[ChatMessage],
        *,
        session_key: str,
        trace_id: str | None = None,
        root_span_id: str | None = None,
        root_span_attributes: dict[str, Any] | None = None,
        session_instance_id: str = "",
    ) -> TurnResult:
        """执行一次有边界、可审计的串行 turn。"""

        if (trace_id is None) != (root_span_id is None):
            raise ValueError("trace_id 与 root_span_id 必须同时提供或同时省略。")
        trace_prestarted = trace_id is not None and root_span_id is not None
        trace_id = trace_id or new_trace_id()
        root_span_id = root_span_id or new_span_id()
        started_at = utc_now_iso()
        started_monotonic = time.monotonic()
        provider_name = str(
            getattr(self.provider, "name", type(self.provider).__name__)
        )
        provider_metadata = _provider_metadata(self.provider, self.model_name)
        tools = self.tool_registry.get_schemas() if self.tool_registry else None
        working_messages = list(messages)
        steps: list[StepSummary] = []
        usage: dict[str, Any] = {}
        fallback_used = False
        consecutive_failed_rounds = 0
        current_user_content = next(
            (
                message.content
                for message in reversed(messages)
                if message.role == "user"
            ),
            "",
        )
        user_message_id = hashlib.sha256(
            f"{session_key}:{current_user_content}".encode()
        ).hexdigest()[:24]
        if self.working_state is not None:
            self.working_state.begin_turn(
                session_key,
                max_iterations=self.max_iterations,
                max_elapsed_seconds=self.max_elapsed_seconds,
            )

        trace = TraceProjection(
            trace_id=trace_id,
            session_id=session_key,
            started_at=started_at,
            provider=provider_name,
            model=self.model_name,
        )
        root_span = SpanProjection(
            span_id=root_span_id,
            trace_id=trace_id,
            parent_span_id=None,
            kind=SpanKind.AGENT,
            name="agent-turn",
            started_at=started_at,
            input_data={"messages": _message_dicts(messages)},
            attributes=dict(root_span_attributes or {}),
        )
        if not trace_prestarted:
            try:
                await self.trajectory_store.record(
                    NewTrajectoryEvent(
                        trace_id=trace_id,
                        span_id=root_span_id,
                        event_type="trace_started",
                        payload={
                            "session_id": session_key,
                            "limits": {
                                "max_iterations": self.max_iterations,
                                "max_elapsed_seconds": self.max_elapsed_seconds,
                                "no_progress_limit": self.no_progress_limit,
                            },
                        },
                        trace=trace,
                        span=root_span,
                    )
                )
            except TrajectoryError:
                return self._trace_write_failure(trace_id)

        iteration = 0
        while iteration < self.max_iterations:
            if self._elapsed(started_monotonic) >= self.max_elapsed_seconds:
                return await self._finish(
                    trace,
                    root_span,
                    TerminationReason.BUDGET_EXHAUSTED,
                    "任务未在时间预算内完成。",
                    iteration,
                    steps,
                    usage,
                    fallback_used,
                    error_type=None,
                    decision="elapsed-time",
                )

            iteration += 1
            step_started = time.monotonic()
            elapsed = self._elapsed(started_monotonic)
            if self.working_state is not None:
                self.working_state.project_iteration(
                    session_key,
                    iteration=iteration,
                    elapsed_seconds=elapsed,
                )
            visible_messages, status_revision = self._assemble_model_context(
                working_messages, session_key
            )
            llm_span_id = new_span_id()
            llm_started_at = utc_now_iso()
            llm_span = SpanProjection(
                span_id=llm_span_id,
                trace_id=trace_id,
                parent_span_id=root_span_id,
                kind=SpanKind.LLM,
                name="model-call",
                started_at=llm_started_at,
                input_data={
                    "messages": _message_dicts(visible_messages),
                    "tools": tools or [],
                },
                attributes={
                    "iteration": iteration,
                    "model": self.model_name,
                    "working_state_revision": status_revision,
                    **provider_metadata,
                },
            )
            try:
                if self.hook_bus is not None:
                    await self.hook_bus.observe(
                        HookName.MODEL_BEFORE,
                        ModelBeforeEvent(
                            trace_id=trace_id,
                            session_key=session_key,
                            iteration=iteration,
                            model=self.model_name,
                            provider=provider_metadata["provider"],
                            protocol=provider_metadata["protocol"],
                            dialect=provider_metadata["dialect"],
                            profile=provider_metadata["profile"],
                            capabilities=tuple(provider_metadata["capabilities"]),
                            messages=tuple(_message_dicts(visible_messages)),
                            tools=tuple(tools or ()),
                        ),
                    )
                # 模型请求先落盘，确保后续调用可以被完整审计。
                await self.trajectory_store.record(
                    NewTrajectoryEvent(
                        trace_id=trace_id,
                        span_id=llm_span_id,
                        event_type="model_requested",
                        payload={
                            "iteration": iteration,
                            "messages": _message_dicts(visible_messages),
                            "tools": tools or [],
                            "working_state_revision": status_revision,
                            **provider_metadata,
                        },
                        trace=trace,
                        span=llm_span,
                    )
                )
            except TrajectoryError:
                return self._trace_write_failure(trace_id, iteration, steps, usage)

            response = _normalize_tool_call_ids(
                await self._chat_with_fallback(visible_messages, tools), iteration
            )
            if self.hook_bus is not None:
                await self.hook_bus.observe(
                    HookName.MODEL_AFTER,
                    ModelAfterEvent(
                        trace_id=trace_id,
                        session_key=session_key,
                        iteration=iteration,
                        provider=response.provider,
                        model=response.model or self.model_name,
                        protocol=response.protocol,
                        dialect=response.dialect,
                        profile=response.profile,
                        request_id=response.request_id,
                        finish_reason=response.finish_reason,
                        attempt_count=response.attempt_count,
                        attempts=tuple(
                            attempt.to_dict() for attempt in response.attempts
                        ),
                        partial_stream=response.partial_stream,
                        fallback_used=response.fallback_used,
                        content=response.content,
                        tool_names=tuple(call.name for call in response.tool_calls),
                        error_type=response.error_type,
                        usage=response.usage,
                    ),
                )
            fallback_used = fallback_used or response.fallback_used
            _merge_usage(usage, response.usage)
            llm_finished = SpanProjection(
                **{
                    **_span_values(llm_span),
                    "ended_at": utc_now_iso(),
                    "status": "failed" if response.error_type else "completed",
                    "output_data": _response_dict(response),
                    "error_type": response.error_type,
                    "error_message": response.content if response.error_type else None,
                }
            )
            try:
                await self.trajectory_store.record(
                    NewTrajectoryEvent(
                        trace_id=trace_id,
                        span_id=llm_span_id,
                        event_type="model_responded",
                        payload={"iteration": iteration, **_response_dict(response)},
                        trace=TraceProjection(
                            **{
                                **_trace_values(trace),
                                "provider": response.provider or provider_name,
                                "fallback_used": fallback_used,
                                "usage": dict(usage),
                                "iteration_count": iteration,
                            }
                        ),
                        span=llm_finished,
                    )
                )
            except TrajectoryError:
                return self._trace_write_failure(trace_id, iteration, steps, usage)

            if response.error_type:
                steps.append(
                    StepSummary(
                        iteration=iteration,
                        provider=response.provider,
                        outcome=LoopOutcome.FAILED,
                        duration_seconds=self._elapsed(step_started),
                        usage=response.usage,
                    )
                )
                return await self._finish(
                    trace,
                    root_span,
                    TerminationReason.FAILED,
                    response.content,
                    iteration,
                    steps,
                    usage,
                    fallback_used,
                    error_type=response.error_type,
                    decision="provider-error",
                    provider=response.provider,
                )

            if not response.tool_calls:
                retry_reason = _completion_retry_reason(response)
                if retry_reason is None:
                    steps.append(
                        StepSummary(
                            iteration=iteration,
                            provider=response.provider,
                            outcome=LoopOutcome.COMPLETED,
                            duration_seconds=self._elapsed(step_started),
                            usage=response.usage,
                        )
                    )
                    return await self._finish(
                        trace,
                        root_span,
                        TerminationReason.COMPLETED,
                        response.content,
                        iteration,
                        steps,
                        usage,
                        fallback_used,
                        error_type=None,
                        decision="completion-accepted",
                        provider=response.provider,
                    )

                working_messages.append(
                    model_message_to_chat(response.message)
                    if response.message is not None
                    else ChatMessage(role="assistant", content=response.content)
                )
                working_messages.append(ChatMessage(role="user", content=retry_reason))
                steps.append(
                    StepSummary(
                        iteration=iteration,
                        provider=response.provider,
                        outcome=LoopOutcome.CONTINUE,
                        duration_seconds=self._elapsed(step_started),
                        usage=response.usage,
                    )
                )
                if not await self._record_decision(
                    trace_id,
                    root_span_id,
                    iteration,
                    "completion-retry",
                    {"feedback": retry_reason},
                ):
                    return self._trace_write_failure(trace_id, iteration, steps, usage)
                continue

            if self.tool_registry is None:
                return await self._finish(
                    trace,
                    root_span,
                    TerminationReason.FAILED,
                    "模型请求了工具，但当前没有可用工具。",
                    iteration,
                    steps,
                    usage,
                    fallback_used,
                    error_type="tool-runtime-unavailable",
                    decision="tool-runtime-unavailable",
                    provider=response.provider,
                )

            working_messages.append(self._assistant_tool_call_message(response))
            tool_messages: list[ChatMessage] = []
            tool_results: list[tuple[ToolCall, ToolResult]] = []
            for index, tool_call in enumerate(response.tool_calls):
                if self._elapsed(started_monotonic) >= self.max_elapsed_seconds:
                    return await self._finish(
                        trace,
                        root_span,
                        TerminationReason.BUDGET_EXHAUSTED,
                        "任务未在时间预算内完成。",
                        iteration,
                        steps,
                        usage,
                        fallback_used,
                        error_type=None,
                        decision="elapsed-time",
                        provider=response.provider,
                    )
                tool_call_id = tool_call.id or f"call_{iteration}_{index}"
                tool_span_id = new_span_id()
                tool_started = utc_now_iso()
                tool_span = SpanProjection(
                    span_id=tool_span_id,
                    trace_id=trace_id,
                    parent_span_id=root_span_id,
                    kind=SpanKind.TOOL,
                    name=tool_call.name,
                    started_at=tool_started,
                    input_data=tool_call.arguments,
                    attributes={"tool_call_id": tool_call_id, "iteration": iteration},
                )
                try:
                    # 工具意图先提交，副作用工具不得在无证据时执行。
                    await self.trajectory_store.record(
                        NewTrajectoryEvent(
                            trace_id=trace_id,
                            span_id=tool_span_id,
                            event_type="tool_intent_recorded",
                            payload={
                                "tool_call_id": tool_call_id,
                                "name": tool_call.name,
                                "arguments": tool_call.arguments,
                            },
                            span=tool_span,
                        )
                    )
                except TrajectoryError:
                    return self._trace_write_failure(trace_id, iteration, steps, usage)

                result = await self.tool_registry.execute(
                    tool_call.name,
                    tool_call.arguments,
                    context=ToolExecutionContext(
                        trace_id=trace_id,
                        session_key=session_key,
                        tool_call_id=tool_call_id,
                        session_instance_id=session_instance_id,
                        span_id=tool_span_id,
                        user_message_id=user_message_id,
                        user_content=current_user_content,
                    ),
                )
                tool_results.append((tool_call, result))
                if self.working_state is not None:
                    artifact = str(
                        result.metadata.get("path")
                        or result.metadata.get("artifact")
                        or ""
                    ).strip()
                    self.working_state.project_iteration(
                        session_key,
                        iteration=iteration,
                        elapsed_seconds=self._elapsed(started_monotonic),
                        last_tool=tool_call.name,
                        last_tool_status=result.effective_status,
                        artifacts=(artifact,) if result.success and artifact else (),
                    )
                executed_arguments = result.metadata.get(
                    "executed_arguments", tool_call.arguments
                )
                raw_content = result.raw_content or result.content
                tool_finished = SpanProjection(
                    **{
                        **_span_values(tool_span),
                        "ended_at": utc_now_iso(),
                        "status": "completed" if result.success else "failed",
                        "input_data": {
                            "original_arguments": tool_call.arguments,
                            "executed_arguments": executed_arguments,
                        },
                        "output_data": {
                            "raw_content": raw_content,
                            "model_content": result.content,
                            "metadata": result.metadata,
                            "status": result.effective_status,
                        },
                        "error_type": (
                            None
                            if result.success
                            else str(result.metadata.get("error") or "tool-error")
                        ),
                    }
                )
                try:
                    await self.trajectory_store.record(
                        NewTrajectoryEvent(
                            trace_id=trace_id,
                            span_id=tool_span_id,
                            event_type="tool_finished",
                            payload={
                                "tool_call_id": tool_call_id,
                                "name": tool_call.name,
                                "success": result.success,
                                "status": result.effective_status,
                                "original_arguments": tool_call.arguments,
                                "executed_arguments": executed_arguments,
                                "raw_content": raw_content,
                                "model_content": result.content,
                                "metadata": result.metadata,
                            },
                            span=tool_finished,
                        )
                    )
                except TrajectoryError:
                    return self._trace_write_failure(trace_id, iteration, steps, usage)
                if tool_call.name == "update_working_checkpoint":
                    revision = result.metadata.get("revision")
                    try:
                        await self.trajectory_store.record(
                            NewTrajectoryEvent(
                                trace_id=trace_id,
                                span_id=tool_span_id,
                                event_type="working_checkpoint_updated",
                                payload={
                                    "session_key": session_key,
                                    "revision": revision,
                                    "success": result.success,
                                    "side_effect_committed": result.success,
                                },
                            )
                        )
                    except TrajectoryError:
                        return self._trace_write_failure(
                            trace_id, iteration, steps, usage
                        )
                tool_messages.append(
                    ChatMessage(
                        role="tool",
                        content=result.content,
                        tool_call_id=tool_call_id,
                        name=tool_call.name,
                    )
                )
                if bool(result.metadata.get("needs_user")):
                    steps.append(
                        StepSummary(
                            iteration=iteration,
                            provider=response.provider,
                            outcome=LoopOutcome.NEEDS_USER,
                            tool_names=tuple(call.name for call, _ in tool_results),
                            duration_seconds=self._elapsed(step_started),
                            usage=response.usage,
                        )
                    )
                    return await self._finish(
                        trace,
                        root_span,
                        TerminationReason.NEEDS_USER,
                        result.content,
                        iteration,
                        steps,
                        usage,
                        fallback_used,
                        error_type=None,
                        decision="needs-user",
                        provider=response.provider,
                    )

            working_messages.extend(tool_messages)
            if all(not result.success for _, result in tool_results):
                consecutive_failed_rounds += 1
            else:
                consecutive_failed_rounds = 0
            fingerprint = _progress_fingerprint(tool_results)
            steps.append(
                StepSummary(
                    iteration=iteration,
                    provider=response.provider,
                    outcome=LoopOutcome.CONTINUE,
                    tool_names=tuple(call.name for call, _ in tool_results),
                    duration_seconds=self._elapsed(step_started),
                    usage=response.usage,
                )
            )
            if consecutive_failed_rounds >= self.no_progress_limit:
                return await self._finish(
                    trace,
                    root_span,
                    TerminationReason.FAILED,
                    "检测到重复失败动作，已停止本次任务。",
                    iteration,
                    steps,
                    usage,
                    fallback_used,
                    error_type="no-progress",
                    decision="no-progress",
                    provider=response.provider,
                )
            if not await self._record_decision(
                trace_id,
                root_span_id,
                iteration,
                "continue",
                {"progress_fingerprint": fingerprint},
            ):
                return self._trace_write_failure(trace_id, iteration, steps, usage)

        return await self._finish(
            trace,
            root_span,
            TerminationReason.BUDGET_EXHAUSTED,
            "任务未在迭代预算内完成。",
            self.max_iterations,
            steps,
            usage,
            fallback_used,
            error_type=None,
            decision="max-iterations",
        )

    def _assemble_model_context(
        self, messages: list[ChatMessage], session_key: str
    ) -> tuple[list[ChatMessage], int]:
        """每次调用都从同一路径追加唯一的最新动态状态。"""

        if self.working_state is None:
            return list(messages), 0
        clean = [
            message
            for message in messages
            if not (
                message.role == "system"
                and (
                    "<agent_status" in message.content
                    or "<working_checkpoint>" in message.content
                )
            )
        ]
        rendered = self.working_state.render_status(session_key)
        clean.append(ChatMessage(role="system", content=rendered.content))
        return clean, rendered.revision

    async def _chat_with_fallback(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
    ) -> LLMResponse:
        try:
            return await invoke_provider(
                self.provider,
                messages,
                tools,
                model=self.model_name,
                stream=self.stream_model,
                on_event=self.model_event_callback,
            )
        except ProviderError as primary_error:
            if self.fallback_provider is not None and not primary_error.partial_stream:
                try:
                    response = await invoke_provider(
                        self.fallback_provider,
                        messages,
                        tools,
                        model=self.model_name,
                        stream=self.stream_model,
                        on_event=self.model_event_callback,
                    )
                except ProviderError as fallback_error:
                    return self._error_response(fallback_error, fallback_used=True)
                return LLMResponse(
                    content=response.content,
                    tool_calls=response.tool_calls,
                    raw=response.raw,
                    provider=response.provider,
                    fallback_used=True,
                    finish_reason=response.finish_reason,
                    usage=response.usage,
                    error_type=response.error_type,
                    message=response.message,
                    model=response.model,
                    request_id=response.request_id,
                    protocol=response.protocol,
                    dialect=response.dialect,
                    profile=response.profile,
                    requested_provider=(
                        response.requested_provider
                        or str(getattr(self.provider, "name", ""))
                    ),
                    requested_model=response.requested_model or self.model_name,
                    fallback_reason=(
                        response.fallback_reason or primary_error.error_type
                    ),
                    attempt_count=(
                        max(1, primary_error.attempt) + response.attempt_count
                    ),
                    attempts=(*primary_error.attempts, *response.attempts),
                    partial_stream=response.partial_stream,
                    capabilities=response.capabilities,
                )
            return self._error_response(primary_error)

    async def _record_decision(
        self,
        trace_id: str,
        root_span_id: str,
        iteration: int,
        decision: str,
        extra: dict[str, Any] | None = None,
    ) -> bool:
        try:
            await self.trajectory_store.record(
                NewTrajectoryEvent(
                    trace_id=trace_id,
                    span_id=root_span_id,
                    event_type="loop_decided",
                    payload={
                        "iteration": iteration,
                        "decision": decision,
                        **(extra or {}),
                    },
                )
            )
        except TrajectoryError:
            return False
        return True

    async def prepare_trace(self, session_key: str, content: str) -> tuple[str, str]:
        """在 turn hooks 前建立轨迹外键，随后由 ``run_turn`` 继续写入。"""

        trace_id, span_id = new_trace_id(), new_span_id()
        now = utc_now_iso()
        provider_name = str(
            getattr(self.provider, "name", type(self.provider).__name__)
        )
        await self.trajectory_store.record(
            NewTrajectoryEvent(
                trace_id=trace_id,
                span_id=span_id,
                event_type="trace_started",
                payload={"session_id": session_key, "prestarted": True},
                trace=TraceProjection(
                    trace_id=trace_id,
                    session_id=session_key,
                    started_at=now,
                    provider=provider_name,
                    model=self.model_name,
                ),
                span=SpanProjection(
                    span_id=span_id,
                    trace_id=trace_id,
                    parent_span_id=None,
                    kind=SpanKind.AGENT,
                    name="agent-turn",
                    started_at=now,
                    input_data={"content": content},
                ),
            )
        )
        return trace_id, span_id

    async def _finish(
        self,
        trace: TraceProjection,
        root_span: SpanProjection,
        reason: TerminationReason,
        content: str,
        iterations: int,
        steps: list[StepSummary],
        usage: dict[str, Any],
        fallback_used: bool,
        *,
        error_type: str | None,
        decision: str,
        provider: str = "",
    ) -> TurnResult:
        if not await self._record_decision(
            trace.trace_id,
            root_span.span_id,
            iterations,
            decision,
            {"termination_reason": reason.value},
        ):
            return self._trace_write_failure(trace.trace_id, iterations, steps, usage)

        ended_at = utc_now_iso()
        response = LLMResponse(
            content=content,
            provider=provider or trace.provider,
            fallback_used=fallback_used,
            usage=dict(usage),
            error_type=error_type,
        )
        final_trace = TraceProjection(
            **{
                **_trace_values(trace),
                "ended_at": ended_at,
                "status": reason.value,
                "termination_reason": reason.value,
                "final_output": content,
                "provider": response.provider,
                "fallback_used": fallback_used,
                "usage": dict(usage),
                "iteration_count": iterations,
            }
        )
        final_root = SpanProjection(
            **{
                **_span_values(root_span),
                "ended_at": ended_at,
                "status": reason.value,
                "output_data": {
                    "content": content,
                    "termination_reason": reason.value,
                },
                "error_type": error_type,
            }
        )
        try:
            await self.trajectory_store.record(
                NewTrajectoryEvent(
                    trace_id=trace.trace_id,
                    span_id=root_span.span_id,
                    event_type="trace_finished",
                    payload={
                        "termination_reason": reason.value,
                        "final_output": content,
                        "usage": usage,
                        "iterations": iterations,
                    },
                    trace=final_trace,
                    span=final_root,
                )
            )
        except TrajectoryError:
            return self._trace_write_failure(trace.trace_id, iterations, steps, usage)
        return TurnResult(
            trace_id=trace.trace_id,
            response=response,
            termination_reason=reason,
            iterations=iterations,
            steps=tuple(steps),
            usage=dict(usage),
            fallback_used=fallback_used,
            error_type=error_type,
        )

    def _trace_write_failure(
        self,
        trace_id: str,
        iterations: int = 0,
        steps: list[StepSummary] | None = None,
        usage: dict[str, Any] | None = None,
    ) -> TurnResult:
        response = LLMResponse(
            content="本地运行轨迹写入失败，已停止后续操作。",
            provider="runtime",
            error_type="trace-write-failed",
        )
        return TurnResult(
            trace_id=trace_id,
            response=response,
            termination_reason=TerminationReason.FAILED,
            iterations=iterations,
            steps=tuple(steps or ()),
            usage=dict(usage or {}),
            error_type="trace-write-failed",
        )

    def _assistant_tool_call_message(self, response: LLMResponse) -> ChatMessage:
        if response.message is not None:
            return model_message_to_chat(response.message)
        return ChatMessage(
            role="assistant",
            content=response.content,
            tool_calls=[
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": json.dumps(
                            tool_call.arguments, ensure_ascii=False, sort_keys=True
                        ),
                    },
                }
                for tool_call in response.tool_calls
            ],
        )

    def _error_response(
        self,
        error: ProviderError | None = None,
        fallback_used: bool = False,
    ) -> LLMResponse:
        return LLMResponse(
            content="抱歉，当前模型服务暂时不可用，请稍后再试。",
            provider=(error.provider if error is not None else "error"),
            fallback_used=fallback_used,
            error_type=(
                error.error_type if error is not None else "provider-unavailable"
            ),
            model=error.model if error is not None else self.model_name,
            request_id=error.request_id if error is not None else "",
            attempt_count=max(1, error.attempt) if error is not None else 1,
            attempts=error.attempts if error is not None else (),
            partial_stream=(error.partial_stream if error is not None else False),
        )

    @staticmethod
    def _elapsed(started: float) -> float:
        return max(0.0, time.monotonic() - started)


def _normalize_tool_call_ids(response: LLMResponse, iteration: int) -> LLMResponse:
    """在写入消息历史前一次性补齐 ID，后续执行和结果只复用该值。"""

    if not response.tool_calls:
        return response
    calls = [
        replace(call, id=call.id or f"call_{iteration}_{index}")
        for index, call in enumerate(response.tool_calls)
    ]
    message = response.message
    if message is not None:
        call_index = 0
        blocks = []
        for block in message.blocks:
            if isinstance(block, ToolUseBlock):
                normalized = calls[call_index]
                blocks.append(
                    ToolUseBlock(
                        id=normalized.id or "",
                        name=block.name,
                        arguments=block.arguments,
                    )
                )
                call_index += 1
            else:
                blocks.append(block)
        message = ModelMessage(role=message.role, blocks=tuple(blocks))
    return replace(response, tool_calls=calls, message=message)


def _completion_retry_reason(response: LLMResponse) -> str | None:
    if not response.content.strip():
        return "[系统反馈] 上一轮响应为空，请重新生成完整回复或调用工具。"
    if response.finish_reason.lower() in {"length", "max_tokens"}:
        return "[系统反馈] 上一轮响应被截断，请缩小步骤并继续完成任务。"
    return None


def _progress_fingerprint(results: list[tuple[ToolCall, ToolResult]]) -> str:
    normalized = [
        {
            "name": call.name,
            "arguments": call.arguments,
            "success": result.success,
            "error": result.metadata.get("error"),
            "result_hash": hashlib.sha256(result.content.encode("utf-8")).hexdigest(),
        }
        for call, result in results
    ]
    encoded = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _message_dicts(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for message in messages:
        value = message.to_dict()
        if message.blocks is not None:
            value["blocks"] = [_safe_block(block) for block in message.blocks]
        values.append(value)
    return values


def _response_dict(response: LLMResponse) -> dict[str, Any]:
    return {
        "content": response.content,
        "tool_calls": [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in response.tool_calls
        ],
        "provider": response.provider,
        "fallback_used": response.fallback_used,
        "finish_reason": response.finish_reason,
        "usage": response.usage,
        "error_type": response.error_type,
        "model": response.model,
        "request_id": response.request_id,
        "protocol": response.protocol,
        "dialect": response.dialect,
        "profile": response.profile,
        "requested_provider": response.requested_provider,
        "requested_model": response.requested_model,
        "fallback_reason": response.fallback_reason,
        "attempt_count": response.attempt_count,
        "attempts": [attempt.to_dict() for attempt in response.attempts],
        "partial_stream": response.partial_stream,
        "capabilities": list(response.capabilities),
    }


def _safe_block(block: dict[str, Any]) -> dict[str, Any]:
    """轨迹保留可见内容，但不落盘 signature/opaque continuation。"""

    return {
        key: value
        for key, value in block.items()
        if key not in {"signature", "opaque", "data"}
    }


def _provider_metadata(provider: object, model: str) -> dict[str, Any]:
    """只投影可公开的 Provider/Profile 信息。"""

    primary = getattr(provider, "primary", None)
    capabilities = getattr(primary, "capabilities", None) or getattr(
        provider, "capabilities", None
    )
    to_strings = getattr(capabilities, "to_strings", None)
    capability_values = (
        cast(Callable[[], tuple[str, ...]], to_strings)()
        if callable(to_strings)
        else ()
    )
    return {
        "provider": str(getattr(provider, "name", type(provider).__name__)),
        "model": str(getattr(primary, "model", "") or model),
        "protocol": str(getattr(provider, "protocol", "")),
        "dialect": str(getattr(provider, "dialect", "")),
        "profile": str(getattr(primary, "profile", "") or "default"),
        "capabilities": [str(value) for value in capability_values],
    }


def _merge_usage(total: dict[str, Any], current: dict[str, Any]) -> None:
    for key, value in current.items():
        if isinstance(value, int | float):
            total[key] = total.get(key, 0) + value


def _trace_values(trace: TraceProjection) -> dict[str, Any]:
    return {
        field_name: getattr(trace, field_name)
        for field_name in trace.__dataclass_fields__
    }


def _span_values(span: SpanProjection) -> dict[str, Any]:
    return {
        field_name: getattr(span, field_name)
        for field_name in span.__dataclass_fields__
    }
