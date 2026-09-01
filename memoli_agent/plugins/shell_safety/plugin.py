"""工具策略插件示例；核心工具自身仍是不可绕过的安全边界。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from memoli_agent.agent.plugins.context import PluginRuntimeContext
from memoli_agent.agent.plugins.events import HookName, ToolBeforeEvent, ToolDecision
from memoli_agent.agent.plugins.registrar import PluginRegistrar


@dataclass(frozen=True, slots=True)
class ShellSafetyPlugin:
    """额外拒绝文件工具访问隐藏路径；不替代核心 WorkspacePathResolver。"""

    def register(self, registrar: PluginRegistrar) -> None:
        registrar.add_policy(HookName.TOOL_BEFORE, self._tool_before)

    async def initialize(self, context: PluginRuntimeContext) -> None:
        del context

    async def terminate(self) -> None:
        return None

    def _tool_before(self, event: ToolBeforeEvent) -> ToolDecision:
        protected_tools = {
            "file_read",
            "file_write",
            "file_patch",
        }
        if event.tool_name not in protected_tools:
            return ToolDecision.allow()
        raw_path = str(event.arguments.get("path", ""))
        path = PurePath(raw_path)
        if path.is_absolute() or ".." in path.parts or "~" in path.parts:
            return ToolDecision.deny("文件工具只允许 workspace 内相对路径。")
        if any(part.startswith(".") for part in path.parts):
            return ToolDecision.deny("文件工具不允许访问隐藏路径。")
        return ToolDecision.allow()


def create_plugin() -> ShellSafetyPlugin:
    return ShellSafetyPlugin()
