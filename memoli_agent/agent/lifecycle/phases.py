"""默认生命周期阶段。

这些阶段组成一轮普通用户消息的最小处理链路：

BeforeTurn -> BeforeReasoning -> PromptRender -> Reasoner -> AfterReasoning -> AfterTurn
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import cast

from memoli_agent.agent.context import ContextBuilder
from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.lifecycle.types import PassiveTurnContext
from memoli_agent.agent.memory.consolidator import MemoryConsolidator
from memoli_agent.agent.memory.runtime import MemoryRuntime
from memoli_agent.agent.plugins.events import (
    ContextContributeEvent,
    HookName,
    ResponseTransformEvent,
    TurnAfterEvent,
    TurnBeforeEvent,
)
from memoli_agent.agent.plugins.hooks import HookBus
from memoli_agent.agent.session import SessionManager
from memoli_agent.agent.skills.runtime import SkillRuntime
from memoli_agent.agent.tools.control import WorkingStateStore
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import (
    NewTrajectoryEvent,
    TrajectoryError,
    TrajectoryStore,
)
from memoli_agent.agent.types import ChatMessage, ContextRequest, TurnState
from memoli_agent.bus.events import OutboundMessage


@dataclass(frozen=True, slots=True)
class BeforeTurnPhase:
    """准备 session 和基础 turn 状态。"""

    session_manager: SessionManager
    hook_registry: HookBus | None = None

    async def run(self, ctx: PassiveTurnContext) -> None:
        """根据入站消息获取会话并创建 TurnState。"""

        session = self.session_manager.get_or_create(ctx.inbound.session_key)
        ctx.session = session
        ctx.turn_state = TurnState(
            session_key=ctx.inbound.session_key,
            inbound=ctx.inbound,
            session=session,
        )
        ctx.metadata["session_key"] = ctx.inbound.session_key
        if self.hook_registry is not None:
            event = await self.hook_registry.transform(
                HookName.TURN_BEFORE,
                TurnBeforeEvent(
                    trace_id=ctx.trace_id,
                    session_key=ctx.inbound.session_key,
                    channel=ctx.inbound.channel,
                    chat_id=ctx.inbound.chat_id,
                    content=ctx.inbound.content,
                    metadata=dict(ctx.metadata),
                ),
            )
            ctx.metadata.update(event.metadata)


@dataclass(frozen=True, slots=True)
class BeforeReasoningPhase:
    """推理前扩展点。

    第七阶段在这里查询长期记忆，并生成可注入 prompt 的记忆块。
    """

    memory_runtime: MemoryRuntime | None = None
    working_state: WorkingStateStore | None = None
    hook_registry: HookBus | None = None
    trajectory_store: TrajectoryStore | None = None

    async def run(self, ctx: PassiveTurnContext) -> None:
        """查询与当前用户输入相关的长期记忆。"""

        if self.memory_runtime is None:
            return

        checkpoint = (
            self.working_state.get_checkpoint(ctx.inbound.session_key)
            if self.working_state is not None
            else None
        )
        try:
            result = await self.memory_runtime.pre_recall(
                user_message=ctx.inbound.content,
                objective=checkpoint.objective if checkpoint else "",
                current_step=checkpoint.current_step if checkpoint else "",
                session_id=ctx.inbound.session_key,
            )
        except Exception as exc:
            ctx.metadata["memory_status"] = "degraded"
            ctx.metadata["memory_error_type"] = type(exc).__name__
            return
        ctx.memory_query_result = result
        ctx.memory_prompt_block = self.memory_runtime.render_prompt_block(result)
        if result.items:
            ctx.metadata["memory_match_count"] = len(result.items)
        ctx.metadata["memory_candidate_count"] = result.candidate_count
        ctx.metadata["memory_filtered_count"] = result.filtered_count
        ctx.metadata["memory_injected_ids"] = [item.item_id for item in result.items]
        ctx.metadata["memory_injected_chars"] = result.injected_chars
        ctx.metadata["memory_status"] = "degraded" if result.degraded else "ready"
        ctx.metadata["memory_reason"] = result.reason
        ctx.metadata["memory_active_lanes"] = list(result.active_lanes)
        ctx.metadata["memory_degraded_lanes"] = list(result.degraded_lanes)
        ctx.metadata["memory_lane_candidate_counts"] = dict(
            result.lane_candidate_counts
        )
        ctx.metadata["memory_query_context_fields"] = list(
            result.query_context_fields
        )
        if self.trajectory_store is not None and ctx.trace_id:
            try:
                await self.trajectory_store.record(
                    NewTrajectoryEvent(
                        trace_id=ctx.trace_id,
                        span_id=ctx.root_span_id or None,
                        event_type="memory_retrieved",
                        payload={
                            "candidate_count": result.candidate_count,
                            "filtered_count": result.filtered_count,
                            "injected_ids": [item.item_id for item in result.items],
                            "injected_chars": result.injected_chars,
                            "active_lanes": list(result.active_lanes),
                            "degraded_lanes": list(result.degraded_lanes),
                            "lane_candidate_counts": dict(
                                result.lane_candidate_counts
                            ),
                            "query_context_fields": list(
                                result.query_context_fields
                            ),
                        },
                    )
                )
            except TrajectoryError:
                ctx.metadata["memory_trace_diagnostic"] = "write-failed"


@dataclass(frozen=True, slots=True)
class PromptRenderPhase:
    """渲染模型上下文。"""

    context_builder: ContextBuilder
    working_state: WorkingStateStore | None = None
    hook_registry: HookBus | None = None
    skill_runtime: SkillRuntime | None = None
    tool_registry: ToolRegistry | None = None
    mcp_names_provider: Callable[[], set[str]] | None = None

    async def run(self, ctx: PassiveTurnContext) -> None:
        """调用 ContextBuilder 生成 messages。"""

        if ctx.turn_state is None:
            raise RuntimeError("PromptRenderPhase 需要先完成 BeforeTurnPhase。")

        if self.working_state is not None:
            ctx.working_prompt_block = self.working_state.render_checkpoint(
                ctx.turn_state.session_key
            )
        if self.skill_runtime is not None and self.tool_registry is not None:
            catalog = self.skill_runtime.build_catalog(
                session_instance_id=ctx.turn_state.session.session_instance_id,
                session_key=ctx.turn_state.session_key,
                tools={tool.name for tool in self.tool_registry.list_tools()},
                mcp_servers=(
                    set(self.mcp_names_provider()) if self.mcp_names_provider else set()
                ),
            )
            ctx.skill_catalog_prompt_block = catalog.content
            ctx.metadata["skill_catalog"] = {
                "candidate_count": catalog.candidate_count,
                "disclosed_count": catalog.disclosed_count,
                "omitted_count": catalog.omitted_count,
                "omitted": catalog.omitted,
                "char_count": catalog.char_count,
                "error": catalog.error,
            }
        ctx.context_result = self.context_builder.render(
            ContextRequest(
                turn_state=ctx.turn_state,
                agent_name=self.context_builder.agent_name,
                system_prompt=self.context_builder.system_prompt,
                skill_catalog_prompt_block=ctx.skill_catalog_prompt_block,
                memory_prompt_block=ctx.memory_prompt_block,
                working_prompt_block=ctx.working_prompt_block,
            )
        )
        ctx.metadata["context_message_count"] = len(ctx.context_result.messages)
        if self.hook_registry is not None:
            event = cast(
                ContextContributeEvent,
                await self.hook_registry.transform(
                    HookName.CONTEXT_CONTRIBUTE,
                    ContextContributeEvent(
                        trace_id=ctx.trace_id,
                        session_key=ctx.inbound.session_key,
                        messages=tuple(
                            message.to_dict() for message in ctx.context_result.messages
                        ),
                    ),
                ),
            )
            if event.sections:
                sections = sorted(
                    event.sections, key=lambda item: (item.order, item.name)
                )
                injected = [
                    ChatMessage(
                        role="system",
                        content=f"[插件上下文:{section.name}]\n{section.content}",
                    )
                    for section in sections
                ]
                ctx.context_result = replace(
                    ctx.context_result,
                    messages=[*injected, *ctx.context_result.messages],
                )
                ctx.metadata["plugin_context_sections"] = [
                    {"name": item.name, "source": item.source_plugin}
                    for item in sections
                ]


@dataclass(frozen=True, slots=True)
class ReasonerPhase:
    """调用 Reasoner 生成回复。"""

    reasoner: Reasoner

    async def run(self, ctx: PassiveTurnContext) -> None:
        """根据渲染后的 messages 调用模型。"""

        if ctx.context_result is None:
            raise RuntimeError("ReasonerPhase 需要先完成 PromptRenderPhase。")

        ctx.turn_result = await self.reasoner.run_turn(
            ctx.context_result.messages,
            session_key=ctx.context_result.session_key,
            trace_id=ctx.trace_id,
            root_span_id=ctx.root_span_id,
            session_instance_id=(
                ctx.session.session_instance_id if ctx.session is not None else ""
            ),
        )
        ctx.llm_response = ctx.turn_result.response
        ctx.metadata["provider"] = ctx.llm_response.provider
        ctx.metadata["fallback_used"] = ctx.llm_response.fallback_used
        ctx.metadata["trace_id"] = ctx.turn_result.trace_id
        ctx.metadata["termination_reason"] = ctx.turn_result.termination_reason.value
        ctx.metadata["iterations"] = ctx.turn_result.iterations
        ctx.metadata["usage"] = dict(ctx.turn_result.usage)
        if ctx.turn_result.error_type:
            ctx.metadata["error_type"] = ctx.turn_result.error_type


@dataclass(frozen=True, slots=True)
class AfterReasoningPhase:
    """保存当前轮用户消息和助手回复。"""

    memory_consolidator: MemoryConsolidator | None = None
    hook_registry: HookBus | None = None

    async def run(self, ctx: PassiveTurnContext) -> None:
        """将本轮对话写入 session 历史。"""

        if ctx.session is None:
            raise RuntimeError("AfterReasoningPhase 需要先完成 BeforeTurnPhase。")
        if ctx.llm_response is None:
            raise RuntimeError("AfterReasoningPhase 需要先完成 ReasonerPhase。")

        if self.hook_registry is not None:
            event = cast(
                ResponseTransformEvent,
                await self.hook_registry.transform(
                    HookName.RESPONSE_TRANSFORM,
                    ResponseTransformEvent(
                        trace_id=ctx.trace_id,
                        session_key=ctx.inbound.session_key,
                        content=ctx.llm_response.content,
                        outbound_metadata=dict(ctx.metadata),
                    ),
                ),
            )
            ctx.llm_response = replace(ctx.llm_response, content=event.content)
            ctx.metadata.update(event.outbound_metadata)

        ctx.session.add_user_message(ctx.inbound.content)
        ctx.session.add_assistant_message(ctx.llm_response.content)

        # 完整对话只写入 trajectory；长期记忆由离线 consolidation 消费轨迹。


@dataclass(frozen=True, slots=True)
class AfterTurnPhase:
    """创建出站消息。"""

    hook_registry: HookBus | None = None
    memory_runtime: MemoryRuntime | None = None
    working_state: WorkingStateStore | None = None

    async def run(self, ctx: PassiveTurnContext) -> None:
        """根据 LLMResponse 构造 OutboundMessage。"""

        if ctx.llm_response is None:
            raise RuntimeError("AfterTurnPhase 需要先完成 ReasonerPhase。")

        if self.memory_runtime is not None and ctx.trace_id:
            checkpoint = (
                self.working_state.get_checkpoint(ctx.inbound.session_key)
                if self.working_state is not None
                else None
            )
            try:
                ctx.metadata["episode_projection"] = (
                    await self.memory_runtime.project_completed_trace(
                        ctx.trace_id,
                        objective=checkpoint.objective if checkpoint else "",
                        current_step=checkpoint.current_step if checkpoint else "",
                    )
                )
            except Exception as exc:
                ctx.metadata["episode_projection"] = {
                    "status": "degraded",
                    "error_type": type(exc).__name__,
                }

        ctx.outbound = OutboundMessage(
            channel=ctx.inbound.channel,
            chat_id=ctx.inbound.chat_id,
            content=ctx.llm_response.content,
            metadata=dict(ctx.metadata),
        )
        if self.hook_registry is not None:
            await self.hook_registry.observe(
                HookName.TURN_AFTER,
                TurnAfterEvent(
                    trace_id=ctx.trace_id,
                    session_key=ctx.inbound.session_key,
                    content=ctx.llm_response.content,
                    termination_reason=(
                        ctx.turn_result.termination_reason.value
                        if ctx.turn_result
                        else ""
                    ),
                    metadata=dict(ctx.metadata),
                ),
            )
