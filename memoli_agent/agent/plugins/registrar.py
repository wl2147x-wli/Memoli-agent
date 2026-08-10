"""插件贡献的事务式注册。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from memoli_agent.agent.plugins.events import HookKind, HookName
from memoli_agent.agent.plugins.hooks import HookBus, HookCallback, HookRegistration
from memoli_agent.agent.plugins.manifest import PluginManifest
from memoli_agent.agent.tools.base import Tool
from memoli_agent.agent.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class _StagedContribution:
    commit: Callable[[], Callable[[], None]]


@dataclass(slots=True)
class RegistrationTransaction:
    """只有全部 commit 成功后贡献才保持可见。"""

    _staged: list[_StagedContribution] = field(default_factory=list)
    _undo: list[Callable[[], None]] = field(default_factory=list)
    _committed: bool = False

    def stage(self, commit: Callable[[], Callable[[], None]]) -> None:
        if self._committed:
            raise RuntimeError("注册事务已经提交。")
        self._staged.append(_StagedContribution(commit=commit))

    def commit(self) -> None:
        if self._committed:
            return
        try:
            for contribution in self._staged:
                self._undo.append(contribution.commit())
        except Exception:
            self.rollback()
            raise
        self._committed = True

    def rollback(self) -> None:
        for undo in reversed(self._undo):
            undo()
        self._undo.clear()
        self._staged.clear()
        self._committed = False

    def close(self) -> None:
        self.rollback()


@dataclass(slots=True)
class PluginRegistrar:
    """插件只能通过该对象声明贡献。"""

    manifest: PluginManifest
    backend: str
    dependency_order: int
    hook_bus: HookBus
    tool_registry: ToolRegistry
    transaction: RegistrationTransaction

    def add_transformer(
        self,
        hook: HookName,
        callback: HookCallback,
        *,
        priority: int = 0,
        handler_name: str = "",
    ) -> None:
        self._add_hook(
            hook,
            HookKind.TRANSFORMER,
            callback,
            priority=priority,
            handler_name=handler_name,
        )

    def add_policy(
        self,
        hook: HookName,
        callback: HookCallback,
        *,
        priority: int = 0,
        handler_name: str = "",
    ) -> None:
        self._add_hook(
            hook,
            HookKind.POLICY,
            callback,
            priority=priority,
            handler_name=handler_name,
        )

    def add_observer(
        self,
        hook: HookName,
        callback: HookCallback,
        *,
        priority: int = 0,
        handler_name: str = "",
    ) -> None:
        self._add_hook(
            hook,
            HookKind.OBSERVER,
            callback,
            priority=priority,
            handler_name=handler_name,
        )

    def add_tool(self, tool: Tool) -> None:
        if tool.name not in self.manifest.tools:
            raise PermissionError(f"manifest 未声明插件工具：{tool.name}")

        def commit() -> Callable[[], None]:
            self.tool_registry.register(tool)
            return lambda: self.tool_registry.unregister(tool.name)

        self.transaction.stage(commit)

    def _add_hook(
        self,
        hook: HookName,
        kind: HookKind,
        callback: HookCallback,
        *,
        priority: int,
        handler_name: str,
    ) -> None:
        if hook not in self.manifest.hooks:
            raise PermissionError(f"manifest 未声明插件 Hook：{hook.value}")
        name = handler_name or getattr(callback, "__name__", type(callback).__name__)
        registration = HookRegistration(
            plugin_id=self.manifest.plugin_id,
            plugin_version=self.manifest.version,
            backend=self.backend,
            hook=hook,
            kind=kind,
            callback=callback,
            priority=priority,
            dependency_order=self.dependency_order,
            deadline_seconds=self.manifest.resources.hook_deadline_seconds,
            handler_name=name,
        )
        self.transaction.stage(lambda: self.hook_bus.register(registration))
