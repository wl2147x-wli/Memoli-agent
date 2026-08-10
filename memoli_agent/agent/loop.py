"""主 AgentLoop。

第五阶段开始，AgentLoop 只负责消息泵职责：

1. 从 MessageBus 的 inbound 队列读取 InboundMessage。
2. 调用 AgentRunner 处理消息。
3. 将 OutboundMessage 发布到 outbound 队列。

一轮对话的具体业务编排已经移动到 PassiveTurnPipeline。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field

from memoli_agent.agent.runner import AgentRunner
from memoli_agent.bus.events import InboundMessage, OutboundMessage
from memoli_agent.bus.queue import MessageBus

logger = logging.getLogger(__name__)


@dataclass
class AgentLoop:
    """主 agent 消息循环。"""

    bus: MessageBus
    runner: AgentRunner
    maintenance: Callable[[], Awaitable[object]] | None = None
    _running: bool = False
    _task: asyncio.Task[None] | None = field(default=None, init=False)

    async def start(self) -> None:
        """启动后台 agent loop。

        start() 只负责创建后台任务，不阻塞当前调用方。
        """

        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self.run(), name="agent_loop")

    async def stop(self) -> None:
        """停止后台 agent loop。

        通过取消后台 task 的方式退出等待中的 consume_inbound()。
        """

        self._running = False
        if self._task is None:
            return

        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run(self) -> None:
        """持续消费入站消息并发布出站回复。"""

        while self._running:
            message = await self.bus.consume_inbound()
            try:
                outbound = await self.process(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # 不把原始异常文本回传给用户，避免凭证或路径泄漏。
                logger.error("单轮处理失败：error_type=%s", type(exc).__name__)
                outbound = OutboundMessage(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content="本轮处理失败，请稍后重试。",
                    metadata={
                        "status": "error",
                        "error_type": "turn-processing-failed",
                        "retryable": True,
                    },
                )
            try:
                await self.bus.publish_outbound(outbound)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("出站发布失败：error_type=%s", type(exc).__name__)
            if self.maintenance is not None:
                try:
                    await self.maintenance()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    # 派生索引维护失败不能终止消息泵；状态保留在 memory job 中。
                    logger.error("后台维护失败：error_type=%s", type(exc).__name__)

    async def process(self, message: InboundMessage) -> OutboundMessage:
        """处理一条入站消息。"""

        return await self.runner.handle_inbound(message)
