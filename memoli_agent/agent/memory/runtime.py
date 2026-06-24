"""记忆 runtime。

MemoryRuntime 是长期记忆系统的对外入口：

- query：按关键词检索长期记忆。
- mutate：写入长期事实记忆。
- render_prompt_block：把检索结果渲染为可注入 prompt 的中文块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class MemoryItem:
    """一条长期记忆。"""

    content: str
    source: str
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    """记忆查询请求。"""

    query: str
    limit: int = 5


@dataclass(frozen=True, slots=True)
class MemoryQueryResult:
    """记忆查询结果。"""

    items: list[MemoryItem]


@dataclass(frozen=True, slots=True)
class MemoryMutation:
    """记忆写入请求。"""

    content: str
    source: str = "manual"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemoryRuntime:
    """长期记忆运行时。"""

    store: Any
    retriever: Any

    async def query(self, request: MemoryQuery) -> MemoryQueryResult:
        """按关键词查询长期记忆。"""

        return self.retriever.query(request)

    async def mutate(self, request: MemoryMutation) -> MemoryItem:
        """写入一条长期事实记忆。"""

        return self.store.append_memory(
            content=request.content,
            source=request.source,
            metadata=request.metadata,
        )

    def render_prompt_block(self, result: MemoryQueryResult) -> str:
        """把检索结果渲染成 prompt block。"""

        if not result.items:
            return ""

        lines = ["相关长期记忆："]
        for item in result.items:
            lines.append(f"- {item.content}")
        return "\n".join(lines)
