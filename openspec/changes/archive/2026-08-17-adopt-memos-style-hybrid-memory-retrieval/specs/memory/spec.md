## MODIFIED Requirements

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

### Requirement: Ranked and scoped retrieval diagnostics

严格关键词召回 SHALL 保留 BM25 lane 内相关性顺序，所有 SQL lane SHALL 在 scope 和其他可下推 hard filter 后应用上限，并报告 Query Plan 摘要、各 lane 候选/降级、融合贡献以及治理、相对阈值、多样性和上下文预算过滤诊断。

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

## ADDED Requirements

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
