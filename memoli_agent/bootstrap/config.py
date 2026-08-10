"""配置加载模块。

第二阶段负责把运行配置从入口文件中抽出来：

- 使用 Python 3.11 标准库 tomllib 读取 config.toml。
- 用 dataclass 描述配置结构，避免在业务代码里到处传 dict。
- 当本地没有 config.toml 时使用默认配置，让项目保持开箱可运行。
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(slots=True)
class RuntimeConfig:
    """应用运行目录配置。"""

    workspace: str = "workspace"


@dataclass(slots=True)
class LLMProviderEndpointConfig:
    """一个模型服务 endpoint。"""

    protocol: str
    api_key: str = field(default="", repr=False)
    base_url: str = ""
    dialect: str = "default"
    timeout_seconds: float = 60.0
    max_retries: int = 1
    requires_key: bool = True

    def __post_init__(self) -> None:
        self.protocol = self.protocol.strip().lower()
        if self.protocol not in {"openai", "openai-compatible", "anthropic", "echo"}:
            raise ValueError(f"未知 llm provider protocol：{self.protocol}")
        if self.timeout_seconds <= 0 or self.max_retries < 0:
            raise ValueError("LLM endpoint 超时必须大于 0，重试次数不能小于 0。")
        if self.protocol == "echo":
            self.requires_key = False


@dataclass(slots=True)
class LLMModelProfileConfig:
    """模型 ID、能力和生成参数。"""

    provider: str
    model: str
    capabilities: list[str] = field(default_factory=lambda: ["text"])
    max_output_tokens: int = 8192
    temperature: float | None = None

    def __post_init__(self) -> None:
        allowed = {
            "text",
            "tools",
            "reasoning",
            "streaming",
            "structured-output",
            "vision",
            "prompt-cache",
        }
        unknown = set(self.capabilities) - allowed
        if unknown:
            raise ValueError(f"未知模型能力：{sorted(unknown)}")
        if "text" not in self.capabilities:
            self.capabilities.insert(0, "text")
        if not self.provider or not self.model or self.max_output_tokens <= 0:
            raise ValueError("模型 Profile 必须包含 provider、model 和正输出上限。")


@dataclass(slots=True)
class LLMRoutesConfig:
    """主 Agent 使用的主 Profile 与有序 fallback。"""

    agent: str = ""
    fallback: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LLMConfig:
    """兼容旧单段配置，并支持 endpoint/profile/route 分层。"""

    provider: str = "echo"
    model: str = "echo"
    api_key: str = field(default="", repr=False)
    base_url: str = ""
    dialect: str = "default"
    timeout_seconds: float = 60.0
    max_retries: int = 1
    max_output_tokens: int = 8192
    stream: bool = False
    providers: dict[str, LLMProviderEndpointConfig] = field(default_factory=dict)
    models: dict[str, LLMModelProfileConfig] = field(default_factory=dict)
    routes: LLMRoutesConfig = field(default_factory=LLMRoutesConfig)

    def __post_init__(self) -> None:
        self.provider = self.provider.strip().lower()
        if self.providers:
            self._validate_profiles()
            return
        if self.provider not in {
            "echo",
            "openai",
            "openai-compatible",
            "anthropic",
        }:
            raise ValueError(f"未知 llm.provider：{self.provider}")
        if self.provider != "echo" and not self.api_key:
            raise ValueError(f"llm.provider={self.provider!r} 必须配置 api_key。")
        if self.timeout_seconds <= 0 or self.max_retries < 0:
            raise ValueError("LLM 超时必须大于 0，重试次数不能小于 0。")

    @property
    def uses_profiles(self) -> bool:
        return bool(self.providers)

    @property
    def primary_profile_name(self) -> str:
        return self.routes.agent if self.uses_profiles else "default"

    @property
    def primary_model(self) -> str:
        if not self.uses_profiles:
            return self.model
        return self.models[self.routes.agent].model

    def _validate_profiles(self) -> None:
        if not self.models:
            raise ValueError("配置 llm.providers 时必须同时配置 llm.models。")
        if not self.routes.agent:
            raise ValueError("配置模型 Profile 时必须设置 llm.routes.agent。")
        for name, endpoint in self.providers.items():
            if endpoint.requires_key and not endpoint.api_key:
                raise ValueError(f"LLM Provider {name!r} 必须配置 api_key。")
        for name, profile in self.models.items():
            if profile.provider not in self.providers:
                raise ValueError(
                    f"模型 Profile {name!r} 引用了未知 Provider {profile.provider!r}。"
                )
        route_names = [self.routes.agent, *self.routes.fallback]
        missing = [name for name in route_names if name not in self.models]
        if missing:
            raise ValueError(f"LLM route 引用了未知 Profile：{missing}")
        if len(route_names) != len(set(route_names)):
            raise ValueError("LLM route 中不能重复同一个 Profile。")
        for name in self.routes.fallback:
            endpoint = self.providers[self.models[name].provider]
            if endpoint.protocol == "echo":
                raise ValueError("Echo 不能配置为隐式 fallback。")


@dataclass(slots=True)
class AgentConfig:
    """主 agent 的基础行为配置。"""

    name: str = "Memoli"
    max_iterations: int = 12
    max_elapsed_seconds: float = 300.0
    no_progress_limit: int = 3
    history_window: int = 20

    def __post_init__(self) -> None:
        if self.max_iterations <= 0:
            raise ValueError("agent.max_iterations 必须大于 0。")
        if self.max_elapsed_seconds <= 0:
            raise ValueError("agent.max_elapsed_seconds 必须大于 0。")
        if self.no_progress_limit <= 0:
            raise ValueError("agent.no_progress_limit 必须大于 0。")


@dataclass(slots=True)
class TrajectoryConfig:
    """本地运行轨迹配置。"""

    enabled: bool = True
    database: str = "workspace/trajectories.db"
    capture_content: str = "redacted"
    max_inline_bytes: int = 65_536
    max_payload_bytes: int = 4_194_304
    payload_directory: str = "workspace/trajectory-payloads"
    sensitive_keys: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.capture_content not in {"metadata-only", "redacted", "full-local"}:
            raise ValueError("trajectory.capture_content 配置无效。")
        if self.max_inline_bytes <= 0:
            raise ValueError("trajectory.max_inline_bytes 必须大于 0。")
        if self.max_payload_bytes < self.max_inline_bytes:
            raise ValueError("trajectory.max_payload_bytes 不能小于内联上限。")
        if not isinstance(self.sensitive_keys, list) or not all(
            isinstance(key, str) for key in self.sensitive_keys
        ):
            raise TypeError("trajectory.sensitive_keys 必须是字符串数组。")


@dataclass(slots=True)
class MemoryEmbeddingConfig:
    """与聊天模型独立的可选 embedding 配置。"""

    enabled: bool = False
    provider: str = "openai-compatible"
    model: str = ""
    version: str = "1"
    base_url: str = "https://api.openai.com/v1"
    api_key_env: str = "MEMOLI_EMBEDDING_API_KEY"
    dimensions: int = 1536
    timeout_seconds: float = 30.0
    batch_size: int = 8
    candidate_limit: int = 200

    def __post_init__(self) -> None:
        if self.provider not in {"openai-compatible", "deterministic", "disabled"}:
            raise ValueError("memory.embedding.provider 配置无效。")
        if self.enabled and not self.model and self.provider == "openai-compatible":
            raise ValueError("启用 embedding 时必须配置 model。")
        if self.dimensions <= 0 or self.batch_size <= 0 or self.candidate_limit <= 0:
            raise ValueError("memory.embedding 的维度和批量上限必须大于 0。")
        if self.timeout_seconds <= 0:
            raise ValueError("memory.embedding.timeout_seconds 必须大于 0。")


@dataclass(slots=True)
class MemoryHybridConfig:
    """确定性混合召回参数。"""

    enabled: bool = True
    rrf_k: int = 60
    candidate_limit: int = 50
    keyword_weight: float = 1.0
    semantic_weight: float = 1.0
    metadata_weight: float = 0.5
    card_limit: int = 2
    claim_limit: int = 5
    episode_limit: int = 2
    spillover_order: list[str] = field(
        default_factory=lambda: ["claim", "card", "episode"]
    )

    def __post_init__(self) -> None:
        if self.rrf_k <= 0 or self.candidate_limit <= 0:
            raise ValueError("memory.hybrid 的 RRF 和候选上限必须大于 0。")
        if min(self.card_limit, self.claim_limit, self.episode_limit) < 0:
            raise ValueError("memory.hybrid 的类型配额不能小于 0。")
        if set(self.spillover_order) != {"card", "claim", "episode"}:
            raise ValueError("memory.hybrid.spillover_order 必须包含三种记忆类型。")


@dataclass(slots=True)
class MemoryConfig:
    """个人长期记忆配置。"""

    enabled: bool = True
    engine: str = "sqlite"
    path: str = "workspace/memory"
    database: str = "workspace/memory.db"
    auto_recall: bool = True
    core_card_limit: int = 8
    core_card_chars: int = 4_000
    recall_limit: int = 8
    recall_chars: int = 8_000
    consolidation_enabled: bool = False
    legacy_import: str = "preview"
    max_cjk_ngram: int = 3
    card_builder_enabled: bool = True
    episode_projection_enabled: bool = True
    maintenance_batch_size: int = 4
    embedding: MemoryEmbeddingConfig = field(default_factory=MemoryEmbeddingConfig)
    hybrid: MemoryHybridConfig = field(default_factory=MemoryHybridConfig)

    def __post_init__(self) -> None:
        if self.engine not in {"sqlite", "markdown"}:
            raise ValueError("memory.engine 仅支持 sqlite 或 markdown。")
        if self.core_card_limit <= 0 or self.recall_limit <= 0:
            raise ValueError("memory 的结果数量上限必须大于 0。")
        if self.core_card_chars <= 0 or self.recall_chars <= 0:
            raise ValueError("memory 的字符预算必须大于 0。")
        if self.legacy_import not in {"off", "preview", "auto"}:
            raise ValueError("memory.legacy_import 配置无效。")
        if self.max_cjk_ngram not in {1, 2, 3}:
            raise ValueError("memory.max_cjk_ngram 必须为 1、2 或 3。")
        if self.maintenance_batch_size <= 0:
            raise ValueError("memory.maintenance_batch_size 必须大于 0。")


@dataclass(slots=True)
class WorkingMemoryConfig:
    """与个人记忆相互独立的任务工作状态配置。"""

    enabled: bool = True
    database: str = "workspace/working-state.db"
    max_chars: int = 4_000
    stale_policy: str = "mark"

    def __post_init__(self) -> None:
        if self.max_chars <= 0:
            raise ValueError("working_memory.max_chars 必须大于 0。")
        if self.stale_policy not in {"mark", "keep"}:
            raise ValueError("working_memory.stale_policy 配置无效。")


@dataclass(slots=True)
class ToolsConfig:
    """工具系统配置。"""

    tool_search_enabled: bool = False
    code_runner: str = "container"
    code_container_cli: str = "docker"
    code_container_image: str = "memoli-code-runner@sha256:" + "0" * 64
    code_python_executable: str = ""
    code_allow_network: bool = False
    code_memory_mb: int = 256
    code_cpus: float = 0.5
    code_pids: int = 64
    code_timeout_seconds: int = 60
    code_max_output_chars: int = 10_000
    file_read_max_lines: int = 2_000
    file_max_output_chars: int = 15_000
    browser_enabled: bool = False
    subagent_tool_enabled: bool = False
    memory_manage_enabled: bool = False

    def __post_init__(self) -> None:
        if self.code_runner not in {"container", "trusted-host", "disabled"}:
            raise ValueError("tools.code_runner 配置无效。")
        if self.code_runner == "container" and not re.search(
            r"@sha256:[0-9a-f]{64}$", self.code_container_image
        ):
            raise ValueError("容器 code runner 镜像必须固定到 sha256 digest。")
        if self.code_runner == "trusted-host" and not self.code_python_executable:
            raise ValueError("trusted-host 必须显式配置 code_python_executable。")
        if self.code_memory_mb <= 0 or self.code_cpus <= 0 or self.code_pids <= 0:
            raise ValueError("code runner 资源限制必须大于 0。")
        if self.code_timeout_seconds <= 0:
            raise ValueError("tools.code_timeout_seconds 必须大于 0。")
        if self.code_max_output_chars <= 0:
            raise ValueError("tools.code_max_output_chars 必须大于 0。")
        if self.file_read_max_lines <= 0:
            raise ValueError("tools.file_read_max_lines 必须大于 0。")
        if self.file_max_output_chars <= 0:
            raise ValueError("tools.file_max_output_chars 必须大于 0。")


@dataclass(slots=True)
class SkillsConfig:
    """版本化 Skill Runtime 配置。

    默认关闭以保持既有九工具运行时不变；启用后才创建注册表并暴露
    ``skill_load``。制品和数据库路径均由宿主控制，Skill 清单不能覆盖。
    """

    enabled: bool = False
    database: str = "workspace/skills.db"
    artifact_root: str = "workspace/skill-artifacts"
    catalog_max_chars: int = 6_000
    skill_max_chars: int = 15_000
    reference_max_chars: int = 30_000
    max_skill_file_bytes: int = 262_144
    max_package_bytes: int = 2_097_152
    verify_integrity_on_load: bool = True
    include_unavailable_in_catalog: bool = False
    allow_runtime_management: bool = False

    def __post_init__(self) -> None:
        limits = (
            self.catalog_max_chars,
            self.skill_max_chars,
            self.reference_max_chars,
            self.max_skill_file_bytes,
            self.max_package_bytes,
        )
        if any(value <= 0 for value in limits):
            raise ValueError("skills 的大小与上下文预算必须大于 0。")
        if self.max_package_bytes < self.max_skill_file_bytes:
            raise ValueError("skills.max_package_bytes 不能小于单文件上限。")
        if self.allow_runtime_management:
            raise ValueError("首版 skills.allow_runtime_management 只能为 false。")
        if self.include_unavailable_in_catalog:
            raise ValueError("首版不会向模型披露依赖不可用的 Skill。")
        if not self.verify_integrity_on_load:
            raise ValueError("首版必须启用 Skill load 完整性校验。")
        _validate_skill_path(self.database, "skills.database")
        _validate_skill_path(self.artifact_root, "skills.artifact_root")


@dataclass(slots=True)
class CLIChannelConfig:
    """CLI 通道配置。"""

    enabled: bool = True


@dataclass(slots=True)
class ChannelsConfig:
    """所有通道配置的集合。"""

    cli: CLIChannelConfig = field(default_factory=CLIChannelConfig)


@dataclass(slots=True)
class PluginSandboxConfig:
    """容器沙箱的宿主侧硬上限。"""

    container_cli: str = "docker"
    runner_image: str = ""
    memory_mb: int = 256
    cpus: float = 0.5
    pids: int = 32
    wall_time_seconds: float = 30.0
    max_output_bytes: int = 1_048_576
    max_rpc_bytes: int = 262_144

    def __post_init__(self) -> None:
        if self.memory_mb < 16 or self.cpus <= 0 or self.pids <= 0:
            raise ValueError("plugins.sandbox 的资源上限配置无效。")
        if self.wall_time_seconds <= 0:
            raise ValueError("plugins.sandbox.wall_time_seconds 必须大于 0。")
        if self.max_output_bytes <= 0 or self.max_rpc_bytes <= 0:
            raise ValueError("plugins.sandbox 的输出上限必须大于 0。")


@dataclass(slots=True)
class PluginsConfig:
    """插件配置。"""

    enabled: list[str] = field(
        default_factory=lambda: ["memory_default", "shell_safety"]
    )
    trusted: list[str] = field(
        default_factory=lambda: ["memory_default", "shell_safety"]
    )
    force_sandbox: list[str] = field(default_factory=list)
    approved_capabilities: dict[str, list[str]] = field(default_factory=dict)
    system_allowed_capabilities: list[str] = field(
        default_factory=lambda: [
            "state.get",
            "state.set",
            "workspace.read",
            "workspace.write",
        ]
    )
    hook_deadline_seconds: float = 2.0
    state_database: str = "workspace/plugin-state.db"
    sandbox: PluginSandboxConfig = field(default_factory=PluginSandboxConfig)

    def __post_init__(self) -> None:
        if self.hook_deadline_seconds <= 0:
            raise ValueError("plugins.hook_deadline_seconds 必须大于 0。")
        if not set(self.trusted).issubset(self.enabled):
            raise ValueError("plugins.trusted 必须是 enabled 的子集。")
        if not set(self.force_sandbox).issubset(self.enabled):
            raise ValueError("plugins.force_sandbox 必须是 enabled 的子集。")


@dataclass(slots=True)
class SubAgentConfig:
    """子 agent 配置。"""

    enabled: bool = True
    root: str = "workspace/subagents"
    database: str = "workspace/subagents/task-graph.db"
    default_profile: str = "general"
    max_concurrent: int = 1
    max_depth: int = 1
    recovery_policy: str = "interrupt"
    profile_max_iterations: dict[str, int] = field(default_factory=dict)
    profile_max_elapsed_seconds: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_concurrent < 1:
            raise ValueError("subagent.max_concurrent 必须大于等于 1")
        if self.max_depth < 1:
            raise ValueError("subagent.max_depth 必须大于等于 1")
        if self.recovery_policy != "interrupt":
            raise ValueError("当前仅支持 subagent.recovery_policy='interrupt'")
        if any(value <= 0 for value in self.profile_max_iterations.values()):
            raise ValueError("profile_max_iterations 的值必须大于 0")
        if any(value <= 0 for value in self.profile_max_elapsed_seconds.values()):
            raise ValueError("profile_max_elapsed_seconds 的值必须大于 0")


@dataclass(slots=True)
class ProactiveConfig:
    """主动循环配置。"""

    enabled: bool = False
    interval_seconds: int = 60
    run_on_start: bool = False
    initial_delay_seconds: float | None = None
    cooldown_seconds: int = 300
    quiet_hours_start: int | None = None
    quiet_hours_end: int | None = None
    quiet_hours_timezone: str = "UTC"
    chat_id: str = "local"
    message: str = "这是一次主动检查。"

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("proactive.interval_seconds 必须大于 0。")
        if self.initial_delay_seconds is not None and self.initial_delay_seconds <= 0:
            raise ValueError("proactive.initial_delay_seconds 必须大于 0。")
        if self.cooldown_seconds < 0:
            raise ValueError("proactive.cooldown_seconds 不能小于 0。")
        quiet_values = (self.quiet_hours_start, self.quiet_hours_end)
        if (quiet_values[0] is None) != (quiet_values[1] is None):
            raise ValueError("quiet-hours 的开始和结束小时必须同时配置。")
        if any(value is not None and not 0 <= value <= 23 for value in quiet_values):
            raise ValueError("quiet-hours 小时必须位于 0..23。")
        if self.quiet_hours_start is not None:
            try:
                ZoneInfo(self.quiet_hours_timezone)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("proactive.quiet_hours_timezone 无效。") from exc


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
    trajectory: TrajectoryConfig = field(default_factory=TrajectoryConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    working_memory: WorkingMemoryConfig = field(default_factory=WorkingMemoryConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
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
    llm = _build_llm_config(raw_config)
    memory_raw = dict(_table(raw_config, "memory"))
    embedding_raw = memory_raw.pop("embedding", {})
    hybrid_raw = memory_raw.pop("hybrid", {})
    if not isinstance(embedding_raw, dict) or not isinstance(hybrid_raw, dict):
        raise TypeError("memory.embedding 和 memory.hybrid 必须是 TOML table。")
    # 旧配置没有 engine 字段时继续使用 Markdown；新示例显式选择 SQLite。
    if memory_raw and "engine" not in memory_raw:
        memory_raw["engine"] = "markdown"

    plugins_raw = dict(_table(raw_config, "plugins"))
    sandbox_raw = plugins_raw.pop("sandbox", {})
    if not isinstance(sandbox_raw, dict):
        raise TypeError("plugins.sandbox 必须是 TOML table。")
    if "enabled" in plugins_raw and "trusted" not in plugins_raw:
        # 兼容旧配置：显式关闭插件时不应被新的默认 trusted 列表阻止启动。
        enabled_plugins = list(plugins_raw["enabled"])
        plugins_raw["trusted"] = [
            name
            for name in ("memory_default", "shell_safety")
            if name in enabled_plugins
        ]
    plugins = PluginsConfig(
        **plugins_raw,
        sandbox=PluginSandboxConfig(**sandbox_raw),
    )

    return AppConfig(
        runtime=RuntimeConfig(**_table(raw_config, "runtime")),
        llm=llm,
        agent=AgentConfig(**_table(raw_config, "agent")),
        trajectory=TrajectoryConfig(**_table(raw_config, "trajectory")),
        memory=MemoryConfig(
            **memory_raw,
            embedding=MemoryEmbeddingConfig(**embedding_raw),
            hybrid=MemoryHybridConfig(**hybrid_raw),
        ),
        working_memory=WorkingMemoryConfig(**_table(raw_config, "working_memory")),
        tools=ToolsConfig(**_table(raw_config, "tools")),
        skills=SkillsConfig(**_table(raw_config, "skills")),
        channels=ChannelsConfig(
            cli=CLIChannelConfig(**_table(channels_raw, "cli")),
        ),
        plugins=plugins,
        subagent=SubAgentConfig(**_table(raw_config, "subagent")),
        proactive=ProactiveConfig(**_table(raw_config, "proactive")),
        mcp=_build_mcp_config(raw_config),
    )


_ENV_VALUE_PATTERN = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def _build_llm_config(raw_config: dict[str, Any]) -> LLMConfig:
    """解析旧单段配置或新的 endpoint/profile/route 配置。"""

    raw = dict(_table(raw_config, "llm"))
    providers_raw = raw.pop("providers", {})
    models_raw = raw.pop("models", {})
    routes_raw = raw.pop("routes", {})
    if not all(
        isinstance(item, dict) for item in (providers_raw, models_raw, routes_raw)
    ):
        raise TypeError("llm.providers、llm.models 和 llm.routes 必须是 TOML table。")
    if providers_raw or models_raw or routes_raw:
        providers: dict[str, LLMProviderEndpointConfig] = {}
        for name, value in providers_raw.items():
            if not isinstance(value, dict):
                raise TypeError(f"llm.providers.{name} 必须是 TOML table。")
            item = dict(value)
            item["api_key"] = _resolve_config_secret(str(item.get("api_key", "")))
            providers[name] = LLMProviderEndpointConfig(**item)
        models: dict[str, LLMModelProfileConfig] = {}
        for name, value in models_raw.items():
            if not isinstance(value, dict):
                raise TypeError(f"llm.models.{name} 必须是 TOML table。")
            models[name] = LLMModelProfileConfig(**value)
        return LLMConfig(
            **raw,
            providers=providers,
            models=models,
            routes=LLMRoutesConfig(**routes_raw),
        )
    if "api_key" in raw:
        raw["api_key"] = _resolve_config_secret(str(raw["api_key"]))
    return LLMConfig(**raw)


def _resolve_config_secret(value: str) -> str:
    """允许 api_key 在配置文件中直接填写或使用完整环境占位符。"""

    match = _ENV_VALUE_PATTERN.fullmatch(value.strip())
    if match is None:
        return value.strip()
    variable = match.group(1)
    resolved = os.getenv(variable, "").strip()
    if not resolved:
        raise ValueError(f"API key 环境占位符 {variable!r} 未设置或为空。")
    return resolved


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


def _validate_skill_path(value: str, field_name: str) -> None:
    """拒绝空路径和显式父目录逃逸；绝对路径仍允许由宿主管理。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} 不能为空。")
    if ".." in Path(value).parts:
        raise ValueError(f"{field_name} 不能包含父目录逃逸。")
