"""从已生效 Claim 构建可追溯 Card 的确定性投影。"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from memoli_agent.agent.memory.models import (
    CardDraft,
    CardDraftStatement,
    CardProjectionKey,
    MemoryScope,
)
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore


class CardGenerationError(RuntimeError):
    """Card 草稿没有通过证据校验。"""


class CardTextGenerator(Protocol):
    def generate(
        self, key: CardProjectionKey, claims: Sequence[tuple[str, str]]
    ) -> CardDraft: ...


@dataclass(frozen=True, slots=True)
class DeterministicCardTextGenerator:
    """逐条保留 Claim 原文，避免生成无证据事实。"""

    def generate(
        self, key: CardProjectionKey, claims: Sequence[tuple[str, str]]
    ) -> CardDraft:
        title = "个人记忆" if key.subject == "general" else key.subject
        statements = tuple(
            CardDraftStatement(content, (claim_id,)) for claim_id, content in claims
        )
        return CardDraft(key, title, statements)


@dataclass(frozen=True, slots=True)
class CardBuildResult:
    projection_key: str
    status: str
    card_id: str = ""
    claim_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CardBuilder:
    store: SQLiteMemoryStore
    generator: CardTextGenerator = DeterministicCardTextGenerator()
    batch_size: int = 4
    worker_id: str = field(default_factory=lambda: f"card-builder-{uuid.uuid4().hex}")

    def tick(self) -> tuple[CardBuildResult, ...]:
        results: list[CardBuildResult] = []
        for job in self.store.claim_projection_jobs(
            "card", self.batch_size, worker_id=self.worker_id
        ):
            projection_key = str(job["projection_key"])
            try:
                payload = json.loads(str(job["payload_json"]))
                key = CardProjectionKey(
                    MemoryScope(payload["scope_kind"], payload["scope_id"]),
                    payload["subject"],
                    payload["card_kind"],
                )
                result = self.build(key)
                self.store.finish_projection_job(
                    "card",
                    projection_key,
                    "skipped" if result.status in {"empty", "frozen"} else "ready",
                    worker_id=self.worker_id,
                )
                results.append(result)
            except Exception as exc:
                self.store.fail_projection_job(
                    "card",
                    projection_key,
                    type(exc).__name__,
                    worker_id=self.worker_id,
                )
                results.append(CardBuildResult(projection_key, "failed"))
        return tuple(results)

    def build(self, key: CardProjectionKey) -> CardBuildResult:
        if self.store.has_unresolved_card_conflict(key):
            raise CardGenerationError("unresolved-card-conflict")
        rows = self.store.eligible_card_claims(key)
        claims = tuple((str(row["claim_id"]), str(row["content"])) for row in rows)
        if not claims:
            return CardBuildResult(key.value, "empty")
        draft = self.generator.generate(key, claims)
        _validate_draft(draft, dict(claims))
        claim_ids = tuple(
            sorted(
                {
                    claim_id
                    for statement in draft.statements
                    for claim_id in statement.claim_ids
                }
            )
        )
        status, card = self.store.apply_card_projection(
            key,
            title=draft.title,
            content=draft.content,
            claim_ids=claim_ids,
            statements=draft.statements,
        )
        return CardBuildResult(
            key.value,
            status,
            card.card_id if card is not None else "",
            claim_ids,
        )


def _validate_draft(draft: CardDraft, claims: dict[str, str]) -> None:
    if not draft.title.strip() or not draft.statements:
        raise CardGenerationError("Card 草稿为空。")
    for statement in draft.statements:
        if not statement.content.strip() or not statement.claim_ids:
            raise CardGenerationError("Card 语句缺少内容或 Claim 引用。")
        if any(claim_id not in claims for claim_id in statement.claim_ids):
            raise CardGenerationError("Card 语句引用了不可用 Claim。")
        normalized = " ".join(statement.content.casefold().split())
        sources = [
            " ".join(claims[claim_id].casefold().split())
            for claim_id in statement.claim_ids
        ]
        if normalized not in sources and normalized != " ".join(sources):
            raise CardGenerationError("Card 语句无法由引用 Claim 直接支持。")
