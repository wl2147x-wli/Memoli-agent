from __future__ import annotations

import asyncio
from pathlib import Path

from benchmarks.memory_retrieval import (
    FIXED_MEMORY_REGRESSION_CASES,
    run_fixed_regression,
    run_semantic_scale_benchmark,
)
from memoli_agent.agent.memory.hybrid import (
    FtsSearchLane,
    HybridMemoryRetriever,
    MetadataSearchLane,
    PatternSearchLane,
    SemanticSearchLane,
)
from memoli_agent.agent.memory.models import EvidenceRef, MemoryMutation
from memoli_agent.agent.memory.semantic import (
    DeterministicEmbedder,
    MemoryIndexWorker,
)
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore


def test_fixed_memory_regression_is_stable_and_bounded(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    for content in (
        "Python 依赖优先使用清华源下载",
        "核心代码使用中文注释",
        "长期记忆保存在 SQLite",
    ):
        store.append_claim(
            MemoryMutation(
                content,
                evidence=(EvidenceRef("fixture", content),),
            )
        )
    embedder = DeterministicEmbedder(dimensions=12)
    worker = MemoryIndexWorker(store, embedder, batch_size=10)
    retriever = HybridMemoryRetriever(
        store,
        fts_lane=FtsSearchLane(store),
        pattern_lane=PatternSearchLane(store),
        metadata_lane=MetadataSearchLane(store),
        semantic_lane=SemanticSearchLane(store, embedder),
    )

    async def scenario() -> None:
        await worker.tick()
        result = await run_fixed_regression(retriever)
        assert result.total == len(FIXED_MEMORY_REGRESSION_CASES)
        assert result.passed == result.total
        assert result.stable is True
        assert result.within_budget is True

    asyncio.run(scenario())


def test_semantic_scale_benchmark_reports_latency_and_size(tmp_path: Path) -> None:
    async def scenario() -> None:
        report = await run_semantic_scale_benchmark(
            tmp_path / "scale.db",
            sizes=(5, 10),
            query_runs=2,
            p95_threshold_ms=10_000,
        )
        assert [sample.item_count for sample in report.samples] == [5, 10]
        assert all(sample.p50_ms >= 0 for sample in report.samples)
        assert all(sample.p95_ms >= sample.p50_ms for sample in report.samples)
        assert all(sample.database_bytes > 0 for sample in report.samples)
        assert report.suggested_vector_extension_threshold is None

    asyncio.run(scenario())
