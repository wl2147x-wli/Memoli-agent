"""工具基类。

第六阶段定义最小工具协议。工具通过 JSON schema 暴露给模型，
执行结果统一包装成 ToolResult，避免工具异常直接打断主 agent。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeAlias


ToolSchema: TypeAlias = dict[str, Any]


class ToolError(RuntimeError):
    """工具执行失败时使用的异常。"""


@dataclass(frozen=True, slots=True)
class ToolResult:
    """工具执行结果。"""

    content: str
    success: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    """工具协议。"""

    name: str
    description: str
    parameters: ToolSchema

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """执行工具并返回结果。"""

        ...
