"""MCP 工具适配器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memoli_agent.agent.mcp.client import MCPClient, MCPToolSpec
from memoli_agent.agent.tools.base import ToolResult


@dataclass(frozen=True, slots=True)
class MCPToolAdapter:
    """把 MCP 工具适配成 Memoli 的 Tool 协议。"""

    client: MCPClient
    spec: MCPToolSpec

    @property
    def name(self) -> str:
        """ToolRegistry 中使用的工具名。"""

        return self.spec.registered_name

    @property
    def description(self) -> str:
        """工具描述。"""

        return self.spec.description or f"MCP 工具：{self.spec.server_name}.{self.spec.name}"

    @property
    def parameters(self) -> dict[str, Any]:
        """OpenAI-compatible 参数 schema。"""

        return self.spec.input_schema

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """调用原始 MCP 工具。"""

        return await self.client.call_tool(self.spec.name, arguments)
