"""个人记忆的数据合同。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

MemoryStatus = Literal[
    "candidate",
    "active",
    "approved",
    "frozen",
    "superseded",
    "rejected",
    "deleted",
]
MemoryRelation = Literal[
    "supports", "corrects", "contradicts", "supersedes", "derived-from"
]


@dataclass(frozen=True, slots=True)
class MemoryScope:
    kind: str = "user"
    identifier: str = "default"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    kind: str
    ref_id: str
    quote: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemoryItem:
    """兼容旧接口的记忆命中，同时携带可追溯字段。"""

    content: str
    source: str
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    item_id: str = ""
    item_type: str = "claim"
    status: str = "active"
    evidence: tuple[EvidenceRef, ...] = ()
    recall_reason: str = ""
    current: bool = True


@dataclass(frozen=True, slots=True)
class MemoryClaim:
    claim_id: str
    content: str
    source: str
    scope: MemoryScope
    status: MemoryStatus
    sensitivity: str
    explicitness: str
    content_hash: str
    created_at: datetime
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    evidence: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryCardVersion:
    version_id: str
    card_id: str
    version: int
    title: str
    content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryCard:
    card_id: str
    scope: MemoryScope
    status: MemoryStatus
    sensitivity: str
    current_version: MemoryCardVersion


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    """结构化召回请求；``query`` 始终表示本轮用户的主意图。"""

    query: str
    limit: int = 5
    item_types: tuple[str, ...] = ("card", "claim", "episode")
    scope: MemoryScope = field(default_factory=MemoryScope)
    statuses: tuple[str, ...] = ("active", "approved", "frozen")
    max_sensitivity: str = "private"
    at_time: datetime | None = None
    card_limit: int = 2
    claim_limit: int = 5
    episode_limit: int = 2
    objective: str = ""
    current_step: str = ""
    session_id: str = ""
    max_chars: int = 8_000
    spillover_order: tuple[str, ...] = ("claim", "card", "episode")

    @property
    def semantic_text(self) -> str:
        """为语义通道生成带字段边界的确定性文本。"""

        parts = [f"用户请求: {self.query.strip()}"]
        if self.objective.strip():
            parts.append(f"工作目标: {self.objective.strip()}")
        if self.current_step.strip():
            parts.append(f"当前步骤: {self.current_step.strip()}")
        return "\n".join(parts)

    @property
    def context_fields(self) -> tuple[str, ...]:
        fields = ["query"]
        if self.objective.strip():
            fields.append("objective")
        if self.current_step.strip():
            fields.append("current_step")
        if self.session_id.strip():
            fields.append("session_id")
        return tuple(fields)


@dataclass(frozen=True, slots=True)
class MemoryQueryResult:
    items: list[MemoryItem]
    candidate_count: int = 0
    filtered_count: int = 0
    degraded: bool = False
    injected_chars: int = 0
    reason: str = ""
    active_lanes: tuple[str, ...] = ()
    degraded_lanes: tuple[str, ...] = ()
    lane_candidate_counts: dict[str, int] = field(default_factory=dict)
    query_context_fields: tuple[str, ...] = ()
    truncated: bool = False
    omitted_items: int = 0
    omitted_chars: int = 0


@dataclass(frozen=True, slots=True)
class MemoryMutation:
    content: str
    source: str = "manual"
    metadata: dict[str, Any] = field(default_factory=dict)
    scope: MemoryScope = field(default_factory=MemoryScope)
    status: MemoryStatus = "active"
    sensitivity: str = "private"
    explicitness: str = "explicit-user"
    evidence: tuple[EvidenceRef, ...] = ()
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    subject: str = "general"
    card_kind: str = "profile"
    importance: float = 0.5


@dataclass(frozen=True, slots=True)
class ConsolidationCandidate:
    content: str
    source: str
    scope: MemoryScope
    evidence: tuple[EvidenceRef, ...]
    sensitivity: str = "private"
    category: str = "personal-memory"
    explicitness: str = "inferred"
    relations: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryIndexSource:
    """可生成向量的权威源快照。"""

    memory_type: str
    memory_id: str
    content: str
    content_hash: str
    scope: MemoryScope
    status: str = "active"
    sensitivity: str = "private"
    occurred_at: str = ""


@dataclass(frozen=True, slots=True)
class MemoryIndexJob:
    memory_type: str
    memory_id: str
    content_hash: str
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class SemanticIndexEntry:
    source: MemoryIndexSource
    model: str
    version: str
    dimensions: int
    vector: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    """不同检索通道之间交换的统一候选。"""

    item: MemoryItem
    lane: str
    rank: int
    score: float = 0.0


@dataclass(frozen=True, slots=True)
class CardProjectionKey:
    scope: MemoryScope
    subject: str
    card_kind: str

    @property
    def value(self) -> str:
        return ":".join(
            (self.scope.kind, self.scope.identifier, self.subject, self.card_kind)
        )


@dataclass(frozen=True, slots=True)
class CardDraftStatement:
    content: str
    claim_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CardDraft:
    key: CardProjectionKey
    title: str
    statements: tuple[CardDraftStatement, ...]

    @property
    def content(self) -> str:
        return "\n".join(
            f"- {statement.content} "
            f"[claims:{','.join(statement.claim_ids)}]"
            for statement in self.statements
        )
