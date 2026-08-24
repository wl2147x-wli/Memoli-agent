"""检索诊断安全测试 (task 7.4)：证明诊断与最终项不泄露 query/记忆正文副本、
原始 embedding、API key 或越权候选内容。

对应 spec 场景：
- "Sensitive or out-of-scope memory matches textually"
- "Pattern search spans many scopes"
- "Retrieval is inspected"（诊断 SHALL NOT 包含 embedding 向量、API key 或
  额外的 query/记忆正文副本）
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from memoli_agent.agent.memory.hybrid import (
    FtsSearchLane,
    HybridMemoryRetriever,
    MetadataSearchLane,
    PatternSearchLane,
    candidate_debug_view,
)
from memoli_agent.agent.memory.models import (
    EvidenceRef,
    MemoryMutation,
    MemoryQuery,
    MemoryScope,
)
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore

_SENSITIVE_BODY = "敏感的清华源凭据位于环境变量"
_OTHER_SCOPE_BODY = "其他 scope 的清华源记忆详情"
_IN_SCOPE_BODY = "项目使用清华源下载依赖"


def _claim(
    content: str,
    *,
    scope: MemoryScope | None = None,
    sensitivity: str = "private",
) -> MemoryMutation:
    return MemoryMutation(
        content,
        scope=scope or MemoryScope(),
        sensitivity=sensitivity,
        evidence=(EvidenceRef("message", f"msg-{content}", content),),
    )


def _retriever(store: SQLiteMemoryStore) -> HybridMemoryRetriever:
    return HybridMemoryRetriever(
        store=store,
        fts_lane=FtsSearchLane(store),
        pattern_lane=PatternSearchLane(store),
        metadata_lane=MetadataSearchLane(store),
        semantic_lane=None,
    )


def _diagnostics_blob(result) -> str:
    """把所有诊断字段序列化为单一字符串，便于全文扫描禁带词。"""

    payload = {
        "query_plan_summary": result.query_plan_summary,
        "filter_counts": result.filter_counts,
        "lane_candidate_counts": result.lane_candidate_counts,
        "degraded_lanes": list(result.degraded_lanes),
        "active_lanes": list(result.active_lanes),
        "reason": result.reason,
        "actual_route": result.actual_route,
        "requested_route": result.requested_route,
        "debug_view": candidate_debug_view(result.items),
        "item_metadata": [item.metadata for item in result.items],
        "item_recall_reasons": [item.recall_reason for item in result.items],
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def test_diagnostics_do_not_leak_out_of_scope_or_sensitive_bodies(
    tmp_path: Path,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    in_scope = store.append_claim(_claim(_IN_SCOPE_BODY))
    store.append_claim(_claim(_SENSITIVE_BODY, sensitivity="sensitive"))
    store.append_claim(
        _claim(_OTHER_SCOPE_BODY, scope=MemoryScope("tenant", "other"))
    )
    retriever = _retriever(store)

    async def scenario() -> None:
        result = await retriever.query(MemoryQuery("清华源", limit=10, claim_limit=10))
        # 越权项绝不进入最终结果。
        returned_ids = {item.item_id for item in result.items}
        all_in_scope = all(
            item.item_id == in_scope.item_id for item in result.items
        )
        assert all_in_scope or returned_ids == {
            in_scope.item_id
        }
        # 全量诊断文本不得包含敏感/越权正文与它们的 evidence quote。
        blob = _diagnostics_blob(result)
        assert _SENSITIVE_BODY not in blob
        assert _OTHER_SCOPE_BODY not in blob
        assert f"msg-{_SENSITIVE_BODY}" not in blob
        assert f"msg-{_OTHER_SCOPE_BODY}" not in blob

    asyncio.run(scenario())


def test_diagnostics_do_not_leak_query_body_or_memory_body_copies(
    tmp_path: Path,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    store.append_claim(_claim(_IN_SCOPE_BODY))
    retriever = _retriever(store)
    query_body = "清华源"

    async def scenario() -> None:
        result = await retriever.query(MemoryQuery(query_body, limit=5, claim_limit=5))
        # query_plan_summary 只含计数/标记，不含 query 正文。
        summary = result.query_plan_summary
        for key in summary:
            forbidden = {"query", "query_text", "primary_text", "embedding_text"}
            assert key.lower() not in forbidden
        # 诊断全文不得重复出现 query 正文（非 selected item 的正文不进入诊断）。
        # selected item 的正文合法出现在 item.content，
        # 但不应出现在诊断 metadata/debug 视图。
        view = candidate_debug_view(result.items)
        debug_blob = json.dumps(view, ensure_ascii=False, default=str)
        assert query_body not in debug_blob
        for item in result.items:
            meta_blob = json.dumps(item.metadata, ensure_ascii=False, default=str)
            # metadata 仅含结构化字段，不含正文副本。
            assert item.content not in meta_blob

    asyncio.run(scenario())


def test_diagnostics_do_not_leak_raw_embeddings_or_api_keys(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    store.append_claim(_claim(_IN_SCOPE_BODY))
    retriever = _retriever(store)

    async def scenario() -> None:
        result = await retriever.query(MemoryQuery("清华源", limit=5, claim_limit=5))
        blob = _diagnostics_blob(result)
        # 不得出现裸向量（长浮点序列）或常见 key 标记。
        assert "sk-" not in blob
        assert "api_key" not in blob.lower()
        assert "OPENAI_API_KEY" not in blob
        # raw_scores 仅保留 FTS BM25 标量，不保留向量。
        for item in result.items:
            raw = item.metadata.get("raw_scores", {})
            for lane, score in raw.items():
                assert isinstance(score, int | float), lane
        # 向量字段不出现在诊断。
        assert not re.search(r"\bvector\b", blob, re.IGNORECASE)

    asyncio.run(scenario())


def test_candidate_debug_view_is_safe(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    store.append_claim(_claim(_IN_SCOPE_BODY))
    store.append_claim(_claim(_SENSITIVE_BODY, sensitivity="sensitive"))
    retriever = _retriever(store)

    async def scenario() -> None:
        result = await retriever.query(MemoryQuery("清华源", limit=5, claim_limit=5))
        view = candidate_debug_view(result.items)
        # 每条诊断仅含 id/type/reason/fused_relevance 四个安全字段。
        for entry in view:
            assert set(entry) <= {"id", "type", "reason", "fused_relevance"}
        blob = json.dumps(view, ensure_ascii=False, default=str)
        assert _SENSITIVE_BODY not in blob
        assert _IN_SCOPE_BODY not in blob

    asyncio.run(scenario())
