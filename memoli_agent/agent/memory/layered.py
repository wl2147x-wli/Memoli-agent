"""Deterministic Card-first/Claim-first/Episode-first retrieval routing."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, replace
from typing import Any

from memoli_agent.agent.memory.models import MemoryItem, MemoryQuery, MemoryQueryResult
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore


@dataclass(frozen=True, slots=True)
class LayeredMemoryRetriever:
    store: SQLiteMemoryStore
    fallback: Any

    async def query(self, request: MemoryQuery) -> MemoryQueryResult:
        route = _route(request)
        if route == "card-first":
            return await self._card_first(request)
        item_types = {
            "claim-first": ("claim", "card"),
            "episode-first": ("episode",),
            "hybrid": request.item_types,
        }[route]
        result = await self._fallback(replace(request, item_types=item_types))
        return replace(
            result,
            requested_route=request.retrieval_mode,
            actual_route=route,
            detail_level=request.detail_level,
        )

    async def _card_first(self, request: MemoryQuery) -> MemoryQueryResult:
        statements = self.store.search_card_statements(request)
        degraded_reasons: list[str] = []
        if not statements and request.direct_claim_fallback:
            fallback = await self._fallback(
                replace(request, item_types=("claim",), claim_limit=request.limit)
            )
            return replace(
                fallback,
                degraded=True,
                reason="card-first-claim-fallback",
                requested_route=request.retrieval_mode,
                actual_route="claim-first",
                detail_level=request.detail_level,
                degraded_reasons=("card-missing-or-no-match",),
            )
        items: list[MemoryItem] = list(statements)
        if request.detail_level in {"fact", "evidence"}:
            claims = self.store.expand_card_statement_claims(
                tuple(item.item_id for item in statements), request
            )
            seen_claims = {
                claim_id
                for statement in statements
                for claim_id in statement.metadata.get("claim_ids", ())
            }
            expanded = [item for item in claims if item.item_id in seen_claims]
            statement_by_claim = {
                claim_id: statement
                for statement in statements
                for claim_id in statement.metadata.get("claim_ids", ())
            }
            items = [
                replace(
                    statement,
                    evidence=(
                        tuple(
                            ref
                            for claim in expanded
                            if claim.item_id in statement.metadata.get("claim_ids", ())
                            for ref in claim.evidence[
                                : request.evidence_expansion_limit
                            ]
                        )
                        if request.detail_level == "evidence"
                        else statement.evidence
                    ),
                    metadata={
                        **statement.metadata,
                        "expanded_claim_ids": tuple(
                            claim.item_id
                            for claim in expanded
                            if claim.item_id in statement.metadata.get("claim_ids", ())
                        ),
                    },
                )
                for statement in statements
            ]
            items.extend(
                claim
                for claim in expanded
                if _normalized(claim.content)
                != _normalized(statement_by_claim[claim.item_id].content)
            )
        items = _bounded(
            items, request.max_chars, request.limit + request.claim_expansion_limit
        )
        return MemoryQueryResult(
            items,
            candidate_count=len(statements),
            injected_chars=sum(len(item.content) for item in items),
            reason="card-first",
            active_lanes=("card-statement",),
            query_context_fields=request.context_fields,
            truncated=len(items) < len(statements),
            requested_route=request.retrieval_mode,
            actual_route="card-first",
            detail_level=request.detail_level,
            degraded_reasons=tuple(degraded_reasons),
        )

    async def _fallback(self, request: MemoryQuery) -> MemoryQueryResult:
        pending = self.fallback.query(request)
        return await pending if inspect.isawaitable(pending) else pending


def _route(request: MemoryQuery) -> str:
    if request.retrieval_mode != "auto":
        return request.retrieval_mode
    query = request.query.casefold()
    if any(
        marker in query
        for marker in (
            "source",
            "evidence",
            "according",
            "current",
            "latest",
            "exact",
            "来源",
            "证据",
            "当前",
            "最新",
            "准确",
            "医疗",
            "法律",
            "财务",
        )
    ):
        return "claim-first"
    if any(
        marker in query
        for marker in (
            "when",
            "history",
            "happened",
            "process",
            "什么时候",
            "历史",
            "那次",
            "过程",
            "发生",
        )
    ):
        return "episode-first"
    if any(
        marker in query
        for marker in (
            "profile",
            "preference",
            "overview",
            "about me",
            "偏好",
            "画像",
            "概览",
            "关于我",
            "总结",
        )
    ):
        return "card-first"
    return "hybrid"


def _bounded(items: list[MemoryItem], max_chars: int, limit: int) -> list[MemoryItem]:
    selected: list[MemoryItem] = []
    used = 0
    identities: set[tuple[str, str]] = set()
    for item in items:
        identity = (item.item_type, item.item_id)
        if identity in identities or len(selected) >= limit:
            continue
        if used + len(item.content) > max_chars:
            continue
        selected.append(item)
        identities.add(identity)
        used += len(item.content)
    return selected


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())
