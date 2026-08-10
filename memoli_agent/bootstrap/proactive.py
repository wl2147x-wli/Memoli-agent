"""主动循环装配模块。"""

from __future__ import annotations

from typing import Any

from memoli_agent.agent.proactive.decision import ProactiveDecision
from memoli_agent.agent.proactive.loop import ProactiveLoop
from memoli_agent.agent.proactive.sensor import ProactiveSensor
from memoli_agent.bootstrap.config import AppConfig
from memoli_agent.bus.queue import MessageBus


def build_proactive_loop(
    config: AppConfig,
    bus: MessageBus,
    memory_runtime: Any | None = None,
) -> ProactiveLoop | None:
    """根据配置创建主动循环。"""

    if not config.proactive.enabled:
        return None

    return ProactiveLoop(
        bus=bus,
        sensor=ProactiveSensor(memory_runtime=memory_runtime),
        decision=ProactiveDecision(
            cooldown_seconds=config.proactive.cooldown_seconds,
            message=config.proactive.message,
            quiet_hours_start=config.proactive.quiet_hours_start,
            quiet_hours_end=config.proactive.quiet_hours_end,
            quiet_hours_timezone=config.proactive.quiet_hours_timezone,
        ),
        interval_seconds=config.proactive.interval_seconds,
        run_on_start=config.proactive.run_on_start,
        initial_delay_seconds=config.proactive.initial_delay_seconds,
        chat_id=config.proactive.chat_id,
    )
