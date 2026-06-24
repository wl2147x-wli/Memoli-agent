"""记忆沉淀模块。

第七阶段只做保守沉淀：把每轮对话流水追加到 HISTORY.md。
不会自动总结成长期事实，避免误记。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memoli_agent.agent.memory.store import MarkdownMemoryStore


@dataclass(frozen=True, slots=True)
class MemoryConsolidator:
    """最小记忆沉淀器。"""

    store: MarkdownMemoryStore

    async def record_turn(
        self,
        user_content: str,
        assistant_content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """记录一轮对话流水。"""

        self.store.append_history(
            user_content=user_content,
            assistant_content=assistant_content,
            metadata=metadata,
        )
