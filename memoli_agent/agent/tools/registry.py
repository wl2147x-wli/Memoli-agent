"""工具注册表。

ToolRegistry 负责统一注册工具、暴露 schema，并执行模型请求的工具调用。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from memoli_agent.agent.plugins.events import (
    HookName,
    ToolAfterEvent,
    ToolBeforeEvent,
    ToolDecisionAction,
)
from memoli_agent.agent.plugins.hooks import HookBus
from memoli_agent.agent.tools.base import Tool, ToolResult
from memoli_agent.agent.tools.execution import ToolExecutionContext, tool_context


@dataclass(slots=True)
class ToolRegistry:
    """工具注册表。"""

    hook_bus: HookBus | None = None
    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        """注册一个工具。"""

        if not tool.name:
            raise ValueError("工具名称不能为空。")
        if tool.name in self._tools:
            raise ValueError(f"工具已注册：{tool.name}")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """幂等移除插件工具，供注册事务回滚使用。"""

        self._tools.pop(name, None)

    def get_schemas(self) -> list[dict[str, Any]]:
        """返回 OpenAI-compatible tools schema。"""

        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        context: ToolExecutionContext | None = None,
    ) -> ToolResult:
        """执行指定工具。"""

        tool = self._tools.get(name)
        if tool is None:
            result = ToolResult(
                content=f"工具不存在：{name}",
                success=False,
                metadata={"tool": name},
            )
            await self._observe_after(name, arguments, result, context)
            return result

        try:
            final_arguments = dict(arguments)
            if self.hook_bus is not None:
                decision, policy_event = await self.hook_bus.policy(
                    ToolBeforeEvent(
                        trace_id=context.trace_id if context else "",
                        session_key=context.session_key if context else "",
                        tool_name=name,
                        arguments=final_arguments,
                        tool_call_id=context.tool_call_id if context else "",
                    )
                )
                final_arguments = dict(policy_event.arguments)
                if decision.action in {
                    ToolDecisionAction.DENY,
                    ToolDecisionAction.REQUIRE_CONFIRMATION,
                }:
                    status = (
                        "confirmation_required"
                        if decision.action is ToolDecisionAction.REQUIRE_CONFIRMATION
                        else "denied"
                    )
                    result = ToolResult(
                        content=decision.reason or "工具调用被插件策略拒绝。",
                        success=False,
                        status=status,
                        metadata={
                            "tool": name,
                            "error": decision.error_type or "PluginPolicyDenied",
                            "executed_arguments": final_arguments,
                        },
                    )
                    await self._observe_after(name, final_arguments, result, context)
                    return result
            with tool_context(context):
                result = await tool.run(final_arguments)
            result = replace(
                result,
                metadata={
                    **result.metadata,
                    "executed_arguments": final_arguments,
                    "status": result.effective_status,
                },
            )
            await self._observe_after(name, final_arguments, result, context)
            return result
        except PermissionError as exc:
            result = ToolResult(
                content=f"工具调用被插件拦截：{exc}",
                success=False,
                metadata={"tool": name, "error": "PermissionError"},
            )
            await self._observe_after(name, arguments, result, context)
            return result
        except Exception as exc:
            result = ToolResult(
                content=f"工具执行失败：{exc}",
                success=False,
                metadata={"tool": name, "error": type(exc).__name__},
            )
            await self._observe_after(name, arguments, result, context)
            return result

    def list_tools(self) -> list[Tool]:
        """返回已注册工具列表。"""

        return list(self._tools.values())

    async def _observe_after(
        self,
        name: str,
        arguments: dict[str, Any],
        result: ToolResult,
        context: ToolExecutionContext | None,
    ) -> None:
        if self.hook_bus is None:
            return
        await self.hook_bus.observe(
            HookName.TOOL_AFTER,
            ToolAfterEvent(
                trace_id=context.trace_id if context else "",
                session_key=context.session_key if context else "",
                tool_name=name,
                arguments=arguments,
                tool_call_id=context.tool_call_id if context else "",
                success=result.success,
                status=result.effective_status,
                content=result.content,
                error_type=str(result.metadata.get("error") or "") or None,
            ),
        )
