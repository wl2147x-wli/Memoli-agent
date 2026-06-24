"""记忆系统装配模块。

第七阶段只支持 Markdown 文件记忆引擎。
"""

from __future__ import annotations

from pathlib import Path

from memoli_agent.agent.memory.retriever import KeywordMemoryRetriever
from memoli_agent.agent.memory.runtime import MemoryRuntime
from memoli_agent.agent.memory.store import MarkdownMemoryStore
from memoli_agent.bootstrap.config import AppConfig


def build_memory_runtime(config: AppConfig) -> MemoryRuntime | None:
    """根据配置创建记忆 runtime。"""

    if not config.memory.enabled:
        return None

    store = MarkdownMemoryStore(Path(config.memory.path))
    store.ensure_files()
    retriever = KeywordMemoryRetriever(store)
    return MemoryRuntime(store=store, retriever=retriever)
