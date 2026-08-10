from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from memoli_agent.agent.proactive.decision import ProactiveDecision
from memoli_agent.agent.proactive.loop import ProactiveLoop
from memoli_agent.agent.proactive.sensor import ProactiveSensor
from memoli_agent.agent.proactive.state import ProactiveSignal, ProactiveState
from memoli_agent.bus.queue import MessageBus


def test_default_start_waits_for_initial_delay() -> None:
    async def scenario() -> tuple[bool, str]:
        bus = MessageBus()
        loop = ProactiveLoop(
            bus,
            ProactiveSensor(),
            ProactiveDecision(0, "ready"),
            interval_seconds=1,
            initial_delay_seconds=0.05,
        )
        await loop.start()
        await asyncio.sleep(0.01)
        published_early = not bus._inbound.empty()
        message = await asyncio.wait_for(bus.consume_inbound(), 0.2)
        await loop.stop()
        return published_early, message.content

    published_early, content = asyncio.run(scenario())
    assert published_early is False
    assert content == "ready"


def test_run_on_start_evaluates_immediately() -> None:
    async def scenario() -> str:
        bus = MessageBus()
        loop = ProactiveLoop(
            bus,
            ProactiveSensor(),
            ProactiveDecision(0, "now"),
            interval_seconds=60,
            run_on_start=True,
        )
        await loop.start()
        message = await asyncio.wait_for(bus.consume_inbound(), 0.2)
        await loop.stop()
        return message.content

    assert asyncio.run(scenario()) == "now"


def test_quiet_hours_support_cross_midnight() -> None:
    decision = ProactiveDecision(
        0,
        "should stay silent",
        quiet_hours_start=22,
        quiet_hours_end=7,
        quiet_hours_timezone="UTC",
    )
    signal = ProactiveSignal(datetime(2026, 8, 9, 23, tzinfo=UTC), 1)
    result = asyncio.run(decision.decide(signal, ProactiveState()))
    assert result.should_send is False
    assert result.metadata == {"reason": "quiet-hours"}

