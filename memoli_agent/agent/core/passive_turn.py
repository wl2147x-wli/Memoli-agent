"""被动对话 turn pipeline。

PassiveTurnPipeline 负责处理一条普通用户消息的完整生命周期。
AgentLoop 不再关心 session、prompt、reasoner 等细节，只调用 runner。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from memoli_agent.agent.context import ContextBuilder
from memoli_agent.agent.context_management import (
    ContextSource,
    PreviewIntegrityLookup,
)
from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.lifecycle.phase import PhaseModule, run_phase_modules
from memoli_agent.agent.lifecycle.phases import (
    AfterReasoningPhase,
    AfterTurnPhase,
    BeforeReasoningPhase,
    BeforeTurnPhase,
    CrossTurnContextPhase,
    PromptRenderPhase,
    ReasonerPhase,
)
from memoli_agent.agent.lifecycle.types import PassiveTurnContext
from memoli_agent.agent.memory.consolidator import MemoryConsolidator
from memoli_agent.agent.memory.runtime import MemoryRuntime
from memoli_agent.agent.plugins.hooks import HookBus
from memoli_agent.agent.session import SessionManager
from memoli_agent.agent.skills.runtime import SkillRuntime
from memoli_agent.agent.tools.control import WorkingStateStore
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import TrajectoryError, TrajectoryStore
from memoli_agent.bus.events import InboundMessage, OutboundMessage


class TurnCancelled(Exception):
    """携带安全关联标识的用户 turn 取消结果。"""

    def __init__(self, trace_id: str) -> None:
        super().__init__("user-cancelled")
        self.trace_id = trace_id


@dataclass(slots=True)
class PassiveTurnPipeline:
    """普通用户消息的一轮被动对话 pipeline。"""

    session_manager: SessionManager
    context_builder: ContextBuilder
    reasoner: Reasoner
    memory_runtime: MemoryRuntime | None = None
    memory_consolidator: MemoryConsolidator | None = None
    hook_registry: HookBus | None = None
    working_state: WorkingStateStore | None = None
    trajectory_store: TrajectoryStore | None = None
    # 可选 durable 跨轮来源：仅主被动 turn 装配（§7.5）；None 时 CrossTurnContextPhase
    # 保持隔离，不读取主 Agent 的跨轮历史，SubAgent 默认隔离由此保证。
    context_source: ContextSource | None = None
    # §7.3 恢复期预览引用完整性校验来源（ContextStateRepository 实现
    # get_preview_by_ref）；仅主被动 turn 装配，None 时跳过校验、保持隔离。
    preview_lookup: PreviewIntegrityLookup | None = None
    # §8.1 跨轮来源单次读取上限（I/O 防护，None=不限）；仅主被动 turn 由 config
    # 注入，CrossTurnContextPhase 据此对 read_turns 加 turn/byte 边界。
    source_read_max_turns: int | None = None
    source_read_max_bytes: int | None = None
    skill_runtime: SkillRuntime | None = None
    tool_registry: ToolRegistry | None = None
    mcp_names_provider: Callable[[], set[str]] | None = None
    phases: list[PhaseModule] = field(init=False)

    def __post_init__(self) -> None:
        """创建默认阶段链。"""

        self.phases = [
            BeforeTurnPhase(self.session_manager, self.hook_registry),
            CrossTurnContextPhase(
                self.context_source,
                self.trajectory_store,
                preview_lookup=self.preview_lookup,
                source_read_max_turns=self.source_read_max_turns,
                source_read_max_bytes=self.source_read_max_bytes,
            ),
            BeforeReasoningPhase(
                self.memory_runtime,
                self.working_state,
                self.hook_registry,
                self.trajectory_store,
            ),
            PromptRenderPhase(
                self.context_builder,
                self.hook_registry,
                self.skill_runtime,
                self.tool_registry,
                self.mcp_names_provider,
            ),
            ReasonerPhase(self.reasoner),
            AfterReasoningPhase(
                self.memory_consolidator,
                self.hook_registry,
                self.trajectory_store,
            ),
            AfterTurnPhase(
                self.hook_registry,
                self.memory_runtime,
                self.working_state,
            ),
        ]

    async def run(self, inbound: InboundMessage) -> OutboundMessage:
        """处理一条入站消息并返回出站消息。"""

        ctx = PassiveTurnContext(inbound=inbound)
        try:
            ctx.trace_id, ctx.root_span_id = await self.reasoner.prepare_trace(
                inbound.session_key, inbound.content
            )
        except TrajectoryError:
            return OutboundMessage(
                channel=inbound.channel,
                chat_id=inbound.chat_id,
                content="本地运行轨迹写入失败，已停止本轮操作。",
                metadata={
                    "status": "error",
                    "error_type": "trace-write-failed",
                    "retryable": False,
                },
            )
        try:
            await run_phase_modules(ctx, self.phases)
        except asyncio.CancelledError:
            # 用户取消仍要留下真实的终止证据；随后继续传播控制流给 AgentLoop。
            await self.reasoner.cancel_trace(
                ctx.trace_id,
                ctx.root_span_id,
                inbound.session_key,
            )
            raise TurnCancelled(ctx.trace_id) from None

        if ctx.outbound is None:
            raise RuntimeError("PassiveTurnPipeline 未生成 OutboundMessage。")

        return ctx.outbound
