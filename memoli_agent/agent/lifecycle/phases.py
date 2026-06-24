"""默认生命周期阶段。

这些阶段组成一轮普通用户消息的最小处理链路：

BeforeTurn -> BeforeReasoning -> PromptRender -> Reasoner -> AfterReasoning -> AfterTurn
"""

from __future__ import annotations

from dataclasses import dataclass

from memoli_agent.agent.context import ContextBuilder
from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.lifecycle.types import PassiveTurnContext
from memoli_agent.agent.memory.consolidator import MemoryConsolidator
from memoli_agent.agent.memory.runtime import MemoryQuery, MemoryRuntime
from memoli_agent.agent.plugins.decorators import (
    AFTER_REASONING,
    AFTER_TURN,
    BEFORE_REASONING,
    BEFORE_TURN,
    PROMPT_RENDER,
    HookRegistry,
)
from memoli_agent.agent.session import SessionManager
from memoli_agent.agent.types import ContextRequest, TurnState
from memoli_agent.bus.events import OutboundMessage


@dataclass(frozen=True, slots=True)
class BeforeTurnPhase:
    """准备 session 和基础 turn 状态。"""

    session_manager: SessionManager
    hook_registry: HookRegistry | None = None

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
            await self.hook_registry.run(BEFORE_TURN, ctx)


@dataclass(frozen=True, slots=True)
class BeforeReasoningPhase:
    """推理前扩展点。

    第七阶段在这里查询长期记忆，并生成可注入 prompt 的记忆块。
    """

    memory_runtime: MemoryRuntime | None = None
    hook_registry: HookRegistry | None = None

    async def run(self, ctx: PassiveTurnContext) -> None:
        """查询与当前用户输入相关的长期记忆。"""

        if self.memory_runtime is None:
            return

        result = await self.memory_runtime.query(
            MemoryQuery(query=ctx.inbound.content, limit=5)
        )
        ctx.memory_query_result = result
        ctx.memory_prompt_block = self.memory_runtime.render_prompt_block(result)
        if result.items:
            ctx.metadata["memory_match_count"] = len(result.items)
        if self.hook_registry is not None:
            await self.hook_registry.run(BEFORE_REASONING, ctx)


@dataclass(frozen=True, slots=True)
class PromptRenderPhase:
    """渲染模型上下文。"""

    context_builder: ContextBuilder
    hook_registry: HookRegistry | None = None

    async def run(self, ctx: PassiveTurnContext) -> None:
        """调用 ContextBuilder 生成 messages。"""

        if ctx.turn_state is None:
            raise RuntimeError("PromptRenderPhase 需要先完成 BeforeTurnPhase。")

        ctx.context_result = self.context_builder.render(
            ContextRequest(
                turn_state=ctx.turn_state,
                agent_name=self.context_builder.agent_name,
                system_prompt=self.context_builder.system_prompt,
                memory_prompt_block=ctx.memory_prompt_block,
            )
        )
        ctx.metadata["context_message_count"] = len(ctx.context_result.messages)
        if self.hook_registry is not None:
            await self.hook_registry.run(PROMPT_RENDER, ctx)


@dataclass(frozen=True, slots=True)
class ReasonerPhase:
    """调用 Reasoner 生成回复。"""

    reasoner: Reasoner

    async def run(self, ctx: PassiveTurnContext) -> None:
        """根据渲染后的 messages 调用模型。"""

        if ctx.context_result is None:
            raise RuntimeError("ReasonerPhase 需要先完成 PromptRenderPhase。")

        ctx.llm_response = await self.reasoner.generate(ctx.context_result.messages)
        ctx.metadata["provider"] = ctx.llm_response.provider
        ctx.metadata["fallback_used"] = ctx.llm_response.fallback_used


@dataclass(frozen=True, slots=True)
class AfterReasoningPhase:
    """保存当前轮用户消息和助手回复。"""

    memory_consolidator: MemoryConsolidator | None = None
    hook_registry: HookRegistry | None = None

    async def run(self, ctx: PassiveTurnContext) -> None:
        """将本轮对话写入 session 历史。"""

        if ctx.session is None:
            raise RuntimeError("AfterReasoningPhase 需要先完成 BeforeTurnPhase。")
        if ctx.llm_response is None:
            raise RuntimeError("AfterReasoningPhase 需要先完成 ReasonerPhase。")

        ctx.session.add_user_message(ctx.inbound.content)
        ctx.session.add_assistant_message(ctx.llm_response.content)

        if self.memory_consolidator is not None:
            await self.memory_consolidator.record_turn(
                user_content=ctx.inbound.content,
                assistant_content=ctx.llm_response.content,
                metadata={"session_key": ctx.inbound.session_key},
            )
        if self.hook_registry is not None:
            await self.hook_registry.run(AFTER_REASONING, ctx)


@dataclass(frozen=True, slots=True)
class AfterTurnPhase:
    """创建出站消息。"""

    hook_registry: HookRegistry | None = None

    async def run(self, ctx: PassiveTurnContext) -> None:
        """根据 LLMResponse 构造 OutboundMessage。"""

        if ctx.llm_response is None:
            raise RuntimeError("AfterTurnPhase 需要先完成 ReasonerPhase。")

        ctx.outbound = OutboundMessage(
            channel=ctx.inbound.channel,
            chat_id=ctx.inbound.chat_id,
            content=ctx.llm_response.content,
            metadata=dict(ctx.metadata),
        )
        if self.hook_registry is not None:
            await self.hook_registry.run(AFTER_TURN, ctx)
