"""主 agent 路由器。

AgentRunner 是 AgentLoop 和具体业务 pipeline 之间的分发层。
第五阶段暂时把所有入站用户消息都交给 PassiveTurnPipeline。
后续 subagent completion、proactive event、内部事件会在这里分流。
"""

from __future__ import annotations

from dataclasses import dataclass

from memoli_agent.agent.core.passive_turn import PassiveTurnPipeline
from memoli_agent.bus.events import InboundMessage, OutboundMessage


@dataclass(frozen=True, slots=True)
class AgentRunner:
    """主 agent 路由器。"""

    passive_turn_pipeline: PassiveTurnPipeline

    async def handle_inbound(self, message: InboundMessage) -> OutboundMessage:
        """处理一条入站消息。"""

        return await self.passive_turn_pipeline.run(message)
