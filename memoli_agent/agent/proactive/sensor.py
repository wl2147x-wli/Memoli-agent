"""主动循环感知器。

第十阶段只读取轻量运行状态：当前时间、tick 次数和记忆系统是否启用。
后续可以在这里接入信息源、任务列表、文件变更或外部事件。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from memoli_agent.agent.proactive.state import ProactiveSignal, ProactiveState


@dataclass(frozen=True, slots=True)
class ProactiveSensor:
    """最小主动感知器。"""

    memory_runtime: Any | None = None

    async def sense(self, state: ProactiveState) -> ProactiveSignal:
        """读取当前最小状态并生成主动信号。"""

        return ProactiveSignal(
            now=datetime.now(UTC),
            tick_count=state.tick_count,
            metadata={
                "memory_enabled": self.memory_runtime is not None,
            },
        )
