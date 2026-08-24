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

系统 SHALL 通过可替换检索端口对核心 Card、当前 Card statement、有效 Claim 和情景 Episode 执行 scope、状态、敏感度与时间过滤，并分别通过严格 FTS5/BM25 lane 和受限短词 Pattern lane 召回文本候选。严格 lane SHALL 保留 BM25 通道内顺序，Pattern lane SHALL 明确标识为宽松召回；最终仅按类型配额和字符预算注入带稳定 ID、来源、召回解释和证据引用的有限结果。

#### Scenario: Relevant memory exists

- **WHEN** 当前用户消息或任务 checkpoint 与当前有效个人记忆存在严格、短词或语义相关匹配
- **THEN** 当前回合 SHALL 接收有界的核心概览和/或检索记忆块
- **AND** 每个注入项 SHALL 可解析到 Card、Claim 或原始 trajectory 证据
- **AND** 召回解释 SHALL 区分 FTS/BM25、Pattern、semantic 和 metadata 的贡献

#### Scenario: No memory matches

- **WHEN** 所有可用 lane 均未返回当前 scope 下的有效条目，或候选全部被 hard filter 与相关性选择移除
- **THEN** 系统 SHALL NOT 注入空记忆标题、其他用户记忆或伪造记忆

#### Scenario: FTS5 is unavailable

- **WHEN** SQLite 运行环境不支持所需 FTS5/trigram 能力或 FTS lane 失败
- **THEN** 系统 SHALL 继续运行受限 Pattern、metadata 和可用的 semantic lane，或在没有任何可用 lane 时返回明确检索不可用状态
- **AND** 检索结果和轨迹 SHALL 标记 `fts` degraded 原因

#### Scenario: Sensitive or out-of-scope memory matches textually

- **WHEN** 一条记忆在 FTS 或 Pattern 上相关但不属于当前用户 scope、状态无效、时间无效或调用者无权查看其敏感等级
- **THEN** 检索层 SHALL 在候选上限和模型上下文选择前过滤该项
- **AND** SHALL NOT 在诊断中泄露该项正文

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

严格关键词召回 SHALL 保留 BM25 lane 内相关性顺序，所有 SQL lane SHALL 在 scope 和其他可下推 hard filter 后应用上限，并报告 Query Plan 摘要、各 lane 候选/降级、融合贡献以及治理、相对阈值、多样性和上下文预算过滤诊断。

#### Scenario: Fallback search spans many scopes
- **WHEN** LIKE fallback 的高排名行包含其他 scope 数据
- **THEN** 系统 SHALL 先完成 scope 过滤再应用候选上限

#### Scenario: Pattern search spans many scopes

- **WHEN** Pattern LIKE 的潜在高排名行包含其他 scope、无效状态、越权敏感度或无效时间数据
- **THEN** 系统 SHALL 先完成可下推 hard filter 再应用候选上限
- **AND** 最终候选与诊断 SHALL NOT 暴露被排除正文

#### Scenario: Retrieval is inspected

- **WHEN** 一次混合检索完成并记录诊断
- **THEN** 诊断 SHALL 包含启用的 query 字段、FTS/Pattern term 数、各 lane 候选数与降级原因、最终项贡献 lane、lane rank、规范化相关性、融合分和聚合过滤计数
- **AND** 诊断 SHALL NOT 包含 embedding 向量、API key 或额外的 query/记忆正文副本

#### Scenario: Context budget truncates ranked results

- **WHEN** 相关候选超过类型、数量或字符预算
- **THEN** 系统 SHALL 保持已选项的确定性相关性顺序并报告被预算省略的项目数与字符数

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

The system SHALL retrieve eligible candidates through separate FTS/BM25, Pattern, semantic, and metadata lanes when those lanes are available. It MUST apply hard governance filters before bounded lane selection, deduplicate by stable memory identity, normalize lane relevance without directly mixing raw BM25 and cosine values, and calculate deterministic fused relevance from the best normalized lane relevance plus a weighted Reciprocal Rank Fusion agreement bonus. It SHALL then apply a relative relevance threshold, multi-lane protection, relevant per-type seeding, deterministic MMR, and final type/count/character budgets. The returned context MUST expose stable IDs, memory types, evidence references, retrieval reasons, and degradation state.

#### Scenario: Multiple lanes return relevant memory
- **WHEN** FTS, Pattern, semantic or metadata lanes return eligible candidates for a query
- **THEN** the system filters, deduplicates, normalizes, fuses and selects candidates according to configured deterministic lane weights, RRF constant, RRF bonus weight, relative threshold, diversity policy, type budgets and total budget

#### Scenario: The same memory appears in multiple lanes
- **WHEN** two or more independent lanes return the same stable memory identity
- **THEN** the final result contains one item whose diagnostic reason identifies every contributing lane and rank
- **AND** the item receives the configured RRF agreement bonus without adding raw BM25 to cosine similarity

#### Scenario: Pattern is the only matching lane

- **WHEN** a candidate is returned only by the relaxed Pattern lane
- **THEN** it SHALL retain the Pattern lane's lower configured trust and remain subject to the relative threshold and diversity selection
- **AND** it SHALL NOT be reported as an FTS/BM25 or multi-lane match

#### Scenario: A short CJK query contains an omitted middle phrase

- **WHEN** a CJK query of at least two characters does not occur contiguously in an eligible memory but one or more of its bounded bigrams occur in order within that memory
- **THEN** the Pattern lane SHALL make that memory eligible as a relaxed candidate within its term and candidate limits
- **AND** the strict FTS lane SHALL remain free to return no match for that expression

#### Scenario: Candidates fall below the relative threshold

- **WHEN** a single-lane candidate's fused relevance is below the configured fraction of the highest eligible fused relevance
- **THEN** the system SHALL remove it before type and context budgets
- **AND** a candidate supported by multiple independent lanes SHALL follow the configured multi-lane protection rule without bypassing hard filters

#### Scenario: Relevant results are redundant

- **WHEN** more eligible candidates remain than the final output budget and their content is mutually similar
- **THEN** deterministic MMR SHALL prefer a relevant but less redundant set using cached compatible vectors or a deterministic textual fallback
- **AND** retrieval SHALL NOT trigger a new embedding request solely for MMR

#### Scenario: A requested memory type has no relevant candidate

- **WHEN** a requested Card, Claim or Episode type has no candidate meeting that type's seed relevance ratio
- **THEN** the system SHALL NOT inject an unrelated item merely to fill that type quota

#### Scenario: Candidates have equal fused scores
- **WHEN** multiple eligible candidates have equal fused relevance
- **THEN** the system SHALL resolve their order by contributing lane count, documented stable type order, time and stable ID

#### Scenario: One retrieval lane is unavailable
- **WHEN** FTS5, Pattern SQL, the embedding provider or the semantic index is unavailable
- **THEN** retrieval SHALL continue through remaining lanes, mark only the unavailable lane as degraded, and still enforce all governance, threshold, diversity and output budgets

#### Scenario: All searchable lanes produce no match
- **WHEN** no eligible candidate remains after retrieval and hard/relevance filtering
- **THEN** retrieval SHALL return an empty memory context with candidate and per-stage filter counts and SHALL NOT inject an empty memory block

#### Scenario: A type quota is not fully used
- **WHEN** one memory type has fewer relevant eligible results than its configured quota
- **THEN** unused capacity SHALL be reassigned only according to the fixed configured spillover order and SHALL never exceed total count or character budget

#### Scenario: The same snapshot is queried repeatedly
- **WHEN** query, authoritative source snapshot, sparse/semantic index versions and retrieval configuration are unchanged
- **THEN** repeated retrieval SHALL produce the same ordered stable IDs and degradation metadata

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

### Requirement: Deterministic memory query planning

系统 SHALL 从结构化 MemoryQuery 一次性构建不可变 Query Plan，区分当前用户主查询、embedding 辅助文本、严格 FTS MATCH 表达式、受限 Pattern terms 和 hard filters。FTS 与 Pattern 的 term 规则 SHALL 共享规范化与 CJK 分段实现，且辅助 working context SHALL NOT 扩大严格或 Pattern 文本匹配范围。

#### Scenario: Query contains CJK and auxiliary working state

- **WHEN** 当前用户 query 包含 CJK 文本且 objective/current-step 非空
- **THEN** Query Plan SHALL 从当前用户 query 生成 FTS 与最多配置数量的 Pattern terms
- **AND** embedding 文本 SHALL 保留字段边界并受长度上限约束
- **AND** objective/current-step SHALL NOT 被当成 FTS 或 Pattern term

#### Scenario: Query is shorter than the trigram window

- **WHEN** 规范化 query 包含长度为两个 CJK 字符或两个 ASCII 字符的 term
- **THEN** Query Plan SHALL 允许该 term 进入 Pattern lane
- **AND** SHALL NOT 为了制造 FTS 命中而向严格 lane 注入无关 unigram OR 条件

#### Scenario: Pattern terms exceed their configured bound

- **WHEN** CJK bigram 和短 ASCII term 数超过 Pattern term 上限
- **THEN** Query Plan SHALL 以确定性顺序截断并在安全诊断中标记 truncation

### Requirement: Rebuildable sparse memory indexes

系统 SHALL 将 Claim、当前 Card/Card statement 和 Episode 的 FTS 搜索结构视为带格式版本的可重建派生数据。schema migration 或显式重建 SHALL 从权威记忆表恢复 sparse 索引，不改变稳定 ID、内容来源、生命周期、Card version、Claim 关系或 trajectory 证据。

#### Scenario: Schema 6 database is upgraded

- **WHEN** runtime 打开受支持的 schema 6 memory database
- **THEN** migration SHALL 在事务保护下创建并回填新 sparse 索引，验证完成后发布新 schema version
- **AND** SHALL NOT 改写或删除权威 Claim、Card、Episode 和证据记录

#### Scenario: Sparse index migration fails

- **WHEN** 新 sparse 索引创建、回填或验证失败
- **THEN** migration SHALL 回滚未完成发布并返回明确错误或可用的降级状态
- **AND** SHALL NOT 以空索引替代已有权威记忆

#### Scenario: Sparse index is explicitly rebuilt

- **WHEN** 索引格式、tokenizer 或 Query Builder 版本变化并请求重建
- **THEN** 系统 SHALL 幂等地从当前权威记录生成同一 stable identity 集合
- **AND** 重建 SHALL NOT 触发记忆治理或生成新的事实

### Requirement: Unified layered retrieval semantics

Card-first、Claim-first、Episode-first 和 hybrid 路由 SHALL 共享同一 Query Plan、hard filters、FTS/Pattern lane 语义和安全诊断。路由只 SHALL 改变目标类型、详情展开和配额；Card-first SHALL 先返回相关 Card statement，并仅在明确请求详情时解析关联 Claim 或证据。

#### Scenario: Card-first finds a relevant statement

- **WHEN** Card-first 路由通过共享 FTS 或 Pattern lane 找到相关 current Card statement
- **THEN** 系统 SHALL 先返回该 statement
- **AND** 仅当 detail level 要求事实或证据时 SHALL 展开关联 Claim/证据

#### Scenario: Card-first has no relevant statement

- **WHEN** Card-first 路由没有通过共享相关性策略保留任何 Card statement 且 direct Claim fallback 已启用
- **THEN** 系统 SHALL 使用同一 Query Plan 运行 Claim-first fallback
- **AND** 诊断 SHALL 明确记录实际路由与 fallback 原因

