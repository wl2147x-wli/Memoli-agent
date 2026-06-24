"""插件装饰器和 HookRegistry。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import inspect
from typing import Any

from memoli_agent.agent.lifecycle.types import PassiveTurnContext


HookFn = Callable[[PassiveTurnContext], None | Awaitable[None]]
ToolPreHookFn = Callable[[str, dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]

BEFORE_TURN = "before_turn"
BEFORE_REASONING = "before_reasoning"
PROMPT_RENDER = "prompt_render"
AFTER_REASONING = "after_reasoning"
AFTER_TURN = "after_turn"
TOOL_PRE = "tool_pre"


@dataclass(slots=True)
class HookRegistry:
    """插件 hook 注册表。"""

    _hooks: dict[str, list[HookFn]] = field(default_factory=dict)
    _tool_pre_hooks: list[ToolPreHookFn] = field(default_factory=list)

    def register(self, phase: str, fn: HookFn) -> None:
        """注册 lifecycle hook。"""

        self._hooks.setdefault(phase, []).append(fn)

    def register_tool_pre(self, fn: ToolPreHookFn) -> None:
        """注册工具执行前 hook。"""

        self._tool_pre_hooks.append(fn)

    def get(self, phase: str) -> list[HookFn]:
        """获取指定阶段的 hooks。"""

        return list(self._hooks.get(phase, []))

    async def run(self, phase: str, ctx: PassiveTurnContext) -> None:
        """运行指定阶段 hooks，异常写入 metadata。"""

        for fn in self.get(phase):
            try:
                result = fn(ctx)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                ctx.metadata.setdefault("plugin_errors", []).append(
                    f"{phase}: {type(exc).__name__}: {exc}"
                )

    async def run_tool_pre(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """运行工具执行前 hooks。"""

        current_arguments = dict(arguments)
        for fn in self._tool_pre_hooks:
            result = fn(tool_name, current_arguments)
            if inspect.isawaitable(result):
                current_arguments = await result
            elif result is not None:
                current_arguments = result
        return current_arguments


def before_turn(fn: HookFn) -> HookFn:
    """标记 before_turn hook。"""

    setattr(fn, "__memoli_hook_phase__", BEFORE_TURN)
    return fn


def before_reasoning(fn: HookFn) -> HookFn:
    """标记 before_reasoning hook。"""

    setattr(fn, "__memoli_hook_phase__", BEFORE_REASONING)
    return fn


def prompt_render(fn: HookFn) -> HookFn:
    """标记 prompt_render hook。"""

    setattr(fn, "__memoli_hook_phase__", PROMPT_RENDER)
    return fn


def after_reasoning(fn: HookFn) -> HookFn:
    """标记 after_reasoning hook。"""

    setattr(fn, "__memoli_hook_phase__", AFTER_REASONING)
    return fn


def after_turn(fn: HookFn) -> HookFn:
    """标记 after_turn hook。"""

    setattr(fn, "__memoli_hook_phase__", AFTER_TURN)
    return fn


def tool_pre(fn: ToolPreHookFn) -> ToolPreHookFn:
    """标记 tool_pre hook。"""

    setattr(fn, "__memoli_hook_phase__", TOOL_PRE)
    return fn
