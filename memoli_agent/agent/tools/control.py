"""长任务状态和用户控制工具。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.execution import current_tool_context
from memoli_agent.agent.working.models import (
    CheckpointPatch,
    RuntimeStatus,
    WorkingCheckpoint,
    WorkingStateRenderResult,
)
from memoli_agent.agent.working.repository import (
    RevisionConflictError,
    WorkingStateRepository,
)


@dataclass(frozen=True, slots=True)
class LongTermUpdateRequest:
    """等待后续离线流程消费的长期整理请求。"""

    request_id: str
    trace_id: str
    session_key: str
    status: str = "pending"
    created_at: str = ""


@dataclass(slots=True)
class WorkingStateStore:
    """组合持久化软 checkpoint 与代码投影硬状态。"""

    repository: WorkingStateRepository = field(default_factory=WorkingStateRepository)
    max_chars: int = 4_000
    runtime_statuses: dict[str, RuntimeStatus] = field(default_factory=dict)
    requests: dict[str, LongTermUpdateRequest] = field(default_factory=dict)

    def update_checkpoint(
        self,
        session_key: str,
        key_info: str,
        related_sop: str,
        *,
        expected_revision: int | None = None,
        objective: str | None = None,
        current_step: str | None = None,
        next_action: str | None = None,
        constraints: tuple[str, ...] | None = None,
        decisions: tuple[str, ...] | None = None,
        artifacts: tuple[str, ...] | None = None,
    ) -> WorkingCheckpoint:
        """有界替换语义 checkpoint，并由 repository 分配 revision。"""

        return self.repository.patch(
            session_key,
            CheckpointPatch(
                expected_revision=expected_revision,
                objective=objective,
                current_step=current_step,
                next_action=next_action,
                key_info=key_info,
                constraints=constraints,
                decisions=decisions,
                artifacts=artifacts,
                related_sop=related_sop,
            ),
        )

    def begin_turn(
        self,
        session_key: str,
        *,
        max_iterations: int,
        max_elapsed_seconds: float,
    ) -> None:
        self.repository.mark_stale_except(session_key)
        self.runtime_statuses[session_key] = RuntimeStatus(
            max_iterations=max_iterations,
            max_elapsed_seconds=max_elapsed_seconds,
        )

    def project_iteration(
        self,
        session_key: str,
        *,
        iteration: int,
        elapsed_seconds: float,
        last_tool: str | None = None,
        last_tool_status: str | None = None,
        artifacts: tuple[str, ...] = (),
    ) -> RuntimeStatus:
        """仅接收 Runtime 已验证的数据，避免模型自报成功。"""

        previous = self.runtime_statuses.get(session_key, RuntimeStatus())
        status = RuntimeStatus(
            iteration=iteration,
            max_iterations=previous.max_iterations,
            elapsed_seconds=max(0.0, elapsed_seconds),
            max_elapsed_seconds=previous.max_elapsed_seconds,
            last_tool=last_tool or previous.last_tool,
            last_tool_status=last_tool_status or previous.last_tool_status,
            completed_steps=previous.completed_steps,
            artifacts=tuple(dict.fromkeys((*previous.artifacts, *artifacts))),
        )
        self.runtime_statuses[session_key] = status
        return status

    def render_status(self, session_key: str) -> WorkingStateRenderResult:
        checkpoint = self.repository.get(session_key)
        hard = self.runtime_statuses.get(session_key, RuntimeStatus())
        revision = checkpoint.revision if checkpoint else 0
        lines = [
            f'<agent_status revision="{revision}" trust="runtime">',
            "<runtime_status>",
            f"iteration: {hard.iteration}/{hard.max_iterations or 'unavailable'}",
            f"elapsed_seconds: {hard.elapsed_seconds:.3f}",
            f"last_tool: {hard.last_tool}",
            f"last_tool_status: {hard.last_tool_status}",
            "artifacts: " + (", ".join(hard.artifacts) or "unavailable"),
            "</runtime_status>",
            '<working_checkpoint trust="agent">',
        ]
        if checkpoint is None:
            lines.append("unavailable")
        else:
            for label, value in (
                ("objective", checkpoint.objective),
                ("current_step", checkpoint.current_step),
                ("next_action", checkpoint.next_action),
                ("key_info", checkpoint.key_info),
                ("related_sop", checkpoint.related_sop),
            ):
                lines.append(f"{label}: {value or 'unavailable'}")
            lines.append(f"status: {checkpoint.status}")
            lines.append(f"stale: {str(checkpoint.stale).lower()}")
        lines.extend(["</working_checkpoint>", "</agent_status>"])
        content = "\n".join(lines)
        truncated = len(content) > self.max_chars
        if truncated:
            content = content[: max(0, self.max_chars - 16)] + "\n...[TRUNCATED]"
        return WorkingStateRenderResult(
            content=content,
            revision=revision,
            truncated=truncated,
            metadata={"session_key": session_key},
        )

    def close(self) -> None:
        self.repository.close()

    def get_checkpoint(self, session_key: str) -> WorkingCheckpoint | None:
        return self.repository.get(session_key)

    def render_checkpoint(self, session_key: str) -> str:
        """兼容旧接口；新 Agent Loop 使用 render_status。"""

        checkpoint = self.repository.get(session_key)
        if checkpoint is None:
            return ""
        parts = ["<working_checkpoint>", checkpoint.key_info]
        if checkpoint.related_sop:
            parts.append(f"相关 SOP：{checkpoint.related_sop}")
        parts.append("</working_checkpoint>")
        return "\n".join(parts)

    def create_request(
        self, trace_id: str, session_key: str, tool_call_id: str
    ) -> LongTermUpdateRequest:
        source = f"{trace_id}:{tool_call_id}".encode()
        request_id = hashlib.sha256(source).hexdigest()[:24]
        request = self.requests.get(request_id)
        if request is None:
            request = LongTermUpdateRequest(
                request_id=request_id,
                trace_id=trace_id,
                session_key=session_key,
                created_at=datetime.now(UTC).isoformat(),
            )
            self.requests[request_id] = request
        return request


@dataclass(slots=True)
class UpdateWorkingCheckpointTool:
    state: WorkingStateStore
    name: str = "update_working_checkpoint"
    description: str = (
        "更新当前任务的短期工作便笺。用于长任务早期/中期和切换子任务前，"
        "不写入长期记忆。"
    )
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "key_info": {
                    "type": "string",
                    "description": "替换当前便笺的关键约束、发现、进度和下一步。",
                },
                "related_sop": {
                    "type": "string",
                    "description": "相关 SOP 或 Skill 名称。",
                },
                "expected_revision": {
                    "type": "integer",
                    "description": "可选；用于阻止过期 checkpoint 覆盖新版本。",
                },
                "objective": {"type": "string"},
                "current_step": {"type": "string"},
                "next_action": {"type": "string"},
                "constraints": {"type": "array", "items": {"type": "string"}},
                "decisions": {"type": "array", "items": {"type": "string"}},
                "artifacts": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["key_info"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        context = current_tool_context()
        key_info = arguments.get("key_info")
        if context is None:
            return _error(self.name, "缺少工具执行上下文。")
        if not isinstance(key_info, str) or not key_info.strip():
            return _error(self.name, "key_info 不能为空。")
        try:
            checkpoint = self.state.update_checkpoint(
                context.session_key,
                key_info,
                str(arguments.get("related_sop") or ""),
                expected_revision=arguments.get("expected_revision"),
                objective=_optional_text(arguments, "objective"),
                current_step=_optional_text(arguments, "current_step"),
                next_action=_optional_text(arguments, "next_action"),
                constraints=_optional_text_tuple(arguments, "constraints"),
                decisions=_optional_text_tuple(arguments, "decisions"),
                artifacts=_optional_text_tuple(arguments, "artifacts"),
            )
        except RevisionConflictError as exc:
            return _error(self.name, str(exc))
        raw = json.dumps(
            {
                "status": "success",
                "session_key": context.session_key,
                "updated_at": checkpoint.updated_at,
                "revision": checkpoint.revision,
            },
            ensure_ascii=False,
        )
        return ToolResult(
            raw,
            raw_content=raw,
            metadata={"tool": self.name, "revision": checkpoint.revision},
        )


@dataclass(frozen=True, slots=True)
class AskUserTool:
    name: str = "ask_user"
    description: str = (
        "需要用户决策、补充信息或授权时暂停任务并提问；多个问题应合并在一次调用中。"
    )
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "要向用户提出的问题。"},
                "candidates": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "单个问题的可选候选项。",
                },
            },
            "required": ["question"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        question = arguments.get("question")
        candidates = arguments.get("candidates", [])
        if not isinstance(question, str) or not question.strip():
            return _error(self.name, "question 不能为空。")
        if not isinstance(candidates, list) or not all(
            isinstance(item, str) for item in candidates
        ):
            return _error(self.name, "candidates 必须是字符串数组。")
        content = question.strip()
        if candidates:
            content += "\n" + "\n".join(
                f"{index}. {candidate}"
                for index, candidate in enumerate(candidates, start=1)
            )
        return ToolResult(
            content,
            raw_content=json.dumps(
                {"question": question.strip(), "candidates": candidates},
                ensure_ascii=False,
            ),
            status="needs-user",
            metadata={
                "tool": self.name,
                "needs_user": True,
                "candidates": candidates,
            },
        )


@dataclass(slots=True)
class StartLongTermUpdateTool:
    state: WorkingStateStore
    name: str = "start_long_term_update"
    description: str = (
        "记录一个待处理的长期经验整理请求；当前调用不会自动更新记忆、"
        "Prompt、Skill 或模型。"
    )
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        context = current_tool_context()
        if context is None:
            return _error(self.name, "缺少工具执行上下文。")
        request = self.state.create_request(
            context.trace_id, context.session_key, context.tool_call_id
        )
        raw = json.dumps(
            {
                "request_id": request.request_id,
                "trace_id": request.trace_id,
                "status": request.status,
            },
            ensure_ascii=False,
        )
        return ToolResult(
            raw,
            raw_content=raw,
            status="pending",
            metadata={"tool": self.name, "request_id": request.request_id},
        )


def _error(tool: str, message: str) -> ToolResult:
    raw = json.dumps({"status": "error", "message": message}, ensure_ascii=False)
    return ToolResult(
        raw,
        success=False,
        raw_content=raw,
        status="error",
        metadata={"tool": tool, "error": "ValueError"},
    )


def _optional_text(arguments: dict[str, Any], name: str) -> str | None:
    value = arguments.get(name)
    return str(value) if value is not None else None


def _optional_text_tuple(
    arguments: dict[str, Any], name: str
) -> tuple[str, ...] | None:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{name} 必须是字符串数组。")
    return tuple(value)
