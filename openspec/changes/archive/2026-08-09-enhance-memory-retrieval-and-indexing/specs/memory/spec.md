## ADDED Requirements

### Requirement: Structured memory query context
The system SHALL construct memory retrieval from a structured query that keeps the current user message, working objective, current step, session identity, scope, requested memory types, time boundary, and output budget distinguishable. The current user message MUST remain the primary retrieval intent, while working state is auxiliary context and MUST NOT weaken scope, sensitivity, status, or temporal constraints.

#### Scenario: Current turn is enriched by working state
- **WHEN** a passive turn has a non-empty user message and an available working checkpoint
- **THEN** the query contains the user message as primary text and objective/current-step as separately identifiable auxiliary fields

#### Scenario: Working checkpoint is unavailable
- **WHEN** a passive turn has no usable working checkpoint
- **THEN** retrieval proceeds with the current user message and applicable session/scope constraints without fabricated working-state text

#### Scenario: Auxiliary context conflicts with a hard constraint
- **WHEN** objective or current-step text is similar to memory outside the allowed scope, sensitivity, status, or time boundary
- **THEN** that memory is excluded regardless of its textual or semantic similarity

#### Scenario: Query diagnostics are persisted
- **WHEN** memory retrieval completes for a traced turn
- **THEN** trajectory diagnostics identify which structured context fields and retrieval lanes were used without persisting API keys or embedding vectors

### Requirement: Rebuildable semantic memory index
The system SHALL support an optional semantic index for eligible Card, Claim, and Episode records. Semantic vectors MUST be stored as versioned derived data associated with stable source IDs and content hashes; source memory and original trajectories MUST remain the authoritative data. Source changes SHALL register idempotent pending index work without making the conversational write path depend on embedding availability.

#### Scenario: New eligible memory is committed
- **WHEN** an eligible Card, Claim, or Episode is committed or its searchable content changes
- **THEN** the system registers one idempotent semantic-index job for its current stable ID and content hash

#### Scenario: Pending memory is queried
- **WHEN** a memory record has no ready vector for the configured model, version, dimensions, and content hash
- **THEN** retrieval does not wait for embedding generation and the record remains eligible through non-semantic lanes

#### Scenario: Embedding succeeds
- **WHEN** the index worker successfully embeds the current content
- **THEN** it atomically publishes a ready vector with model, version, dimensions, content hash, and indexed time metadata

#### Scenario: Embedding fails
- **WHEN** the embedding provider is unavailable, times out, or returns an invalid vector
- **THEN** the system keeps the source memory intact, records bounded retry state, and continues retrieval through available non-semantic lanes

#### Scenario: Embedding configuration is disabled
- **WHEN** no semantic provider is configured or semantic retrieval is explicitly disabled
- **THEN** the memory subsystem remains fully usable through keyword and metadata retrieval without requiring a provider credential

#### Scenario: Index version is stale
- **WHEN** a stored vector does not match the configured model, version, dimensions, or current content hash
- **THEN** the vector is excluded from semantic retrieval and the current source is eligible for reindexing

#### Scenario: Semantic index is rebuilt
- **WHEN** an operator or migration requests a full semantic-index rebuild
- **THEN** the system reconstructs derived vectors from authoritative Card, Claim, and Episode sources without changing their IDs, evidence, lifecycle, or current Card versions

### Requirement: Deterministic hybrid memory retrieval
The system SHALL retrieve candidates through keyword, semantic, and metadata lanes when those lanes are available, apply governance filters before final selection, deduplicate candidates by stable memory identity, and fuse ranked lanes with a deterministic Reciprocal Rank Fusion policy. The final context MUST obey per-type count budgets and a total character budget and MUST expose stable IDs, memory types, evidence references, retrieval reasons, and degradation state.

#### Scenario: Multiple lanes return relevant memory
- **WHEN** keyword, semantic, and metadata lanes return candidates for a query
- **THEN** the system filters, deduplicates, fuses, and selects candidates according to configured deterministic lane weights, RRF constant, type budgets, and total budget

#### Scenario: The same memory appears in multiple lanes
- **WHEN** two or more lanes return the same stable memory identity
- **THEN** the final result contains one item whose diagnostic reason identifies the contributing lanes

#### Scenario: Candidates have equal fused scores
- **WHEN** multiple eligible candidates have equal fused scores
- **THEN** the system resolves their order with a documented stable type, time, and ID tie-break sequence

#### Scenario: One retrieval lane is unavailable
- **WHEN** FTS5, the embedding provider, or the semantic index is unavailable
- **THEN** retrieval continues through the remaining lanes, marks the unavailable lane as degraded, and still enforces all governance and output budgets

#### Scenario: All searchable lanes produce no match
- **WHEN** no eligible candidate remains after retrieval and hard filtering
- **THEN** the system returns an empty memory context with candidate/filter counts and does not inject an empty memory block

#### Scenario: A type quota is not fully used
- **WHEN** one memory type has fewer eligible results than its configured quota
- **THEN** unused capacity is reassigned only according to a fixed configured spillover order and never exceeds the total count or character budget

#### Scenario: The same snapshot is queried repeatedly
- **WHEN** the query, source snapshot, index version, and retrieval configuration are unchanged
- **THEN** repeated retrieval produces the same ordered stable IDs and degradation metadata

### Requirement: Governed automatic Card projection
The system SHALL provide a Card projection process that creates or revises Card content only from in-scope, effective, evidence-backed active or approved Claims. Every projected statement MUST be traceable to one or more Claim IDs, and automatic projection MUST preserve Card version history, frozen state, temporal conflicts, and user governance.

#### Scenario: Eligible Claims form a new Card
- **WHEN** eligible Claims share a supported scope, subject, and Card kind and no corresponding Card exists
- **THEN** the builder creates a Card with a first version whose projected statements reference the supporting Claim IDs

#### Scenario: Evidence changes an existing Card
- **WHEN** eligible Claim content changes the projection of an existing non-frozen Card
- **THEN** the builder atomically creates a new Card version, advances the current-version pointer, and preserves all earlier versions

#### Scenario: Projection content is unchanged
- **WHEN** the newly computed projection has the same normalized content and supporting Claim set as the current version
- **THEN** the builder performs no version write and reports an idempotent no-op

#### Scenario: Only candidate Claims exist
- **WHEN** matching Claims are candidate, rejected, expired, out of scope, or lack evidence
- **THEN** the builder does not use them to create or revise a Card and does not change their lifecycle state

#### Scenario: A Card is frozen
- **WHEN** an automatic projection targets a user-frozen Card
- **THEN** the builder leaves the current Card version unchanged and records a bounded skipped reason

#### Scenario: Effective Claims conflict
- **WHEN** two eligible Claims describe a temporal or unresolved contradiction
- **THEN** the projection preserves their evidence and validity distinction instead of silently deleting or declaring either Claim true

#### Scenario: Projection validation or generation fails
- **WHEN** projected text contains an unsupported statement or the optional generation provider fails
- **THEN** the builder rejects the draft, leaves the current Card and Claims unchanged, and records a retryable or terminal bounded error

### Requirement: Automatic contextual Episode projection
The system SHALL automatically and idempotently project each successfully committed runtime trace into one or more bounded Episode search segments. Each segment MUST contain a deterministic context prefix, a reference to original trajectory detail, scope and occurrence metadata, a segmenter version, and a content hash. Episode projection and indexing failures MUST NOT roll back the completed runtime turn or overwrite the original trajectory.

#### Scenario: A trace is successfully committed
- **WHEN** a runtime turn and its complete trace have been durably committed
- **THEN** the system schedules or performs Episode projection using that committed trace as the original evidence source

#### Scenario: A trace is incomplete
- **WHEN** a trace has not reached its durable completion boundary
- **THEN** automatic Episode projection does not publish searchable segments for it

#### Scenario: Context is added to an ambiguous fragment
- **WHEN** a trajectory fragment is too local to identify its session purpose or task step by itself
- **THEN** its searchable segment includes a bounded deterministic prefix derived from available session, current user request, working objective/current-step, and turn outcome fields

#### Scenario: Original episode detail is requested
- **WHEN** a retrieved Episode segment is resolved for detailed use
- **THEN** the system follows its trajectory reference to the original committed messages/events rather than treating the search prefix as original evidence

#### Scenario: The same trace notification is repeated
- **WHEN** Episode projection receives the same trace and segmenter version more than once
- **THEN** stable segment identities are upserted without duplicate searchable Episodes

#### Scenario: Episode projection fails
- **WHEN** the trajectory store is temporarily unreadable or segment construction fails
- **THEN** the completed turn and original trace remain intact, the failure is bounded and observable, and projection can be retried idempotently

#### Scenario: Episode segments are rebuilt
- **WHEN** the segmenter version changes or an operator requests rebuild
- **THEN** the system replaces derived segments for each affected trace using stable versioned rules while preserving the original trajectory and unrelated long-term memory
