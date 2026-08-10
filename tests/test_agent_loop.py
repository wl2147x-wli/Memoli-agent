from __future__ import annotations

import asyncio
from dataclasses import dataclass

from memoli_agent.agent.loop import AgentLoop
from memoli_agent.bus.events import InboundMessage, OutboundMessage
from memoli_agent.bus.queue import MessageBus


@dataclass
class ScriptedRunner:
    calls: int = 0

    async def handle_inbound(self, message: InboundMessage) -> OutboundMessage:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("secret exception detail")
        return OutboundMessage(message.channel, message.chat_id, "ok")


def test_message_failure_does_not_stop_following_message() -> None:
    async def scenario() -> tuple[OutboundMessage, OutboundMessage]:
        bus = MessageBus()
        loop = AgentLoop(bus, ScriptedRunner())  # type: ignore[arg-type]
        await loop.start()
        for content in ("first", "second"):
            await bus.publish_inbound(InboundMessage("cli", "c", "u", content))
        first = await asyncio.wait_for(bus.consume_outbound(), 1)
        second = await asyncio.wait_for(bus.consume_outbound(), 1)
        await loop.stop()
        return first, second

    first, second = asyncio.run(scenario())
    assert first.metadata == {
        "status": "error",
        "error_type": "turn-processing-failed",
        "retryable": True,
    }
    assert "secret exception detail" not in first.content
    assert second.content == "ok"


class FailingPublishBus(MessageBus):
    def __init__(self) -> None:
        super().__init__()
        self.publish_calls = 0
        self.delivered: list[OutboundMessage] = []

    async def publish_outbound(self, message: OutboundMessage) -> None:
        self.publish_calls += 1
        if self.publish_calls == 1:
            raise RuntimeError("publish failed")
        self.delivered.append(message)


def test_publish_and_maintenance_failures_do_not_stop_loop() -> None:
    async def scenario() -> FailingPublishBus:
        bus = FailingPublishBus()
        runner = ScriptedRunner(calls=1)

        async def maintenance() -> None:
            raise RuntimeError("maintenance failed")

        loop = AgentLoop(bus, runner, maintenance=maintenance)  # type: ignore[arg-type]
        await loop.start()
        for content in ("first", "second"):
            await bus.publish_inbound(InboundMessage("cli", "c", "u", content))
        for _ in range(100):
            if bus.publish_calls == 2:
                break
            await asyncio.sleep(0.001)
        await loop.stop()
        return bus

    bus = asyncio.run(scenario())
    assert bus.publish_calls == 2
    assert [message.content for message in bus.delivered] == ["ok"]


def test_cancelled_turn_propagates_from_message_loop() -> None:
    class CancelledRunner:
        async def handle_inbound(self, message: InboundMessage) -> OutboundMessage:
            raise asyncio.CancelledError

    async def scenario() -> bool:
        bus = MessageBus()
        loop = AgentLoop(bus, CancelledRunner())  # type: ignore[arg-type]
        loop._running = True
        task = asyncio.create_task(loop.run())
        await bus.publish_inbound(InboundMessage("cli", "c", "u", "cancel"))
        try:
            await task
        except asyncio.CancelledError:
            return task.cancelled()
        return False

    assert asyncio.run(scenario()) is True
