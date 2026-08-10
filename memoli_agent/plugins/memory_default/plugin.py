"""最小示例插件；真实记忆系统仍由核心 Runtime 负责。"""

from __future__ import annotations

from dataclasses import dataclass

from memoli_agent.agent.plugins.context import PluginRuntimeContext
from memoli_agent.agent.plugins.events import HookName, TurnAfterEvent
from memoli_agent.agent.plugins.registrar import PluginRegistrar


@dataclass(slots=True)
class MemoryDefaultPlugin:
    """演示只读 Observer，不改变记忆或 Agent 行为。"""

    initialized: bool = False

    def register(self, registrar: PluginRegistrar) -> None:
        registrar.add_observer(HookName.TURN_AFTER, self._after_turn)

    async def initialize(self, context: PluginRuntimeContext) -> None:
        self.initialized = context.plugin_id == "memory_default"

    async def terminate(self) -> None:
        self.initialized = False

    def _after_turn(self, event: TurnAfterEvent) -> None:
        del event


def create_plugin() -> MemoryDefaultPlugin:
    return MemoryDefaultPlugin()
