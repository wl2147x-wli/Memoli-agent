"""内置工具集合。

第六阶段提供一批最小可运行工具。第七阶段开始，memory 工具会接入
Markdown 长期记忆系统。
"""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memoli_agent.agent.memory.runtime import MemoryMutation, MemoryQuery, MemoryRuntime
from memoli_agent.agent.subagent.manager import SubAgentManager
from memoli_agent.agent.tools.base import ToolResult


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
        utc_now = datetime.now(timezone.utc)
        return ToolResult(
            content=f"本地时间：{local_now.isoformat()}\nUTC 时间：{utc_now.isoformat()}",
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
            return ToolResult("记忆系统未启用。", success=False)

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
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """检索长期记忆。"""

        if self.memory_runtime is None:
            return ToolResult("记忆系统未启用。", success=False)

        query = str(arguments.get("query", "")).strip().lower()
        if not query:
            return ToolResult("缺少 query 参数。", success=False)

        result = await self.memory_runtime.query(MemoryQuery(query=query, limit=5))
        if not result.items:
            return ToolResult("没有找到相关长期记忆。", metadata={"tool": self.name})

        return ToolResult(
            content="\n".join(item.content for item in result.items),
            metadata={"tool": self.name, "match_count": len(result.items)},
        )


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
class SpawnSubAgentTool:
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
