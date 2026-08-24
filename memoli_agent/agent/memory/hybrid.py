"""FTS、Pattern、semantic、metadata 四路候选的 MemOS 风格确定性融合。

通道分工：FTS5 trigram 负责严格全文候选，Pattern LIKE 补足短词窗口，
vector/structural 通道并行。各 lane 输出 ``ChannelHit``，融合只消费
``normalized_relevance`` 与 ``rank``：``base = max(norm) + rrf_bonus_weight ×
Σ(weight/(rrf_k+rank))``，再依次经过相对阈值、多通道保护、按类型 smart seed、
确定性 MMR 与类型/数量/字符预算。原始 BM25、cosine 与 importance 绝不进入
跨 lane 加法，仅作为安全诊断字段保留。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from typing import Any

from memoli_agent.agent.memory.models import (
    ChannelHit,
    MemoryItem,
    MemoryQuery,
    MemoryQueryResult,
)
from memoli_agent.agent.memory.query_plan import build_query_plan
from memoli_agent.agent.memory.semantic import (
    Embedder,
    cosine_similarity,
    decode_vector,
)
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore

_LANE_ORDER: dict[str, int] = {"fts": 0, "pattern": 1, "semantic": 2, "metadata": 3}
_TYPE_ORDER: dict[str, int] = {"card": 0, "card-statement": 0, "claim": 1, "episode": 2}


@dataclass(frozen=True, slots=True)
class KeywordSearchLane:
    """遗留 keyword 通道：仍走 ``store.search``，仅为旧基准与基准脚本保留。

    新的 ``HybridMemoryRetriever`` 不再使用本 lane；严格全文召回由
    ``FtsSearchLane`` 承担，宽松召回由 ``PatternSearchLane`` 承担。
    """

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
class FtsSearchLane:
    """严格 FTS 通道：``memory_search`` + ``bm25()``，``1/rank`` 规范化。"""

    store: SQLiteMemoryStore
    name: str = "fts"

    def search(
        self, request: MemoryQuery, plan: Any, limit: int
    ) -> tuple[list[ChannelHit], bool, int, str]:
        hits, degraded, filtered, reason = self.store.fts_recall(
            request, plan, limit=limit
        )
        channel_hits: list[ChannelHit] = []
        for rank, (item, raw) in enumerate(hits, start=1):
            channel_hits.append(
                ChannelHit(
                    identity=(item.item_type, item.item_id),
                    item=item,
                    lane=self.name,
                    rank=rank,
                    normalized_relevance=1.0 / rank,
                    raw_score=raw,
                    reason=reason,
                )
            )
        return channel_hits, degraded, filtered, reason


@dataclass(frozen=True, slots=True)
class PatternSearchLane:
    """宽松 Pattern 通道：转义 LIKE OR，``1/rank`` 规范化。"""

    store: SQLiteMemoryStore
    name: str = "pattern"

    def search(
        self, request: MemoryQuery, plan: Any, limit: int
    ) -> tuple[list[ChannelHit], int, str]:
        items, scanned, reason = self.store.pattern_recall(
            request, plan, limit=limit
        )
        channel_hits: list[ChannelHit] = []
        for rank, item in enumerate(items, start=1):
            channel_hits.append(
                ChannelHit(
                    identity=(item.item_type, item.item_id),
                    item=item,
                    lane=self.name,
                    rank=rank,
                    normalized_relevance=1.0 / rank,
                    raw_score=None,
                    reason=reason,
                )
            )
        return channel_hits, scanned, reason


@dataclass(frozen=True, slots=True)
class MetadataSearchLane:
    """结构/核心通道：仅明确结构匹配给固定低相关性，不与文本召回等价。"""

    store: SQLiteMemoryStore
    name: str = "metadata"
    relevance: float = 0.1

    def search(self, request: MemoryQuery, limit: int) -> list[ChannelHit]:
        items = self.store.metadata_candidates(request, limit)
        return [
            ChannelHit(
                identity=(item.item_type, item.item_id),
                item=item,
                lane=self.name,
                rank=rank,
                normalized_relevance=self.relevance,
                raw_score=None,
                reason="metadata",
            )
            for rank, item in enumerate(items, start=1)
        ]


@dataclass(frozen=True, slots=True)
class SemanticSearchLane:
    """语义通道：cosine 裁剪到 [0,1]，``rank`` 用于 RRF 奖励。"""

    store: SQLiteMemoryStore
    embedder: Embedder
    candidate_limit: int = 200
    name: str = "semantic"

    async def search(self, request: MemoryQuery, limit: int) -> list[ChannelHit]:
        vectors = await self.embedder.embed((request.semantic_text,))
        query_vector = vectors[0]
        rows = self.store.ready_semantic_rows(
            request,
            model=self.embedder.model,
            version=self.embedder.version,
            dimensions=self.embedder.dimensions,
            limit=min(self.candidate_limit, max(limit * 8, limit)),
        )
        scored: list[tuple[float, MemoryItem]] = []
        for item, blob in rows:
            sim = cosine_similarity(
                query_vector, decode_vector(blob, self.embedder.dimensions)
            )
            if not math.isfinite(sim):
                continue
            scored.append((max(0.0, min(1.0, sim)), item))
        scored.sort(key=lambda pair: (-pair[0], pair[1].item_id))
        hits: list[ChannelHit] = []
        for rank, (norm, item) in enumerate(scored[:limit], start=1):
            hits.append(
                ChannelHit(
                    identity=(item.item_type, item.item_id),
                    item=item,
                    lane=self.name,
                    rank=rank,
                    normalized_relevance=norm,
                    raw_score=norm,
                    reason="semantic",
                )
            )
        return hits


@dataclass(frozen=True, slots=True)
class HybridMemoryRetriever:
    """MemOS 风格四路融合检索器。"""

    store: SQLiteMemoryStore
    fts_lane: FtsSearchLane
    pattern_lane: PatternSearchLane
    metadata_lane: MetadataSearchLane
    semantic_lane: SemanticSearchLane | None = None
    rrf_k: int = 60
    rrf_bonus_weight: float = 0.4
    lane_weights: dict[str, float] = field(
        default_factory=lambda: {
            "fts": 1.0,
            "pattern": 0.4,
            "semantic": 1.0,
            "metadata": 0.5,
        }
    )
    candidate_limit: int = 50
    fts_candidate_limit: int = 64
    pattern_candidate_limit: int = 32
    relative_threshold: float = 0.2
    multi_lane_protection: bool = True
    smart_seed_ratio: float = 0.7
    mmr_enabled: bool = True
    mmr_lambda: float = 0.7

    async def query(self, request: MemoryQuery) -> MemoryQueryResult:
        if not request.query.strip():
            return MemoryQueryResult(
                [],
                query_context_fields=request.context_fields,
                reason="empty-query",
                query_plan_summary={"has_embedding_text": False},
            )
        plan = build_query_plan(request)
        hits_by_lane: dict[str, list[ChannelHit]] = {}
        degraded: list[str] = []
        lane_counts: dict[str, int] = {}
        hard_filtered = 0

        try:
            fts_hits, fts_degraded, fts_filtered, fts_reason = self.fts_lane.search(
                request, plan, self.fts_candidate_limit
            )
            hits_by_lane["fts"] = fts_hits
            lane_counts["fts"] = len(fts_hits)
            hard_filtered += fts_filtered
            if fts_degraded:
                degraded.append(f"fts:{fts_reason}")
        except Exception:
            hits_by_lane["fts"] = []
            lane_counts["fts"] = 0
            degraded.append("fts:error")

        try:
            pat_hits, pat_scanned, pat_reason = self.pattern_lane.search(
                request, plan, self.pattern_candidate_limit
            )
            hits_by_lane["pattern"] = pat_hits
            lane_counts["pattern"] = len(pat_hits)
            hard_filtered += max(0, pat_scanned - len(pat_hits))
        except Exception:
            hits_by_lane["pattern"] = []
            lane_counts["pattern"] = 0
            degraded.append("pattern:error")

        try:
            hits_by_lane["metadata"] = self.metadata_lane.search(
                request, self.candidate_limit
            )
            lane_counts["metadata"] = len(hits_by_lane["metadata"])
        except Exception:
            hits_by_lane["metadata"] = []
            lane_counts["metadata"] = 0
            degraded.append("metadata:error")

        if self.semantic_lane is not None and self.semantic_lane.embedder.enabled:
            try:
                hits_by_lane["semantic"] = await self.semantic_lane.search(
                    request, self.candidate_limit
                )
                lane_counts["semantic"] = len(hits_by_lane["semantic"])
            except Exception:
                hits_by_lane["semantic"] = []
                lane_counts["semantic"] = 0
                degraded.append("semantic:error")

        fused, filter_counts, candidate_count = _fuse(
            hits_by_lane, self, request
        )
        selected = _apply_budgets(fused, request, filter_counts)
        active_lanes = tuple(
            name for name, hits in hits_by_lane.items() if hits
        )
        selected_ids = {(item.item_type, item.item_id) for item in selected}
        omitted = max(0, len(fused) - len(selected))
        omitted_chars = sum(
            len(f.item.content) for f in fused if f.identity not in selected_ids
        )
        return MemoryQueryResult(
            selected,
            candidate_count=candidate_count,
            filtered_count=max(0, candidate_count - len(selected)),
            degraded=bool(degraded),
            injected_chars=sum(len(item.content) for item in selected),
            reason="memos-fusion" if selected else "memos-no-match",
            active_lanes=active_lanes,
            degraded_lanes=tuple(degraded),
            lane_candidate_counts=lane_counts,
            query_context_fields=request.context_fields,
            truncated=len(selected) < len(fused),
            omitted_items=omitted,
            omitted_chars=omitted_chars,
            query_plan_summary=dict(plan.summary),
            filter_counts={
                "hard_filter": hard_filtered,
                **filter_counts,
            },
        )


@dataclass(frozen=True, slots=True)
class _Contribution:
    lane: str
    rank: int
    normalized_relevance: float
    raw_score: float | None


@dataclass(frozen=True, slots=True)
class _Fused:
    identity: tuple[str, str]
    item: MemoryItem
    fused_relevance: float
    contributions: tuple[_Contribution, ...]
    lane_count: int


def _fuse(
    hits_by_lane: dict[str, list[ChannelHit]],
    cfg: HybridMemoryRetriever,
    request: MemoryQuery,
) -> tuple[list[_Fused], dict[str, int], int]:
    """去重聚合 → base+RRF bonus → 相对阈值 + 多通道保护 → smart seed → MMR。"""

    agg: dict[tuple[str, str], list[ChannelHit]] = {}
    item_by_id: dict[tuple[str, str], MemoryItem] = {}
    for lane_name, hits in hits_by_lane.items():
        for hit in hits:
            if not hit.item.item_id:
                raise ValueError(f"{lane_name} lane 返回了空 item_id。")
            agg.setdefault(hit.identity, []).append(hit)
            item_by_id.setdefault(hit.identity, hit.item)

    fused: list[_Fused] = []
    for identity, hits in agg.items():
        contributions = tuple(
            _Contribution(h.lane, h.rank, h.normalized_relevance, h.raw_score)
            for h in hits
        )
        base = max(c.normalized_relevance for c in contributions)
        bonus = cfg.rrf_bonus_weight * sum(
            cfg.lane_weights.get(c.lane, 1.0) / (max(1, cfg.rrf_k) + c.rank)
            for c in contributions
        )
        fused.append(
            _Fused(
                identity=identity,
                item=item_by_id[identity],
                fused_relevance=base + bonus,
                contributions=contributions,
                lane_count=len(contributions),
            )
        )
    candidate_count = len(fused)
    if not fused:
        return [], {"relative_threshold": 0, "multi_lane_protected": 0,
                     "smart_seed": 0, "mmr": 0}, 0

    fused.sort(
        key=lambda f: (
            -f.fused_relevance,
            -f.lane_count,
            _TYPE_ORDER.get(f.item.item_type, 99),
            -(f.item.timestamp.timestamp() if f.item.timestamp else 0),
            f.item.item_id,
        )
    )

    max_score = fused[0].fused_relevance
    threshold = cfg.relative_threshold * max_score
    surviving: list[_Fused] = []
    rt_dropped = 0
    mlp_kept = 0
    for f in fused:
        if f.fused_relevance >= threshold:
            surviving.append(f)
            continue
        if cfg.multi_lane_protection and f.lane_count >= 2:
            surviving.append(f)
            mlp_kept += 1
            continue
        rt_dropped += 1

    surviving, ss_dropped = _smart_seed(surviving, cfg, request)
    surviving = _mmr_reorder(surviving, cfg, request)
    filter_counts = {
        "relative_threshold": rt_dropped,
        "multi_lane_protected": mlp_kept,
        "smart_seed": ss_dropped,
        "mmr": 0,
    }
    return surviving, filter_counts, candidate_count


def _smart_seed(
    candidates: list[_Fused],
    cfg: HybridMemoryRetriever,
    request: MemoryQuery,
) -> tuple[list[_Fused], int]:
    """按类型 smart seed：仅保留每类型最高分 × ratio 及以上的候选，
    以及该类型最高分作为保底种子；不相关类型不强塞结果。"""

    if not candidates:
        return candidates, 0
    ratios = cfg.smart_seed_ratio
    quotas = {
        "card": max(0, request.card_limit),
        "claim": max(0, request.claim_limit),
        "episode": max(0, request.episode_limit),
    }
    type_max: dict[str, float] = {}
    type_top_seen: dict[str, str] = {}
    for f in candidates:
        qt = _quota_type(f.item.item_type)
        if quotas.get(qt, 0) <= 0:
            continue
        if f.fused_relevance > type_max.get(qt, -1.0):
            type_max[qt] = f.fused_relevance
            type_top_seen[qt] = f.item.item_id
    kept: list[_Fused] = []
    dropped = 0
    for f in candidates:
        qt = _quota_type(f.item.item_type)
        if quotas.get(qt, 0) <= 0:
            # 该类型无配额：不参与 smart seed 裁剪，留待 spillover 预算处理。
            kept.append(f)
            continue
        bar = ratios * type_max.get(qt, 0.0)
        if f.fused_relevance >= bar or f.item.item_id == type_top_seen.get(qt):
            kept.append(f)
        else:
            dropped += 1
    return kept, dropped


def _mmr_reorder(
    candidates: list[_Fused],
    cfg: HybridMemoryRetriever,
    request: MemoryQuery,
) -> list[_Fused]:
    """确定性 MMR：仅改变顺序，不改变资格；优先缓存向量，否则文本 bigram Jaccard。"""

    if not cfg.mmr_enabled or len(candidates) <= 1:
        return candidates
    target = max(request.limit, 1)
    if len(candidates) <= target:
        # 不超过预算时仍做轻量重排：按 fused 顺序保持，避免无谓扰动。
        return candidates
    vectors = _cached_vectors(candidates, cfg)
    bigrams = {
        f.identity: _text_bigrams(f.item.content) for f in candidates
    }

    def sim(a: tuple[str, str], b: tuple[str, str]) -> float:
        va, vb = vectors.get(a), vectors.get(b)
        if va is not None and vb is not None:
            return _cosine_floats(va, vb)
        sa, sb = bigrams.get(a, set()), bigrams.get(b, set())
        if not sa and not sb:
            return 0.0
        inter = len(sa & sb)
        union = len(sa | sb)
        return inter / union if union else 0.0

    ordered: list[_Fused] = [candidates[0]]
    pool = list(candidates[1:])
    while pool:
        best_index = 0
        best_score = -math.inf
        for index, candidate in enumerate(pool):
            max_sim = max(
                sim(candidate.identity, chosen.identity) for chosen in ordered
            )
            score = cfg.mmr_lambda * candidate.fused_relevance - (
                1.0 - cfg.mmr_lambda
            ) * max_sim
            if score > best_score or (
                score == best_score
                and candidate.identity < pool[best_index].identity
            ):
                best_score = score
                best_index = index
        ordered.append(pool.pop(best_index))
    return ordered


def _cached_vectors(
    candidates: list[_Fused], cfg: HybridMemoryRetriever
) -> dict[tuple[str, str], list[float]]:
    embedder = cfg.semantic_lane.embedder if cfg.semantic_lane else None
    if embedder is None or not embedder.enabled:
        return {}
    identities = tuple(f.identity for f in candidates)
    return cfg.store.cached_vectors(
        identities,
        model=embedder.model,
        version=embedder.version,
        dimensions=embedder.dimensions,
    )


def _cosine_floats(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))


_CJK_RE = re.compile(r"[㐀-鿿]")


def _text_bigrams(content: str) -> set[str]:
    """规范化文本的 token/CJK bigram 集合，用于无向量时的 MMR 相似度。"""

    normalized = " ".join(content.casefold().split())
    grams: set[str] = set()
    for token in re.findall(r"\w+", normalized):
        grams.add(token)
    for run in _CJK_RE.findall(normalized):
        grams.add(run)
    prev = None
    for ch in normalized:
        if _CJK_RE.match(ch):
            if prev is not None:
                grams.add(prev + ch)
            prev = ch
        else:
            prev = None
    return grams


def _quota_type(item_type: str) -> str:
    return "card" if item_type == "card-statement" else item_type


def _apply_budgets(
    candidates: list[_Fused],
    request: MemoryQuery,
    filter_counts: dict[str, int],
) -> list[MemoryItem]:
    """类型配额 + spillover + 总数/字符预算作为最终硬边界。"""

    quotas = {
        "card": max(0, request.card_limit),
        "claim": max(0, request.claim_limit),
        "episode": max(0, request.episode_limit),
    }
    counts: dict[str, int] = {qt: 0 for qt in quotas}
    selected: list[_Fused] = []
    used_ids: set[tuple[str, str]] = set()
    used_chars = 0

    def admit(f: _Fused) -> bool:
        nonlocal used_chars
        identity = (f.item.item_type, f.item.item_id)
        if identity in used_ids or len(selected) >= request.limit:
            return False
        if used_chars + len(f.item.content) > request.max_chars:
            return False
        selected.append(f)
        used_ids.add(identity)
        counts[_quota_type(f.item.item_type)] += 1
        used_chars += len(f.item.content)
        return True

    for f in candidates:
        qt = _quota_type(f.item.item_type)
        if counts[qt] < quotas[qt] and len(selected) < request.limit:
            admit(f)
    for item_type in request.spillover_order:
        for f in candidates:
            if _quota_type(f.item.item_type) == item_type:
                admit(f)

    char_dropped = 0
    type_count_dropped = 0
    admitted_ids = {f.identity for f in selected}
    for f in candidates:
        if f.identity in admitted_ids:
            continue
        if used_chars + len(f.item.content) > request.max_chars:
            char_dropped += 1
        else:
            type_count_dropped += 1
    filter_counts["char_budget"] = char_dropped
    filter_counts["type_count_budget"] = type_count_dropped

    items: list[MemoryItem] = []
    for f in selected:
        lanes = tuple(
            sorted(
                {c.lane for c in f.contributions},
                key=lambda n: _LANE_ORDER.get(n, 99),
            )
        )
        lane_ranks = {c.lane: c.rank for c in f.contributions}
        norm_scores = {c.lane: c.normalized_relevance for c in f.contributions}
        raw_scores = {
            c.lane: c.raw_score for c in f.contributions if c.raw_score is not None
        }
        items.append(
            replace(
                f.item,
                recall_reason=f"fuse:{'+'.join(lanes)}",
                metadata={
                    **f.item.metadata,
                    "fused_relevance": f.fused_relevance,
                    "contributing_lanes": lanes,
                    "lane_ranks": lane_ranks,
                    "normalized_scores": norm_scores,
                    "raw_scores": raw_scores,
                },
            )
        )
    return items


def candidate_debug_view(items: list[MemoryItem]) -> list[dict[str, Any]]:
    """仅返回安全诊断，不暴露正文或向量。"""

    return [
        {
            "id": item.item_id,
            "type": item.item_type,
            "reason": item.recall_reason,
            "fused_relevance": item.metadata.get("fused_relevance"),
        }
        for item in items
    ]
