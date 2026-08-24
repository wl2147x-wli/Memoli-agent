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
JobState = Literal[
    "pending",
    "running",
    "retry",
    "completed",
    "cancelled",
    "dead-letter",
    "quarantined",
    "suppressed",
    "needs-user-review",
]
GovernanceDecisionKind = Literal["approve", "reject", "needs-user-review", "defer"]
GovernanceOutcome = Literal[
    "approved", "rejected", "escalated", "deferred", "stale", "denied"
]
RetrievalMode = Literal["auto", "card-first", "claim-first", "episode-first", "hybrid"]
MemoryDetailLevel = Literal["summary", "fact", "evidence"]
TriggerKind = Literal["chat-window", "long-task"]
TraceConsumptionState = Literal[
    "observed",
    "reserved",
    "consumed",
    "quarantined",
    "suppressed",
    "released",
]
UpdateIntentState = Literal["waiting-for-trigger", "satisfied", "cancelled"]
TurnKind = Literal["chat", "long-task", "ineligible"]


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
class EvidenceLocator:
    trace_id: str
    message_id: str
    role: str
    quote: str
    content_hash: str
    start_offset: int | None = None
    end_offset: int | None = None


@dataclass(frozen=True, slots=True)
class SourceSegment:
    trace_id: str
    session_id: str
    message_id: str
    role: str
    sequence: int
    occurred_at: datetime
    content: str
    content_hash: str
    scope: MemoryScope = field(default_factory=lambda: MemoryScope())
    sensitivity: str = "private"
    prompt_allowed: bool = True
    embedding_allowed: bool = True
    selection: str = "envelope"


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
    retrieval_mode: RetrievalMode = "auto"
    detail_level: MemoryDetailLevel = "summary"
    card_statement_limit: int = 6
    claim_expansion_limit: int = 6
    evidence_expansion_limit: int = 3
    statement_ids: tuple[str, ...] = ()
    direct_claim_fallback: bool = True

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
    requested_route: str = "auto"
    actual_route: str = "hybrid"
    detail_level: str = "summary"
    degraded_reasons: tuple[str, ...] = ()
    query_plan_summary: dict[str, Any] = field(default_factory=dict)
    filter_counts: dict[str, int] = field(default_factory=dict)


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
    fact_type: str = "profile"
    subject: str = "general"
    card_kind: str = "profile"
    entity: str = ""
    predicate: str = ""
    value: Any = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    importance: float = 0.5
    confidence: float = 0.5
    evidence_locators: tuple[EvidenceLocator, ...] = ()


@dataclass(frozen=True, slots=True)
class ExtractorFingerprint:
    name: str
    version: str
    schema_version: str
    prompt_version: str
    policy_version: str
    provider: str = ""
    model: str = ""
    segmenter_version: str = "1"

    @property
    def value(self) -> str:
        import hashlib
        import json

        payload = json.dumps(
            {
                "name": self.name,
                "version": self.version,
                "schema": self.schema_version,
                "prompt": self.prompt_version,
                "policy": self.policy_version,
                "provider": self.provider,
                "model": self.model,
                "segmenter": self.segmenter_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CandidateDraft:
    content: str
    fact_type: str
    subject: str
    card_kind: str
    sensitivity: str
    explicitness: str
    confidence: float
    importance: float
    evidence: tuple[EvidenceLocator, ...]
    entity: str = ""
    predicate: str = ""
    value: Any = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    relations: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class LongTermUpdateRequest:
    request_id: str
    source_type: str
    scope: MemoryScope
    trace_ids: tuple[str, ...]
    state: JobState
    version_fingerprint: str
    created_at: datetime
    updated_at: datetime
    session_id: str = ""
    trace_cursor: str = ""
    priority: int = 0
    attempts: int = 0
    max_attempts: int = 5
    worker_id: str = ""
    lease_until: datetime | None = None
    available_at: datetime | None = None
    last_error_type: str = ""
    candidate_count: int = 0


@dataclass(frozen=True, slots=True)
class TraceConsumption:
    consumer: str
    scope: MemoryScope
    session_id: str
    trace_id: str
    trace_started_at: datetime
    trigger_kind: TriggerKind | None
    state: TraceConsumptionState
    observed_at: datetime
    updated_at: datetime
    request_id: str = ""
    reserved_at: datetime | None = None
    consumed_at: datetime | None = None
    released_at: datetime | None = None
    actor: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class UpdateIntent:
    hint_id: str
    scope: MemoryScope
    session_id: str
    boundary_key: str
    state: UpdateIntentState
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TurnClassification:
    trace_id: str
    session_id: str
    kind: TurnKind
    completed: bool
    successful_business_tool_calls: int = 0
    distinct_business_tool_kinds: int = 0
    elapsed_seconds: float = 0.0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class TriggerDiagnostics:
    session_id: str
    pending_chat_count: int
    chat_turn_threshold: int
    recent_trigger_kind: TriggerKind | None = None
    reserved: int = 0
    consumed: int = 0


@dataclass(frozen=True, slots=True)
class CandidateRelation:
    candidate_id: str
    target_claim_id: str
    relation: MemoryRelation
    expected_target_revision: int | None = None
    confidence: float = 1.0
    status: str = "proposed"


@dataclass(frozen=True, slots=True)
class GovernanceJob:
    job_id: str
    candidate_id: str
    expected_revision: int
    state: JobState
    governor_version: str
    policy_version: str
    prompt_version: str
    created_at: datetime
    updated_at: datetime
    attempts: int = 0
    max_attempts: int = 5
    worker_id: str = ""
    lease_until: datetime | None = None
    available_at: datetime | None = None
    last_error_type: str = ""
    task_id: str = ""
    escalation_reason: str = ""


@dataclass(frozen=True, slots=True)
class GovernanceDecision:
    candidate_id: str
    expected_revision: int
    decision: GovernanceDecisionKind
    reason_codes: tuple[str, ...]
    confidence: float
    governor_version: str
    prompt_version: str
    policy_version: str
    relation: str = ""
    target_claim_id: str = ""


@dataclass(frozen=True, slots=True)
class GovernanceAudit:
    decision_id: str
    job_id: str
    candidate_id: str
    expected_revision: int
    decision: GovernanceDecisionKind
    outcome: GovernanceOutcome
    actor: str
    reason_codes: tuple[str, ...]
    created_at: datetime
    actual_revision: int | None = None


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
    prompt_allowed: bool = True
    embedding_allowed: bool = True


@dataclass(frozen=True, slots=True)
class MemoryIndexJob:
    memory_type: str
    memory_id: str
    content_hash: str
    attempts: int = 0
    worker_id: str = ""
    lease_until: datetime | None = None
    max_attempts: int = 5


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
class QueryPlan:
    """不可变查询计划。

    严格 FTS、宽松 Pattern 与语义通道共享同一份查询产物；辅助工作上下文
    (objective/current-step) 只进入 ``embedding_text``，绝不扩大严格或 Pattern
    文本匹配范围。``summary`` 仅包含可安全持久化的计数与标志，不记录 query 正文副本。
    """

    primary_text: str
    embedding_text: str
    fts_match: str
    pattern_terms: tuple[str, ...]
    fts_term_count: int
    pattern_term_count: int
    pattern_truncated: bool
    enabled_fields: tuple[str, ...]
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChannelHit:
    """统一通道命中契约。

    融合只消费 ``normalized_relevance`` 与 ``rank``；``raw_score`` 仅用于安全诊断，
    禁止进入跨 lane 加法。``identity`` 是跨通道去重用的稳定记忆标识
    ``(item_type, item_id)``。
    """

    identity: tuple[str, str]
    item: MemoryItem
    lane: str
    rank: int
    normalized_relevance: float
    raw_score: float | None = None
    reason: str = ""


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
            f"- {statement.content} [claims:{','.join(statement.claim_ids)}]"
            for statement in self.statements
        )
