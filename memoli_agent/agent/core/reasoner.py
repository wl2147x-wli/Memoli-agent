"""极简串行 Agent Loop。"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, cast

from memoli_agent.agent.context_management import (
    CommittedTurnStore,
    CompactionError,
    ContextBudgetExhausted,
    ContextCompactionCircuitOpen,
    ContextCompilation,
    ContextCompiler,
    ContextSnapshotInvalidated,
    ContextStateError,
    TaskAwareCompactor,
    ToolResultPreviewer,
    build_envelope,
)
from memoli_agent.agent.core.results import (
    LoopOutcome,
    StepSummary,
    TerminationReason,
    TurnResult,
)
from memoli_agent.agent.llm.contracts import (
    EventCallback,
    ModelMessage,
    ProviderExchange,
    ReasoningPolicy,
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
    ASSISTANT_MESSAGE_COMMITTED,
    TOOL_MESSAGE_COMMITTED,
    TURN_INPUT_COMMITTED,
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
from memoli_agent.presentation.events import (
    PresentationEvent,
    PresentationEventHub,
    PresentationEventKind,
)


@dataclass(slots=True)
class _TurnCommitState:
    """单次 turn 内的 committed 记录状态（可变，仅 run_turn 作用域存活）。

    ``can_commit`` 由 ``CommittedTurnStore`` 运行时协议判定——``NullTrajectoryStore``
    不实现 ``current_epoch``/``next_turn_seq``，天然关闭记录（§2.6）。``next_seq``
    为下一个待分配的 message_seq（初值 1），turn_output 在 phases 层取此值续写。
    """

    epoch: int = 1
    turn_seq: int = 0
    next_seq: int = 1
    can_commit: bool = False
    capture_mode: str = ""


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
    presentation_events: PresentationEventHub | None = None
    context_compiler: ContextCompiler | None = None
    tool_result_previewer: ToolResultPreviewer | None = None
    task_compactor: TaskAwareCompactor | None = None
    reasoning_policy: ReasoningPolicy = field(default_factory=ReasoningPolicy)

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
        exchange = ProviderExchange(trace_id, reasoning_policy=self.reasoning_policy)
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
        emergency_retries = 0
        # §5.6 loop-guard：本轮已成功压缩则抑制后续 plan，单轮最多压缩一个批次。
        compacted_this_turn = False
        capability_revision: int | None = None
        current_user_position = next(
            (
                index
                for index in range(len(messages) - 1, -1, -1)
                if messages[index].role == "user"
            ),
            -1,
        )
        current_user_content = (
            messages[current_user_position].content
            if current_user_position >= 0
            else ""
        )
        user_message_id = hashlib.sha256(
            f"{trace_id}:{current_user_position}:{current_user_content}".encode()
        ).hexdigest()[:24]
        if self.working_state is not None:
            self.working_state.begin_turn(
                session_key,
                max_iterations=self.max_iterations,
                max_elapsed_seconds=self.max_elapsed_seconds,
            )

        # §2.3 跨轮 committed turn 状态：仅当 trajectory store 实现 CommittedTurnStore
        # 协议时记录（NullTrajectoryStore 不实现 → 关闭记录，§2.6）。
        commit = _TurnCommitState(
            capture_mode=getattr(self.trajectory_store, "capture_content", "") or ""
        )
        # §2.3 经 isinstance 收窄到 CommittedTurnStore 协议后访问其
        # current_epoch/next_turn_seq。pyright 不经 bool 变量收窄
        # self.trajectory_store，故用局部 committed_store + if 直接收窄；
        # NullTrajectoryStore 不实现该协议 → committed_store=None（§2.6）。
        committed_store = self.trajectory_store if isinstance(
            self.trajectory_store, CommittedTurnStore
        ) else None
        if committed_store is not None:
            commit.can_commit = True
            try:
                commit.epoch = await committed_store.current_epoch(session_key)
                commit.turn_seq = await committed_store.next_turn_seq(
                    session_key, commit.epoch
                )
            except TrajectoryError:
                commit.can_commit = False

        async def _commit_message(event_type: str, message: ChatMessage) -> None:
            # 记录 canonical envelope（§2.4：内容取自 to_dict()，已排除隐藏 reasoning
            # 与训练/评价字段；凭证脱敏由 trajectory 落盘 _clean_value 统一完成）。
            # 记录失败不阻断主控制流——committed 事件缺失由 reader 降级处理。
            if not commit.can_commit:
                return
            sequence = commit.next_seq
            commit.next_seq += 1
            envelope = build_envelope(
                message,
                epoch=commit.epoch,
                turn_seq=commit.turn_seq,
                message_seq=sequence,
                capture_mode=commit.capture_mode,
            )
            try:
                await cast(TrajectoryStore, self.trajectory_store).record(
                    NewTrajectoryEvent(
                        trace_id=trace_id,
                        span_id=root_span_id,
                        event_type=event_type,
                        payload=envelope,
                    )
                )
            except TrajectoryError:
                pass

        async def _finish_turn(*args: Any, **kwargs: Any) -> TurnResult:
            # 把单次 turn 的 committed 状态注入 _finish，避免在每个终止分支重复传参。
            return await self._finish(*args, commit=commit, **kwargs)

        trace = TraceProjection(
            trace_id=trace_id,
            session_id=session_key,
            started_at=started_at,
            context_epoch=commit.epoch,
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
            input_data={
                "messages": _message_dicts(messages),
                "session_id": session_key,
                "current_user_message_id": user_message_id,
                "current_user_message_index": current_user_position,
            },
            attributes=dict(root_span_attributes or {}),
        )
        await self._publish_presentation(
            PresentationEvent(
                PresentationEventKind.TURN_STARTED,
                session_key,
                trace_id,
                turn_id=trace_id,
                status="running",
            )
        )
        if not trace_prestarted:
            try:
                await cast(TrajectoryStore, self.trajectory_store).record(
                    NewTrajectoryEvent(
                        trace_id=trace_id,
                        span_id=root_span_id,
                        event_type="trace_started",
                        payload={
                            "session_id": session_key,
                            "current_user_message_id": user_message_id,
                            "current_user_message_index": current_user_position,
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
        # turn_input：在 trace 落盘后记录当前用户输入（不含循环内 retry 脚手架）。
        if current_user_position >= 0:
            await _commit_message(
                TURN_INPUT_COMMITTED, messages[current_user_position]
            )

        # §6.6 turn 起始重放未投递的审计 outbox（best-effort，绝不阻塞主控制流）。
        # context-state 事务已提交、压缩决定已生效；此处仅补投递上一轮因轨迹写入
        # 临时失败而 pending/failed 的 context audit 事件（重放只记轨迹、不调
        # commit/merge，spec 幂等）。失败与无 task_compactor 场景都静默跳过。
        if self.task_compactor is not None:
            try:
                await self.task_compactor.replay_outbox(
                    session_key=session_key,
                    trajectory_store=self.trajectory_store,
                )
            except Exception:  # noqa: BLE001 — 审计重放不得阻塞主 turn
                pass

        iteration = 0
        while iteration < self.max_iterations:
            if self._elapsed(started_monotonic) >= self.max_elapsed_seconds:
                return await _finish_turn(
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
            compiled_metadata: dict[str, Any] = {}
            iteration_tools = (
                self.tool_registry.get_schemas(
                    session_key=session_key,
                    conversation_epoch=commit.epoch,
                )
                if self.tool_registry is not None and self.context_compiler is None
                else list(tools or ())
            )
            # 仅 context_compiler 非空分支才 compile 赋值；reactive 块经同一
            # 守卫到达，调用 _apply_compaction_plan 前用 assert 收窄（pyright
            # 无法跨两个独立 if 关联“context_compiler 非空 ⟹ compilation 已赋值”）。
            compilation: ContextCompilation | None = None
            if self.context_compiler is not None:
                try:
                    compilation = self.context_compiler.compile(
                        session_key=session_key,
                        session_instance_id=session_instance_id,
                        messages=visible_messages,
                        tools=iteration_tools,
                        working_state_revision=status_revision,
                        compacted_this_turn=compacted_this_turn,
                        epoch=commit.epoch,
                        revoked_tool_names=(
                            self.tool_registry.revoked_tool_names
                            if self.tool_registry
                            else frozenset()
                        ),
                        capability_revision=capability_revision,
                    )
                except (ContextBudgetExhausted, ContextCompactionCircuitOpen) as exc:
                    return await _finish_turn(
                        trace,
                        root_span,
                        TerminationReason.BUDGET_EXHAUSTED,
                        str(exc),
                        iteration,
                        steps,
                        usage,
                        fallback_used,
                        error_type=exc.error_type,
                        decision="context-budget-exhausted",
                    )
                except ContextSnapshotInvalidated as exc:
                    # §7.2 安全撤销 fail-closed：snapshot 因能力撤销失效，编译拒绝
                    # 用其冻结 schema（仍含已撤销能力）向模型暴露；立即结束 turn 为
                    # 失败，不静默替换。恢复需新 epoch 重新冻结当前 schema。
                    return await _finish_turn(
                        trace,
                        root_span,
                        TerminationReason.FAILED,
                        str(exc),
                        iteration,
                        steps,
                        usage,
                        fallback_used,
                        error_type=exc.error_type,
                        decision="snapshot-invalidated",
                    )
                except ContextStateError as exc:
                    return await _finish_turn(
                        trace,
                        root_span,
                        TerminationReason.FAILED,
                        str(exc),
                        iteration,
                        steps,
                        usage,
                        fallback_used,
                        error_type="context-state-error",
                        decision="capability-revision-persist-failed",
                    )
                # §5.2/§5.6：soft/hard 触发后经统一协调器压缩 plan.batch 并重编译；
                # 压缩失败保原视图并计数，重编译后 hard 仍超预算才显式结束。
                try:
                    compilation, compacted_this_turn = (
                        await self._apply_compaction_plan(
                            compilation,
                            compacted_this_turn=compacted_this_turn,
                            session_key=session_key,
                            session_instance_id=session_instance_id,
                            visible_messages=visible_messages,
                            tools=iteration_tools,
                            status_revision=status_revision,
                            trace_id=trace_id,
                            root_span_id=root_span_id,
                            commit=commit,
                        )
                    )
                except (ContextBudgetExhausted, CompactionError) as exc:
                    return await _finish_turn(
                        trace,
                        root_span,
                        TerminationReason.BUDGET_EXHAUSTED,
                        str(exc),
                        iteration,
                        steps,
                        usage,
                        fallback_used,
                        error_type=exc.error_type,
                        decision="context-compaction-hard-failed",
                    )
                visible_messages = list(compilation.messages)
                iteration_tools = list(compilation.tools)
                capability_revision = compilation.capability_revision
                compiled_metadata = compilation.metadata()
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
                    "tools": iteration_tools,
                },
                attributes={
                    "iteration": iteration,
                    "model": self.model_name,
                    "working_state_revision": status_revision,
                    **compiled_metadata,
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
                            tools=tuple(iteration_tools),
                        ),
                    )
                # 模型请求先落盘，确保后续调用可以被完整审计。
                await cast(TrajectoryStore, self.trajectory_store).record(
                    NewTrajectoryEvent(
                        trace_id=trace_id,
                        span_id=llm_span_id,
                        event_type="model_requested",
                        payload={
                            "iteration": iteration,
                            "messages": _message_dicts(visible_messages),
                            "tools": iteration_tools,
                            "working_state_revision": status_revision,
                            "context_compilation": compiled_metadata,
                            **provider_metadata,
                        },
                        trace=trace,
                        span=llm_span,
                    )
                )
            except TrajectoryError:
                return self._trace_write_failure(trace_id, iteration, steps, usage)

            response = _normalize_tool_call_ids(
                await self._chat_with_fallback(
                    visible_messages,
                    iteration_tools,
                    session_key=session_key,
                    trace_id=trace_id,
                    exchange=exchange,
                ),
                iteration,
            )
            if (
                response.error_type == "provider-context-length"
                and self.context_compiler is not None
                and emergency_retries
                < self.context_compiler.settings.emergency_retry_limit
            ):
                previous_hash = str(compiled_metadata.get("context_hash") or "")
                previous_tokens = int(
                    compiled_metadata.get("estimated_input_tokens") or 0
                )
                # §5.1/§5.7：emergency 经统一协调器——确定性 shed 重编译（不调
                # LLM 压缩、不提交 archive），熔断/编译失败返回原 compilation
                # （同 hash → improved 判否）。improved 要求 hash 不同且 token 更少。
                # 上方 context_compiler 非空 ⟹ 循环顶部已 compile 赋值。
                assert compilation is not None
                shed, _ = await self._apply_compaction_plan(
                    compilation,
                    compacted_this_turn=compacted_this_turn,
                    session_key=session_key,
                    session_instance_id=session_instance_id,
                    visible_messages=visible_messages,
                    tools=tools,
                    status_revision=status_revision,
                    trace_id=trace_id,
                    root_span_id=root_span_id,
                    commit=commit,
                    working_messages=working_messages,
                    emergency=True,
                )
                improved = (
                    shed.context_hash != previous_hash
                    and shed.budget.estimated_input_tokens < previous_tokens
                )
                if improved:
                    emergency_retries += 1
                    await self._record_decision(
                        trace_id,
                        root_span_id,
                        iteration,
                        "context-emergency-retry",
                        {
                            "before_context_hash": previous_hash,
                            "after_context_hash": shed.context_hash,
                            "before_tokens": previous_tokens,
                            "after_tokens": shed.budget.estimated_input_tokens,
                        },
                    )
                    visible_messages = list(shed.messages)
                    iteration_tools = list(shed.tools)
                    compiled_metadata = shed.metadata()
                    response = _normalize_tool_call_ids(
                        await self._chat_with_fallback(
                            visible_messages,
                            iteration_tools,
                            session_key=session_key,
                            trace_id=trace_id,
                            exchange=exchange,
                        ),
                        iteration,
                    )
            exchange.accept(response)
            # §5.7：无法改善（压缩失败/熔断/最小必需仍超限/新请求未变小）
            # 时不重试，保持原 Provider 错误由后续 response.error_type 分支
            # 稳定结束，不以相同输入循环重试或切换窗口更小的 Provider。
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
            cache_usage = (
                self.context_compiler.record_provider_usage(session_key, response.usage)
                if self.context_compiler is not None
                else {}
            )
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
                await cast(TrajectoryStore, self.trajectory_store).record(
                    NewTrajectoryEvent(
                        trace_id=trace_id,
                        span_id=llm_span_id,
                        event_type="model_responded",
                        payload={
                            "iteration": iteration,
                            "context_compilation": compiled_metadata,
                            "cache_usage": cache_usage,
                            **_response_dict(response),
                        },
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
                exchange.fail()
                steps.append(
                    StepSummary(
                        iteration=iteration,
                        provider=response.provider,
                        outcome=LoopOutcome.FAILED,
                        duration_seconds=self._elapsed(step_started),
                        usage=response.usage,
                    )
                )
                return await _finish_turn(
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
                    exchange.complete()
                    steps.append(
                        StepSummary(
                            iteration=iteration,
                            provider=response.provider,
                            outcome=LoopOutcome.COMPLETED,
                            duration_seconds=self._elapsed(step_started),
                            usage=response.usage,
                        )
                    )
                    return await _finish_turn(
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
                return await _finish_turn(
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

            assistant_tool_call = self._assistant_tool_call_message(response)
            working_messages.append(assistant_tool_call)
            # assistant tool-call 提交点（不含 completion-retry 脚手架与纯文本响应，
            # 后者由 phases 层 turn_output_committed 记录）。
            await _commit_message(ASSISTANT_MESSAGE_COMMITTED, assistant_tool_call)
            tool_messages: list[ChatMessage] = []
            tool_results: list[tuple[ToolCall, ToolResult]] = []
            for index, tool_call in enumerate(response.tool_calls):
                if self._elapsed(started_monotonic) >= self.max_elapsed_seconds:
                    return await _finish_turn(
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
                    await cast(TrajectoryStore, self.trajectory_store).record(
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

                await self._publish_presentation(
                    PresentationEvent(
                        PresentationEventKind.TOOL_STARTED,
                        session_key,
                        trace_id,
                        tool_call.name,
                        turn_id=trace_id,
                        step_id=tool_call_id,
                        status="running",
                    )
                )
                tool_clock = time.monotonic()
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
                        conversation_epoch=commit.epoch,
                        capability_revision=capability_revision or 1,
                        allowed_tool_names=frozenset(
                            _schema_tool_names(iteration_tools)
                        ),
                    ),
                )
                tool_results.append((tool_call, result))
                await self._publish_presentation(
                    PresentationEvent(
                        PresentationEventKind.TOOL_FINISHED,
                        session_key,
                        trace_id,
                        tool_call.name,
                        turn_id=trace_id,
                        step_id=tool_call_id,
                        status=result.effective_status,
                        elapsed_seconds=self._elapsed(tool_clock),
                        error_type=(
                            ""
                            if result.success
                            else str(result.metadata.get("error") or "tool-error")
                        ),
                    )
                )
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
                model_content = result.content
                preview_metadata: dict[str, Any] = {}
                if self.tool_result_previewer is not None:
                    governed_content = cast(
                        TrajectoryStore, self.trajectory_store
                    ).sanitize_for_capture(raw_content)
                    try:
                        raw_event = await cast(
                            TrajectoryStore, self.trajectory_store
                        ).record(
                            NewTrajectoryEvent(
                                trace_id=trace_id,
                                span_id=tool_span_id,
                                event_type="tool_result_payload_stored",
                                payload={
                                    "tool_call_id": tool_call_id,
                                    "name": tool_call.name,
                                    "raw_content": governed_content,
                                },
                            )
                        )
                    except TrajectoryError:
                        return self._trace_write_failure(
                            trace_id, iteration, steps, usage
                        )
                    payload_ref = (
                        f"trajectory-payload:{raw_event.payload_id}"
                        if raw_event.payload_id is not None
                        else f"trajectory-event:{trace_id}:{raw_event.sequence}"
                    )
                    preview = self.tool_result_previewer.freeze(
                        session_key=session_key,
                        tool_call_id=tool_call_id,
                        tool_name=tool_call.name,
                        content=governed_content,
                        payload_ref=payload_ref,
                        epoch=commit.epoch,
                    )
                    if preview.transformed:
                        model_content = preview.preview
                    preview_metadata = {
                        "preview_id": preview.preview_id,
                        "payload_ref": preview.payload_ref,
                        "content_hash": preview.content_hash,
                    }
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
                            "model_content": model_content,
                            "preview": preview_metadata,
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
                    await cast(TrajectoryStore, self.trajectory_store).record(
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
                                "model_content": model_content,
                                "preview": preview_metadata,
                                "metadata": result.metadata,
                            },
                            span=tool_finished,
                        )
                    )
                except TrajectoryError:
                    return self._trace_write_failure(trace_id, iteration, steps, usage)
                if tool_call.name == "update_working_checkpoint":
                    revision = result.metadata.get("revision")
                    await self._publish_presentation(
                        PresentationEvent(
                            PresentationEventKind.CHECKPOINT_CHANGED,
                            session_key,
                            trace_id,
                            turn_id=trace_id,
                            step_id=tool_call_id,
                            status="updated" if result.success else "failed",
                        )
                    )
                    try:
                        await cast(TrajectoryStore, self.trajectory_store).record(
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
                tool_message = ChatMessage(
                    role="tool",
                    content=model_content,
                    tool_call_id=tool_call_id,
                    name=tool_call.name,
                )
                tool_messages.append(tool_message)
                # tool 结果提交点：保留 tool_call_id/name 以维持工具协议配对。
                await _commit_message(TOOL_MESSAGE_COMMITTED, tool_message)
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
                    return await _finish_turn(
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
                return await _finish_turn(
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

        return await _finish_turn(
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

    async def _apply_compaction_plan(
        self,
        compilation: ContextCompilation,
        *,
        compacted_this_turn: bool,
        session_key: str,
        session_instance_id: str,
        visible_messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        status_revision: int,
        trace_id: str,
        root_span_id: str,
        commit: _TurnCommitState,
        working_messages: list[ChatMessage] | None = None,
        emergency: bool = False,
    ) -> tuple[ContextCompilation, bool]:
        """§5.1/§5.2/§5.6/§5.7：统一压缩协调器——soft/hard/emergency 共用同一入口。

        按 plan、execute、validate、commit 顺序执行。emergency 分支走确定性 shed
        （不调用 LLM 压缩、不提交 archive，design「无 compaction provider 时只允许
        确定性降载，不得把机械截断标记成 archive」），熔断/编译失败/最小必需仍超
        限时返回原 compilation（同 hash → 调用方 ``improved`` 判否），让原
        context-length 错误稳定传播。soft/hard 分支对 plan.batch 执行任务感知压缩
        并在提交后重编译（loop-guard）；压缩 Provider/校验失败时保原可发送视图、
        计数失败且不标记源 turn 已覆盖（原视图已通过预算，合法请求存在，故 soft/
        hard 均不结束）；重编译后仍超预算时 soft 保原视图，hard 视为无法生成合法
        请求而显式结束（抛出由调用方捕获）。
        """
        if emergency:
            # §5.1/§5.7：emergency 经统一协调器——确定性 shed 重编译，不调 LLM
            # 压缩、不提交 archive。熔断/最小必需仍超限返回原 compilation（同 hash）。
            assert working_messages is not None and self.context_compiler is not None
            visible, _ = self._assemble_model_context(working_messages, session_key)
            try:
                recompiled = self.context_compiler.compile(
                    session_key=session_key,
                    session_instance_id=session_instance_id,
                    messages=visible,
                    tools=list(tools or ()),
                    working_state_revision=status_revision,
                    emergency=True,
                    epoch=commit.epoch,
                    revoked_tool_names=(
                        self.tool_registry.revoked_tool_names
                        if self.tool_registry
                        else frozenset()
                    ),
                    capability_revision=compilation.capability_revision,
                )
            except (ContextBudgetExhausted, ContextCompactionCircuitOpen):
                return compilation, True
            return recompiled, True
        plan = compilation.compaction_plan
        if (
            plan is None
            or plan.mode not in ("soft", "hard")
            or compacted_this_turn
            or self.task_compactor is None
            or not plan.batch
        ):
            return compilation, compacted_this_turn
        # 到此必有 context_compiler（compilation.compaction_plan 由其 compile() 产出；
        # 与 emergency 分支 1059 同一不变式），显式收窄 Optional 供下方
        # record_compaction_failure/clear_compaction_failures/compile 访问。
        assert self.context_compiler is not None
        try:
            await self.task_compactor.compact(
                session_key=session_key,
                messages=list(plan.batch),
                trace_id=trace_id,
                parent_span_id=root_span_id,
                trajectory_store=self.trajectory_store,
                target_tokens=plan.target_tokens,
                parent_archive_refs=plan.parent_archive_refs,
                epoch=commit.epoch,
            )
        except ContextStateError:
            # §6.3：并发/重试 coverage/generation 冲突——commit_archive 事务原子
            # 回滚，无孤立 archive、未标记源 turn 覆盖。冲突意味着 Provider 已产出
            # 合法 archive（仅提交时撞并发 archive 的 coverage/generation），故视同
            # 成功路径：清熔断 + 走下方 fresh re-compile（重读 coverage，冲突批次
            # refs 已被并发 archive 覆盖 → _drop_covered_groups 排除；correction 15
            # 不得复用 stale compilation）。compacted_this_turn 置位防本轮再压缩。
            # 不计熔断失败（非 Provider/校验故障；spec「事务无法提交」的有界重试
            # 即此 fresh re-compile）。
            pass
        except CompactionError:
            # §5.2/§5.6：压缩 Provider/校验失败——保原可发送视图、计数失败、不标记
            # 源 turn 已覆盖。原视图已通过预算（合法请求存在），故 soft/hard 均不结束。
            self.context_compiler.record_compaction_failure(session_key)
            return compilation, True
        self.context_compiler.clear_compaction_failures(session_key)
        # §6.5：direct compact 已提交（frontier +1），若超 archive_frontier_tokens/
        # max_items 则 best-effort 合并最旧相邻 frontier。合并失败不阻断本轮重编译
        # （merge_frontier 吞已知异常；此处兜底防未知异常崩溃本轮——spec「原有
        # frontier 保持不变」+ §6.4 bounded injection 兜底注入）。显式 None-guard
        # 收窄 Optional，避免新增 pyright 报错（context_compiler.settings 访问）。
        if self.task_compactor is not None and self.context_compiler is not None:
            settings = self.context_compiler.settings
            try:
                await self.task_compactor.merge_frontier(
                    session_key=session_key,
                    trace_id=trace_id,
                    parent_span_id=root_span_id,
                    trajectory_store=self.trajectory_store,
                    epoch=commit.epoch,
                    frontier_tokens=settings.archive_frontier_tokens,
                    frontier_max_items=settings.archive_frontier_max_items,
                )
            except Exception:  # noqa: BLE001 — best-effort 合并不阻断重编译
                pass
        try:
            recompiled = self.context_compiler.compile(
                session_key=session_key,
                session_instance_id=session_instance_id,
                messages=visible_messages,
                tools=list(tools or ()),
                working_state_revision=status_revision,
                compacted_this_turn=True,
                epoch=commit.epoch,
                capability_revision=compilation.capability_revision,
            )
        except ContextBudgetExhausted:
            # 重编译仍超预算：soft 保原视图，hard 显式结束。
            if plan.mode == "hard":
                raise
            return compilation, True
        return recompiled, True

    async def _chat_with_fallback(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        *,
        session_key: str,
        trace_id: str,
        exchange: ProviderExchange,
    ) -> LLMResponse:
        callback = self._build_model_event_callback(session_key, trace_id)
        await self._publish_presentation(
            PresentationEvent(
                PresentationEventKind.MODEL_STARTED,
                session_key,
                trace_id,
                turn_id=trace_id,
                step_id="model",
                status="running",
            )
        )
        try:
            return await invoke_provider(
                self.provider,
                messages,
                tools,
                model=self.model_name,
                stream=self.stream_model,
                reasoning_policy=exchange.reasoning_policy,
                continuation=exchange.continuation,
                on_event=callback,
            )
        except ProviderError as primary_error:
            if (
                self.stream_model
                and primary_error.error_type == "provider-response-protocol"
            ):
                try:
                    response = await invoke_provider(
                        self.provider,
                        messages,
                        tools,
                        model=self.model_name,
                        stream=False,
                        reasoning_policy=exchange.reasoning_policy,
                        continuation=exchange.continuation,
                        on_event=callback,
                    )
                except ProviderError as recovery_error:
                    return self._error_response(recovery_error)
                return replace(
                    response,
                    fallback_reason="stream-protocol-recovery",
                    attempt_count=max(1, primary_error.attempt)
                    + max(1, response.attempt_count),
                    attempts=(*primary_error.attempts, *response.attempts),
                    partial_stream=primary_error.partial_stream,
                )
            if (
                self.fallback_provider is not None
                and exchange.continuation is None
                and not primary_error.partial_stream
                and primary_error.error_type != "provider-context-length"
            ):
                try:
                    response = await invoke_provider(
                        self.fallback_provider,
                        messages,
                        tools,
                        model=self.model_name,
                        stream=self.stream_model,
                        reasoning_policy=exchange.reasoning_policy,
                        on_event=callback,
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
                    continuation=response.continuation,
                )
            return self._error_response(primary_error)

    def _build_model_event_callback(
        self,
        session_key: str,
        trace_id: str,
    ) -> EventCallback | None:
        if self.model_event_callback is None and self.presentation_events is None:
            return None

        async def callback(event: Any) -> None:
            if self.model_event_callback is not None:
                await self.model_event_callback(event)
            if self.presentation_events is not None:
                try:
                    await self.presentation_events.publish_model_event(
                        session_key,
                        trace_id,
                        event,
                    )
                except Exception:
                    # 表现层是 Observer，故障不能改变模型与工具行为。
                    return

        return callback

    async def _publish_presentation(self, event: PresentationEvent) -> None:
        if self.presentation_events is None:
            return
        try:
            await self.presentation_events.publish(event)
        except Exception:
            # 表现层是 Observer，任何故障都不能改变 Agent 行为。
            return

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

    async def cancel_trace(
        self,
        trace_id: str,
        root_span_id: str,
        session_key: str,
    ) -> None:
        """把用户取消写成可审计终态；写入失败不得掩盖取消控制流。"""

        ended_at = utc_now_iso()
        provider_name = str(
            getattr(self.provider, "name", type(self.provider).__name__)
        )
        try:
            await self.trajectory_store.record(
                NewTrajectoryEvent(
                    trace_id=trace_id,
                    span_id=root_span_id,
                    event_type="trace_cancelled",
                    payload={
                        "termination_reason": "cancelled",
                        "error_type": "user-cancelled",
                    },
                    trace=TraceProjection(
                        trace_id=trace_id,
                        session_id=session_key,
                        started_at=ended_at,
                        ended_at=ended_at,
                        status="cancelled",
                        termination_reason="cancelled",
                        provider=provider_name,
                        model=self.model_name,
                    ),
                    span=SpanProjection(
                        span_id=root_span_id,
                        trace_id=trace_id,
                        parent_span_id=None,
                        kind=SpanKind.AGENT,
                        name="agent-turn",
                        started_at=ended_at,
                        ended_at=ended_at,
                        status="cancelled",
                        output_data={"termination_reason": "cancelled"},
                        error_type="user-cancelled",
                    ),
                )
            )
        except TrajectoryError:
            return
        await self._publish_presentation(
            PresentationEvent(
                PresentationEventKind.TURN_CANCELLED,
                session_key,
                trace_id,
                turn_id=trace_id,
                status="cancelled",
                error_type="user-cancelled",
            )
        )

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
        commit: _TurnCommitState | None = None,
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
        terminal_kind = (
            PresentationEventKind.TURN_COMPLETED
            if reason in {TerminationReason.COMPLETED, TerminationReason.NEEDS_USER}
            else PresentationEventKind.TURN_FAILED
        )
        await self._publish_presentation(
            PresentationEvent(
                terminal_kind,
                trace.session_id,
                trace.trace_id,
                turn_id=trace.trace_id,
                status=reason.value,
                usage=tuple(
                    sorted(
                        (key, int(value))
                        for key, value in usage.items()
                        if isinstance(value, int)
                    )
                ),
                error_type=error_type or "",
            )
        )
        # 跨轮 committed 状态：commit 为 None 或不可提交时全为 0（phases 据此跳过
        # turn_output）。经 ``commit is not None`` 直接收窄（pyright 不经
        # bool 变量收窄）。
        if commit is not None and commit.can_commit:
            committed_epoch = commit.epoch
            committed_turn_seq = commit.turn_seq
            committed_output_seq = commit.next_seq
        else:
            committed_epoch = 0
            committed_turn_seq = 0
            committed_output_seq = 0
        return TurnResult(
            trace_id=trace.trace_id,
            response=response,
            termination_reason=reason,
            iterations=iterations,
            steps=tuple(steps),
            usage=dict(usage),
            fallback_used=fallback_used,
            error_type=error_type,
            committed_epoch=committed_epoch,
            committed_turn_seq=committed_turn_seq,
            committed_output_seq=committed_output_seq,
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


def _schema_tool_names(tools: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for item in tools:
        function = item.get("function")
        if isinstance(function, dict):
            name = str(function.get("name") or "")
            if name:
                names.add(name)
    return names


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
