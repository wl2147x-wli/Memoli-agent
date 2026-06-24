"""工具搜索和按需解锁模块。

第六阶段只做最小关键词搜索，不做 deferred tool 解锁。
"""

from __future__ import annotations

from dataclasses import dataclass

from memoli_agent.agent.tools.base import Tool
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
