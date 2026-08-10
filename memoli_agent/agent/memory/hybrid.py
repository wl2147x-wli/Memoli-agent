"""关键词、语义和元数据三路候选的确定性融合。"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from memoli_agent.agent.memory.models import (
    MemoryItem,
    MemoryQuery,
    MemoryQueryResult,
)
from memoli_agent.agent.memory.semantic import (
    Embedder,
    cosine_similarity,
    decode_vector,
)
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore


@dataclass(frozen=True, slots=True)
class KeywordSearchLane:
    store: SQLiteMemoryStore
    name: str = "keyword"

    def search(self, request: MemoryQuery, limit: int) -> tuple[list[MemoryItem], bool]:
        expanded = replace(
            request,
            limit=limit,
            card_limit=limit,
            claim_limit=limit,
            episode_limit=limit,
        )
        result = self.store.search(expanded)
        return result.items, result.degraded


@dataclass(frozen=True, slots=True)
class MetadataSearchLane:
    store: SQLiteMemoryStore
    name: str = "metadata"

    def search(self, request: MemoryQuery, limit: int) -> list[MemoryItem]:
        return self.store.metadata_candidates(request, limit)


@dataclass(frozen=True, slots=True)
class SemanticSearchLane:
    store: SQLiteMemoryStore
    embedder: Embedder
    candidate_limit: int = 200
    name: str = "semantic"

    async def search(self, request: MemoryQuery, limit: int) -> list[MemoryItem]:
        vectors = await self.embedder.embed((request.semantic_text,))
        query_vector = vectors[0]
        rows = self.store.ready_semantic_rows(
            request,
            model=self.embedder.model,
            version=self.embedder.version,
            dimensions=self.embedder.dimensions,
            limit=min(self.candidate_limit, max(limit * 8, limit)),
        )
        scored = [
            (
                cosine_similarity(
                    query_vector,
                    decode_vector(blob, self.embedder.dimensions),
                ),
                item,
            )
            for item, blob in rows
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1].item_id))
        return [item for _, item in scored[:limit]]


@dataclass(frozen=True, slots=True)
class HybridMemoryRetriever:
    store: SQLiteMemoryStore
    keyword_lane: KeywordSearchLane
    metadata_lane: MetadataSearchLane
    semantic_lane: SemanticSearchLane | None = None
    rrf_k: int = 60
    lane_weights: dict[str, float] = field(
        default_factory=lambda: {"keyword": 1.0, "semantic": 1.0, "metadata": 0.5}
    )
    candidate_limit: int = 50

    async def query(self, request: MemoryQuery) -> MemoryQueryResult:
        if not request.query.strip():
            return MemoryQueryResult(
                [], query_context_fields=request.context_fields, reason="empty-query"
            )
        lanes: dict[str, list[MemoryItem]] = {}
        degraded: list[str] = []
        try:
            keyword, keyword_degraded = self.keyword_lane.search(
                request, self.candidate_limit
            )
            lanes["keyword"] = keyword
            if keyword_degraded:
                degraded.append("keyword:fts-unavailable")
        except Exception:
            lanes["keyword"] = []
            degraded.append("keyword:error")
        try:
            lanes["metadata"] = self.metadata_lane.search(
                request, self.candidate_limit
            )
        except Exception:
            lanes["metadata"] = []
            degraded.append("metadata:error")
        if self.semantic_lane is not None and self.semantic_lane.embedder.enabled:
            try:
                lanes["semantic"] = await self.semantic_lane.search(
                    request, self.candidate_limit
                )
            except Exception:
                lanes["semantic"] = []
                degraded.append("semantic:error")

        fused = _rrf(lanes, self.rrf_k, self.lane_weights)
        selected = _apply_type_and_char_budgets(fused, request)
        candidate_ids = {
            (item.item_type, item.item_id)
            for lane_items in lanes.values()
            for item in lane_items
        }
        active_lanes = tuple(name for name, items in lanes.items() if items)
        return MemoryQueryResult(
            selected,
            candidate_count=len(candidate_ids),
            filtered_count=max(0, len(candidate_ids) - len(selected)),
            degraded=bool(degraded),
            injected_chars=sum(len(item.content) for item in selected),
            reason="hybrid-rrf" if selected else "hybrid-no-match",
            active_lanes=active_lanes,
            degraded_lanes=tuple(degraded),
            lane_candidate_counts={name: len(items) for name, items in lanes.items()},
            query_context_fields=request.context_fields,
            truncated=len(selected) < len(fused),
            omitted_items=max(0, len(fused) - len(selected)),
            omitted_chars=sum(len(item.content) for item in fused[len(selected) :]),
        )


def _rrf(
    lanes: dict[str, list[MemoryItem]],
    rrf_k: int,
    weights: dict[str, float],
) -> list[MemoryItem]:
    scores: dict[tuple[str, str], float] = {}
    items: dict[tuple[str, str], MemoryItem] = {}
    reasons: dict[tuple[str, str], list[str]] = {}
    for lane_name, lane_items in lanes.items():
        for rank, item in enumerate(lane_items, start=1):
            if not item.item_id:
                raise ValueError(f"{lane_name} lane 返回了空 item_id。")
            key = (item.item_type, item.item_id)
            scores[key] = scores.get(key, 0.0) + weights.get(lane_name, 1.0) / (
                max(1, rrf_k) + rank
            )
            items.setdefault(key, item)
            reasons.setdefault(key, []).append(lane_name)
    type_order = {"card": 0, "claim": 1, "episode": 2}
    ordered = sorted(
        scores,
        key=lambda key: (
            -scores[key],
            type_order.get(items[key].item_type, 99),
            -items[key].timestamp.timestamp(),
            key[1],
        ),
    )
    return [
        replace(
            items[key],
            recall_reason=f"rrf:{'+'.join(sorted(reasons[key]))}",
            metadata={
                **items[key].metadata,
                "rrf_score": scores[key],
                "retrieval_lanes": tuple(sorted(reasons[key])),
            },
        )
        for key in ordered
    ]


def _apply_type_and_char_budgets(
    candidates: list[MemoryItem], request: MemoryQuery
) -> list[MemoryItem]:
    quotas = {
        "card": max(0, request.card_limit),
        "claim": max(0, request.claim_limit),
        "episode": max(0, request.episode_limit),
    }
    selected: list[MemoryItem] = []
    used_ids: set[tuple[str, str]] = set()
    counts: dict[str, int] = {item_type: 0 for item_type in quotas}
    used_chars = 0

    def add(item: MemoryItem) -> bool:
        nonlocal used_chars
        identity = (item.item_type, item.item_id)
        if identity in used_ids or len(selected) >= request.limit:
            return False
        if used_chars + len(item.content) > request.max_chars:
            return False
        selected.append(item)
        used_ids.add(identity)
        counts[item.item_type] = counts.get(item.item_type, 0) + 1
        used_chars += len(item.content)
        return True

    for item in candidates:
        if counts.get(item.item_type, 0) < quotas.get(item.item_type, 0):
            add(item)
    for item_type in request.spillover_order:
        for item in candidates:
            if item.item_type == item_type:
                add(item)
    return selected


def candidate_debug_view(items: list[MemoryItem]) -> list[dict[str, Any]]:
    """仅返回安全诊断，不暴露正文或向量。"""

    return [
        {
            "id": item.item_id,
            "type": item.item_type,
            "reason": item.recall_reason,
        }
        for item in items
    ]
