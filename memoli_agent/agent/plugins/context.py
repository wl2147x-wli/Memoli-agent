"""不暴露应用秘密和裸 Runtime 对象的插件上下文。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from memoli_agent.agent.plugins.capabilities import ScopedPluginState


class CapabilityClient(Protocol):
    """插件可调用的统一能力客户端。"""

    async def call(
        self,
        capability: str,
        arguments: dict[str, Any],
        *,
        trace_id: str = "",
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class PluginRuntimeContext:
    """传给插件的最小运行期资源集合。"""

    plugin_id: str
    plugin_version: str
    backend: str
    config: Mapping[str, Any] = field(default_factory=dict)
    capabilities: CapabilityClient | None = None
    state: ScopedPluginState | None = None


# 保留类型别名以减少内部迁移噪声；字段已不再暴露 AppConfig 或注册表。
PluginContext = PluginRuntimeContext
