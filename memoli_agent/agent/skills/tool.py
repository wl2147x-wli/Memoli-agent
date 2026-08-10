"""模型可见的唯一 Skill 工具。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from memoli_agent.agent.skills.runtime import SkillRuntime
from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.execution import current_tool_context
from memoli_agent.agent.trajectory import (
    NewTrajectoryEvent,
    TrajectoryError,
    TrajectoryStore,
)


@dataclass(frozen=True, slots=True)
class SkillLoadTool:
    """加载当前会话已绑定的 Skill 正文或参考文件，不执行其中脚本。"""

    runtime: SkillRuntime
    tool_names_provider: Callable[[], set[str]]
    mcp_names_provider: Callable[[], set[str]] = field(default=lambda: set())
    trajectory_store: TrajectoryStore | None = None

    @property
    def name(self) -> str:
        return "skill_load"

    @property
    def description(self) -> str:
        return (
            "读取当前会话可见的版本化 Skill 正文或其 reference；"
            "不会执行脚本或提升权限。"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Catalog 中的 Skill 名称"},
                "reference": {
                    "type": "string",
                    "description": "可选的 references/ 或 templates/ 包内相对路径",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        }

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        context = current_tool_context()
        unknown_arguments = sorted(set(arguments) - {"name", "reference"})
        raw_name = arguments.get("name", "")
        invalid_types = not isinstance(raw_name, str)
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        reference_value = arguments.get("reference")
        invalid_types = invalid_types or (
            reference_value is not None and not isinstance(reference_value, str)
        )
        reference = (
            str(reference_value).strip() if reference_value is not None else None
        )
        await self._record(
            "skill_load_requested",
            {
                "name": name,
                "reference": reference or "",
                "session_instance_id": context.session_instance_id if context else "",
            },
        )
        if unknown_arguments or invalid_types:
            outcome = None
            result = ToolResult(
                content="skill_load 包含未知参数。",
                success=False,
                status="denied",
                metadata={
                    "skill_name": name,
                    "unknown_arguments": unknown_arguments,
                    "rejection_reason": "invalid-arguments",
                    "error": "SkillLoadRejected",
                },
            )
        elif context is None or not context.session_instance_id:
            outcome = None
            result = ToolResult(
                content="缺少 Skill 会话快照上下文。",
                success=False,
                status="denied",
                metadata={
                    "skill_name": name,
                    "rejection_reason": "missing-session-context",
                    "error": "SkillLoadRejected",
                },
            )
        elif not name:
            outcome = None
            result = ToolResult(
                content="skill_load 缺少 name。",
                success=False,
                status="denied",
                metadata={
                    "skill_name": "",
                    "rejection_reason": "invalid-name",
                    "error": "SkillLoadRejected",
                },
            )
        else:
            outcome = self.runtime.load(
                session_instance_id=context.session_instance_id,
                name=name,
                reference=reference,
                tools=self.tool_names_provider(),
                mcp_servers=self.mcp_names_provider(),
            )
            result = ToolResult(
                content=outcome.content,
                raw_content=outcome.raw_content,
                success=outcome.success,
                status=outcome.status,
                metadata={
                    **outcome.metadata,
                    "session_instance_id": context.session_instance_id,
                },
            )
        if context is not None:
            result = replace(
                result,
                metadata={
                    **result.metadata,
                    "session_instance_id": context.session_instance_id,
                },
            )
        await self._record(
            "skill_loaded" if result.success else "skill_load_rejected",
            {
                "name": name,
                "reference": reference or "",
                "success": result.success,
                **result.metadata,
            },
        )
        return result

    async def _record(self, event_type: str, payload: dict[str, Any]) -> None:
        context = current_tool_context()
        if self.trajectory_store is None or context is None or not context.trace_id:
            return
        try:
            await self.trajectory_store.record(
                NewTrajectoryEvent(
                    trace_id=context.trace_id,
                    span_id=context.span_id or None,
                    event_type=event_type,
                    payload={"tool_call_id": context.tool_call_id, **payload},
                )
            )
        except TrajectoryError:
            # Skill 内容加载不因可观测性支路失败而改变结果。
            return
