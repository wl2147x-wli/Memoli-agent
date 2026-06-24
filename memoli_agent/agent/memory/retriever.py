"""记忆检索模块。

第七阶段使用关键词匹配，不引入 embedding、rerank 或向量库。
"""

from __future__ import annotations

from dataclasses import dataclass

from memoli_agent.agent.memory.runtime import MemoryQuery, MemoryQueryResult
from memoli_agent.agent.memory.store import MarkdownMemoryStore


@dataclass(frozen=True, slots=True)
class KeywordMemoryRetriever:
    """基于关键词的记忆检索器。"""

    store: MarkdownMemoryStore

    def query(self, request: MemoryQuery) -> MemoryQueryResult:
        """按关键词检索长期记忆。"""

        query = request.query.strip().lower()
        if not query:
            return MemoryQueryResult(items=[])

        keywords = _split_keywords(query)
        matches = []
        for item in self.store.load_memory_items():
            content_lower = item.content.lower()
            if any(keyword in content_lower for keyword in keywords):
                matches.append(item)

        return MemoryQueryResult(items=matches[: request.limit])


def _split_keywords(query: str) -> list[str]:
    """把查询拆成简单关键词。"""

    normalized = query.replace("，", " ").replace("。", " ")
    keywords = [part.strip() for part in normalized.split() if part.strip()]
    return keywords or [query]
