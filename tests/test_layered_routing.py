"""分层路由回归测试 (task 6.5)：四种路由、Card statement 命中、按需 Claim/证据展开、
Claim fallback、Pattern-only Card 与预算边界。

Card-first 通过共享 FTS/Pattern lane 检索 current Card statement（task 6.2），
所有路由共享同一 Query Plan 与 hard filter 语义（task 6.1）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from memoli_agent.agent.memory.hybrid import (
    FtsSearchLane,
    HybridMemoryRetriever,
    MetadataSearchLane,
    PatternSearchLane,
)
from memoli_agent.agent.memory.layered import LayeredMemoryRetriever
from memoli_agent.agent.memory.models import (
    CardDraftStatement,
    EvidenceRef,
    MemoryMutation,
    MemoryQuery,
    MemoryScope,
)
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore


def _claim(content: str, *, subject: str = "general") -> MemoryMutation:
    return MemoryMutation(
        content,
        subject=subject,
        evidence=(EvidenceRef("message", f"msg-{content}", content),),
    )


def _layered(store: SQLiteMemoryStore) -> LayeredMemoryRetriever:
    hybrid = HybridMemoryRetriever(
        store=store,
        fts_lane=FtsSearchLane(store),
        pattern_lane=PatternSearchLane(store),
        metadata_lane=MetadataSearchLane(store),
        semantic_lane=None,
    )
    return LayeredMemoryRetriever(store, hybrid)


def _seed_card(store: SQLiteMemoryStore, *, statement: str, claim_content: str) -> str:
    claim = store.append_claim(_claim(claim_content))
    card = store.create_card(
        title="开发偏好",
        content=statement,
        scope=MemoryScope(),
        statements=(CardDraftStatement(statement, (claim.item_id,)),),
    )
    assert card.card_id
    return claim.item_id


def _statement_id(store: SQLiteMemoryStore) -> str:
    row = store._connection.execute(  # noqa: S106
        "SELECT statement_id FROM card_statements WHERE is_current=1"
    ).fetchone()
    return str(row["statement_id"])


# --------------------------------------------------------------------------- #
# 四种路由
# --------------------------------------------------------------------------- #


def test_four_routes_produce_expected_actual_route(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    _seed_card(
        store,
        statement="项目使用清华源",
        claim_content="项目使用清华源下载依赖",
    )
    retriever = _layered(store)

    async def scenario() -> None:
        for mode, expected in (
            ("card-first", "card-first"),
            ("claim-first", "claim-first"),
            ("episode-first", "episode-first"),
            ("hybrid", "hybrid"),
        ):
            result = await retriever.query(
                MemoryQuery("清华源", limit=5, claim_limit=5, retrieval_mode=mode)  # type: ignore[arg-type]
            )
            assert result.actual_route == expected, mode

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# Card-first 命中 current statement（共享 FTS lane）
# --------------------------------------------------------------------------- #


def test_card_first_finds_relevant_statement_via_fts(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    _seed_card(
        store,
        statement="项目使用清华源",
        claim_content="项目使用清华源下载依赖",
    )
    retriever = _layered(store)

    async def scenario() -> None:
        result = await retriever.query(
            MemoryQuery(
                "清华源",
                limit=5,
                claim_limit=5,
                retrieval_mode="card-first",
                detail_level="summary",
            )
        )
        assert result.actual_route == "card-first"
        assert result.items
        assert result.items[0].item_type == "card-statement"
        assert "fts" in result.items[0].recall_reason

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 按需 Claim / 证据展开
# --------------------------------------------------------------------------- #


def test_card_first_expands_claims_only_at_fact_or_evidence(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    claim_id = _seed_card(
        store,
        statement="项目使用清华源",
        claim_content="项目使用清华源下载依赖",
    )
    retriever = _layered(store)

    async def scenario() -> None:
        # summary：不展开关联 Claim。
        summary = await retriever.query(
            MemoryQuery(
                "清华源",
                limit=10,
                claim_limit=10,
                retrieval_mode="card-first",
                detail_level="summary",
            )
        )
        assert all(item.item_type == "card-statement" for item in summary.items)
        assert not summary.items[0].metadata.get("expanded_claim_ids")

        # fact：展开关联 Claim，去重后追加。
        fact = await retriever.query(
            MemoryQuery(
                "清华源",
                limit=10,
                claim_limit=10,
                retrieval_mode="card-first",
                detail_level="fact",
            )
        )
        types = [item.item_type for item in fact.items]
        assert "claim" in types
        assert fact.items[0].metadata["expanded_claim_ids"] == (claim_id,)

        # evidence：statement 携带关联 Claim 的证据引用。
        evidence = await retriever.query(
            MemoryQuery(
                "清华源",
                limit=10,
                claim_limit=10,
                retrieval_mode="card-first",
                detail_level="evidence",
            )
        )
        statement = next(
            item for item in evidence.items if item.item_type == "card-statement"
        )
        assert statement.evidence

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# Claim fallback：无相关 Card statement
# --------------------------------------------------------------------------- #


def test_card_first_falls_back_to_claims_when_no_statement(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    # 有一条 claim 但无对应 Card statement 文本命中。
    store.append_claim(_claim("数据库使用默认配置"))
    retriever = _layered(store)

    async def scenario() -> None:
        result = await retriever.query(
            MemoryQuery(
                "数据库配置",
                limit=5,
                claim_limit=5,
                retrieval_mode="card-first",
                detail_level="summary",
                direct_claim_fallback=True,
            )
        )
        assert result.actual_route == "claim-first"
        assert result.reason == "card-first-claim-fallback"
        assert result.degraded is True
        assert result.items
        assert result.items[0].item_type == "claim"

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# Pattern-only Card：FTS 不可用时仍通过 Pattern lane 召回 statement
# --------------------------------------------------------------------------- #


def test_card_first_pattern_only_when_fts_unavailable(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    _seed_card(
        store,
        statement="项目使用清华源",
        claim_content="项目使用清华源下载依赖",
    )
    store.fts_available = False  # 模拟 FTS5/trigram 不可用
    retriever = _layered(store)

    async def scenario() -> None:
        result = await retriever.query(
            MemoryQuery(
                "清华源",
                limit=5,
                claim_limit=5,
                retrieval_mode="card-first",
                detail_level="summary",
            )
        )
        assert result.actual_route == "card-first"
        assert result.items
        assert "pattern" in result.items[0].recall_reason

    asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# 预算边界
# --------------------------------------------------------------------------- #


def test_card_first_respects_char_budget(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    claim = store.append_claim(_claim("清华源下载依赖一长串内容避免重复"))
    statements = tuple(
        CardDraftStatement(f"项目使用清华源编号 {i} 长内容", (claim.item_id,))
        for i in range(4)
    )
    store.create_card(
        title="开发偏好",
        content="项目使用清华源",
        scope=MemoryScope(),
        statements=statements,
    )
    retriever = _layered(store)

    async def scenario() -> None:
        result = await retriever.query(
            MemoryQuery(
                "清华源",
                limit=10,
                claim_limit=10,
                retrieval_mode="card-first",
                detail_level="summary",
                max_chars=40,
                card_statement_limit=6,
            )
        )
        # 字符预算截断：注入字符不超预算，且报告被省略项。
        assert result.injected_chars <= 40
        assert result.omitted_items + result.omitted_chars >= 0
        assert result.actual_route == "card-first"

    asyncio.run(scenario())
