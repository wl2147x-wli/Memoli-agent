## Context

当前个人记忆在线链路已经能够显式写入 Claim、投影版本化 Card、从已完成 Trajectory 构建 Episode，并通过后台维护生成可重建语义索引。离线整理侧则只有 `MemoryConsolidator`、`consolidation_runs` 和 candidate-only 原子提交：Runtime 仍传入 `memory_consolidator=None`，`CandidateExtractor` 没有正式实现，`start_long_term_update` 只把 pending 请求放进 `WorkingStateStore.requests` 进程内字典，且没有 Worker 消费。Episode 投影发生在出站构造前，Card/Embedding 维护由主消息泵串行等待；Job 领取后缺少租约，进程中断可能留下永久 `running` 状态。

本变更跨越 Memory、Trajectory、Tool、SubAgent、Runtime 生命周期、配置和 CLI 诊断。必须继续满足三条约束：Trajectory 是不可变权威证据；Extractor、离线 Worker 和普通 Assistant 不能直接把隐式提取发布为正式事实，低风险自动批准只能由独立 Governance SubAgent 提议并通过确定性 Policy Gate；离线失败不能阻塞普通 Agent Turn 或破坏已发布记忆。

## Goals / Non-Goals

**Goals:**

- 交付持久、幂等、可恢复的长期整理请求和独立离线 Worker。
- 只从已完成、已脱敏、授权 scope 内的 Trajectory 读取提取输入，并对每个 Candidate 回查证据。
- 提供可替换且版本化的 Extractor、结构化 Candidate、相关现有记忆检索与冲突/时态关系阶段。
- 保证隐式结果先进入 candidate，由独立 Governance SubAgent 按风险和证据分级审核，并为升级候选提供用户/人工 approve、reject、edit/correct 治理闭环。
- 让 Card、Episode 和 Semantic Index 的派生维护具有租约恢复、有界重试、dead-letter、批处理和安全诊断。
- 将非必要派生工作移出用户回复和下一轮 turn 的关键路径。

**Non-Goals:**

- 不允许 Extractor、离线 Worker、普通 Assistant 或未经 Policy Gate 的治理模型直接发布 active/approved/frozen 记忆。
- 不自动修改 Prompt、Skill、代码、工具 Schema 或模型参数。
- 不把 Assistant 文本、派生前缀、摘要或远程内容本身当作用户事实证据。
- 不在本变更中实现 Skill Learning、Evolution Lab、后训练、RAPTOR、GraphRAG 或共享知识库。
- 不要求外部消息队列、外部向量数据库、GPU 或新的常驻服务。
- 不要求删除现有 Claim、Card、Episode、Trajectory 或改变其稳定 ID。

## Decisions

### 1. 离线请求和任务状态归属 `memory.db`

新增 schema-versioned `long_term_update_requests`，并扩展派生 Job 状态，而不继续把请求放在 `WorkingStateStore` 进程内字典。请求至少保存 request ID、来源类型、trace/session/scope、选择边界、状态、优先级、attempts、worker/lease、版本指纹、时间和安全错误分类。

选择 `memory.db` 是因为请求的消费者、候选和 consolidation run 具有同一事务与保留边界；Working State 仍只保存当前任务语义状态。替代方案是独立 `jobs.db` 或外部队列，但当前单机 SQLite-first Runtime 不需要额外部署复杂度。

状态机为：

```text
pending -> running -> completed
                   -> retry -> running
                   -> dead-letter
pending/running -> cancelled（仅在尚未提交候选时）
```

Worker 领取时使用事务和租约；启动时把 lease 已过期的 `running` 恢复为 `retry`。永久配置/Schema/权限错误进入 dead-letter；短暂 Provider/锁/网络错误按有界指数退避重试。

### 2. Worker 是 Runtime 管理的独立 asyncio 生命周期组件

Bootstrap 在 `memory.enabled && consolidation_enabled` 且 Extractor 配置有效时创建 `OfflineMemoryWorker`。Application 按依赖顺序启动和停止它；Worker 使用有界轮询加本地 wake event，在没有新 turn 时也能排空积压。在线工具只持久化请求并唤醒 Worker，不等待提取。

Episode、Card 和 Semantic Index 维护复用同一派生维护调度边界，但不同 Job 类型保持独立状态和批次。远程 Extractor/Embedding I/O 不在 AgentLoop 的消息泵中 `await`。关闭时停止领取新任务，给当前事务有界完成时间，未完成租约由下次启动恢复。

替代方案是继续在每轮后调用 `maintenance_tick()`；该方案简单但会阻塞下一轮、无法在空闲时排空，也无法跨崩溃恢复，故不采用为正式路径。保留一次性 `maintenance_tick()` 仅作为测试/运维适配器。

### 3. Worker 内部从权威 Trajectory 构造输入

持久请求只保存 trace ID、明确 trace 集或已提交轨迹游标，不保存调用者提供的任意 Segment 正文。Worker 在处理时只选择存在结束事件的完整 Trace，读取脱敏后的受管 payload，并生成包含 source refs、role、时间和内容哈希的不可变输入快照。

自动批次按 scope 维护“最后成功消费位置”；显式请求默认只覆盖关联当前 Trace，除非治理入口明确请求更大范围。消费 checkpoint 与 Candidate/Relation/Run 在同一事务中提交，提取或验证失败不推进。

不完整 Trace、已删除/无权访问的来源和 scope 不一致请求被拒绝或跳过，并记录不含正文的原因。

### 4. Extractor 是版本化端口，输出固定结构

定义异步批量 Extractor 端口，输入为权威 Source Segment，输出为固定 Candidate Draft。每个批次记录：extractor name/version、schema version、prompt/policy version、provider/model（若适用）、segmenter version 和输入内容哈希。幂等批次键包含 scope、来源集合/范围和上述版本指纹，因此升级 Extractor 后可显式重跑而不与旧批次冲突。

Candidate Draft 支持：content、fact type、subject/card kind、可选 entity/predicate/value、validity、importance、confidence、sensitivity、explicitness、evidence locators 和关系提示。自由文本 content 始终保留；结构字段是可选增强，不强迫所有事实三元组化。

默认配置继续关闭 consolidation。启用时必须选择明确 Extractor；测试提供 deterministic Extractor，正式运行可使用本地或 OpenAI-compatible adapter。密钥只从环境变量读取。

### 5. Evidence Verifier 位于 Extractor 与提交之间

Extractor 输出不能直接写库。Verifier 必须回查每个 evidence locator：source Trace/Message 存在、Trace 已完成、role 符合声明、quote/offset 与脱敏权威文本一致、source hash 匹配、scope/权限允许且敏感策略允许处理。

`explicit-user` Candidate 至少有一个逐字匹配的 user message 证据；Assistant、Tool Result 可作为事件/结果证据，但不能单独证明用户偏好或关系。上下文前缀、Card、摘要和 Embedding 不能成为原始证据。任何必需证据失败使整个批次不提交，并记录安全错误分类。

### 6. 抽取与关系解析分成两阶段

第一阶段只从 Source Segment 抽取 Candidate Draft；第二阶段使用 Candidate 的 scope、entity、predicate、时间和文本检索当前及历史 Claim，确定 exact duplicate、supports、corrects、contradicts、supersedes 或独立事实。关系目标必须存在于同一允许 scope，并通过生命周期校验。

确定性 exact hash 去重先执行；语义相似只生成关系建议，不自动删除或覆盖历史。无法可靠消歧时保留独立 candidate 并将 governance job 标记为 `needs-user-review`，不猜测 target ID。

事实归并按以下优先级执行，后续层不得绕过前一层的确定性结论：

1. **Run 幂等**：相同 scope、来源范围和完整版本指纹复用既有成功 run。
2. **精确重复**：同 scope 的规范化正文 hash 与 live Claim 相同，复用既有 Claim，并用 `(claim_id, evidence kind, evidence ref_id, locator/hash)` 幂等补充新 Evidence；记录 duplicate 审计，不创建第二个 Candidate、governance job 或 Card statement。
3. **语义等价/supports**：结构化事实槽位和含义相同但措辞不同，关系解析器生成 `supports`；治理通过后优先把新 Evidence 合并到既有当前 Claim并记录来源关系，而不是保留第二个当前近义 Claim。只有 Evidence 指向不同独立事实时才保留新 Claim。
4. **纠正/替代**：相同事实槽位的值不一致但有明确纠正意图或不重叠有效时间，生成带确定目标 ID 和 expected revision 的 `corrects`/`supersedes` 方案；批准事务必须同时将新 Candidate 置为 approved、旧 Claim 置为 superseded、保存关系和审计并登记一次 Card/Index 投影，任一步失败全部回滚。
5. **未决矛盾**：同一事实槽位和重叠有效时间存在不兼容值，但证据不足以确定优先级时，只保存 `contradicts` 与 `needs-user-review`；新 Candidate 不得批准、旧 Claim 不变且不得触发正式 Card 投影。

“事实槽位”至少由 scope、subject/card kind、可用的 entity/predicate 和有效时间区间构成；缺少结构字段时可以使用规范化文本检索生成候选关系，但不能据此自动执行 semantic merge、supersede 或删除。Evidence 合并必须保留每条来源定位、哈希、时间和 extractor/run 版本，不把多条证据压成不可审计摘要。

### 7. 独立 Governance SubAgent 执行分级自治治理

Candidate 与 consolidation run 在同一事务提交时，同时在 `memory.db` 登记权威 `governance_job`。治理调度器按租约领取 job，调用现有 SubAgent Runtime 中新增的 `memory-governor` Profile；通用 `task-graph.db` 仅保存执行轨迹和 task ID，不作为 Candidate 决策的事实源，从而避免跨库事务决定正式记忆状态。

`memory-governor` 采用最小权限：只能读取目标 Candidate、已验证 Evidence 和同 scope 相关 Claim，并只能通过专用 `memory_candidate_decide` 提交固定 JSON 决定；不得使用通用 `memory_manage`、文件写入、网络、代码执行或再次委派。决定至少包含 candidate ID、expected revision、approve/reject/needs-user-review/defer、置信度、reason codes、关系判断以及 governor/prompt/policy 版本。原始轨迹文本作为不可信数据传入，不能扩展工具权限或覆盖治理指令。

自动批准采用分级规则：低风险显式事实在证据有效、无冲突且类型位于白名单时可以批准；低风险隐式偏好必须至少有两条来自独立已完成 Trajectory 的一致证据、无反向证据、时间有效且满足配置阈值。凭据、身份认证、医疗、法律、财务、精确身份/地址、关系推断、高风险决策、敏感策略禁止项、与正式记忆冲突以及任何涉及 frozen 记忆的候选必须进入 `needs_user_review`。

自动拒绝只适用于客观无效证据、越权来源、非法 schema、确定性重复或禁止存储类型；语义不确定、证据不足或关系无法消歧时不得自动拒绝，而应 defer、继续积累证据或升级用户。Extractor、Offline Worker、普通 Assistant 和 Governance SubAgent 本身都不能直接写 Claim 状态；确定性 Policy Gate 重新校验 Evidence、scope、风险、冲突、策略版本和 `expected_revision` 后才执行决定。

批准使用 `candidate_id + expected_revision` 的 compare-and-set，并在 `memory.db` 单事务内记录 actor `memory-governor:<profile-version>:<task-id>`、决定、理由、Evidence、模型/prompt/policy 版本和新状态，再登记 Card/Index Job。决策幂等键包含 candidate ID/revision、governor version 和 policy version；用户并发修改导致 revision 过期时决定标记 stale 且不得覆盖新状态。

Claim 生命周期继续只表达 `candidate -> approved/rejected/...`；`pending/running/retry/completed/dead-letter/needs-user-review` 属于 governance job，Card/Index 另用 projection job 状态。这样排队或审核失败的 Candidate 仍保持 candidate，不会被默认召回。Frozen 仍不能由自动主体覆盖。

用户保留最终治理权。个人记忆管理合同支持 candidate list/show、approve、reject、重新审核和带新 Evidence 的 correct/edit；用户决定可以处理 `needs_user_review` 或纠正自动决定，并完整保留审计。CLI 状态区显示有界的待用户审核数量，提供 `/memory candidates`（或等价命令）查看列表与详情，并通过治理服务提交批准/拒绝，不直接操作 SQLite。CLI/API 返回 request/run/candidate/governance stable ID 和当前状态，不返回越权正文。

### 8. 派生 Job 使用统一租约与 dead-letter 语义

长期请求、Card Projection 和 Semantic Index Job 都保存 state、attempts、last_error_type、available_at、worker_id、lease_until 和 updated_at。领取、完成、失败、取消和恢复使用条件更新避免双消费。达到 `max_attempts` 或遇到永久错误后进入 dead-letter；运维入口可以检查并显式重试。

Embedding Worker 按 provider batch 能力真正批量发送文本；同一来源只保留当前 embedding 模型/版本的索引，切换或重建时清理旧索引，不提供历史 embedding 版本回退。Episode/Claim 的 `prompt_allowed`、`embedding_allowed` 和敏感等级在进入远程 Provider 前再次校验。

Card 继续作为 Claim 的可重建物化视图而非新的事实源。Card projection key 固定为 `(scope kind, scope id, subject, card kind)`；Worker 只选择同 key、带 Evidence、状态为 active/approved 且当前有效的 Claim，并先排除被当前 approved Claim 通过 `corrects`/`supersedes` 支配的目标。若同一事实槽位仍有两个无法排序的不兼容当前 Claim，Card job 必须安全失败或进入 `needs-user-review` 诊断，不得把矛盾语句同时发布。

默认 Card Generator 保持确定性：按稳定顺序把 Claim 原文生成 statement，每条 statement 保存其完整 Claim ID 集并通过直接支持校验。相同 projection key 复用稳定 Card ID；规范化 title/content 与有序 Claim ID 集均未变化时返回 unchanged，发生变化时追加不可变 CardVersion、替换当前 supports 关系并登记语义索引 job，旧版本继续可审计。Frozen Card 不被自动重建；Card 构建和索引失败不得回滚已批准 Claim。

### 9. 召回采用 Card-first 分层路由而不是 Card-only

Card 是稳定事实的低噪声入口，Claim 是权威事实和生命周期，Evidence/Trajectory 是依据，Episode 是事件历史。默认 `auto` 路由先按查询意图选择首选类型：稳定画像、偏好和项目概览使用 Card-first；精确值、来源、当前性和高风险查询使用 Claim-first；历史事件和过程使用 Episode-first；无法可靠分类时以较小预算并行检索 Card、Claim 和 Episode，再执行现有确定性 RRF 与治理过滤。

Card-first 分两阶段执行。第一阶段检索当前 Card 和 Card statement，只把命中的有界 statement 摘要加入候选上下文；第二阶段在用户请求依据/精确值/时间、问题高风险、Card stale/degraded、存在冲突、摘要不足或模型显式请求展开时，沿持久 `statement_id -> claim_ids` 关系读取对应 Claim，而不是对全库重新做一次无约束 Claim 搜索。进一步需要核验时再沿 Claim 的 EvidenceRef 读取授权的原始 Trajectory/message。

为避免解析 Card Markdown 和展开整张 Card 的全部 Claim，CardVersion 发布事务同时维护结构化 `card_statements` 与 `card_statement_claims`。statement 至少保存 statement ID、card/version ID、ordinal、正文、content hash、敏感度与有序 Claim ID；当前版本 statement 可独立进入 keyword/semantic 索引，检索命中必须返回 card ID、version、statement ID 和 Claim refs。旧版本 statement 只用于审计，不进入默认召回。

Claim 直达通道始终保留，并在 Card 不存在、projection pending/retry/dead-letter、Card frozen 且可能滞后、查询要求精确/最新/证据、高风险策略要求核验或 Card 无匹配时启用。该回退只读取 active/approved/frozen 且当前有效的 Claim，并在最终上下文按稳定记忆身份和 Claim refs 去重，防止同时注入 Card statement 与完全相同 Claim 正文。Episode 不挂在 Card 后面，事件型查询直接检索 Episode；需要把事件提升为事实时仍须经过 Candidate/治理流程。

召回合同增加 `retrieval_mode = auto|card-first|claim-first|episode-first|hybrid`、`detail_level = summary|fact|evidence` 和有界 statement/claim/evidence expansion budgets。自动预召回默认使用 `auto + summary`；显式 `memory_recall` 可请求更深层级，但 scope、敏感度、生命周期、总字符预算和降级诊断在每一层都必须重新执行。Card-first 任何阶段失败时必须安全回退而非返回伪完整结果。

替代方案是所有类型始终平行召回；它实现简单但会同时注入 Card 与其 Claim、增加 token 和重复噪声。另一个替代方案是 Card-only；它会在投影延迟、dead-letter、frozen 或精确查询下漏掉权威 Claim，因此不采用。

### 10. 配置保持关闭兼容并显式校验

建议配置：

```toml
[memory]
consolidation_enabled = false

[memory.offline]
poll_seconds = 2.0
batch_size = 4
lease_seconds = 120
max_attempts = 5
retry_max_seconds = 300
auto_scan_enabled = false

[memory.offline.extractor]
provider = "disabled"       # disabled / deterministic / openai-compatible
model = ""
version = "1"
schema_version = "1"
prompt_version = "1"
api_key_env = "MEMOLI_MEMORY_EXTRACTOR_API_KEY"
timeout_seconds = 60.0

[memory.offline.governance]
enabled = true
profile = "memory-governor"
policy_version = "1"
prompt_version = "1"
batch_size = 8
lease_seconds = 120
max_attempts = 5
min_independent_evidence = 2
auto_approve_explicit_low_risk = true
auto_approve_implicit_low_risk = true

[memory.retrieval]
mode = "auto"
detail_level = "summary"
card_statement_limit = 6
claim_expansion_limit = 6
evidence_expansion_limit = 3
direct_claim_fallback = true
```

旧配置缺少新字段时保持 consolidation 关闭或使用保守默认值。`consolidation_enabled=true` 但 Extractor disabled/缺少必需配置时启动失败并给出明确错误，不静默假装离线学习可用。治理启用但 Profile 或策略无效时停止自动批准并把 Candidate 保持为 candidate/安全升级，不得退化为无 Policy Gate 的直接发布。

## Risks / Trade-offs

- **[Extractor 误判形成大量候选]** → 所有隐式输出 candidate-only；增加 Evidence 回查、结构校验、相关记忆对比、needs-user-review 和批准门禁。
- **[语义归并误把两个事实合成一个]** → 只有结构化事实槽位一致且治理通过时才合并 Evidence；缺少结构字段、值/时态不确定或存在反向证据时保留独立 Candidate 并升级用户，所有原始 Evidence 保持可追溯。
- **[远程 Extractor/Embedding 泄露私人信息]** → 分离 prompt/embedding policy，默认关闭远程处理，按 scope/敏感等级过滤，密钥只从环境变量读取，诊断不保存正文。
- **[SQLite 多连接竞争]** → 领取和提交使用短事务、busy timeout 与租约；网络 I/O 不持有写事务；保持有界批次。
- **[Worker 崩溃或重复执行]** → 租约恢复、版本化幂等键、exact source hash 和单事务 Candidate/Run/checkpoint 提交。
- **[候选长期无人审批]** → 由独立 Governance SubAgent 自动处理满足硬规则的低风险候选；CLI 显示 `needs_user_review` 数量并允许用户查看证据和决策，高风险候选不得因积压而放宽门槛。
- **[治理模型错误批准或被 Evidence Prompt Injection]** → 治理 Profile 最小权限、结构化决定、原始文本不可信标记、确定性 Policy Gate、低风险白名单、两条独立证据、CAS revision、完整审计与用户纠正；模型置信度不能单独触发批准。
- **[Extractor 与 Governor 错误相关]** → 使用独立角色、独立 prompt/policy 版本和可选独立 provider/model，Governor 必须读取已回查 Evidence 和相关正式记忆而不是复用 Extractor 的结论文本。
- **[后台任务抢占在线资源]** → 独立协程、低并发、有界批次、Provider 超时和可暂停配置；在线 turn 不等待维护。
- **[Card-first 漏掉最新 Claim]** → 保留 Claim 直达回退，以 projection/job/source revision 暴露 stale/degraded 状态；精确、高风险、最新和证据查询强制展开或直达 Claim。
- **[Card 与 Claim 重复注入浪费上下文]** → statement 级索引和 Claim refs 去重；展开后按配置以 Claim 事实替换或折叠已覆盖的 Card statement，并统一执行字符预算。
- **[大型 Card 语义过宽]** → 独立持久化并索引当前 Card statement，按 statement 命中后只展开关联 Claim，不以整张 Card 向量作为唯一定位粒度。
- **[Schema 增长提高迁移风险]** → 逐版本原子迁移、迁移前备份建议、未知版本 fail-closed、保留旧表和稳定 ID。
- **[Extractor 版本变化导致重复候选]** → 版本化 run 允许重算，但 Claim identity 仍按 scope/source/evidence 去重，并在报告中区分重算与新增事实。

## Migration Plan

1. 增加 memory schema 新版本，原子创建 durable request、governance job/decision、lease/dead-letter 字段和 Candidate 结构元数据；保留现有表、ID 和索引。
2. 迁移现有 `pending/retry/running` 派生 Job：`running` 统一改为可重试并清空旧 worker；ready 保持 ready。
3. 部署代码但保持 `consolidation_enabled=false`，运行 schema、工具兼容、显式记忆和现有召回回归。
4. 使用 deterministic Extractor 和 deterministic Governor 在隔离 workspace 验证 request、Worker、Evidence、Policy Gate、用户升级、Card/Index 和崩溃恢复。
5. 首次启用正式 Governor 时只允许低风险显式候选自动批准，其他候选保持 `needs-user-review`，并保留一键关闭自动批准的回滚路径。
6. 由操作者显式确认低风险显式流程稳定后，再单独启用低风险隐式候选的至少两条独立证据规则；auto scan 继续单独显式开启。
7. 回滚时先停止 Worker；新表可保留未使用，旧 Runtime 只有在支持该 schema 版本时才允许打开。若需要代码级回滚，使用迁移前备份恢复，禁止静默降级 user_version。

## Open Questions

- 正式首版 Extractor 仅复用聊天 Provider 路由，还是必须配置独立 Provider/凭证？设计默认独立配置以隔离成本和数据授权。
- CLI 首版采用 `/memory candidates` 子命令还是 `/memory-review` 独立命令可在实现时按现有命令注册模式选择，但必须提供待用户审核数量、列表、详情、approve/reject 和安全确认，且复用同一治理服务合同。
- 自动扫描应按时间游标还是显式 Trace 序列游标？实现前应以 Trajectory 的稳定排序键确定，避免仅靠时间戳并列丢失。
- 高敏感内容是否允许本地 Extractor？需要在实现时确定敏感等级到 provider class 的默认矩阵，并通过配置测试固定。
