"""异步消息总线。

MessageBus 是 channel 和 AgentLoop 之间的边界：

- channel 把用户消息放入 inbound 队列。
- AgentLoop 从 inbound 队列消费消息。
- AgentLoop 把回复放入 outbound 队列。
- channel 从 outbound 队列取出回复并展示/发送。

第一阶段只实现最小队列能力，不做订阅分发、不做重试、不做持久化。
"""

from __future__ import annotations

import asyncio

from memoli_agent.bus.events import InboundMessage, OutboundMessage


class MessageBus:
    """主 agent 的最小异步消息总线。"""

    def __init__(self) -> None:
        """创建入站和出站两个队列。"""

        self._inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def publish_inbound(self, message: InboundMessage) -> None:
        """发布入站消息。

        调用方通常是 CLI、IPC、Telegram 等 channel。
        """

        await self._inbound.put(message)

    async def consume_inbound(self) -> InboundMessage:
        """消费一条入站消息。

        调用方通常是 AgentLoop。没有消息时会异步等待。
        """

        return await self._inbound.get()

    async def publish_outbound(self, message: OutboundMessage) -> None:
        """发布出站消息。

        调用方通常是 AgentLoop。
        """

        await self._outbound.put(message)

    async def consume_outbound(self) -> OutboundMessage:
        """消费一条出站消息。

        调用方通常是 channel。没有消息时会异步等待。
        """

        return await self._outbound.get()
