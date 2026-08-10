"""记忆系统三层评测指标的最小、无第三方依赖实现。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BenchmarkLayer = Literal["generation", "retrieval", "usage"]


@dataclass(frozen=True, slots=True)
class MemoryBenchmarkCase:
    """覆盖基础回忆、冲突/时序和主动关联的固定用例合同。"""

    case_id: str
    layer: BenchmarkLayer
    category: str
    expected_ids: frozenset[str]


DEFAULT_CASES = (
    MemoryBenchmarkCase("basic-recall", "retrieval", "basic", frozenset({"c1"})),
    MemoryBenchmarkCase(
        "multi-session-conflict", "retrieval", "conflict-temporal", frozenset({"c2"})
    ),
    MemoryBenchmarkCase(
        "proactive-association", "usage", "proactive", frozenset({"c3"})
    ),
    MemoryBenchmarkCase(
        "explicit-generation", "generation", "generation", frozenset({"c4"})
    ),
)


@dataclass(frozen=True, slots=True)
class MemoryMetrics:
    recall_at_k: float
    precision_at_k: float
    current_version_hit_rate: float
    evidence_coverage: float
    status_accuracy: float
    injected_chars: int
    latency_ms: float


@dataclass(frozen=True, slots=True)
class LayerEvaluation:
    """分层报告，防止端到端总分掩盖生成、召回或使用瓶颈。"""

    generation: MemoryMetrics
    retrieval: MemoryMetrics
    usage: MemoryMetrics


def retrieval_metrics(
    expected_ids: set[str],
    returned_ids: list[str],
    *,
    current_flags: list[bool],
    evidence_flags: list[bool],
    status_correct: list[bool],
    injected_chars: int,
    latency_ms: float,
) -> MemoryMetrics:
    """分别测生成/召回/使用时可复用这些原子指标，避免只看端到端总分。"""

    hits = sum(item_id in expected_ids for item_id in returned_ids)
    return MemoryMetrics(
        recall_at_k=hits / max(1, len(expected_ids)),
        precision_at_k=hits / max(1, len(returned_ids)),
        current_version_hit_rate=sum(current_flags) / max(1, len(current_flags)),
        evidence_coverage=sum(evidence_flags) / max(1, len(evidence_flags)),
        status_accuracy=sum(status_correct) / max(1, len(status_correct)),
        injected_chars=injected_chars,
        latency_ms=latency_ms,
    )
