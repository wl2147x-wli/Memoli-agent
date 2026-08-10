"""工具协议与统一结果。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeAlias

ToolSchema: TypeAlias = dict[str, Any]


class ToolError(RuntimeError):
    """工具执行失败时使用的异常。"""


@dataclass(frozen=True, slots=True)
class ToolResult:
    """工具执行结果。

    ``content`` 是返回模型的有界内容，``raw_content`` 是写入本地轨迹的
    完整可观察结果。两者分离后，裁剪上下文不会丢失后续处理所需的事实。
    """

    content: str
    success: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_content: str | None = None
    status: str = "success"

    @property
    def effective_status(self) -> str:
        """兼容旧工具：失败结果未显式给状态时统一视为 error。"""

        if not self.success and self.status == "success":
            return "error"
        return self.status


class Tool(Protocol):
    """工具协议。"""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def parameters(self) -> ToolSchema: ...

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """执行工具并返回结果。"""

        ...
