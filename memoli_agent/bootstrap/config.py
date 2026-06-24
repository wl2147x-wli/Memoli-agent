"""配置加载模块。

第二阶段负责把运行配置从入口文件中抽出来：

- 使用 Python 3.11 标准库 tomllib 读取 config.toml。
- 用 dataclass 描述配置结构，避免在业务代码里到处传 dict。
- 当本地没有 config.toml 时使用默认配置，让项目保持开箱可运行。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RuntimeConfig:
    """应用运行目录配置。"""

    workspace: str = "workspace"


@dataclass(slots=True)
class LLMConfig:
    """LLM 供应商配置。

    第二阶段只保存配置，不真正连接模型；真实 provider 会在后续阶段接入。
    """

    provider: str = "openai-compatible"
    model: str = "gpt-4.1-mini"
    api_key: str = ""
    base_url: str = ""


@dataclass(slots=True)
class AgentConfig:
    """主 agent 的基础行为配置。"""

    name: str = "Memoli"
    max_iterations: int = 8
    history_window: int = 20


@dataclass(slots=True)
class MemoryConfig:
    """记忆系统配置。

    第二阶段只读取这些字段，真正的记忆引擎会在后续阶段实现。
    """

    enabled: bool = True
    engine: str = "markdown"
    path: str = "workspace/memory"


@dataclass(slots=True)
class ToolsConfig:
    """工具系统配置。"""

    tool_search_enabled: bool = True


@dataclass(slots=True)
class CLIChannelConfig:
    """CLI 通道配置。"""

    enabled: bool = True


@dataclass(slots=True)
class ChannelsConfig:
    """所有通道配置的集合。"""

    cli: CLIChannelConfig = field(default_factory=CLIChannelConfig)


@dataclass(slots=True)
class PluginsConfig:
    """插件配置。"""

    enabled: list[str] = field(
        default_factory=lambda: ["memory_default", "shell_safety"]
    )


@dataclass(slots=True)
class SubAgentConfig:
    """子 agent 配置。"""

    enabled: bool = True
    root: str = "workspace/subagents"
    default_profile: str = "general"
    max_concurrent: int = 2


@dataclass(slots=True)
class ProactiveConfig:
    """主动循环配置。"""

    enabled: bool = False
    interval_seconds: int = 60
    cooldown_seconds: int = 300
    chat_id: str = "local"
    message: str = "这是一次主动检查。"


@dataclass(slots=True)
class MCPServerConfig:
    """单个 MCP server 配置。"""

    name: str
    transport: str = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    enabled: bool = True
    env: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class MCPConfig:
    """MCP 配置。"""

    enabled: bool = False
    servers: list[MCPServerConfig] = field(default_factory=list)


@dataclass(slots=True)
class AppConfig:
    """应用总配置。

    AppRuntime 只依赖这个对象，不直接读取 TOML 文件。
    """

    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    channels: ChannelsConfig = field(default_factory=ChannelsConfig)
    plugins: PluginsConfig = field(default_factory=PluginsConfig)
    subagent: SubAgentConfig = field(default_factory=SubAgentConfig)
    proactive: ProactiveConfig = field(default_factory=ProactiveConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)


def load_config(path: str | Path = "config.toml") -> AppConfig:
    """加载应用配置。

    如果指定路径不存在，则返回默认配置。这样用户第一次运行项目时，
    不需要先复制 config.example.toml。
    """

    config_path = Path(path)
    if not config_path.exists():
        return AppConfig()

    with config_path.open("rb") as file:
        raw_config = tomllib.load(file)

    return _build_app_config(raw_config)


def _build_app_config(raw_config: dict[str, Any]) -> AppConfig:
    """把 TOML 解析出的 dict 转成强类型配置对象。"""

    channels_raw = _table(raw_config, "channels")

    return AppConfig(
        runtime=RuntimeConfig(**_table(raw_config, "runtime")),
        llm=LLMConfig(**_table(raw_config, "llm")),
        agent=AgentConfig(**_table(raw_config, "agent")),
        memory=MemoryConfig(**_table(raw_config, "memory")),
        tools=ToolsConfig(**_table(raw_config, "tools")),
        channels=ChannelsConfig(
            cli=CLIChannelConfig(**_table(channels_raw, "cli")),
        ),
        plugins=PluginsConfig(**_table(raw_config, "plugins")),
        subagent=SubAgentConfig(**_table(raw_config, "subagent")),
        proactive=ProactiveConfig(**_table(raw_config, "proactive")),
        mcp=_build_mcp_config(raw_config),
    )


def _build_mcp_config(raw_config: dict[str, Any]) -> MCPConfig:
    """构建 MCP 配置。"""

    mcp_raw = dict(_table(raw_config, "mcp"))
    servers_raw = mcp_raw.pop("servers", [])
    if not isinstance(servers_raw, list):
        raise TypeError("配置项 'mcp.servers' 必须是 TOML 数组。")

    servers = []
    for server_raw in servers_raw:
        if not isinstance(server_raw, dict):
            raise TypeError("每个 MCP server 配置必须是 TOML 表。")
        servers.append(MCPServerConfig(**server_raw))

    return MCPConfig(
        servers=servers,
        **mcp_raw,
    )


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    """安全读取 TOML 表。

    缺失的表会返回空 dict，由 dataclass 默认值补齐字段。
    """

    value = data.get(key, {})
    if not isinstance(value, dict):
        raise TypeError(f"配置项 {key!r} 必须是 TOML 表。")
    return value
