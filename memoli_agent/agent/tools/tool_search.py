"""工具搜索和按需解锁模块。

第六阶段只做最小关键词搜索，不做 deferred tool 解锁。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from memoli_agent.agent.tools.base import Tool, ToolResult
from memoli_agent.agent.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class ToolSearch:
    """按关键词搜索已注册工具。"""

    registry: ToolRegistry

    def search(self, query: str) -> list[Tool]:
        """根据工具名和描述进行简单匹配。"""

        keyword = query.strip().lower()
        if not keyword:
            return self.registry.list_tools()

        return [
            tool
            for tool in self.registry.list_tools()
            if keyword in tool.name.lower() or keyword in tool.description.lower()
        ]


@dataclass(frozen=True, slots=True)
class ToolSearchTool:
    """Model-facing deterministic entry point for deferred tool schemas."""

    registry: ToolRegistry
    limit: int = 8
    name: str = "tool_search"
    description: str = "Search and disclose deferred plugin or MCP tools by keyword."
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "").strip()
        selected = self.registry.disclose(query, limit=self.limit)
        return ToolResult(
            content=(
                "disclosed tools: " + ", ".join(tool.name for tool in selected)
                if selected
                else "no deferred tools matched"
            ),
            metadata={
                "query": query,
                "disclosed": [tool.name for tool in selected],
            },
        )
