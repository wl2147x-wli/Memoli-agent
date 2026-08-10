"""主动循环。

ProactiveLoop 定时执行感知和决策。如果决策需要主动发送消息，则把消息
作为 InboundMessage 投递给主 MessageBus，由现有 AgentLoop 继续处理。
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field

from memoli_agent.agent.proactive.decision import ProactiveDecision
from memoli_agent.agent.proactive.sensor import ProactiveSensor
from memoli_agent.agent.proactive.state import ProactiveState
from memoli_agent.bus.events import InboundMessage
from memoli_agent.bus.queue import MessageBus


@dataclass(slots=True)
class ProactiveLoop:
    """本地主动循环。"""

    bus: MessageBus
    sensor: ProactiveSensor
    decision: ProactiveDecision
    interval_seconds: int = 60
    run_on_start: bool = False
    initial_delay_seconds: float | None = None
    chat_id: str = "local"
    state: ProactiveState = field(default_factory=ProactiveState)
    _running: bool = False
    _task: asyncio.Task[None] | None = field(default=None, init=False)

    async def start(self) -> None:
        """启动主动循环后台任务。"""

        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self.run(), name="proactive_loop")

    async def stop(self) -> None:
        """停止主动循环。"""

        self._running = False
        if self._task is None:
            return

        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run(self) -> None:
        """定时执行主动检查。"""

        if self.run_on_start:
            await self._tick()
        else:
            delay = (
                self.interval_seconds
                if self.initial_delay_seconds is None
                else self.initial_delay_seconds
            )
            await asyncio.sleep(max(0, delay))
            if self._running:
                await self._tick()

        while self._running:
            await asyncio.sleep(max(1, self.interval_seconds))
            if self._running:
                await self._tick()

    async def _tick(self) -> None:
        """执行一次主动检查。"""

        self.state.tick_count += 1
        signal = await self.sensor.sense(self.state)
        result = await self.decision.decide(signal, self.state)
        if not result.should_send:
            self.state.metadata["last_skip_reason"] = result.metadata
            return

        self.state.last_triggered_at = signal.now
        await self.bus.publish_inbound(
            InboundMessage(
                channel="proactive",
                chat_id=self.chat_id,
                sender="proactive",
                content=result.content,
                metadata={
                    "event": "proactive_tick",
                    "tick_count": self.state.tick_count,
                    **result.metadata,
                },
            )
        )
