"""默认生命周期阶段。

这些阶段组成一轮普通用户消息的最小处理链路（装配顺序见 passive_turn）：

BeforeTurn -> CrossTurnContext -> BeforeReasoning -> PromptRender
-> Reasoner -> AfterReasoning -> AfterTurn

CrossTurnContext 读取当前 conversation epoch 的规范化 committed turn
（主 Agent 装配 durable ContextSource；SubAgent 自建 Reasoner 绕过本链
故不获跨轮历史），其输出由 PromptRender 消费；当前 turn 继续用
Reasoner.working_messages。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import cast

from memoli_agent.agent.context import ContextBuilder
from memoli_agent.agent.context_management import (
    CommittedTurnStore,
    ContextSource,
    PreviewIntegrityLookup,
    build_envelope,
    verify_turn_previews,
)
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
    TURN_OUTPUT_COMMITTED,
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
class CrossTurnContextPhase:
    """解析当前 conversation epoch 与近期完整 turn（§3.1 跨轮上下文边界）。

    从 trajectory store 读取权威 epoch，再经 ContextSource 读取当前 epoch 内
    已终止、排除当前 trace 的规范化 turn，重构为可见 messages 写入 ctx.recent_turns。
    无 durable source（SubAgent/降级，§7.5）时保持空 recent_turns，绝不拼接旧
    Session history、损坏轨迹或 metadata-only 内容（§2.6）。
    """

    context_source: ContextSource | None = None
    trajectory_store: TrajectoryStore | None = None
    # §6.7 跨轮来源单次读取的 turn/byte I/O 上限（None=无上限，保留当前行为）；
    # 触及时 reader 返回 source-truncated 诊断 + 续读游标，由调用方分批推进。
    source_read_max_turns: int | None = None
    source_read_max_bytes: int | None = None
    # §7.3 恢复期预览引用完整性校验来源（ContextStateRepository 实现
    # get_preview_by_ref）；仅主被动 turn 装配（§7.5），None 时跳过校验、保持隔离。
    preview_lookup: PreviewIntegrityLookup | None = None

    async def run(self, ctx: PassiveTurnContext) -> None:
        """解析 epoch 与近期完整 turn，写入 ctx 供 PromptRenderPhase 消费。"""

        session_key = ctx.inbound.session_key
        epoch = ctx.conversation_epoch
        if (
            self.trajectory_store is not None
            and isinstance(self.trajectory_store, CommittedTurnStore)
        ):
            try:
                epoch = await self.trajectory_store.current_epoch(session_key)
            except TrajectoryError:
                ctx.metadata["cross_turn_status"] = "epoch-unavailable"
                ctx.metadata["cross_turn_epoch"] = epoch
                # 权威 epoch 不可读时仍尝试用镜像读取，read_turns 内部会再降级。
            else:
                ctx.conversation_epoch = epoch
                ctx.metadata["cross_turn_epoch"] = epoch
        else:
            ctx.metadata["cross_turn_epoch"] = epoch
        if self.context_source is None:
            # 未装配 durable source：保持隔离，不读旧历史（§7.5）。
            ctx.metadata["cross_turn_status"] = "isolated"
            return
        try:
            read = await self.context_source.read_turns(
                session_key=session_key,
                epoch=epoch,
                exclude_trace_id=ctx.trace_id or None,
                max_turns=self.source_read_max_turns,
                max_bytes=self.source_read_max_bytes,
            )
        except TrajectoryError:
            ctx.metadata["cross_turn_status"] = "read-failed"
            return
        turns = read.turns
        # §7.3 恢复期引用完整性校验：对含已冻结预览的 tool-result 消息校验
        # epoch/tool_call_id/canonical hash/payload_ref；不一致的整 turn 排除
        # （不拆散 tool pair、不重新生成预览），使校验失败可观察、不影响其他 turn。
        excluded = 0
        if self.preview_lookup is not None:
            verified: list = []
            for turn in turns:
                if (
                    verify_turn_previews(
                        turn,
                        session_key=session_key,
                        preview_lookup=self.preview_lookup,
                    )
                    is not None
                ):
                    verified.append(turn)
                else:
                    excluded += 1
            turns = tuple(verified)
            if excluded:
                ctx.metadata["cross_turn_preview_excluded_turns"] = excluded
        ctx.recent_turns = tuple(
            message for turn in turns for message in turn.to_messages()
        )
        ctx.metadata["cross_turn_status"] = "ready"
        ctx.metadata["cross_turn_turn_count"] = len(turns)
        ctx.metadata["cross_turn_message_count"] = len(ctx.recent_turns)
        # §6.7 source-truncated 诊断：触及 turn/byte I/O 上限时记录续读游标，
        # 使截断的未读内容可观察、可分批推进，绝不静默当作「无更多历史」。
        ctx.metadata["cross_turn_truncated"] = read.truncated
        ctx.metadata["cross_turn_next_after_turn_seq"] = read.next_after_turn_seq


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
        ctx.metadata["memory_query_context_fields"] = list(result.query_context_fields)
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
                            "omitted_items": result.omitted_items,
                            "omitted_chars": result.omitted_chars,
                            "active_lanes": list(result.active_lanes),
                            "degraded_lanes": list(result.degraded_lanes),
                            "lane_candidate_counts": dict(result.lane_candidate_counts),
                            "query_context_fields": list(result.query_context_fields),
                            "query_plan_summary": dict(result.query_plan_summary),
                            "filter_counts": dict(result.filter_counts),
                            "actual_route": result.actual_route,
                            "requested_route": result.requested_route,
                        },
                    )
                )
            except TrajectoryError:
                ctx.metadata["memory_trace_diagnostic"] = "write-failed"


@dataclass(frozen=True, slots=True)
class PromptRenderPhase:
    """渲染模型上下文。"""

    context_builder: ContextBuilder
    hook_registry: HookBus | None = None
    skill_runtime: SkillRuntime | None = None
    tool_registry: ToolRegistry | None = None
    mcp_names_provider: Callable[[], set[str]] | None = None

    async def run(self, ctx: PassiveTurnContext) -> None:
        """调用 ContextBuilder 生成 messages。"""

        if ctx.turn_state is None:
            raise RuntimeError("PromptRenderPhase 需要先完成 BeforeTurnPhase。")

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
                recent_turns=ctx.recent_turns,
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
                current = ctx.context_result.messages
                ctx.context_result = replace(
                    ctx.context_result,
                    messages=[current[0], *injected, *current[1:]],
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
    """记录最终 transformed 输出并触发响应后扩展点。"""

    memory_consolidator: MemoryConsolidator | None = None
    hook_registry: HookBus | None = None
    trajectory_store: TrajectoryStore | None = None

    async def run(self, ctx: PassiveTurnContext) -> None:
        """RESPONSE_TRANSFORM 之后记录 turn_output committed envelope。"""

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

        # turn_output：变换后记录最终用户可见输出（§2.3）。committed_turn_seq 为 0
        # 表示 Reasoner 未记录 committed turn（轨迹关闭/不支持），跳过。
        if (
            self.trajectory_store is not None
            and ctx.turn_result is not None
            and ctx.turn_result.committed_turn_seq
            and ctx.turn_result.trace_id
        ):
            envelope = build_envelope(
                ChatMessage(role="assistant", content=ctx.llm_response.content),
                epoch=ctx.turn_result.committed_epoch,
                turn_seq=ctx.turn_result.committed_turn_seq,
                message_seq=ctx.turn_result.committed_output_seq,
                capture_mode=(
                    getattr(self.trajectory_store, "capture_content", "") or ""
                ),
            )
            try:
                await self.trajectory_store.record(
                    NewTrajectoryEvent(
                        trace_id=ctx.turn_result.trace_id,
                        span_id=ctx.root_span_id or None,
                        event_type=TURN_OUTPUT_COMMITTED,
                        payload=envelope,
                    )
                )
            except TrajectoryError:
                # turn_output 缺失由 reader 降级处理，不影响主控制流。
                pass

        # 完整对话只写入 trajectory；Session 不再保留消息历史副本（§3.1），
        # 长期记忆由离线 consolidation 消费轨迹。


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
                    self.memory_runtime.schedule_completed_trace(
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
