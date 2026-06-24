"""插件管理器。"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field

from memoli_agent.agent.plugins.base import Plugin, PluginLoadResult
from memoli_agent.agent.plugins.context import PluginContext


@dataclass(slots=True)
class PluginManager:
    """本地插件管理器。"""

    enabled_plugins: list[str]
    context: PluginContext
    plugins: list[Plugin] = field(default_factory=list)
    load_results: list[PluginLoadResult] = field(default_factory=list)

    def load_enabled_plugins(self) -> list[PluginLoadResult]:
        """加载配置中启用的插件。"""

        self.plugins.clear()
        self.load_results.clear()

        for plugin_name in self.enabled_plugins:
            result = self._load_one(plugin_name)
            self.load_results.append(result)

        return list(self.load_results)

    async def initialize_plugins(self) -> None:
        """初始化所有已加载插件。"""

        for plugin in self.plugins:
            try:
                await plugin.initialize(self.context)
            except Exception as exc:
                self.load_results.append(
                    PluginLoadResult(
                        name=plugin.name,
                        success=False,
                        error=f"initialize failed: {type(exc).__name__}: {exc}",
                    )
                )

    async def terminate_plugins(self) -> None:
        """关闭所有已加载插件。"""

        for plugin in reversed(self.plugins):
            try:
                await plugin.terminate(self.context)
            except Exception:
                continue

    def register_plugins(self) -> None:
        """让插件注册工具和 hooks。"""

        for plugin in self.plugins:
            try:
                plugin.register(self.context)
            except Exception as exc:
                self.load_results.append(
                    PluginLoadResult(
                        name=plugin.name,
                        success=False,
                        error=f"register failed: {type(exc).__name__}: {exc}",
                    )
                )

    def _load_one(self, plugin_name: str) -> PluginLoadResult:
        """加载单个插件模块。"""

        module_name = f"memoli_agent.plugins.{plugin_name}.plugin"
        try:
            module = importlib.import_module(module_name)
            plugin = self._get_plugin_from_module(module)
            self.plugins.append(plugin)
            return PluginLoadResult(name=plugin_name, success=True)
        except Exception as exc:
            return PluginLoadResult(
                name=plugin_name,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )

    def _get_plugin_from_module(self, module: object) -> Plugin:
        """从模块中获取插件对象。"""

        create_plugin = getattr(module, "create_plugin", None)
        if callable(create_plugin):
            return create_plugin()

        plugin = getattr(module, "plugin", None)
        if plugin is None:
            raise AttributeError("插件模块必须暴露 plugin 或 create_plugin()。")
        return plugin
