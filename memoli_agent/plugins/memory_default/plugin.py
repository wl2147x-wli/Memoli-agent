"""默认记忆插件。

第八阶段只用于验证 lifecycle hook 能正常被插件注册和调用。
实际记忆读写仍由 MemoryRuntime 负责。
"""

from __future__ import annotations

from dataclasses import dataclass

from memoli_agent.agent.lifecycle.types import PassiveTurnContext
from memoli_agent.agent.plugins.context import PluginContext
from memoli_agent.agent.plugins.decorators import (
    AFTER_TURN,
    BEFORE_REASONING,
)


@dataclass(frozen=True, slots=True)
class MemoryDefaultPlugin:
    """默认记忆插件。"""

    name: str = "memory_default"

    async def initialize(self, context: PluginContext) -> None:
        """初始化插件。"""

    async def terminate(self, context: PluginContext) -> None:
        """关闭插件。"""

    def register(self, context: PluginContext) -> None:
        """注册 lifecycle hooks。"""

        context.hook_registry.register(BEFORE_REASONING, self._before_reasoning)
        context.hook_registry.register(AFTER_TURN, self._after_turn)

    def _before_reasoning(self, ctx: PassiveTurnContext) -> None:
        """标记记忆插件已参与推理前阶段。"""

        ctx.metadata["memory_plugin_active"] = True

    def _after_turn(self, ctx: PassiveTurnContext) -> None:
        """标记记忆插件已参与回合结束阶段。"""

        ctx.metadata["memory_plugin_after_turn"] = True


def create_plugin() -> MemoryDefaultPlugin:
    """创建插件实例。"""

    return MemoryDefaultPlugin()
