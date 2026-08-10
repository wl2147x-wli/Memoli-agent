"""MCP client 管理器。"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from memoli_agent.agent.mcp.client import MCPClient, MCPToolSpec
from memoli_agent.agent.mcp.tool import MCPToolAdapter
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.bootstrap.config import MCPServerConfig

logger = logging.getLogger(__name__)


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
        if self.clients:
            await self.close_all()
        registered_names: dict[str, tuple[str, str]] = {}
        for config in self.server_configs:
            if not config.enabled:
                continue

            client = MCPClient(config)
            try:
                await client.connect()
                specs = await client.list_tools()
                discovered_names = dict(registered_names)
                for spec in specs:
                    previous = discovered_names.get(spec.registered_name)
                    current = (spec.server_name, spec.name)
                    if previous is not None and previous != current:
                        raise ValueError(
                            "MCP 工具规范名冲突："
                            f"{previous[0]}.{previous[1]} 与 "
                            f"{current[0]}.{current[1]} -> {spec.registered_name}"
                        )
                    discovered_names[spec.registered_name] = current
            except Exception as exc:
                await self._close_client(client)
                await self.close_all()
                self.connect_results = [
                    MCPConnectResult(
                        result.server_name,
                        False,
                        "MCP 初始化因后续 server 失败已回滚。",
                    )
                    for result in self.connect_results
                ]
                self.connect_results.append(
                    MCPConnectResult(
                        server_name=config.name,
                        success=False,
                        message=(
                            str(exc)
                            if isinstance(exc, ValueError)
                            else f"连接失败：{type(exc).__name__}"
                        ),
                    )
                )
                break

            self.clients[config.name] = client
            self.tool_specs.extend(specs)
            registered_names = discovered_names
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

        clients = list(self.clients.values())
        self.clients.clear()
        self.tool_specs.clear()
        for client in clients:
            await self._close_client(client)

    @staticmethod
    async def _close_client(client: MCPClient) -> None:
        """关闭单个 client；一个关闭错误不能跳过其他资源清理。"""

        try:
            await client.close()
        except Exception as exc:
            logger.warning("MCP client 关闭失败：error_type=%s", type(exc).__name__)
