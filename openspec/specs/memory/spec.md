# Memory Specification

## Purpose

定义 Memoli 当前基于 Markdown 文件的长期事实持久化、关键词检索、prompt 注入与对话流水沉淀行为，并明确禁用状态和不会自动生成事实记忆的边界。
## Requirements
### Requirement: Explicit fact mutation

系统 SHALL 仅在存在明确用户依据、人工操作或获准离线发布主体时改变个人记忆的正式状态，并 SHALL 为每次操作保存稳定 ID、scope、来源、时间和修订记录。

#### Scenario: Agent writes a fact

- **WHEN** 受治理记忆操作收到关联当前用户消息的非空事实
- **THEN** 系统 SHALL 保存 explicit-user claim、证据引用和相关元数据
- **AND** SHALL 返回稳定 claim ID 和实际发布状态

#### Scenario: Model infers an unstated preference

- **WHEN** 模型推断用户未明确陈述的偏好且没有允许的批准主体
- **THEN** 系统 SHALL 拒绝正式写入或保存为 candidate
- **AND** SHALL NOT 在高风险决策中把该 candidate 当作确定事实

#### Scenario: Memory is disabled

- **WHEN** 个人记忆写入在 memory 系统未启用时被请求
- **THEN** 系统 SHALL 返回 disabled 结果
- **AND** SHALL NOT 创建或修改 memory database

### Requirement: Keyword retrieval and prompt injection

系统 SHALL 通过可替换检索端口对核心 cards、active claims 和情景轨迹片段执行 scope/状态/时间过滤及 FTS5/BM25 检索，并在有匹配时按类型配额和字符预算注入带 ID、来源和召回解释的有限结果。

#### Scenario: Relevant memory exists

- **WHEN** 当前用户消息或任务 checkpoint 与当前有效个人记忆存在相关匹配
- **THEN** 当前回合 SHALL 接收有界的核心概览和/或检索记忆块
- **AND** 每个注入项 SHALL 可解析到 card、claim 或原始 trajectory 证据

#### Scenario: No memory matches

- **WHEN** 检索没有返回当前 scope 下的有效条目
- **THEN** 系统 SHALL NOT 注入空记忆标题、其他用户记忆或伪造记忆

#### Scenario: FTS5 is unavailable

- **WHEN** SQLite 运行环境不支持 FTS5 或主要检索 lane 失败
- **THEN** 系统 SHALL 退化到有界规范化关键词 lane 或返回明确检索不可用状态
- **AND** 检索结果和轨迹 SHALL 标记 degraded 原因

#### Scenario: Sensitive or out-of-scope memory matches textually

- **WHEN** 一条记忆字面相关但不属于当前用户/scope 或调用者无权查看其敏感等级
- **THEN** 检索层 SHALL 在该内容进入模型上下文前将其过滤

### Requirement: Persistent evidence-backed SQLite memory

启用个人记忆后，系统 SHALL 使用 schema-versioned 本地 SQLite 数据库持久化 claims、card versions、证据关系、修订、整理批次和可重建检索索引，并 SHALL 将每条正式或候选记忆绑定到当前用户 scope 和至少一个可审计来源。

#### Scenario: Memory starts for the first time

- **WHEN** 配置的 memory database 尚不存在
- **THEN** 系统 SHALL 原子创建受支持版本的 schema 和检索索引
- **AND** SHALL NOT 修改或删除已有 trajectory 数据

#### Scenario: Runtime restarts

- **GIVEN** claims、cards 和修订已经提交
- **WHEN** Agent 关闭后重新启动
- **THEN** 当前 active 版本、历史 claim 和证据关系 SHALL 仍可查询

#### Scenario: Unknown schema version is found

- **WHEN** memory database schema 高于当前实现支持的版本或 migration 失败
- **THEN** 系统 SHALL 报告明确 schema 错误并停止使用该数据库
- **AND** SHALL NOT 静默删除、重建或降级已有个人记忆

### Requirement: Append-only claims and versioned cards

系统 SHALL 以追加 claim 保存观察到的个人事实演化，并以版本化 card 表达少量当前用户、人物、关系、项目和目标概览；纠正 SHALL 通过新 claim、关系和 card version 表达而不是破坏旧记录。

#### Scenario: New evidence supports an existing card

- **WHEN** 新 claim 与已有 card 一致且通过发布条件
- **THEN** 系统 SHALL 保留新 claim 及其独立来源
- **AND** SHALL 通过新 card version 或支持关系更新当前投影

#### Scenario: A later statement contradicts an older fact

- **WHEN** 用户提供与旧 claim 冲突的当前信息
- **THEN** 系统 SHALL 保存新旧 claim、时间和来源
- **AND** SHALL 通过 corrects、contradicts 或 supersedes 关系标识演化

### Requirement: Bounded core memory overview

系统 SHALL 从当前有效 card 中选择少量核心用户画像作为有界概览，并 SHALL 按 user/scope、状态、冻结优先级、card 数量和字符预算限制常驻内容。

#### Scenario: Core cards are available

- **WHEN** 当前用户存在 active 或 frozen 核心 cards
- **THEN** 当前回合 SHALL 获得不超过配置上限的结构化概览
- **AND** 每个概览项 SHALL 可关联稳定 card ID 和支持 claim

#### Scenario: Core cards exceed the budget

- **WHEN** 候选核心 cards 超过数量或字符预算
- **THEN** 系统 SHALL 优先保留 scope 匹配的 frozen 和明确用户事实
- **AND** SHALL NOT 将被裁剪内容表示为不存在或已失效

### Requirement: Contextual episodic trajectory index

系统 SHALL 能够从已提交的 SQLite trajectory 构建可重建的情景检索片段，并为片段保存 trace 范围、时间、scope、上下文前缀和原始证据解析信息。

#### Scenario: An ambiguous conversation fragment is indexed

- **WHEN** 原始消息脱离其人物、主题、时间或任务背景会产生歧义
- **THEN** 派生索引 SHALL 为搜索文本增加明确标识为派生内容的上下文前缀
- **AND** 实际检索结果 SHALL 仍能解析到未被前缀改写的原始轨迹消息

#### Scenario: Episodic index is rebuilt

- **WHEN** 管理操作删除并重建情景检索索引
- **THEN** 已提交 trajectory SHALL 保持不变
- **AND** 同一索引规则 SHALL 不重复创建相同 trace 范围的片段

### Requirement: Candidate-only offline consolidation

系统 SHALL 在在线 turn 之外按未消费轨迹范围或显式长期整理请求执行幂等 consolidation，并 SHALL 将隐式提取结果先保存为 candidate 而不是直接发布为正式核心记忆。

#### Scenario: A consolidation batch succeeds

- **WHEN** 离线整理选择一组尚未消费的已提交轨迹
- **THEN** 系统 SHALL 逐段提取候选、绑定原始证据、执行 schema/scope/source 校验并记录稳定批次键
- **AND** 隐式偏好、关系或归纳事实 SHALL 保持 candidate 直至满足批准条件

#### Scenario: Consolidation is retried

- **GIVEN** 相同轨迹范围已有成功的 consolidation 批次
- **WHEN** 该批次被重复请求
- **THEN** 系统 SHALL 返回既有结果或幂等跳过
- **AND** SHALL NOT 重复创建相同来源的 claim

#### Scenario: Consolidation fails before commit

- **WHEN** 提取、校验或数据库事务失败
- **THEN** 系统 SHALL NOT 推进已消费 checkpoint
- **AND** 已发布 memory 和原始 trajectory SHALL 保持不变

### Requirement: Temporal conflict and lifecycle filtering

系统 SHALL 支持 candidate、active、frozen、superseded、rejected 和 deleted 生命周期，并在检索阶段结合有效时间、明确纠正、scope 和版本关系选择当前可用记忆。

#### Scenario: User changes a preference

- **WHEN** 用户明确提供与旧偏好冲突的新偏好
- **THEN** 默认检索 SHALL 优先显式、当前有效的新版本
- **AND** 旧版本 SHALL 保留来源但 SHALL NOT 作为当前偏好注入

#### Scenario: A memory is expired or deleted

- **WHEN** claim/card 已超过有效期或状态为 deleted、rejected 或 superseded
- **THEN** 默认检索 SHALL 排除该项
- **AND** 审计查询 SHALL 仍能区分其历史状态和修订原因

### Requirement: User memory governance

用户 SHALL 能按自身 scope 查看、纠正、冻结、删除和导出个人记忆，并 SHALL 获得操作的实际影响范围和来源说明。

#### Scenario: User corrects a memory

- **WHEN** 用户纠正错误记忆
- **THEN** 系统 SHALL 停止默认召回错误版本并保存修正证据
- **AND** SHALL 返回新旧 memory ID 或 version 关系

#### Scenario: User freezes a memory

- **WHEN** 用户冻结一条 active 记忆
- **THEN** 自动 consolidation SHALL NOT 替换或删除该记忆
- **AND** 后续更改 SHALL 需要用户操作或允许的批准主体

#### Scenario: User deletes a memory

- **WHEN** 用户删除其有权管理的个人记忆
- **THEN** 该记忆 SHALL 立即停止默认召回并从普通导出中排除或标记 deleted
- **AND** 系统 SHALL 说明来源 trajectory 是否仍遵循独立保留策略

### Requirement: Safe and idempotent Markdown migration

系统 SHALL 为现有 `MEMORY.md` 提供预览、备份、manifest 和幂等导入，并 SHALL 将 legacy 文件哈希作为外部证据而不伪造 trajectory 引用。

#### Scenario: Legacy memory is imported

- **WHEN** 用户批准从可解析的 `MEMORY.md` 导入
- **THEN** 每个导入 claim SHALL 保存原内容、来源、可解析时间、文件哈希和 `legacy-import` 标记
- **AND** 原 Markdown 文件 SHALL 保持可恢复

#### Scenario: Legacy import is repeated

- **GIVEN** 同一文件内容已成功导入
- **WHEN** migration 再次运行
- **THEN** 系统 SHALL 根据 manifest 和幂等键跳过重复条目

#### Scenario: Legacy history and recent context are encountered

- **WHEN** migration 发现 `HISTORY.md` 或 `RECENT_CONTEXT.md`
- **THEN** 系统 SHALL 备份并在报告中列出它们
- **AND** SHALL NOT 自动把其中的 Assistant 文本、流水或摘要提升为长期用户事实

### Requirement: Scope-safe historical claim identity

系统 SHALL 只在同一 scope 的当前记忆之间去重，并 SHALL 保留 deleted、rejected、superseded 历史而不阻止重新记忆相同内容。

#### Scenario: Deleted content is remembered again
- **WHEN** 用户重新保存同一 scope 中已软删除的内容
- **THEN** 系统 SHALL 创建新的 Claim identity
- **AND** 原删除记录 SHALL 保持历史状态

#### Scenario: Same content exists in another scope
- **WHEN** 两个不同 scope 保存规范化后相同的内容
- **THEN** 系统 SHALL 分别保存且不得跨 scope 复用 identity

### Requirement: Atomic memory mutation and migration

记忆写入、关系改写、consolidation 批次和 schema 迁移 SHALL 原子完成，并在中断后保持可重试状态。

#### Scenario: Consolidation extraction fails midway
- **WHEN** 任一候选提取或验证失败
- **THEN** 本批 Claim、Card 与关系 SHALL NOT 部分提交
- **AND** run SHALL 记录失败原因分类

### Requirement: Explicit memory lifecycle

系统 SHALL 校验 Claim 与 Card 状态转移；历史状态不可复活，Frozen 只允许用户或人工 actor 解冻或删除。

#### Scenario: Automated actor mutates frozen memory
- **WHEN** 非用户 actor 尝试解冻或删除 Frozen 记忆
- **THEN** 系统 SHALL 拒绝状态转移

### Requirement: Ranked and scoped retrieval diagnostics

关键词召回 SHALL 保留 BM25 相关性顺序，在 scope 过滤后应用上限，并报告治理过滤与上下文截断诊断。

#### Scenario: Fallback search spans many scopes
- **WHEN** LIKE fallback 的高排名行包含其他 scope 数据
- **THEN** 系统 SHALL 先完成 scope 过滤再应用候选上限

#### Scenario: Context budget truncates recall
- **WHEN** 召回内容超过注入预算
- **THEN** 结果 SHALL 报告 truncated、omitted_items 和 omitted_chars

### Requirement: Governed personal-memory export

用户导出 SHALL 包含当前 Card 与 Claim 的 scope、状态、敏感级别、证据引用和时间，默认 SHALL NOT 包含 Episode。

#### Scenario: User exports current memory
- **WHEN** 用户请求导出个人记忆
- **THEN** 导出 SHALL 同时包含符合 scope 的当前 Card 和 Claim
- **AND** SHALL 排除 Episode，除非另行请求轨迹导出

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

