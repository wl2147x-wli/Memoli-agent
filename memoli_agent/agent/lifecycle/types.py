"""生命周期上下文类型。

PassiveTurnPipeline 会把一轮对话拆成多个阶段。每个阶段共享同一个
PassiveTurnContext，并把自己的产物写回 context，后续阶段继续使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from memoli_agent.agent.memory.runtime import MemoryQueryResult
from memoli_agent.agent.provider import LLMResponse
from memoli_agent.agent.session import Session
from memoli_agent.agent.types import ContextRenderResult, TurnState
from memoli_agent.bus.events import InboundMessage, OutboundMessage


@dataclass(slots=True)
class PassiveTurnContext:
    """被动对话一轮处理的共享上下文。"""

    inbound: InboundMessage
    session: Session | None = None
    turn_state: TurnState | None = None
    context_result: ContextRenderResult | None = None
    memory_query_result: MemoryQueryResult | None = None
    memory_prompt_block: str = ""
    llm_response: LLMResponse | None = None
    outbound: OutboundMessage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


BeforeTurnContext = PassiveTurnContext
BeforeReasoningContext = PassiveTurnContext
PromptRenderContext = PassiveTurnContext
AfterReasoningContext = PassiveTurnContext
AfterTurnContext = PassiveTurnContext
