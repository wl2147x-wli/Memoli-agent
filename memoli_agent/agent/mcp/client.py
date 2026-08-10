"""MCP client 封装。

本模块只在真正连接 MCP server 时导入官方 SDK，避免默认关闭 MCP 时影响项目启动。
"""

from __future__ import annotations

from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass
from typing import Any

from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.bootstrap.config import MCPServerConfig


@dataclass(frozen=True, slots=True)
class MCPToolSpec:
    """MCP 工具描述。"""

    server_name: str
    name: str
    registered_name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(slots=True)
class MCPClient:
    """单个 stdio MCP server client。"""

    config: MCPServerConfig
    _session: Any | None = None
    _exit_stack: AsyncExitStack | None = None
    _connected: bool = False

    async def connect(self) -> None:
        """连接并初始化 MCP server。"""

        if self._connected:
            return

        if self.config.transport != "stdio":
            raise ValueError(f"暂不支持 MCP transport：{self.config.transport}")

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise RuntimeError(
                "未安装 MCP Python SDK，请使用 pyproject.toml 安装项目依赖。"
            ) from exc

        exit_stack = AsyncExitStack()
        try:
            server_params = StdioServerParameters(
                command=self.config.command,
                args=list(self.config.args),
                env=dict(self.config.env) or None,
            )
            read_stream, write_stream = await exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            session = await exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
        except BaseException:
            # 初始化完成前资源只属于局部 stack，任何失败都必须立即释放。
            with suppress(Exception):
                await exit_stack.aclose()
            raise

        self._session = session
        self._exit_stack = exit_stack
        self._connected = True

    async def list_tools(self) -> list[MCPToolSpec]:
        """列出 server 暴露的工具。"""

        session = self._require_session()
        result = await session.list_tools()
        tools = getattr(result, "tools", [])
        specs: list[MCPToolSpec] = []
        for tool in tools:
            name = str(getattr(tool, "name", ""))
            if not name:
                continue
            specs.append(
                MCPToolSpec(
                    server_name=self.config.name,
                    name=name,
                    registered_name=build_registered_tool_name(self.config.name, name),
                    description=str(getattr(tool, "description", "") or ""),
                    input_schema=_read_input_schema(tool),
                )
            )
        return specs

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """调用 MCP 工具并转换为 ToolResult。"""

        try:
            session = self._require_session()
            result = await session.call_tool(name, arguments)
            content = _format_call_result(result)
            is_error = bool(getattr(result, "isError", False))
            return ToolResult(
                content=content,
                success=not is_error,
                metadata={"server": self.config.name, "mcp_tool": name},
            )
        except Exception as exc:
            return ToolResult(
                content="MCP 工具调用失败。",
                success=False,
                metadata={
                    "server": self.config.name,
                    "mcp_tool": name,
                    "error": type(exc).__name__,
                },
            )

    async def close(self) -> None:
        """关闭 MCP 连接。"""

        self._connected = False
        self._session = None
        if self._exit_stack is not None:
            with suppress(Exception):
                await self._exit_stack.aclose()
        self._exit_stack = None

    def _require_session(self) -> Any:
        """返回已连接的 session。"""

        if self._session is None:
            raise RuntimeError(f"MCP server 尚未连接：{self.config.name}")
        return self._session


def build_registered_tool_name(server_name: str, tool_name: str) -> str:
    """构建 ToolRegistry 中的 MCP 工具名。"""

    return f"mcp__{_safe_name(server_name)}__{_safe_name(tool_name)}"


def _safe_name(value: str) -> str:
    """把 MCP 名称转换成 OpenAI-compatible 工具名片段。"""

    safe_chars = []
    for char in value:
        if char.isascii() and (char.isalnum() or char in {"_", "-"}):
            safe_chars.append(char)
        else:
            safe_chars.append("_")
    return "".join(safe_chars).strip("_") or "unnamed"


def _read_input_schema(tool: Any) -> dict[str, Any]:
    """读取 MCP 工具输入 schema。"""

    schema = getattr(tool, "inputSchema", None)
    if schema is None:
        schema = getattr(tool, "input_schema", None)
    if isinstance(schema, dict):
        return schema
    if schema is not None and hasattr(schema, "model_dump"):
        dumped = schema.model_dump()
        if isinstance(dumped, dict):
            return dumped
    return {"type": "object", "properties": {}, "additionalProperties": True}


def _format_call_result(result: Any) -> str:
    """把 MCP call_tool 结果格式化为文本。"""

    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return str(structured)

    content_items = getattr(result, "content", [])
    parts: list[str] = []
    for item in content_items:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(str(text))
            continue
        parts.append(str(item))
    return "\n".join(parts) if parts else str(result)
