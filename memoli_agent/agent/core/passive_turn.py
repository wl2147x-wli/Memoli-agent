"""被动对话 turn pipeline。

PassiveTurnPipeline 负责处理一条普通用户消息的完整生命周期。
AgentLoop 不再关心 session、prompt、reasoner 等细节，只调用 runner。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from memoli_agent.agent.context import ContextBuilder
from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.memory.consolidator import MemoryConsolidator
from memoli_agent.agent.memory.runtime import MemoryRuntime
from memoli_agent.agent.plugins.decorators import HookRegistry
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
from memoli_agent.agent.session import SessionManager
from memoli_agent.bus.events import InboundMessage, OutboundMessage


@dataclass(slots=True)
class PassiveTurnPipeline:
    """普通用户消息的一轮被动对话 pipeline。"""

    session_manager: SessionManager
    context_builder: ContextBuilder
    reasoner: Reasoner
    memory_runtime: MemoryRuntime | None = None
    memory_consolidator: MemoryConsolidator | None = None
    hook_registry: HookRegistry | None = None
    phases: list[PhaseModule] = field(init=False)

    def __post_init__(self) -> None:
        """创建默认阶段链。"""

        self.phases = [
            BeforeTurnPhase(self.session_manager, self.hook_registry),
            BeforeReasoningPhase(self.memory_runtime, self.hook_registry),
            PromptRenderPhase(self.context_builder, self.hook_registry),
            ReasonerPhase(self.reasoner),
            AfterReasoningPhase(self.memory_consolidator, self.hook_registry),
            AfterTurnPhase(self.hook_registry),
        ]

    async def run(self, inbound: InboundMessage) -> OutboundMessage:
        """处理一条入站消息并返回出站消息。"""

        ctx = PassiveTurnContext(inbound=inbound)
        await run_phase_modules(ctx, self.phases)

        if ctx.outbound is None:
            raise RuntimeError("PassiveTurnPipeline 未生成 OutboundMessage。")

        return ctx.outbound
