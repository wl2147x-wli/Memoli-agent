"""插件 manifest 读取、校验与依赖排序。"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memoli_agent.agent.plugins.base import PluginExecutionMode
from memoli_agent.agent.plugins.events import HookName

RUNTIME_VERSION = "0.1.0"
_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


@dataclass(frozen=True, slots=True)
class PluginPermissions:
    """插件请求的宿主能力。"""

    capabilities: tuple[str, ...] = ()
    workspace_read: tuple[str, ...] = ()
    workspace_write: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PluginResources:
    """插件请求的资源上限；系统配置只能进一步收紧。"""

    hook_deadline_seconds: float = 2.0
    memory_mb: int = 256
    cpus: float = 0.5
    pids: int = 32
    max_output_bytes: int = 1_048_576
    max_rpc_bytes: int = 262_144

    def __post_init__(self) -> None:
        if self.hook_deadline_seconds <= 0:
            raise ValueError("plugin resources.hook_deadline_seconds 必须大于 0。")
        if self.memory_mb < 16 or self.cpus <= 0 or self.pids <= 0:
            raise ValueError("plugin resources 的 memory/cpus/pids 配置无效。")
        if self.max_output_bytes <= 0 or self.max_rpc_bytes <= 0:
            raise ValueError("plugin resources 的输出上限必须大于 0。")


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """导入插件代码前即可验证的声明。"""

    plugin_id: str
    version: str
    runtime: str = ">=0.1,<0.2"
    entrypoint: str = "plugin:create_plugin"
    execution: PluginExecutionMode = PluginExecutionMode.IN_PROCESS
    description: str = ""
    dependencies: tuple[str, ...] = ()
    hooks: tuple[HookName, ...] = ()
    tools: tuple[str, ...] = ()
    permissions: PluginPermissions = field(default_factory=PluginPermissions)
    resources: PluginResources = field(default_factory=PluginResources)
    config: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1
    plugin_dir: Path = Path()

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError(f"不支持的 plugin manifest schema：{self.schema_version}")
        if not _ID_PATTERN.fullmatch(self.plugin_id):
            raise ValueError(f"插件 ID 无效：{self.plugin_id}")
        if not self.version.strip():
            raise ValueError("插件 version 不能为空。")
        if ":" not in self.entrypoint:
            raise ValueError("插件 entrypoint 必须为 module:attribute。")
        for dependency in self.dependencies:
            if not _ID_PATTERN.fullmatch(dependency):
                raise ValueError(f"插件依赖 ID 无效：{dependency}")
        if len(set(self.hooks)) != len(self.hooks):
            raise ValueError("manifest hooks 不能重复。")
        if len(set(self.tools)) != len(self.tools):
            raise ValueError("manifest tools 不能重复。")


def load_manifest(plugin_dir: Path, expected_id: str | None = None) -> PluginManifest:
    """从插件目录读取 ``plugin.toml``，且不导入插件代码。"""

    path = plugin_dir / "plugin.toml"
    if not path.is_file():
        raise FileNotFoundError(f"插件缺少 manifest：{path}")
    with path.open("rb") as file:
        raw = tomllib.load(file)
    if not isinstance(raw, dict):
        raise TypeError("plugin.toml 根节点必须为 TOML table。")
    allowed_root = {
        "schema_version",
        "id",
        "version",
        "runtime",
        "entrypoint",
        "execution",
        "description",
        "dependencies",
        "hooks",
        "tools",
        "permissions",
        "resources",
        "config",
    }
    unknown_root = sorted(set(raw) - allowed_root)
    if unknown_root:
        raise ValueError(f"manifest 包含禁止或未知字段：{', '.join(unknown_root)}")
    plugin_id = str(raw.get("id") or "")
    if expected_id is not None and plugin_id != expected_id:
        raise ValueError(f"manifest ID {plugin_id!r} 与配置 {expected_id!r} 不一致。")
    permissions_raw = _mapping(raw.get("permissions"), "permissions")
    resources_raw = _mapping(raw.get("resources"), "resources")
    config_raw = _mapping(raw.get("config"), "config")
    unknown_permissions = sorted(
        set(permissions_raw) - {"capabilities", "workspace_read", "workspace_write"}
    )
    if unknown_permissions:
        raise ValueError(
            f"permissions 包含禁止或未知字段：{', '.join(unknown_permissions)}"
        )
    try:
        hooks = tuple(
            HookName(str(item)) for item in _string_list(raw.get("hooks"), "hooks")
        )
        manifest = PluginManifest(
            schema_version=int(raw.get("schema_version", 1)),
            plugin_id=plugin_id,
            version=str(raw.get("version") or ""),
            runtime=str(raw.get("runtime") or ">=0.1,<0.2"),
            entrypoint=str(raw.get("entrypoint") or "plugin:create_plugin"),
            execution=PluginExecutionMode(str(raw.get("execution") or "in_process")),
            description=str(raw.get("description") or ""),
            dependencies=tuple(_string_list(raw.get("dependencies"), "dependencies")),
            hooks=hooks,
            tools=tuple(_string_list(raw.get("tools"), "tools")),
            permissions=PluginPermissions(
                capabilities=tuple(
                    _string_list(permissions_raw.get("capabilities"), "capabilities")
                ),
                workspace_read=tuple(
                    _string_list(
                        permissions_raw.get("workspace_read"), "workspace_read"
                    )
                ),
                workspace_write=tuple(
                    _string_list(
                        permissions_raw.get("workspace_write"), "workspace_write"
                    )
                ),
            ),
            resources=PluginResources(**resources_raw),
            config=dict(config_raw),
            plugin_dir=plugin_dir.resolve(),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"插件 {plugin_id or expected_id or plugin_dir.name} manifest 无效：{exc}"
        ) from exc
    if not version_satisfies(RUNTIME_VERSION, manifest.runtime):
        raise ValueError(
            f"插件 {manifest.plugin_id} 要求 Runtime {manifest.runtime}，"
            f"当前为 {RUNTIME_VERSION}。"
        )
    return manifest


def sort_manifests(manifests: list[PluginManifest]) -> list[PluginManifest]:
    """按依赖拓扑和插件 ID 返回确定性顺序。"""

    by_id = {manifest.plugin_id: manifest for manifest in manifests}
    if len(by_id) != len(manifests):
        raise ValueError("启用插件 ID 重复。")
    missing = sorted(
        {
            dependency
            for manifest in manifests
            for dependency in manifest.dependencies
            if dependency not in by_id
        }
    )
    if missing:
        raise ValueError(f"插件依赖未启用：{', '.join(missing)}")
    incoming = {
        manifest.plugin_id: set(manifest.dependencies) for manifest in manifests
    }
    ordered: list[PluginManifest] = []
    while incoming:
        ready = sorted(plugin_id for plugin_id, deps in incoming.items() if not deps)
        if not ready:
            cycle = ", ".join(sorted(incoming))
            raise ValueError(f"插件依赖形成循环：{cycle}")
        for plugin_id in ready:
            ordered.append(by_id[plugin_id])
            incoming.pop(plugin_id)
            for deps in incoming.values():
                deps.discard(plugin_id)
    return ordered


def version_satisfies(version: str, constraint: str) -> bool:
    """支持 manifest 所需的最小 SemVer 比较表达式。"""

    actual = _version_tuple(version)
    for item in (part.strip() for part in constraint.split(",")):
        if not item:
            continue
        match = re.fullmatch(r"(>=|<=|==|>|<)?\s*(\d+(?:\.\d+){0,2})", item)
        if match is None:
            raise ValueError(f"不支持的 Runtime 版本约束：{item}")
        operator = match.group(1) or "=="
        target = _version_tuple(match.group(2))
        comparisons = {
            "==": actual == target,
            ">=": actual >= target,
            "<=": actual <= target,
            ">": actual > target,
            "<": actual < target,
        }
        if not comparisons[operator]:
            return False
    return True


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    if not 1 <= len(parts) <= 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"版本格式无效：{value}")
    return tuple([*(int(part) for part in parts), 0, 0][:3])  # type: ignore[return-value]


def _mapping(value: object, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"{name} 必须为 TOML table。")
    return {str(key): item for key, item in value.items()}


def _string_list(value: object, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"{name} 必须为字符串数组。")
    return list(value)
