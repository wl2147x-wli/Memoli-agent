"""MCP client 管理器。"""

from __future__ import annotations

from dataclasses import dataclass, field

from memoli_agent.agent.mcp.client import MCPClient, MCPToolSpec
from memoli_agent.agent.mcp.tool import MCPToolAdapter
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.bootstrap.config import MCPServerConfig


@dataclass(frozen=True, slots=True)
class MCPConnectResult:
    """单个 MCP server 连接结果。"""

    server_name: str
    success: bool
    message: str
    tool_count: int = 0


@dataclass(slots=True)
class MCPClientManager:
    """管理多个 MCP server client。"""

    server_configs: list[MCPServerConfig]
    clients: dict[str, MCPClient] = field(default_factory=dict)
    tool_specs: list[MCPToolSpec] = field(default_factory=list)
    connect_results: list[MCPConnectResult] = field(default_factory=list)

    async def connect_all(self) -> list[MCPConnectResult]:
        """连接所有已启用 MCP server 并发现工具。"""

        self.connect_results.clear()
        self.tool_specs.clear()
        for config in self.server_configs:
            if not config.enabled:
                continue

            client = MCPClient(config)
            try:
                await client.connect()
                specs = await client.list_tools()
            except Exception as exc:
                await client.close()
                self.connect_results.append(
                    MCPConnectResult(
                        server_name=config.name,
                        success=False,
                        message=str(exc),
                    )
                )
                continue

            self.clients[config.name] = client
            self.tool_specs.extend(specs)
            self.connect_results.append(
                MCPConnectResult(
                    server_name=config.name,
                    success=True,
                    message="已连接。",
                    tool_count=len(specs),
                )
            )

        return list(self.connect_results)

    def register_tools(self, tool_registry: ToolRegistry) -> None:
        """把已发现 MCP 工具注册到 ToolRegistry。"""

        for spec in self.tool_specs:
            client = self.clients.get(spec.server_name)
            if client is None:
                continue
            tool_registry.register(MCPToolAdapter(client=client, spec=spec))

    async def close_all(self) -> None:
        """关闭所有 MCP client。"""

        for client in list(self.clients.values()):
            await client.close()
        self.clients.clear()
        self.tool_specs.clear()
