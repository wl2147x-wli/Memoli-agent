"""确定性、类型化且可追踪的插件 Hook Bus。"""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from enum import Enum
from typing import Any

from memoli_agent.agent.plugins.events import (
    OBSERVER_HOOKS,
    POLICY_HOOKS,
    TRANSFORMER_HOOKS,
    HookEvent,
    HookKind,
    HookName,
    HookPatch,
    ToolBeforeEvent,
    ToolDecision,
    ToolDecisionAction,
    apply_patch_to_event,
    validate_decision,
    validate_patch,
)
from memoli_agent.agent.trajectory import (
    NewTrajectoryEvent,
    NullTrajectoryStore,
    TrajectoryError,
    TrajectoryStore,
)

HookCallback = Callable[[Any], object | Awaitable[object]]


@dataclass(frozen=True, slots=True)
class HookRegistration:
    """一个带来源和顺序信息的 Hook。"""

    plugin_id: str
    plugin_version: str
    backend: str
    hook: HookName
    kind: HookKind
    callback: HookCallback
    priority: int = 0
    dependency_order: int = 0
    deadline_seconds: float = 2.0
    handler_name: str = ""

    @property
    def identity(self) -> tuple[str, HookName, str]:
        return (self.plugin_id, self.hook, self.handler_name)


@dataclass(slots=True)
class HookBus:
    """按依赖、优先级和插件 ID 串行执行 hooks。"""

    trajectory_store: TrajectoryStore = field(default_factory=NullTrajectoryStore)
    default_deadline_seconds: float = 2.0
    _registrations: list[HookRegistration] = field(default_factory=list)
    _durations_ms: dict[int, float] = field(default_factory=dict)

    def register(self, registration: HookRegistration) -> Callable[[], None]:
        """注册 Hook 并返回幂等撤销函数。"""

        self._validate_kind(registration.hook, registration.kind)
        if any(item.identity == registration.identity for item in self._registrations):
            raise ValueError(
                "Hook 已注册："
                f"{registration.plugin_id}:{registration.hook.value}:"
                f"{registration.handler_name}"
            )
        self._registrations.append(registration)
        self._registrations.sort(key=self._sort_key)
        removed = False

        def unregister() -> None:
            nonlocal removed
            if removed:
                return
            removed = True
            self._registrations = [
                item for item in self._registrations if item is not registration
            ]

        return unregister

    def registrations(self, hook: HookName | None = None) -> list[HookRegistration]:
        """返回稳定顺序的注册快照。"""

        if hook is None:
            return list(self._registrations)
        return [item for item in self._registrations if item.hook is hook]

    async def transform(self, hook: HookName, event: HookEvent) -> HookEvent:
        """串行运行 Transformer，失败时丢弃该次 Patch。"""

        if hook not in TRANSFORMER_HOOKS:
            raise ValueError(f"{hook.value} 不是 Transformer Hook。")
        current = event
        for order, registration in enumerate(self.registrations(hook), start=1):
            try:
                result = await self._invoke(registration, current, order)
                patch = validate_patch(hook, result)
                patch = _attribute_patch(patch, registration.plugin_id, order)
                current = apply_patch_to_event(current, patch)
                await self._record(
                    current.trace_id,
                    "plugin_hook_completed",
                    registration,
                    order,
                    {
                        "patch": _jsonable(patch),
                        "status": "completed",
                        "duration_ms": self._duration(registration),
                    },
                )
            except TrajectoryError:
                raise
            except Exception as exc:
                await self._record_failure(current.trace_id, registration, order, exc)
        return current

    async def policy(
        self,
        event: ToolBeforeEvent,
    ) -> tuple[ToolDecision, ToolBeforeEvent]:
        """串行执行工具 Policy；异常和非法结果均 fail-closed。"""

        current = event
        for order, registration in enumerate(
            self.registrations(HookName.TOOL_BEFORE), start=1
        ):
            try:
                result = await self._invoke(registration, current, order)
                if result is None:
                    result = ToolDecision.allow()
                result = validate_decision(result)
                if result.action is ToolDecisionAction.REWRITE:
                    current = replace(current, arguments=dict(result.arguments))
                await self._record(
                    current.trace_id,
                    "plugin_hook_completed",
                    registration,
                    order,
                    {
                        "decision": _jsonable(result),
                        "status": "completed",
                        "duration_ms": self._duration(registration),
                    },
                )
                if result.action in {
                    ToolDecisionAction.DENY,
                    ToolDecisionAction.REQUIRE_CONFIRMATION,
                }:
                    return result, current
            except TrajectoryError:
                raise
            except Exception as exc:
                await self._record_failure(current.trace_id, registration, order, exc)
                return (
                    ToolDecision.deny(
                        "插件工具策略执行失败，当前调用已安全拒绝。",
                        error_type=type(exc).__name__,
                    ),
                    current,
                )
        return ToolDecision.allow(), current

    async def observe(self, hook: HookName, event: HookEvent) -> None:
        """串行运行只读 Observer，返回值不会影响主流程。"""

        if hook not in OBSERVER_HOOKS:
            raise ValueError(f"{hook.value} 不是 Observer Hook。")
        for order, registration in enumerate(self.registrations(hook), start=1):
            try:
                _ = await self._invoke(registration, event, order)
                await self._record(
                    event.trace_id,
                    "plugin_hook_completed",
                    registration,
                    order,
                    {
                        "status": "completed",
                        "duration_ms": self._duration(registration),
                    },
                )
            except TrajectoryError:
                # Observer 没有决策权；诊断轨迹失败不能改变主流程结果。
                continue
            except Exception as exc:
                await self._record_failure(event.trace_id, registration, order, exc)

    async def _invoke(
        self,
        registration: HookRegistration,
        event: HookEvent,
        order: int,
    ) -> object:
        await self._record(
            event.trace_id,
            "plugin_hook_started",
            registration,
            order,
            {"status": "started"},
        )
        started = time.monotonic()

        async def call() -> object:
            result = registration.callback(event)
            if inspect.isawaitable(result):
                return await result
            return result

        deadline = min(
            registration.deadline_seconds,
            self.default_deadline_seconds,
        )
        try:
            return await asyncio.wait_for(call(), timeout=deadline)
        finally:
            self._durations_ms[id(registration)] = (time.monotonic() - started) * 1000

    async def _record_failure(
        self,
        trace_id: str,
        registration: HookRegistration,
        order: int,
        exc: Exception,
    ) -> None:
        await self._record(
            trace_id,
            "plugin_hook_failed",
            registration,
            order,
            {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "duration_ms": self._duration(registration),
            },
        )

    def _duration(self, registration: HookRegistration) -> float:
        return round(self._durations_ms.get(id(registration), 0.0), 3)

    async def _record(
        self,
        trace_id: str,
        event_type: str,
        registration: HookRegistration,
        order: int,
        extra: dict[str, Any],
    ) -> None:
        if not trace_id:
            return
        await self.trajectory_store.record(
            NewTrajectoryEvent(
                trace_id=trace_id,
                event_type=event_type,
                payload={
                    "plugin_id": registration.plugin_id,
                    "plugin_version": registration.plugin_version,
                    "backend": registration.backend,
                    "hook": registration.hook.value,
                    "kind": registration.kind.value,
                    "order": order,
                    "handler": registration.handler_name,
                    **extra,
                },
            )
        )

    @staticmethod
    def _sort_key(item: HookRegistration) -> tuple[int, int, str, str]:
        return (
            item.dependency_order,
            -item.priority,
            item.plugin_id,
            item.handler_name,
        )

    @staticmethod
    def _validate_kind(hook: HookName, kind: HookKind) -> None:
        expected = (
            HookKind.TRANSFORMER
            if hook in TRANSFORMER_HOOKS
            else HookKind.POLICY
            if hook in POLICY_HOOKS
            else HookKind.OBSERVER
        )
        if kind is not expected:
            raise ValueError(f"{hook.value} 必须注册为 {expected.value}。")


def _attribute_patch(patch: HookPatch, plugin_id: str, order: int) -> HookPatch:
    from memoli_agent.agent.plugins.events import ContextPatch

    if not isinstance(patch, ContextPatch):
        return patch
    return ContextPatch(
        sections=tuple(
            replace(section, source_plugin=plugin_id, order=order)
            for section in patch.sections
        )
    )


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
