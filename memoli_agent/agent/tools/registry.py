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

_INTERNAL_TOOL_NAMES = frozenset(
    {
        "memory_write",
        "memory_recall",
        "memory_manage",
        "start_long_term_update",
        "update_working_checkpoint",
        "ask_user",
        "governance_candidate_read",
        "governance_evidence_read",
        "governance_related_claims",
        "governance_decide",
    }
)


def tool_purpose(name: str) -> str:
    """Return non-model-visible execution purpose; unknown tools are business tools."""

    return "internal" if name in _INTERNAL_TOOL_NAMES else "business"


@dataclass(slots=True)
class ToolRegistry:
    """工具注册表。"""

    hook_bus: HookBus | None = None
    _tools: dict[str, Tool] = field(default_factory=dict)
    _progressive_disclosure: bool = False
    _base_tool_names: set[str] = field(default_factory=set)
    _disclosed_tool_names: set[str] = field(default_factory=set)
    _purposes: dict[str, str] = field(default_factory=dict)
    # §7.2 安全撤销记录：区别于 rollback ``unregister``，安全撤销使已冻结 snapshot
    # 进入 fail-closed（停止暴露/执行该能力），故单独追踪以供 ContextCompiler 取用。
    _revoked: set[str] = field(default_factory=set)

    def register(self, tool: Tool, *, purpose: str | None = None) -> None:
        """注册一个工具。"""

        if not tool.name:
            raise ValueError("工具名称不能为空。")
        if tool.name in self._tools:
            raise ValueError(f"工具已注册：{tool.name}")
        self._tools[tool.name] = tool
        selected_purpose = purpose or str(getattr(tool, "purpose", "") or "")
        self._purposes[tool.name] = selected_purpose or tool_purpose(tool.name)

    def unregister(self, name: str) -> None:
        """幂等移除插件工具，供注册事务回滚使用。"""

        self._tools.pop(name, None)
        self._purposes.pop(name, None)

    def revoke(self, name: str) -> None:
        """§7.2 安全撤销：将工具标记为安全撤销并移出可执行集合（不再可调用，
        ``execute`` 返回不存在），同时记录到 ``_revoked`` 供 ContextCompiler 对
        仍声明该能力的已冻结 snapshot fail-closed。幂等，区别于 rollback
        ``unregister``（非安全变更，仅影响后续新 epoch）。"""

        self._revoked.add(name)
        self._tools.pop(name, None)
        self._purposes.pop(name, None)

    @property
    def revoked_tool_names(self) -> frozenset[str]:
        """§7.2 已安全撤销的工具名集合（供编译器 fail-closed 冻结 snapshot）。"""

        return frozenset(self._revoked)

    def purpose_of(self, name: str) -> str:
        return self._purposes.get(name, tool_purpose(name))

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
            for tool in sorted(self._visible_tools(), key=lambda item: item.name)
        ]

    def enable_progressive_disclosure(self) -> None:
        """Freeze current tools as the stable base; later registrations are deferred."""

        self._progressive_disclosure = True
        self._base_tool_names = set(self._tools)

    def disclose(self, query: str, *, limit: int = 8) -> list[Tool]:
        """Deterministically disclose bounded deferred tools matching a query."""

        keyword = query.strip().casefold()
        if not self._progressive_disclosure or not keyword or limit <= 0:
            return []
        candidates = [
            tool
            for name, tool in self._tools.items()
            if name not in self._base_tool_names
            and name not in self._disclosed_tool_names
            and (
                keyword in tool.name.casefold()
                or keyword in tool.description.casefold()
            )
        ]
        selected = sorted(candidates, key=lambda item: item.name)[:limit]
        self._disclosed_tool_names.update(item.name for item in selected)
        return selected

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        context: ToolExecutionContext | None = None,
    ) -> ToolResult:
        """执行指定工具。"""

        tool = self._tools.get(name)
        if tool is not None and self._progressive_disclosure:
            visible_names = self._base_tool_names | self._disclosed_tool_names
            if name not in visible_names:
                tool = None
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

    def _visible_tools(self) -> list[Tool]:
        if not self._progressive_disclosure:
            return list(self._tools.values())
        names = self._base_tool_names | self._disclosed_tool_names
        return [tool for name, tool in self._tools.items() if name in names]

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
