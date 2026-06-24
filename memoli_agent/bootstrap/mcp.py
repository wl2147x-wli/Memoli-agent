"""MCP 装配模块。"""

from __future__ import annotations

from memoli_agent.agent.mcp.registry import MCPClientManager
from memoli_agent.bootstrap.config import AppConfig


def build_mcp_manager(config: AppConfig) -> MCPClientManager | None:
    """根据配置创建 MCP client 管理器。"""

    if not config.mcp.enabled:
        return None
    return MCPClientManager(server_configs=config.mcp.servers)
