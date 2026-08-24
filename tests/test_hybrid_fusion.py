"""MemOS 风格混合检索的通道与融合测试：配置、FTS/Pattern 召回边界、
FTS 不可用降级、base+RRF 融合、相对阈值、多通道保护、smart seed、MMR 与
重复查询稳定性。覆盖 tasks 2.5 / 4.7 / 4.8 / 5.8。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from memoli_agent.agent.memory.hybrid import (
    FtsSearchLane,
    HybridMemoryRetriever,
    MetadataSearchLane,
    PatternSearchLane,
)
from memoli_agent.agent.memory.models import (
    EvidenceRef,
    MemoryMutation,
    MemoryQuery,
    MemoryScope,
)
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore
from memoli_agent.bootstrap.config import MemoryHybridConfig


def _claim(
    content: str,
    *,
    status: str = "active",
    scope: MemoryScope | None = None,
    sensitivity: str = "private",
) -> MemoryMutation:
    return MemoryMutation(
        content,
        scope=scope or MemoryScope(),
        status=status,  # type: ignore[arg-type]
        sensitivity=sensitivity,
        evidence=(EvidenceRef("message", f"msg-{content}", content),),
    )


def _retriever(
    store: SQLiteMemoryStore,
    *,
    embedder: object | None = None,
    **overrides: object,
) -> HybridMemoryRetriever:
    defaults: dict[str, object] = dict(
        store=store,
        fts_lane=FtsSearchLane(store),
        pattern_lane=PatternSearchLane(store),
        metadata_lane=MetadataSearchLane(store),
        semantic_lane=embedder,
    )
    defaults.update(overrides)
    return HybridMemoryRetriever(**defaults)  # type: ignore[arg-type]


def _seed(store: SQLiteMemoryStore) -> dict[str, str]:
    mirror = store.append_claim(_claim("项目使用清华镜像源下载依赖"))
    tsinghua = store.append_claim(_claim("项目使用清华源下载依赖"))
    short = store.append_claim(_claim("使用 ai 辅助编程"))
    sensitive = store.append_claim(
        _claim("敏感的清华源凭据位于环境变量", sensitivity="sensitive")
    )
    other_scope = store.append_claim(
        _claim("其他 scope 的清华源记忆", scope=MemoryScope("tenant", "other"))
    )
    return {
        "mirror": mirror.item_id,
        "tsinghua": tsinghua.item_id,
        "short": short.item_id,
        "sensitive": sensitive.item_id,
        "other_scope": other_scope.item_id,
    }


# --------------------------------------------------------------------------- #
# 2.5 配置：默认值、自定义、旧键拒绝、非法边界、embedding 关闭组装
# --------------------------------------------------------------------------- #


def test_default_config_matches_memos_defaults() -> None:
    cfg = MemoryHybridConfig()
    assert cfg.rrf_k == 60
    assert cfg.rrf_bonus_weight == 0.4
    assert cfg.relative_threshold == 0.2
    assert cfg.smart_seed_ratio == 0.7
    assert cfg.mmr_lambda == 0.7
    assert cfg.fts_weight == 1.0 and cfg.pattern_weight == 0.4
    assert cfg.pattern_term_limit == 16
    assert not hasattr(cfg, "keyword_weight")


def test_custom_config_is_accepted() -> None:
    cfg = MemoryHybridConfig(
        rrf_bonus_weight=0.3,
        fts_weight=0.8,
        pattern_weight=0.2,
        relative_threshold=0.1,
        multi_lane_protection=False,
        smart_seed_ratio=0.5,
        mmr_enabled=False,
    )
    assert cfg.rrf_bonus_weight == 0.3
    assert cfg.multi_lane_protection is False


def test_old_keyword_weight_is_rejected_with_migration_hint() -> None:
    with pytest.raises(ValueError, match="fts_weight"):
        MemoryHybridConfig.from_raw({"keyword_weight": 1.0})


def test_invalid_bounds_are_rejected() -> None:
    with pytest.raises(ValueError, match="大于 0"):
        MemoryHybridConfig(rrf_k=0)
    with pytest.raises(ValueError, match="非负"):
        MemoryHybridConfig(fts_weight=-0.1)
    with pytest.raises(ValueError, match="比例参数"):
        MemoryHybridConfig(relative_threshold=1.5)


def test_all_zero_lane_weights_are_rejected() -> None:
    with pytest.raises(ValueError, match="至少一个召回 lane"):
        MemoryHybridConfig(
            fts_weight=0.0,
            pattern_weight=0.0,
            semantic_weight=0.0,
            metadata_weight=0.0,
        )


def test_embedding_disabled_assembles_without_semantic_lane(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    store.append_claim(_claim("项目使用清华源下载依赖"))
    retriever = _retriever(store, embedder=None)
    assert retriever.semantic_lane is None

    async def scenario() -> None:
        result = await retriever.query(MemoryQuery("清华源", limit=3, claim_limit=3))
        assert any(item.item_type == "claim" for item in result.items)
        assert "semantic" not in result.active_lanes

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 4.7 FTS 与 Pattern 召回边界
# --------------------------------------------------------------------------- #


def test_pattern_recalls_inserted_middle_phrase_where_fts_does_not(
    tmp_path: Path,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    ids = _seed(store)
    # 关闭 smart seed / 相对阈值，让 Pattern 召回的弱候选直达预算阶段。
    retriever = _retriever(
        store, relative_threshold=0.0, smart_seed_ratio=0.0, embedder=None
    )

    async def scenario() -> None:
        # "清华源" 在 "清华镜像源" 中不连续出现：严格 trigram FTS 不命中，
        # Pattern bigram (清华) 召回镜像源 claim。
        result = await retriever.query(
            MemoryQuery("清华源", limit=5, claim_limit=5)
        )
        hit = next(
            (item for item in result.items if item.item_id == ids["mirror"]), None
        )
        assert hit is not None
        assert "pattern" in hit.metadata["contributing_lanes"]
        assert "fts" not in hit.metadata["contributing_lanes"]

    asyncio.run(scenario())


def test_strict_fts_recalls_exact_continuous_cjk(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    ids = _seed(store)
    retriever = _retriever(store, embedder=None)

    async def scenario() -> None:
        result = await retriever.query(
            MemoryQuery("清华镜像源", limit=5, claim_limit=5)
        )
        hit = next(item for item in result.items if item.item_id == ids["mirror"])
        assert "fts" in hit.metadata["contributing_lanes"]

    asyncio.run(scenario())


def test_short_ascii_term_only_hits_pattern_lane(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    ids = _seed(store)
    retriever = _retriever(store, embedder=None)

    async def scenario() -> None:
        # 2 字 ASCII "ai" 低于 trigram 窗口，不进入严格 FTS，仅 Pattern 召回。
        result = await retriever.query(MemoryQuery("ai", limit=5, claim_limit=5))
        hit = next(
            (item for item in result.items if item.item_id == ids["short"]), None
        )
        assert hit is not None
        assert "pattern" in hit.metadata["contributing_lanes"]
        assert "fts" not in hit.metadata["contributing_lanes"]

    asyncio.run(scenario())


def test_cross_scope_and_sensitivity_hard_filters(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    ids = _seed(store)
    retriever = _retriever(store, embedder=None)

    async def scenario() -> None:
        result = await retriever.query(
            MemoryQuery("清华源", limit=10, claim_limit=10)
        )
        hit_ids = {item.item_id for item in result.items}
        # 其他 scope 与敏感凭据即便文本命中也不可越权返回。
        assert ids["other_scope"] not in hit_ids
        assert ids["sensitive"] not in hit_ids

    asyncio.run(scenario())


def test_lane_candidate_limit_is_bounded(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    for index in range(40):
        store.append_claim(_claim(f"清华源记忆编号 {index}"))
    retriever = _retriever(
        store, pattern_candidate_limit=8, fts_candidate_limit=8, embedder=None
    )

    async def scenario() -> None:
        result = await retriever.query(
            MemoryQuery("清华源", limit=20, claim_limit=20)
        )
        assert result.lane_candidate_counts["pattern"] <= 8
        assert result.lane_candidate_counts["fts"] <= 8

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 4.8 FTS 不可用与单通道故障降级
# --------------------------------------------------------------------------- #


def test_fts_unavailable_keeps_pattern_working(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    ids = _seed(store)
    store.fts_available = False  # 模拟 trigram/bm25 不可用
    retriever = _retriever(store, embedder=None)

    async def scenario() -> None:
        result = await retriever.query(
            MemoryQuery("清华源", limit=5, claim_limit=5)
        )
        # FTS 不可用仅独立降级，Pattern 仍召回。
        assert any(item.item_id == ids["tsinghua"] for item in result.items)
        assert any("fts" in reason for reason in result.degraded_lanes)
        assert "pattern" in result.active_lanes

    asyncio.run(scenario())


def test_pattern_failure_degrades_independently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    ids = _seed(store)

    def boom(
        self: PatternSearchLane, request: MemoryQuery, plan: object, limit: int
    ) -> object:
        raise RuntimeError("pattern injected failure")

    monkeypatch.setattr(PatternSearchLane, "search", boom)
    retriever = _retriever(store, embedder=None)

    async def scenario() -> None:
        result = await retriever.query(
            MemoryQuery("清华镜像源", limit=5, claim_limit=5)
        )
        # Pattern 失败仅独立降级，FTS 仍召回。
        assert "pattern:error" in result.degraded_lanes
        assert any(item.item_id == ids["mirror"] for item in result.items)

    asyncio.run(scenario())


def test_all_lanes_empty_returns_no_match(tmp_path: Path) -> None:
    # 空库：四路召回均无候选，metadata 也不返回结构候选。
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    retriever = _retriever(store, embedder=None)

    async def scenario() -> None:
        result = await retriever.query(
            MemoryQuery("完全不存在的检索词xyz", limit=5, claim_limit=5)
        )
        assert result.items == []
        assert result.reason == "memos-no-match"

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 5.8 融合：通道重合、raw score 隔离、相对阈值、多通道保护、MMR、稳定性
# --------------------------------------------------------------------------- #


def test_multi_lane_overlap_ranks_above_single_lane(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    ids = _seed(store)
    # 关闭 smart seed / 阈值，保留弱候选以便对比双路 vs 单路融合分。
    retriever = _retriever(
        store, relative_threshold=0.0, smart_seed_ratio=0.0, embedder=None
    )

    async def scenario() -> None:
        # "清华源"：tsinghua 被严格 FTS + Pattern 双路命中，
        # mirror 仅 Pattern 单路命中；多通道重合应排在单路之上。
        result = await retriever.query(
            MemoryQuery("清华源", limit=5, claim_limit=5)
        )
        by_id = {item.item_id: item for item in result.items}
        tsinghua = by_id.get(ids["tsinghua"])
        mirror = by_id.get(ids["mirror"])
        assert tsinghua is not None
        assert "fts" in tsinghua.metadata["contributing_lanes"]
        assert "pattern" in tsinghua.metadata["contributing_lanes"]
        # contributing_lanes 去重，且按稳定 _LANE_ORDER 排列（fts 在 pattern 之前）。
        lanes = tsinghua.metadata["contributing_lanes"]
        assert len(lanes) == len(set(lanes))
        assert lanes.index("fts") < lanes.index("pattern")
        if mirror is not None:
            assert tsinghua.metadata["fused_relevance"] >= mirror.metadata[
                "fused_relevance"
            ]

    asyncio.run(scenario())


def test_raw_scores_do_not_enter_fused_relevance(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    _seed(store)
    retriever = _retriever(store, embedder=None)

    async def scenario() -> None:
        result = await retriever.query(
            MemoryQuery("清华镜像源", limit=5, claim_limit=5)
        )
        for item in result.items:
            fused = item.metadata["fused_relevance"]
            raw = item.metadata.get("raw_scores", {})
            # fused = max(norm) + 有界 RRF bonus，处于合理上界，绝不等于裸 BM25。
            assert 0.0 < fused <= 1.5
            if "fts" in raw:
                assert raw["fts"] != fused

    asyncio.run(scenario())


def test_relative_threshold_drops_weak_candidates(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    ids = _seed(store)
    # 高阈值 + 关闭多通道保护 + smart_seed_ratio=0：弱相关单路候选被丢弃。
    retriever = _retriever(
        store,
        relative_threshold=0.9,
        multi_lane_protection=False,
        smart_seed_ratio=0.0,
        embedder=None,
    )

    async def scenario() -> None:
        result = await retriever.query(
            MemoryQuery("清华镜像源", limit=10, claim_limit=10)
        )
        # 强相关 mirror (fts+pattern) 保留；弱相关 tsinghua (pattern-only) 被阈值丢弃。
        assert ids["mirror"] in {item.item_id for item in result.items}
        assert result.filter_counts["relative_threshold"] >= 1

    asyncio.run(scenario())


def test_multi_lane_protection_retains_more_than_disabling(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    _seed(store)

    async def run(protection: bool) -> object:
        retriever = _retriever(
            store,
            relative_threshold=0.99,
            multi_lane_protection=protection,
            smart_seed_ratio=0.0,
            embedder=None,
        )
        return await retriever.query(MemoryQuery("清华源", limit=10, claim_limit=10))

    protected = asyncio.run(run(True))
    unprotected = asyncio.run(run(False))
    # 保护开启时，低于阈值的多通道候选不被丢弃，结果数 >= 关闭时。
    assert len(protected.items) >= len(unprotected.items)
    assert "multi_lane_protected" in protected.filter_counts


def test_irrelevant_type_not_forced_into_results(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    _seed(store)
    retriever = _retriever(store, embedder=None)

    async def scenario() -> None:
        # 请求只要 claim；card/episode 配额为 0，spillover 也不强塞。
        result = await retriever.query(
            MemoryQuery(
                "清华源",
                limit=5,
                claim_limit=5,
                card_limit=0,
                episode_limit=0,
                item_types=("claim",),
            )
        )
        assert all(item.item_type == "claim" for item in result.items)

    asyncio.run(scenario())


def test_repeated_query_is_stable(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    _seed(store)
    retriever = _retriever(store, embedder=None)

    async def scenario() -> None:
        request = MemoryQuery("清华源", limit=5, claim_limit=5)
        first = await retriever.query(request)
        second = await retriever.query(request)
        assert [item.item_id for item in first.items] == [
            item.item_id for item in second.items
        ]

    asyncio.run(scenario())


def test_mmr_reorder_is_deterministic_and_bounded(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    for index in range(30):
        store.append_claim(_claim(f"清华源记忆编号 {index} 详情各异"))
    retriever = _retriever(store, embedder=None)

    async def scenario() -> None:
        # 30 个候选超过 limit=8，触发确定性 MMR 重排：结果受限、两次查询顺序一致。
        request = MemoryQuery("清华源", limit=8, claim_limit=8)
        first = await retriever.query(request)
        second = await retriever.query(request)
        assert len(first.items) <= 8
        assert [item.item_id for item in first.items] == [
            item.item_id for item in second.items
        ]

    asyncio.run(scenario())


def test_diagnostics_carry_safe_metadata_only(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    _seed(store)
    retriever = _retriever(store, embedder=None)

    async def scenario() -> None:
        result = await retriever.query(
            MemoryQuery("清华镜像源", limit=5, claim_limit=5)
        )
        for item in result.items:
            md = item.metadata
            assert "fused_relevance" in md
            assert "contributing_lanes" in md
            assert "lane_ranks" in md
            assert "normalized_scores" in md
        # query plan 摘要仅含计数与标记，不含 query 正文副本。
        summary = result.query_plan_summary
        assert "query_text" not in summary
        assert "primary_text" not in summary
        assert "fts_term_count" in summary
        assert "pattern_term_count" in summary

    asyncio.run(scenario())
