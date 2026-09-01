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

系统 SHALL 只在同一用户会话累计形成 20 个尚未消费的完整闲聊回合，或一个至少完成 10 个成功非内部业务工具调用且满足工具种类/最小耗时条件的长期任务回合成功完成后，才在在线 turn 之外为对应轨迹创建幂等、版本化 consolidation 请求；系统 SHALL 从当前回合的权威用户输入构造提取批次、回查原始证据，并 SHALL 将非显式正式写入的提取结果保存为 candidate，而不是直接发布为正式核心记忆。

#### Scenario: Twenty completed chat turns trigger consolidation

- **WHEN** 同一 `cli:` session 存在 20 个未被任何整理批次消费、均已成功结束且未被分类为多工具长期任务的用户—Agent 闲聊回合
- **THEN** 系统 SHALL 按稳定顺序为这 20 个回合创建一个持久、幂等的 chat-window consolidation request
- **AND** 少于 20 个合格闲聊回合时 SHALL NOT 自动创建提取请求

#### Scenario: A multi-tool long-running task triggers consolidation

- **WHEN** 一个 `cli:` 回合以 completed 终态结束，且长期任务分类器确认其中至少有 10 个成功完成的非内部业务工具调用，并且至少涉及两个不同业务工具种类或 trace 已持续至少 60 秒
- **THEN** 系统 SHALL 在 trace 提交后为该任务轨迹创建一个持久、幂等的 long-task consolidation request
- **AND** failed、cancelled、needs-user、少于 10 个成功业务调用、未满足工具种类/持续时间条件或仅调用记忆/状态/治理内部工具的回合 SHALL NOT 触发长期任务提取

#### Scenario: Two trigger paths observe the same trace

- **WHEN** 同一完整 trace 同时可能位于闲聊窗口边界并满足长期任务条件
- **THEN** 系统 SHALL 通过稳定 trace consumption identity 只把该 trace 绑定到一个权威 request
- **AND** SHALL NOT 重复提取、重复推进计数或创建重复 Candidate

#### Scenario: A triggered consolidation batch succeeds

- **WHEN** Worker 领取一个由 chat-window 或 long-task 触发的持久请求
- **THEN** 系统 SHALL 只读取请求绑定 trace 的当前用户回合权威输入，执行版本化原子事实提取、schema/scope/source/Evidence 校验、相关记忆对比并记录稳定批次键
- **AND** Candidate、关系、request 状态和 trace consumption 状态 SHALL 在同一 `memory.db` 事务中提交
- **AND** 隐式偏好、关系或归纳事实 SHALL 保持 candidate，直至独立 Governance SubAgent 的决定通过确定性 Policy Gate 或有权用户批准

#### Scenario: Extractor finds no durable memory

- **WHEN** 已触发批次中的问题、闲聊或任务内容没有形成任何长期事实且版本化 Extractor 返回空 Candidate 集
- **THEN** 系统 SHALL 将 request 和对应 trace consumption 正常标记为 completed
- **AND** SHALL NOT 创建占位 Candidate、治理 Job、Card statement 或失败诊断

#### Scenario: Consolidation is retried

- **GIVEN** 相同 scope、触发类型、trace 集合和 extractor/schema/policy 版本已有成功 consolidation 批次
- **WHEN** 该批次被重复请求或 Worker 在提交后重启
- **THEN** 系统 SHALL 返回既有结果或幂等跳过
- **AND** SHALL NOT 重复创建相同来源和证据的 Claim、治理 Job或派生投影

#### Scenario: Consolidation fails before commit

- **WHEN** 轨迹读取、原子提取、校验或数据库事务失败
- **THEN** 系统 SHALL NOT 将绑定 trace 标记为 consumed，也不得推进闲聊窗口计数边界
- **AND** 已发布 memory 和原始 trajectory SHALL 保持不变

#### Scenario: Authority commit rolls back atomically

- **WHEN** Worker 已在事务外完成轨迹读取、current-turn 选择、Extractor 调用和 Evidence 校验，但在权威 `memory.db` 提交期间任一 lease、reservation 或 revision 条件更新失败
- **THEN** Candidate、Evidence、关系、Governance Job、Consolidation Run completed、request completed 和 consumption consumed SHALL 在同一短事务中整体回滚
- **AND** 可重建的 Episode、Card 构建或 semantic embedding 执行 SHALL NOT 被纳入该权威事务，但对应派生 Job 的必要入队记录 SHALL 与产生该需求的权威状态变化原子提交

#### Scenario: Runtime restarts before threshold or task completion

- **WHEN** Runtime 在累计闲聊回合不足 20、请求尚未创建或长期任务尚未提交终态时重启
- **THEN** 触发调度器 SHALL 从持久 trace consumption 状态和已完成 trajectory 恢复计数与分类
- **AND** SHALL NOT 丢失合格回合、回放已消费回合或读取未完成 trace

#### Scenario: A consolidation batch succeeds

- **WHEN** 离线 Worker 领取一个持久请求或选择一组尚未消费的已完成轨迹
- **THEN** 系统 SHALL 从权威 trajectory 构造带 source reference 和内容哈希的输入，执行版本化提取、schema/scope/source/证据校验、相关记忆对比并记录稳定批次键
- **AND** Candidate、关系、run 状态和消费 checkpoint SHALL 在同一事务中提交
- **AND** 隐式偏好、关系或归纳事实 SHALL 先保持 candidate，直至独立 Governance SubAgent 的决定通过确定性 Policy Gate 或允许的用户/人工主体批准

#### Scenario: Extractor version changes

- **GIVEN** 相同轨迹范围已有旧 extractor 版本的成功批次
- **WHEN** 操作者用新的 extractor、schema 或 policy 版本显式重跑
- **THEN** 系统 SHALL 创建可区分的新 run 并继续按 scope、来源和证据去重 Candidate
- **AND** SHALL 保留旧 run 的版本、结果和审计状态

#### Scenario: Incomplete or unauthorized trace is selected

- **WHEN** 请求引用未完成、已删除、越权或不属于请求 scope 的 trajectory
- **THEN** 系统 SHALL 拒绝或跳过该来源并记录可审计原因
- **AND** SHALL NOT 将该来源正文发送给 Extractor 或写入 Candidate

#### Scenario: Consolidation is disabled

- **WHEN** `consolidation_enabled` 为 false
- **THEN** 系统 SHALL NOT 启动离线提取 Worker或自动扫描轨迹
- **AND** 显式 Claim 写入、Episode 投影和普通记忆召回 SHALL 保持可用

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

系统 SHALL 在可用时继续通过 keyword、semantic 和 metadata lanes 检索候选、在最终选择前执行治理过滤、按稳定记忆身份去重并使用确定性 Reciprocal Rank Fusion；系统 SHALL 在 `auto` 模式按查询意图选择 Card-first、Claim-first、Episode-first 或有界 hybrid 路由，并 SHALL 支持从当前 Card statement 沿结构化关系按需展开 Claim 和 Evidence。最终上下文 MUST 遵守每类型数量、statement/claim/evidence 展开和总字符预算，并 MUST 暴露稳定 ID、记忆类型、Card/statement/Claim/Evidence 引用、检索原因、路由和降级状态。

#### Scenario: Multiple lanes return relevant memory
- **WHEN** keyword、semantic 和 metadata lanes 为当前路由返回相关候选
- **THEN** 系统 SHALL 按配置的确定性 lane 权重、RRF 常量、类型预算和总预算执行过滤、去重、融合与选择

#### Scenario: The same memory appears in multiple lanes
- **WHEN** 两个或多个 lane 返回相同稳定记忆身份
- **THEN** 最终结果 SHALL 只包含一个项目且诊断原因标识所有贡献 lane

#### Scenario: Candidates have equal fused scores
- **WHEN** 多个合格候选具有相同融合分数
- **THEN** 系统 SHALL 使用文档化的稳定类型、时间和 ID tie-break 顺序

#### Scenario: One retrieval lane is unavailable
- **WHEN** FTS5、Embedding Provider 或 semantic index 不可用
- **THEN** 检索 SHALL 通过剩余 lane 或允许的直接回退继续，标记不可用 lane 为 degraded，并继续执行全部治理与输出预算

#### Scenario: All searchable lanes produce no match
- **WHEN** 检索和硬过滤后没有合格候选
- **THEN** 系统 SHALL 返回带 candidate/filter 计数的空记忆上下文且不得注入空 memory block

#### Scenario: A type quota is not fully used
- **WHEN** 某个记忆类型的合格结果少于配置 quota
- **THEN** 未使用容量 SHALL 只按固定配置的 spillover 顺序重新分配且不得超过总数量或字符预算

#### Scenario: The same snapshot is queried repeatedly
- **WHEN** query、来源快照、Card/statement/index 版本、路由和检索配置均未变化
- **THEN** 重复检索 SHALL 产生相同顺序的稳定 ID、展开关系和降级元数据

#### Scenario: Stable profile query uses Card-first retrieval
- **WHEN** `auto` 路由将查询判定为稳定画像、偏好、配置或项目概览
- **THEN** 第一阶段 SHALL 优先检索当前 Card statement 并只选择有界摘要
- **AND** Card 摘要足够且没有精确、证据、高风险、冲突或降级触发条件时 SHALL NOT 展开全部关联 Claim

#### Scenario: Card statement requires authoritative detail
- **WHEN** 用户请求依据、精确值或时间，查询为高风险，Card stale/degraded/冲突，摘要不足或调用方显式请求 fact/evidence 细节
- **THEN** 系统 SHALL 沿命中 statement 的持久 Claim refs 有界展开当前 Claim，并在需要时继续沿 EvidenceRef 展开授权来源
- **AND** SHALL NOT 通过解析展示 Markdown 或无界全库 Claim 搜索确定 statement 的来源

#### Scenario: Card projection cannot represent the latest fact
- **WHEN** Card 不存在、projection pending/retry/dead-letter、Card frozen 且可能滞后、Card 无匹配或查询明确要求最新权威事实
- **THEN** 系统 SHALL 使用受治理的 Claim 直达回退并报告 Card 降级原因
- **AND** SHALL NOT 因派生 Card 不可用而隐藏有效 active/approved/frozen Claim

#### Scenario: Event query bypasses Card-first routing
- **WHEN** `auto` 路由将查询判定为历史事件、执行过程或某次任务结果
- **THEN** 系统 SHALL 直接使用 Episode-first 检索并保持 Episode 的来源引用
- **AND** SHALL NOT 把 Episode 当作正式用户事实或要求先命中 Card

#### Scenario: Current CardVersion is published
- **WHEN** CardBuilder 发布新的当前 CardVersion
- **THEN** 系统 SHALL 原子保存有序 Card statement、statement content hash 和 statement-to-Claim 映射，并只让当前版本进入默认 keyword/semantic 检索
- **AND** 历史 statement SHALL 保持可审计但不得作为当前结果返回

#### Scenario: Card and expanded Claim overlap
- **WHEN** 最终候选同时包含 Card statement 和其展开的相同 Claim
- **THEN** 系统 SHALL 按稳定 Claim refs 折叠重复事实并只计算一次事实内容预算
- **AND** 结果 SHALL 保留 Card、statement、Claim 和贡献 lane 的可追踪元数据

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

### Requirement: Durable offline-memory requests

系统 SHALL 将长期整理请求持久化为可查询、可恢复的版本化状态，并 SHALL 保存稳定 request ID、来源、scope、trace 选择边界、状态、尝试次数、租约、版本指纹和安全错误分类。

#### Scenario: Runtime restarts with a pending request

- **WHEN** Runtime 在持久请求尚未完成时关闭并重新启动
- **THEN** 请求 SHALL 继续保持 pending/retry 或在租约过期后恢复为可领取状态
- **AND** SHALL NOT 因重启丢失请求或重复提交已完成候选

#### Scenario: Worker crashes while processing

- **WHEN** Worker 在领取请求后未提交结果且租约到期
- **THEN** 系统 SHALL 使请求重新可领取并保留尝试次数及上次错误分类
- **AND** 另一个 Worker SHALL NOT 在有效租约内并发消费同一请求

#### Scenario: Retry budget is exhausted

- **WHEN** 请求达到配置的最大尝试次数或发生永久 schema、权限或配置错误
- **THEN** 系统 SHALL 将请求转入 dead-letter 或等价终态
- **AND** SHALL 允许操作者查看安全诊断并显式重试，而不自动无限循环

### Requirement: Versioned candidate extraction contract

系统 SHALL 通过可替换 Extractor 从权威 Source Segment 生成固定 schema 的 Candidate Draft，并 SHALL 为每个 run 记录 extractor、schema、prompt/policy、provider/model、segmenter 和输入内容版本；Candidate SHALL 支持自然语言事实、事实类型、subject/card kind、可选实体/属性、有效时间、重要度、置信度、敏感等级、explicitness 和 evidence locator。

#### Scenario: Extractor returns a valid draft

- **WHEN** Extractor 为允许 scope 内的完整来源返回符合当前 schema 的候选
- **THEN** 系统 SHALL 保留自然语言事实及提供的有效结构字段并进入证据回查和关系解析
- **AND** SHALL 将 Extractor 版本指纹关联到 run 和 Candidate

#### Scenario: Extractor returns malformed or unknown fields

- **WHEN** Extractor 输出无法按当前 schema 解析、包含未知类别或越界字段值
- **THEN** 本批次 SHALL 校验失败且不得部分提交
- **AND** 系统 SHALL 记录有界错误分类而不持久化原始 Provider 响应

### Requirement: Authoritative evidence verification

离线 Candidate 在提交前 SHALL 回查每个证据定位器对应的已提交 trajectory/message、role、逐字引用或 offset、内容哈希、scope 和访问权限；派生摘要、上下文前缀、Card 或 Assistant 陈述 SHALL NOT 单独证明用户事实。

#### Scenario: Explicit user claim has valid evidence

- **WHEN** Candidate 声明 `explicit-user` 且引用当前 scope 内真实 user message 的匹配原文
- **THEN** 系统 SHALL 保存稳定 Evidence reference、原文定位和来源哈希
- **AND** Candidate SHALL 继续进入提交阶段

#### Scenario: Evidence reference is fabricated

- **WHEN** message/trace 不存在、role 不匹配、quote 不在来源中、hash 已变化或 scope 越权
- **THEN** 系统 SHALL 拒绝整个批次或该规范规定的原子单元
- **AND** SHALL NOT 创建可召回 Candidate 或把越权正文发送给后续 Provider

#### Scenario: Tool or assistant text implies a preference

- **WHEN** 候选用户偏好仅由 Tool Result、Assistant 文本、摘要或上下文前缀支持
- **THEN** 系统 SHALL NOT 将其标记为 explicit-user 或批准为正式用户事实
- **AND** 可保留的事件性信息 SHALL 使用与其实际来源一致的类型和治理状态

### Requirement: Candidate conflict and governance lifecycle

系统 SHALL 在提交 Candidate 前对同 scope 的当前及历史记忆执行确定性去重和相关候选检索，并 SHALL 将支持、纠正、冲突、替代或不确定关系保存为可审计结果；系统 SHALL 为 Candidate 创建持久治理任务，并只允许独立 Governance SubAgent 经确定性 Policy Gate 或有权用户/人工主体批准 Candidate 进入正式状态。

#### Scenario: Candidate exactly duplicates current memory

- **WHEN** Candidate 与同 scope、同来源语义和证据身份的当前 Claim 完全重复
- **THEN** 系统 SHALL 幂等复用既有 Claim、按稳定 Evidence 身份补充尚未存在的来源并记录 duplicate 审计
- **AND** SHALL NOT 创建第二条当前 Claim、重复 governance job、重复 Card statement 或重复派生投影

#### Scenario: Candidate semantically supports an existing claim

- **WHEN** Candidate 与同 scope、相同事实槽位的当前 Claim 含义等价但措辞或 Evidence 不同，且关系解析结果为 supports
- **THEN** 治理通过后系统 SHALL 优先把新 Evidence 幂等合并到既有 Claim并保留来源/run 版本审计
- **AND** SHALL NOT 保留第二条语义等价的当前 Claim，除非 Evidence 证明它们是两个独立事实

#### Scenario: Candidate may contradict existing memory

- **WHEN** Candidate 与相关当前 Claim 在实体、属性或有效时间上冲突但无法确定优先级
- **THEN** 系统 SHALL 保存 candidate 和 `needs-user-review` governance 诊断或冲突关系
- **AND** SHALL NOT 自动 supersede、删除或覆盖现有正式记忆
- **AND** SHALL NOT 为该未决 Candidate 登记正式 Card/索引投影

#### Scenario: Approved correction supersedes an existing claim

- **WHEN** 有权治理决定批准一个具有确定目标、明确纠正意图或可排序有效时间的 corrects/supersedes Candidate
- **THEN** 系统 SHALL 在同一事务中把新 Claim 转为 approved、目标 Claim 转为 superseded、保存关系/actor/Evidence/revision 并登记一次 Card/索引投影
- **AND** 任一 expected revision、frozen、关系、证据或写入校验失败 SHALL 回滚全部状态和派生 job 变更

#### Scenario: Governance SubAgent approves a low-risk explicit candidate

- **WHEN** Candidate 有已验证的显式 user Evidence、属于配置的低风险白名单、同 scope 无冲突且 Governance SubAgent 提交 approve 决定
- **THEN** Policy Gate SHALL 重新校验证据、scope、风险、策略版本和 Candidate revision，并在全部通过后原子转为 approved
- **AND** 系统 SHALL 记录 governor/profile/model/prompt/policy 版本、reason codes、actor 和决定幂等键，再登记 Card/索引投影

#### Scenario: Governance SubAgent approves a low-risk implicit candidate

- **WHEN** 低风险隐式偏好至少由配置数量的独立已完成 Trajectory 一致支持、没有反向证据、时间有效且 Governance SubAgent 提交 approve 决定
- **THEN** Policy Gate SHALL 仅在独立 Evidence 数量至少为默认值二且所有硬规则通过时批准
- **AND** 单一模型置信度、单条行为证据或 Extractor 结论本身 SHALL NOT 足以触发批准

#### Scenario: Candidate requires user review

- **WHEN** Candidate 涉及凭据、身份认证、医疗、法律、财务、精确身份/地址、关系推断、高风险决策、敏感策略禁止项、正式记忆冲突或 frozen 记忆
- **THEN** Governance SubAgent/Policy Gate SHALL 将 governance job 标记为 `needs-user-review` 并保持 Claim 为 candidate
- **AND** CLI/治理接口 SHALL 能向有权用户展示安全摘要和审核入口而不默认召回该 Candidate

#### Scenario: Governance SubAgent rejects an objectively invalid candidate

- **WHEN** Candidate 证据客观无效或越权、schema 非法、确定性重复或属于禁止存储类型
- **THEN** Policy Gate MAY 将 Candidate 转为 rejected 并保存可审计 reason code
- **AND** 语义不确定、证据不足或关系无法消歧 SHALL 改为 defer 或 needs-user-review，而不是自动拒绝

#### Scenario: Governance decision is stale or exceeds authority

- **WHEN** 决定的 expected revision 不再匹配、scope 不一致、策略版本无效或决定试图覆盖 frozen/高风险记忆
- **THEN** Policy Gate SHALL 拒绝状态迁移并记录 stale/denied 结果
- **AND** SHALL NOT 登记 Card/索引投影或覆盖用户并发完成的决定

#### Scenario: User approves a candidate

- **WHEN** 有权用户或人工主体查看来源后批准其 scope 内 Candidate
- **THEN** 系统 SHALL 原子记录 actor、修订、证据和新状态，并登记对应 Card/索引投影
- **AND** 后续默认召回 SHALL 只按正式生命周期和时间规则使用该记忆

#### Scenario: User overrides or corrects an autonomous decision

- **WHEN** 有权用户查看自动治理审计后拒绝、重新审核或使用新显式 Evidence 修正该记忆
- **THEN** 系统 SHALL 通过合法生命周期和版本化关系保存用户决定，不抹除原 Governance Decision
- **AND** 后续 Governor SHALL NOT 使用旧 revision 覆盖用户决定

#### Scenario: User rejects a candidate

- **WHEN** 有权用户或人工主体拒绝 Candidate
- **THEN** Candidate SHALL 进入 rejected 状态并停止默认召回和正式 Card 投影
- **AND** 系统 SHALL 保留最小审计和拒绝 actor，而不删除原始 trajectory

### Requirement: Conflict-safe evidence-backed Card projection

系统 SHALL 将 Card 构建为正式 Claim 的可重建、版本化物化视图；Card SHALL 按 scope、subject 和 card kind 分组，只包含带 Evidence、当前有效且未被正式 corrects/supersedes 关系支配的 active/approved Claim，并 SHALL 保留每条 statement 到 Claim 的直接支持关系。

#### Scenario: Approved claim schedules a card projection

- **WHEN** Claim 被批准或其 Evidence/生命周期改变且影响对应 `(scope, subject, card kind)`
- **THEN** 系统 SHALL 幂等登记该稳定 projection key 的 Card job
- **AND** Candidate、rejected、superseded、deleted、过期或无 Evidence Claim SHALL NOT 进入 Card 内容

#### Scenario: Card projection has unchanged canonical input

- **WHEN** 同 projection key 的规范化 title/content 和有序 Claim ID 集与当前 CardVersion 完全相同
- **THEN** Worker SHALL 返回 unchanged 且不得创建重复 CardVersion 或重复索引 job

#### Scenario: Card projection changes

- **WHEN** 当前有效 Claim 集或确定性 Card 内容相对现有版本发生变化
- **THEN** 系统 SHALL 复用稳定 Card ID并原子追加新 CardVersion、更新当前 supports 关系和登记语义索引 job
- **AND** 旧 CardVersion、历史 Claim 和 Evidence SHALL 保持可审计

#### Scenario: Dominated claim is excluded from a card

- **WHEN** 一个当前 approved Claim 通过正式 corrects 或 supersedes 关系支配旧 Claim
- **THEN** CardBuilder SHALL 排除被支配目标并只渲染当前事实
- **AND** SHALL NOT 在同一当前 CardVersion 中同时展示新旧不兼容值

#### Scenario: Unresolved contradiction reaches projection

- **WHEN** CardBuilder 在同一事实槽位和重叠有效时间发现两个无法排序的不兼容 active/approved Claim
- **THEN** Card job SHALL 安全失败或进入 `needs-user-review` 诊断且保持上一 CardVersion
- **AND** SHALL NOT 发布包含矛盾语句的新版本或把 Card 本身用作解决冲突的事实来源

#### Scenario: Card generator emits an unsupported statement

- **WHEN** Card draft 的语句为空、缺少 Claim ID、引用不可用 Claim或内容不能由所引 Claim 直接支持
- **THEN** 系统 SHALL 拒绝整个 Card draft并保持上一 CardVersion
- **AND** 派生失败 SHALL NOT 回滚或改变权威 Claim

#### Scenario: Frozen card receives an automatic rebuild

- **WHEN** projection key 对应的 Card 状态为 frozen
- **THEN** 自动 CardBuilder SHALL 跳过版本更新并记录安全结果
- **AND** 只有有权用户/人工主体可通过显式治理改变 frozen Card

### Requirement: Recoverable derived-memory maintenance

Card、Episode 和 Semantic Index 等派生维护 SHALL 使用有界批次、租约、可恢复状态、有界重试和 dead-letter 语义，并 SHALL 在没有新用户 turn 时继续按配置排空积压；派生失败不得改变权威 Claim、Card 历史或 Trajectory。

#### Scenario: Derived job is abandoned by a crashed worker

- **WHEN** 派生 Job 保持 running 但租约已过期
- **THEN** 后续 Worker SHALL 安全恢复该 Job 为可重试状态
- **AND** 完成操作 SHALL 使用条件更新防止双重发布

#### Scenario: Remote embedding handles a batch

- **WHEN** 多个允许远程处理的当前来源同时待索引且 Provider 支持批量输入
- **THEN** Worker SHALL 在配置批次与 Provider 限制内合并请求并分别原子发布有效结果
- **AND** 单项失败或过期 SHALL NOT 损坏其他权威来源

#### Scenario: Embedding model or version is switched

- **WHEN** 运维重建语义索引并切换 embedding 模型或版本
- **THEN** 系统 SHALL 清理该来源的旧语义索引并仅发布当前配置对应的索引
- **AND** 旧 embedding 版本 SHALL NOT 继续占用存储或参与召回

#### Scenario: Sensitive source forbids remote processing

- **WHEN** Episode、Claim 或 Card 的敏感策略禁止远程 Extractor 或 Embedding
- **THEN** Worker SHALL 在发出网络请求前过滤该来源并记录不含正文的策略结果
- **AND** 该来源 SHALL 继续通过允许的本地或非语义路径保持可用

### Requirement: Atomic candidate extraction and explicit-memory deduplication

版本化 Extractor SHALL 在一次已触发批次内输出零个或多个原子 Candidate Draft；系统 SHALL 以当前用户回合的逐字 Evidence、已成功提交的显式记忆依据、结构化事实槽位和现有正式 Claim 执行确定性去重，且 SHALL NOT 引入独立的 Eligibility Gate。

#### Scenario: One message contains multiple durable facts

- **WHEN** Extractor 从同一当前用户消息识别多个独立长期事实
- **THEN** 系统 SHALL 为每个事实输出独立 content、事实结构和精确 Evidence quote
- **AND** SHALL NOT 把整段多事实对话保存为单个不可治理 Candidate

#### Scenario: Explicit memory already covers extracted fact

- **WHEN** 当前用户 Evidence 已由成功的 `memory_manage remember/correct` 写入正式 Claim，且 Extractor Draft 与该依据和事实身份相同或等价
- **THEN** consolidation SHALL 复用现有 Claim并幂等补充缺失 Evidence/审计
- **AND** SHALL NOT 创建重复 Candidate、governance job、Card statement 或 index job

#### Scenario: Extractor returns a conversational question

- **WHEN** Extractor 合同把一次性问题或任务请求判定为无长期事实并返回空结果
- **THEN** 系统 SHALL 接受该空批次为成功结果
- **AND** Evidence Verifier、关系解析器和 Governor SHALL NOT 被用于制造占位记忆

#### Scenario: Candidate relation is uncertain

- **WHEN** 原子 Candidate 与正式 Claim 可能支持、纠正或冲突但结构和证据不足以确定关系
- **THEN** 系统 SHALL 保留 Candidate 与不确定诊断并交由治理
- **AND** SHALL NOT 通过文本相似度直接覆盖、合并或发布正式记忆

### Requirement: Recoverable governance and derived-state diagnostics

系统 SHALL 对 governance dead-letter 提供有条件、可审计的显式重试或用户升级入口，并 SHALL 在面向用户的诊断中把成功派生终态与待执行状态清楚区分；任何离线失败不得阻塞主 Agent 回合。

#### Scenario: Governance runtime defect is repaired

- **WHEN** 操作者对仍处于 candidate 且 revision 未变化的 dead-letter governance job 执行 retry
- **THEN** 系统 SHALL 清除旧租约、重置有界尝试状态并重新排队同一个稳定 Job
- **AND** SHALL 保留此前失败任务 ID、错误分类和审计历史

#### Scenario: Candidate changed before governance retry

- **WHEN** dead-letter Job 绑定的 Candidate 已被用户批准、拒绝、修正或 revision 已变化
- **THEN** retry SHALL 返回 stale/not-changed 且不得重新调度旧决定
- **AND** SHALL NOT 覆盖用户状态或登记重复派生任务

#### Scenario: Projection output is ready

- **WHEN** Card 或 Episode projection 的内部状态为 `ready` 且不会再被普通 claim 操作领取
- **THEN** CLI 和运行诊断 SHALL 将其报告为 completed/ready-output，而不是 pending backlog
- **AND** SHALL 分别报告真正的 pending、retry、running 和 dead-letter 数量

### Requirement: Recoverable consolidation dead-letter reservations

系统 SHALL 将失败耗尽的 consolidation request 与其 trace binding 转入可诊断的 quarantine，而不是永久保留活跃 reservation 或按 TTL 自动释放；系统 SHALL 支持有审计的 retry、suppress 和独立运维 force-release，并 SHALL 防止普通 Agent 静默重放同一 trace。

#### Scenario: Consolidation request exhausts retries

- **WHEN** consolidation request 达到最大尝试次数且尚未提交 Candidate
- **THEN** request 和对应 trace consumption SHALL 转为 dead-letter/quarantined，停止占用活跃 Worker backlog
- **AND** 其他触发 lane SHALL NOT 自动重新绑定或提取该 trace

#### Scenario: Quarantined request becomes stale

- **WHEN** quarantined request 超过默认 `dead_letter_stale_after_seconds=86400`
- **THEN** CLI 和运行诊断 SHALL 将其单列为 `stale-dead-letter`
- **AND** TTL 到期 SHALL NOT 自动 retry、release、consume 或重放该 trace

#### Scenario: Operator suppresses an uncommitted dead-letter

- **WHEN** 有权操作者取消一个尚未提交 Candidate 的 quarantined request
- **THEN** request 和 consumption SHALL 转为 suppressed 终态，不再占用活跃 reservation
- **AND** suppressed trace SHALL 保留审计并继续禁止自动重放

#### Scenario: Dead-letter already produced a candidate

- **WHEN** quarantined request 已关联任何已提交 Candidate
- **THEN** 普通 retry/cancel SHALL 返回 stale/not-changed，且不得 release trace binding
- **AND** 系统 SHALL 保留 Candidate、Evidence、治理状态和审计历史

#### Scenario: Operator force-releases a trace

- **WHEN** 独立运维接口在确认没有已提交 Candidate 后显式 force-release quarantined 或 suppressed trace
- **THEN** consumption SHALL 转为 released 并记录 actor、原因和时间
- **AND** 模型可见的普通 Agent 工具 SHALL NOT 暴露该 force-release 能力
