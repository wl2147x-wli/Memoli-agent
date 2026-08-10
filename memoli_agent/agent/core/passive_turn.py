"""被动对话 turn pipeline。

PassiveTurnPipeline 负责处理一条普通用户消息的完整生命周期。
AgentLoop 不再关心 session、prompt、reasoner 等细节，只调用 runner。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from memoli_agent.agent.context import ContextBuilder
from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.lifecycle.phase import PhaseModule, run_phase_modules
from memoli_agent.agent.lifecycle.phases import (
    AfterReasoningPhase,
    AfterTurnPhase,
    BeforeReasoningPhase,
    BeforeTurnPhase,
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
    skill_runtime: SkillRuntime | None = None
    tool_registry: ToolRegistry | None = None
    mcp_names_provider: Callable[[], set[str]] | None = None
    phases: list[PhaseModule] = field(init=False)

    def __post_init__(self) -> None:
        """创建默认阶段链。"""

        self.phases = [
            BeforeTurnPhase(self.session_manager, self.hook_registry),
            BeforeReasoningPhase(
                self.memory_runtime,
                self.working_state,
                self.hook_registry,
                self.trajectory_store,
            ),
            PromptRenderPhase(
                self.context_builder,
                self.working_state,
                self.hook_registry,
                self.skill_runtime,
                self.tool_registry,
                self.mcp_names_provider,
            ),
            ReasonerPhase(self.reasoner),
            AfterReasoningPhase(self.memory_consolidator, self.hook_registry),
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
        await run_phase_modules(ctx, self.phases)

        if ctx.outbound is None:
            raise RuntimeError("PassiveTurnPipeline 未生成 OutboundMessage。")

        return ctx.outbound
