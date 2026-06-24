"""工具注册表。

ToolRegistry 负责统一注册工具、暴露 schema，并执行模型请求的工具调用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from memoli_agent.agent.plugins.decorators import HookRegistry
from memoli_agent.agent.tools.base import Tool, ToolResult


@dataclass(slots=True)
class ToolRegistry:
    """工具注册表。"""

    hook_registry: HookRegistry | None = None
    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        """注册一个工具。"""

        if not tool.name:
            raise ValueError("工具名称不能为空。")
        self._tools[tool.name] = tool

    def get_schemas(self) -> list[dict[str, Any]]:
        """返回 OpenAI-compatible tools schema。"""

        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """执行指定工具。"""

        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                content=f"工具不存在：{name}",
                success=False,
                metadata={"tool": name},
            )

        try:
            final_arguments = arguments
            if self.hook_registry is not None:
                final_arguments = await self.hook_registry.run_tool_pre(
                    name,
                    arguments,
                )
            return await tool.run(final_arguments)
        except PermissionError as exc:
            return ToolResult(
                content=f"工具调用被插件拦截：{exc}",
                success=False,
                metadata={"tool": name, "error": "PermissionError"},
            )
        except Exception as exc:
            return ToolResult(
                content=f"工具执行失败：{exc}",
                success=False,
                metadata={"tool": name, "error": type(exc).__name__},
            )

    def list_tools(self) -> list[Tool]:
        """返回已注册工具列表。"""

        return list(self._tools.values())
