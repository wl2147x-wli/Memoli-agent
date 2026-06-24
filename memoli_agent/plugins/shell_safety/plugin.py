"""Shell 安全插件。

当前项目还没有 shell 工具，因此本插件先保护 filesystem_read。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from memoli_agent.agent.plugins.context import PluginContext


@dataclass(frozen=True, slots=True)
class ShellSafetyPlugin:
    """基础安全插件。"""

    name: str = "shell_safety"

    async def initialize(self, context: PluginContext) -> None:
        """初始化插件。"""

    async def terminate(self, context: PluginContext) -> None:
        """关闭插件。"""

    def register(self, context: PluginContext) -> None:
        """注册工具执行前检查。"""

        context.hook_registry.register_tool_pre(self._tool_pre)

    def _tool_pre(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """检查危险工具参数。"""

        if tool_name != "filesystem_read":
            return arguments

        raw_path = str(arguments.get("path", ""))
        path = PurePath(raw_path)
        dangerous_parts = {"..", "~"}
        if path.is_absolute() or any(part in dangerous_parts for part in path.parts):
            raise PermissionError("filesystem_read 只允许读取 workspace 内相对路径。")

        if any(part.startswith(".") for part in path.parts):
            raise PermissionError("filesystem_read 不允许读取隐藏路径。")

        return arguments


def create_plugin() -> ShellSafetyPlugin:
    """创建插件实例。"""

    return ShellSafetyPlugin()
