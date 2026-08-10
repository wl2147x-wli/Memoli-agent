"""无反馈学习的固定记忆回归集与 SQLite 精确向量性能基准。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from memoli_agent.agent.memory.hybrid import (
    HybridMemoryRetriever,
    KeywordSearchLane,
    MetadataSearchLane,
    SemanticSearchLane,
)
from memoli_agent.agent.memory.models import EvidenceRef, MemoryMutation, MemoryQuery
from memoli_agent.agent.memory.semantic import (
    DeterministicEmbedder,
    MemoryIndexWorker,
)
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore


@dataclass(frozen=True, slots=True)
class MemoryRegressionCase:
    query: str
    expected_type: str
    expected_text: str
    max_chars: int = 200


FIXED_MEMORY_REGRESSION_CASES = (
    MemoryRegressionCase("依赖从哪里下载", "claim", "清华源"),
    MemoryRegressionCase("代码注释语言", "claim", "中文注释"),
    MemoryRegressionCase("长期记忆存储", "claim", "SQLite"),
)


@dataclass(frozen=True, slots=True)
class MemoryRegressionResult:
    total: int
    passed: int
    stable: bool
    within_budget: bool


async def run_fixed_regression(
    retriever: HybridMemoryRetriever,
    cases: tuple[MemoryRegressionCase, ...] = FIXED_MEMORY_REGRESSION_CASES,
) -> MemoryRegressionResult:
    passed = 0
    stable = True
    within_budget = True
    for case in cases:
        request = MemoryQuery(case.query, max_chars=case.max_chars)
        first = await retriever.query(request)
        second = await retriever.query(request)
        stable = stable and [item.item_id for item in first.items] == [
            item.item_id for item in second.items
        ]
        within_budget = within_budget and first.injected_chars <= case.max_chars
        if any(
            item.item_type == case.expected_type
            and case.expected_text in item.content
            for item in first.items
        ):
            passed += 1
    return MemoryRegressionResult(len(cases), passed, stable, within_budget)


@dataclass(frozen=True, slots=True)
class SemanticScaleSample:
    item_count: int
    p50_ms: float
    p95_ms: float
    database_bytes: int


@dataclass(frozen=True, slots=True)
class SemanticScaleReport:
    samples: tuple[SemanticScaleSample, ...]
    suggested_vector_extension_threshold: int | None


async def run_semantic_scale_benchmark(
    database: Path,
    *,
    sizes: tuple[int, ...] = (100, 500, 1_000),
    query_runs: int = 20,
    p95_threshold_ms: float = 100.0,
) -> SemanticScaleReport:
    """在全新数据库上测量精确扫描；不会读取或覆盖用户记忆。"""

    if database.exists():
        raise FileExistsError(f"基准数据库已存在：{database}")
    if not sizes or any(size <= 0 for size in sizes) or tuple(sorted(sizes)) != sizes:
        raise ValueError("sizes 必须是严格递增的正整数。")
    store = SQLiteMemoryStore(database)
    embedder = DeterministicEmbedder(dimensions=32)
    worker = MemoryIndexWorker(store, embedder, batch_size=64)
    retriever = HybridMemoryRetriever(
        store,
        KeywordSearchLane(store),
        MetadataSearchLane(store),
        SemanticSearchLane(store, embedder, candidate_limit=max(sizes)),
        candidate_limit=max(sizes),
    )
    samples: list[SemanticScaleSample] = []
    created = 0
    try:
        for target in sizes:
            while created < target:
                store.append_claim(
                    MemoryMutation(
                        f"基准记忆 {created}：项目 {created % 17} 使用 SQLite",
                        evidence=(EvidenceRef("benchmark", str(created)),),
                    )
                )
                created += 1
            while (await worker.tick()).processed:
                pass
            durations: list[float] = []
            for run in range(max(1, query_runs)):
                started = time.perf_counter()
                await retriever.query(MemoryQuery(f"项目 {run % 17} 的存储"))
                durations.append((time.perf_counter() - started) * 1_000)
            durations.sort()
            samples.append(
                SemanticScaleSample(
                    target,
                    _percentile(durations, 0.50),
                    _percentile(durations, 0.95),
                    database.stat().st_size,
                )
            )
    finally:
        store.close()
    threshold = next(
        (sample.item_count for sample in samples if sample.p95_ms > p95_threshold_ms),
        None,
    )
    return SemanticScaleReport(tuple(samples), threshold)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, round((len(values) - 1) * percentile)))
    return values[index]
