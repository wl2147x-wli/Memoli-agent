"""内置工具集合。

第六阶段提供一批最小可运行工具。第七阶段开始，memory 工具会接入
Markdown 长期记忆系统。
"""

from __future__ import annotations

import ast
import json
import operator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memoli_agent.agent.memory.models import EvidenceRef, MemoryScope
from memoli_agent.agent.memory.runtime import MemoryMutation, MemoryQuery, MemoryRuntime
from memoli_agent.agent.subagent.manager import SubAgentManager
from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.execution import current_tool_context


@dataclass(frozen=True, slots=True)
class TimeTool:
    """返回当前时间。"""

    name: str = "time"
    description: str = "获取当前本地时间和 UTC 时间。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """执行时间查询。"""

        local_now = datetime.now().astimezone()
        utc_now = datetime.now(UTC)
        return ToolResult(
            content=(
                f"本地时间：{local_now.isoformat()}\nUTC 时间：{utc_now.isoformat()}"
            ),
            metadata={"tool": self.name},
        )


@dataclass(frozen=True, slots=True)
class CalculatorTool:
    """安全计算基础数学表达式。"""

    name: str = "calculator"
    description: str = "计算基础数学表达式，支持加减乘除、幂、取余和括号。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "要计算的数学表达式，例如 1 + 2 * 3。",
                }
            },
            "required": ["expression"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """执行计算。"""

        expression = str(arguments.get("expression", "")).strip()
        if not expression:
            return ToolResult("缺少 expression 参数。", success=False)

        result = _safe_eval(expression)
        return ToolResult(
            content=str(result),
            metadata={"tool": self.name, "expression": expression},
        )


@dataclass(slots=True)
class MemoryWriteTool:
    """写入长期记忆。"""

    memory_runtime: MemoryRuntime | None
    name: str = "memory_write"
    description: str = "写入一条长期记忆，保存到 workspace/memory/MEMORY.md。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要写入的记忆内容。",
                }
            },
            "required": ["content"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """写入长期记忆。"""

        if self.memory_runtime is None:
            raw = json.dumps(
                {"status": "disabled", "hits": [], "reason": "memory-disabled"},
                ensure_ascii=False,
            )
            return ToolResult(
                raw,
                success=False,
                raw_content=raw,
                status="disabled",
                metadata={"tool": self.name, "disabled": True},
            )

        content = str(arguments.get("content", "")).strip()
        if not content:
            return ToolResult("缺少 content 参数。", success=False)

        item = await self.memory_runtime.mutate(
            MemoryMutation(
                content=content,
                source="tool",
                metadata={"tool": self.name},
            )
        )
        return ToolResult(
            "已写入长期记忆。",
            metadata={"tool": self.name, "timestamp": item.timestamp.isoformat()},
        )


@dataclass(slots=True)
class MemoryRecallTool:
    """检索长期记忆。"""

    memory_runtime: MemoryRuntime | None
    name: str = "memory_recall"
    description: str = "按关键词检索长期记忆。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "检索关键词。",
                },
                "types": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                "scope_kind": {"type": "string"},
                "scope_id": {"type": "string"},
                "statuses": {"type": "array", "items": {"type": "string"}},
                "max_sensitivity": {"type": "string"},
                "at_time": {
                    "type": "string",
                    "description": "可选 ISO-8601 时间，用于时态检索。",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """检索长期记忆。"""

        if self.memory_runtime is None:
            raw = json.dumps(
                {"status": "disabled", "hits": [], "reason": "memory-disabled"},
                ensure_ascii=False,
            )
            return ToolResult(
                raw,
                success=False,
                raw_content=raw,
                status="disabled",
                metadata={"tool": self.name, "disabled": True},
            )

        query = str(arguments.get("query", "")).strip().lower()
        if not query:
            return ToolResult("缺少 query 参数。", success=False)

        try:
            result = await self.memory_runtime.query(
                MemoryQuery(
                    query=query,
                    limit=min(20, max(1, int(arguments.get("limit", 5)))),
                    item_types=tuple(
                        arguments.get("types") or ("card", "claim", "episode")
                    ),
                    scope=MemoryScope(
                        str(arguments.get("scope_kind") or "user"),
                        str(arguments.get("scope_id") or "default"),
                    ),
                    statuses=tuple(arguments.get("statuses") or ("active", "frozen")),
                    max_sensitivity=str(arguments.get("max_sensitivity") or "private"),
                    at_time=(
                        datetime.fromisoformat(str(arguments["at_time"]))
                        if arguments.get("at_time")
                        else None
                    ),
                )
            )
        except Exception as exc:
            raw = json.dumps(
                {"status": "degraded", "hits": [], "reason": type(exc).__name__},
                ensure_ascii=False,
            )
            return ToolResult(
                raw,
                success=False,
                raw_content=raw,
                status="degraded",
                metadata={"tool": self.name, "degraded": True},
            )
        if not result.items:
            return ToolResult("没有找到相关长期记忆。", metadata={"tool": self.name})

        hits = [
            {
                "id": item.item_id,
                "type": item.item_type,
                "content": item.content,
                "status": item.status,
                "current": item.current,
                "reason": item.recall_reason,
                "evidence": [
                    {"kind": ref.kind, "ref_id": ref.ref_id} for ref in item.evidence
                ],
            }
            for item in result.items
        ]
        content = json.dumps(
            {
                "status": "degraded" if result.degraded else "success",
                "hits": hits,
                "candidate_count": result.candidate_count,
                "filtered_count": result.filtered_count,
                "reason": result.reason,
            },
            ensure_ascii=False,
        )
        return ToolResult(
            content=content,
            raw_content=content,
            metadata={
                "tool": self.name,
                "match_count": len(result.items),
                "degraded": result.degraded,
            },
        )


@dataclass(slots=True)
class MemoryManageTool:
    """带显式证据校验的个人记忆治理入口。"""

    memory_runtime: MemoryRuntime | None
    name: str = "memory_manage"
    description: str = "记住、纠正、冻结、删除、列出或导出个人记忆。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "remember",
                        "correct",
                        "freeze",
                        "forget",
                        "list",
                        "export",
                    ],
                },
                "content": {"type": "string"},
                "basis_quote": {
                    "type": "string",
                    "description": "remember/correct 时必须逐字来自当前用户消息。",
                },
                "entity_type": {"type": "string", "enum": ["claim", "card"]},
                "entity_id": {"type": "string"},
                "scope_kind": {"type": "string"},
                "scope_id": {"type": "string"},
                "max_sensitivity": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        if self.memory_runtime is None:
            return ToolResult(
                json.dumps({"status": "disabled", "hits": []}, ensure_ascii=False),
                success=False,
                status="disabled",
                metadata={"tool": self.name, "disabled": True},
            )
        store = self.memory_runtime.store
        action = str(arguments.get("action") or "")
        scope = MemoryScope(
            str(arguments.get("scope_kind") or "user"),
            str(arguments.get("scope_id") or "default"),
        )
        context = current_tool_context()
        if action in {"remember", "correct"}:
            content = str(arguments.get("content") or "").strip()
            basis = str(arguments.get("basis_quote") or "").strip()
            if (
                context is None
                or not content
                or not basis
                or basis not in context.user_content
            ):
                return ToolResult(
                    "正式记忆写入被拒绝：缺少当前用户消息中的显式依据。",
                    success=False,
                    status="rejected",
                    metadata={"tool": self.name, "error": "missing-explicit-basis"},
                )
            item = await self.memory_runtime.mutate(
                MemoryMutation(
                    content=content,
                    source="memory-manage",
                    scope=scope,
                    evidence=(EvidenceRef("message", context.user_message_id, basis),),
                    metadata={"message_id": context.user_message_id},
                )
            )
            if action == "correct" and arguments.get("entity_id"):
                old_id = str(arguments["entity_id"])
                store.set_status(
                    str(arguments.get("entity_type") or "claim"),
                    old_id,
                    "superseded",
                    context.user_message_id,
                )
                if str(arguments.get("entity_type") or "claim") == "claim":
                    store.link_claims(item.item_id, old_id, "corrects")
            return _json_tool_result(
                self.name, {"status": "success", "id": item.item_id}
            )
        if action in {"freeze", "forget"}:
            entity_id = str(arguments.get("entity_id") or "")
            if not entity_id:
                return ToolResult("缺少 entity_id。", success=False)
            store.set_status(
                str(arguments.get("entity_type") or "claim"),
                entity_id,
                "frozen" if action == "freeze" else "deleted",
                f"user:{context.user_message_id}" if context else "human",
            )
            return _json_tool_result(self.name, {"status": "success", "id": entity_id})
        if action == "list":
            items = store.list_items(scope)
            return _json_tool_result(
                self.name,
                {"status": "success", "items": [_item_summary(item) for item in items]},
            )
        if action == "export":
            items = store.export_items(
                scope,
                max_sensitivity=str(arguments.get("max_sensitivity") or "private"),
            )
            return _json_tool_result(self.name, {"status": "success", "items": items})
        return ToolResult("不支持的 action。", success=False)


@dataclass(frozen=True, slots=True)
class FilesystemReadTool:
    """读取 workspace 内的文本文件。"""

    workspace: Path
    name: str = "filesystem_read"
    description: str = "读取 workspace 目录内的文本文件。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对 workspace 的文件路径。",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """读取受限文件。"""

        raw_path = str(arguments.get("path", "")).strip()
        if not raw_path:
            return ToolResult("缺少 path 参数。", success=False)

        workspace_root = self.workspace.resolve()
        target = (workspace_root / raw_path).resolve()
        if target != workspace_root and workspace_root not in target.parents:
            return ToolResult("拒绝读取 workspace 外的文件。", success=False)

        if not target.exists() or not target.is_file():
            return ToolResult(f"文件不存在：{raw_path}", success=False)

        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return ToolResult("文件不是 UTF-8 文本。", success=False)

        return ToolResult(
            content=content,
            metadata={"tool": self.name, "path": str(target)},
        )


@dataclass(slots=True)
class LegacySpawnSubAgentTool:
    """创建子 agent 任务。"""

    subagent_manager: SubAgentManager | None
    name: str = "spawn_subagent"
    description: str = "委派一个本地子 agent 执行边界清晰的子任务。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "子 agent 需要完成的具体任务说明。",
                },
                "profile": {
                    "type": "string",
                    "description": "子 agent profile，可选 general、research、coding。",
                },
                "background": {
                    "type": "boolean",
                    "description": "是否后台执行。默认 false，表示同步等待结果。",
                },
                "parent_session_key": {
                    "type": "string",
                    "description": "主会话 key，可选，用于后台完成事件回流。",
                },
            },
            "required": ["instruction"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """执行子 agent 委派。"""

        if self.subagent_manager is None:
            return ToolResult("SubAgent 系统未启用。", success=False)

        instruction = str(arguments.get("instruction", "")).strip()
        if not instruction:
            return ToolResult("缺少 instruction 参数。", success=False)

        profile = str(arguments.get("profile") or "").strip()
        parent_session_key = str(arguments.get("parent_session_key") or "").strip()
        background = bool(arguments.get("background", False))

        if background:
            task_id = self.subagent_manager.spawn_background(
                instruction=instruction,
                profile_name=profile,
                parent_session_key=parent_session_key,
                metadata={"tool": self.name, "background": True},
            )
            return ToolResult(
                content=f"已创建后台子 agent 任务：{task_id}",
                metadata={"tool": self.name, "task_id": task_id, "background": True},
            )

        result = await self.subagent_manager.run_task(
            instruction=instruction,
            profile_name=profile,
            parent_session_key=parent_session_key,
            metadata={"tool": self.name, "background": False},
        )
        return ToolResult(
            content=result.content,
            success=result.success,
            metadata={
                "tool": self.name,
                "task_id": result.task_id,
                "profile": result.profile_name,
                "task_dir": str(result.task_dir),
            },
        )


@dataclass(slots=True)
class SpawnSubAgentTool:
    """创建结构化 SubAgent 委派任务。"""

    subagent_manager: SubAgentManager | None
    name: str = "spawn_subagent"
    description: str = "委派一个有明确目标、验收标准和依赖关系的本地子 Agent 任务。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "instruction": {"type": "string", "description": "具体任务目标。"},
                "profile": {
                    "type": "string",
                    "enum": ["general", "research", "coding"],
                },
                "background": {"type": "boolean"},
                "parent_session_key": {
                    "type": "string",
                    "description": "兼容参数；运行时优先使用当前会话。",
                },
                "acceptance_criteria": _string_array("可验证的完成标准。"),
                "constraints": _string_array("执行边界与限制。"),
                "confirmed_facts": _string_array("父 Agent 已确认的事实。"),
                "memory_refs": _string_array("允许读取的记忆引用。"),
                "artifact_refs": _string_array("允许读取的制品引用。"),
                "dependency_ids": _string_array("必须先完成的 task_id。"),
                "side_effecting": {"type": "boolean"},
                "max_iterations": {"type": "integer", "minimum": 1},
                "max_elapsed_seconds": {"type": "number", "exclusiveMinimum": 0},
                "depth": {"type": "integer", "minimum": 1},
            },
            "required": ["instruction"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        if self.subagent_manager is None:
            return ToolResult("SubAgent 系统未启用。", success=False)
        instruction = str(arguments.get("instruction") or "").strip()
        if not instruction:
            return ToolResult("缺少 instruction 参数。", success=False)
        context = current_tool_context()
        session_key = (
            context.session_key if context is not None else ""
        ) or str(arguments.get("parent_session_key") or "").strip()
        options: dict[str, Any] = {
            key: tuple(
                str(item) for item in arguments.get(key, []) if str(item).strip()
            )
            for key in (
                "acceptance_criteria",
                "constraints",
                "confirmed_facts",
                "memory_refs",
                "artifact_refs",
                "dependency_ids",
            )
        }
        options["side_effecting"] = bool(arguments.get("side_effecting", False))
        for key in ("max_iterations", "max_elapsed_seconds", "depth"):
            if arguments.get(key) is not None:
                options[key] = arguments[key]
        profile = str(arguments.get("profile") or "").strip()
        background = bool(arguments.get("background", False))
        try:
            if background:
                task_id = self.subagent_manager.spawn_background(
                    instruction,
                    profile,
                    session_key,
                    {"tool": self.name},
                    **options,
                )
                return ToolResult(
                    f"已创建后台子 Agent 任务：{task_id}",
                    metadata={
                        "tool": self.name,
                        "task_id": task_id,
                        "background": True,
                    },
                )
            result = await self.subagent_manager.run_task(
                instruction,
                profile,
                session_key,
                {"tool": self.name},
                **options,
            )
        except (ValueError, RuntimeError) as exc:
            return ToolResult(str(exc), success=False, metadata={"tool": self.name})
        return ToolResult(
            result.content,
            success=result.success,
            metadata={
                "tool": self.name,
                "task_id": result.task_id,
                "profile": result.profile_name,
                "status": result.status,
                "trace_id": result.trace_id,
                "task_dir": str(result.task_dir),
            },
        )


@dataclass(slots=True)
class ManageSubAgentTool:
    """查询、取消、恢复 SubAgent 任务或重建兼容导出。"""

    subagent_manager: SubAgentManager | None
    name: str = "manage_subagent"
    description: str = "按当前会话管理已持久化的子 Agent 任务。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "cancel", "resume", "regenerate"],
                },
                "task_id": {"type": "string"},
                "confirm_side_effects": {"type": "boolean"},
            },
            "required": ["action"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        if self.subagent_manager is None:
            return ToolResult("SubAgent 系统未启用。", success=False)
        action = str(arguments.get("action") or "").strip()
        task_id = str(arguments.get("task_id") or "").strip()
        context = current_tool_context()
        session_key = context.session_key if context is not None else ""
        try:
            if action == "list":
                payload: Any = [
                    self.subagent_manager.describe_task(task.task_id, session_key)
                    for task in self.subagent_manager.list_tasks(session_key)
                ]
            elif action == "get":
                task = self.subagent_manager.get_task(task_id, session_key)
                if task is None:
                    raise ValueError("任务不存在或不属于当前会话")
                payload = self.subagent_manager.describe_task(task.task_id, session_key)
            elif action == "cancel":
                task = await self.subagent_manager.cancel_task(
                    task_id, root_session_key=session_key
                )
                payload = self.subagent_manager.describe_task(task.task_id, session_key)
            elif action == "resume":
                task = self.subagent_manager.resume_task(
                    task_id,
                    root_session_key=session_key,
                    confirm_side_effects=bool(
                        arguments.get("confirm_side_effects", False)
                    ),
                )
                payload = self.subagent_manager.describe_task(task.task_id, session_key)
            elif action == "regenerate":
                if self.subagent_manager.get_task(task_id, session_key) is None:
                    raise ValueError("任务不存在或不属于当前会话")
                self.subagent_manager.regenerate_exports(task_id)
                payload = {"task_id": task_id, "regenerated": True}
            else:
                raise ValueError(f"不支持的 action：{action}")
        except (ValueError, RuntimeError) as exc:
            return ToolResult(str(exc), success=False, metadata={"tool": self.name})
        return ToolResult(
            json.dumps(payload, ensure_ascii=False, indent=2),
            metadata={"tool": self.name, "action": action},
        )


def _string_array(description: str) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "description": description}


def _task_view(task: Any) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "agent_id": task.agent_id,
        "profile": task.profile_name,
        "objective": task.objective,
        "status": task.status.value,
        "trace_id": task.trace_id,
        "result_summary": task.result_summary,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def _safe_eval(expression: str) -> int | float:
    """使用 AST 白名单计算数学表达式。"""

    node = ast.parse(expression, mode="eval")
    return _eval_node(node.body)


def _eval_node(node: ast.AST) -> int | float:
    """递归计算 AST 节点。"""

    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value

    if isinstance(node, ast.BinOp):
        operator_fn = _BINARY_OPERATORS.get(type(node.op))
        if operator_fn is None:
            raise ValueError("不支持的二元运算。")
        return operator_fn(_eval_node(node.left), _eval_node(node.right))

    if isinstance(node, ast.UnaryOp):
        operator_fn = _UNARY_OPERATORS.get(type(node.op))
        if operator_fn is None:
            raise ValueError("不支持的一元运算。")
        return operator_fn(_eval_node(node.operand))

    raise ValueError("表达式包含不支持的内容。")


def _json_tool_result(tool: str, payload: dict[str, Any]) -> ToolResult:
    raw = json.dumps(payload, ensure_ascii=False)
    return ToolResult(raw, raw_content=raw, metadata={"tool": tool})


def _item_summary(item: Any) -> dict[str, Any]:
    return {
        "id": item.item_id,
        "type": item.item_type,
        "content": item.content,
        "status": item.status,
    }
