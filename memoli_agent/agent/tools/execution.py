"""工具执行共享边界。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """不暴露给模型的单次工具调用上下文。"""

    trace_id: str
    session_key: str
    tool_call_id: str
    user_message_id: str = ""
    user_content: str = ""
    session_instance_id: str = ""
    span_id: str = ""


_CURRENT_CONTEXT: ContextVar[ToolExecutionContext | None] = ContextVar(
    "memoli_tool_execution_context", default=None
)


@contextmanager
def tool_context(context: ToolExecutionContext | None) -> Iterator[None]:
    """在一次工具执行期间绑定上下文，并确保执行后恢复。"""

    token = _CURRENT_CONTEXT.set(context)
    try:
        yield
    finally:
        _CURRENT_CONTEXT.reset(token)


def current_tool_context() -> ToolExecutionContext | None:
    """返回当前工具上下文。"""

    return _CURRENT_CONTEXT.get()


@dataclass(frozen=True, slots=True)
class WorkspacePathResolver:
    """把工具路径限制在单一 workspace 中。"""

    workspace: Path

    @property
    def root(self) -> Path:
        return self.workspace.resolve()

    def resolve(self, raw_path: str, *, must_exist: bool = False) -> Path:
        """解析路径并拒绝通过绝对路径、符号链接或 junction 越界。"""

        if not raw_path.strip():
            raise ValueError("缺少 path 参数。")
        requested = Path(raw_path)
        candidate = requested if requested.is_absolute() else self.root / requested
        target = candidate.resolve(strict=False)
        if target != self.root and self.root not in target.parents:
            raise PermissionError("拒绝访问 workspace 外的路径。")
        if must_exist and not target.exists():
            raise FileNotFoundError(f"目标不存在：{raw_path}")
        return target

    def existing_file(self, raw_path: str) -> Path:
        """解析一个已经存在的普通文件。"""

        target = self.resolve(raw_path, must_exist=True)
        if not target.is_file():
            raise ValueError(f"目标不是普通文件：{raw_path}")
        return target

    def writable_file(self, raw_path: str) -> Path:
        """解析可写文件；父目录必须已经存在且仍位于 workspace。"""

        target = self.resolve(raw_path)
        if target == self.root:
            raise ValueError("workspace 根目录不能作为文件写入。")
        parent = target.parent.resolve(strict=True)
        if parent != self.root and self.root not in parent.parents:
            raise PermissionError("拒绝写入 workspace 外的路径。")
        if not parent.is_dir():
            raise ValueError("目标父路径不是目录。")
        if target.exists() and not target.is_file():
            raise ValueError("目标不是普通文件。")
        return target


def bound_text(content: str, max_chars: int) -> tuple[str, bool]:
    """保留头部并用明确标记裁剪模型可见文本。"""

    if len(content) <= max_chars:
        return content, False
    marker = "\n...[TRUNCATED]"
    if max_chars <= len(marker):
        return marker[:max_chars], True
    keep = max(0, max_chars - len(marker))
    return content[:keep] + marker, True
