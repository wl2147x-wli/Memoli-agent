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
        ),
        interval_seconds=config.proactive.interval_seconds,
        chat_id=config.proactive.chat_id,
    )
