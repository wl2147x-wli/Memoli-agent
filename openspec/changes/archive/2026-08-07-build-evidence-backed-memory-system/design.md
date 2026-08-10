## Context

Memoli 已具备串行 Agent Loop、完整 SQLite trajectory、有限 session history，以及参考 GenericAgent 实现的 `update_working_checkpoint`。当前个人记忆仍由 `MEMORY.md`、`HISTORY.md`、`RECENT_CONTEXT.md` 和简单字符串匹配组成：长期事实缺少稳定 ID、类型、scope、来源关系和版本；`HISTORY.md` 又与更完整的 SQLite trajectory 重复。现有 `WorkingStateStore` 只保存自由文本投影，是否重新注入取决于具体上下文路径，且不能区分 Harness 可确定计算的硬状态与模型总结的软状态。

本设计将《AI Agent Book》中的三项结论落到 Memoli：第二章的 Agent 状态栏应尽量由代码增量维护并置于上下文末尾；第三章的高级用户记忆需要“少量结构化概览 + 大量原始细节按需检索”；第八章要求在线执行只记录证据，离线流程再产生受验证的候选更新。GenericAgent 的价值在于 checkpoint 不经过相似度检索，而是在后续模型决策中直接可见；本设计保留这个机制，但把它统一到 Agent Loop 的 prompt 装配边界。

约束包括：Python 3.11+、标准库 SQLite、当前不做并发、不得把评价标签写入原始轨迹、工具和存储适配器保持可替换、用户可审查和修正个人记忆。

## Goals / Non-Goals

**Goals:**

- 明确分离 working state、session context、trajectory evidence、personal memory 和 procedural skill。
- 每次模型调用前直接注入最新、有界、可区分来源的工作状态，而不对工作记忆做语义检索。
- 用 SQLite claims、card versions、evidence links 和 FTS5 建立可追溯、可更新、可回滚的个人记忆。
- 让少量核心画像常驻概览，大量事实、事件和原始对话细节按需检索。
- 以追加 claim 和新 card version 表达纠正与冲突，不破坏旧证据。
- 使显式用户记忆操作、离线候选整理和正式发布具有不同权限和生命周期。
- 提供 Markdown 兼容迁移、禁用/降级行为、检索解释和三层记忆评测入口。

**Non-Goals:**

- 不实现 embedding、向量数据库、reranker、GraphRAG 或任意生成代码形式的 User as Code。
- 不在本 change 自动生成或发布 Skill、Prompt、工具实现和模型参数更新。
- 不为原始轨迹增加 reward、成功标签、错误归因、Rubric 或训练标签。
- 不实现主动通知、多用户共享知识库、跨设备同步或云端 memory provider。
- 不把所有历史对话压缩后复制到个人记忆数据库。

## Decisions

### 1. 五类状态具有独立职责

- Session context：当前会话的有界原始消息窗口。
- Working state：当前任务的目标、约束、进度、预算和运行状态。
- Trajectory：append-only 的完整在线运行证据。
- Personal memory：关于用户、相关人物、项目、目标、偏好和事件的跨会话知识。
- Procedural skill：可复用工作流和操作规则，继续由 Skill/SOP 能力管理。

选择按职责分离，而不是以一个通用 `memory_type` 混存所有内容，因为五者的写入权限、寿命、检索方式和删除语义不同。特别是一次成功工具链不等于稳定用户事实，也不等于已经验证的 Skill。

### 2. 工作记忆采用“确定性硬状态 + 语义 checkpoint”

Harness 根据真实运行事件增量投影硬状态：task/session 标识、迭代与时间预算、工作目录、最近工具及状态、连续失败、重复动作、已验证产物和结构化 TODO。模型不得直接声明这些字段。

`update_working_checkpoint` 只更新软状态：目标、用户约束、当前步骤、进展、关键发现、失败方案、下一步和相关 SOP/资源。更新采用有界替换/结构化 patch 与 revision 检查，不无限追加；每次成功更新进入 trajectory。

替代方案是完全沿用 GA 的单个 `key_info` 字符串。该方案极简，但模型可能把“计划运行测试”写成“测试已通过”，也无法可靠统计失败次数。混合方案保留 GA 的低成本语义便签，同时让可确定计算的信息由代码负责。

### 3. 最新工作状态由 Agent Loop 统一直接注入

所有 Provider 调用，包括首轮、工具结果后的下一轮、重试和 fallback，必须经过同一个动态上下文装配器。装配器在调用前读取最新 checkpoint、从当前 trajectory/turn state 投影硬状态，并渲染唯一的 `<agent_status source="memoli-harness" revision="...">` 块。

状态块置于模型可见上下文末尾，静态 system prompt 不因状态变化而重写。运行时 prompt 只包含最新状态版本；历史版本保存在 trajectory，而不是在上下文中持续累积。选择替换末尾状态，是因为本阶段状态块较小、无并发且清晰性优先，缓存失效只影响尾部动态内容。

### 4. 工作 checkpoint 与长期记忆独立持久化

工作 checkpoint 通过独立 `WorkingStateRepository` 持久化到 workspace 内 schema-versioned SQLite 状态库，进程内保留当前任务缓存。长期 memory 关闭时，checkpoint 和确定性状态栏仍可工作。checkpoint 以 task/session scope、revision、状态和更新时间区分；新任务不自动继承旧进度，显式恢复才重新激活旧 checkpoint。

替代方案是把 checkpoint 放入 `memory.db`。该方案少一个文件，但会让禁用个人记忆同时禁用 Agent Loop 状态，且保留/删除策略耦合，因此不采用。

### 5. `trajectory.db` 是唯一权威运行历史

停止在线追加 `HISTORY.md`。个人记忆只保存指向已提交 trace/event/payload 的引用和必要的内容哈希，不复制完整工具输出。需要 Markdown 历史时从 SQLite 确定性导出。

检索用的 trajectory segment、上下文前缀和 FTS 行均为可重建派生索引；索引损坏不能修改原始 trajectory。Memory、Evolution 和 Post-training 必须通过各自显式流程消费轨迹。

### 6. 个人记忆使用 append-only claims 与版本化 cards

`memory.db` 至少包含：

- `memory_claims`：追加式主张，记录用户 scope、kind、自然语言 statement、可选 subject/predicate/object、发生/观察/有效时间、来源类型、置信度、敏感等级和状态。
- `memory_evidence`：claim/card 到 message、event、trace 或 legacy file hash 的多对多证据链接。
- `memory_cards` 与 `memory_card_versions`：用户、人物、关系、项目、目标等少量结构化概览及当前版本指针。
- `memory_card_claims`：card version 与支持、纠正、冲突或替代 claim 的关系。
- `memory_revisions`：发布、冻结、纠正、删除和恢复审计。
- `memory_items_fts` 与 `trajectory_segments_fts`：可重建 FTS5 索引。
- `consolidation_runs`：输入轨迹范围、幂等键、状态、候选数和错误，不含评价标签。

claim 不原地改写；纠正产生新 claim 和关系。card 更新产生新 version，并保留旧 version。这样兼顾 Mem0 式追加历史和 Advanced JSON Cards 的当前结构化概览。

### 7. 采用“核心概览 + 细节检索”的双层记忆

核心层只包含用户固定、明确要求或高价值且当前有效的少量 card，按配置限制 card 数和总字符，不把整个 `memory.db` 常驻 prompt。默认自动加载 scope 匹配的核心用户/当前项目/长期目标概览。

细节层按当前用户消息、checkpoint objective 和 current step 构造查询，从 active claims、非核心 cards 和 contextual trajectory segments 中检索。复杂的多会话、时间线或证据核对由 `memory_recall` 继续迭代检索。

这种结构比“所有记忆都常驻”更抗 context rot，也比“只做 RAG”更容易发现跨会话关联。

### 8. 第一阶段以 FTS5/BM25 为主并提供确定性降级

不增加分词或 embedding 外部依赖。索引器为自然语言保留原文，并在 Python 中为连续 CJK 文本生成受限字符 n-gram 搜索字段；SQLite FTS5/BM25 提供主要稀疏检索。排序融合字面命中、类型、scope、当前有效性、显式程度和事件时间，不把模型自报置信度作为批准门槛。

如果运行环境缺少 FTS5，系统退化到有界的规范化关键词/LIKE lane，结果显式标记 `degraded`；不得静默返回伪空结果。检索端口保留将来接入 embedding lane 和 RRF 的位置。

### 9. 检索先过滤再注入，并记录解释

检索顺序为：user/tenant scope → status → sensitivity/权限 → valid time → FTS/keyword → 类型与时间重排 → 去重 → card/claim/segment 配额 → 字符预算。失效、deleted、rejected 和 superseded 内容默认不进入 prompt。

结果返回稳定 memory ID、类型、摘要、当前性、来源引用和诸如 `core-card`、`fts-match`、`scope-match`、`current-version`、`degraded-keyword` 的召回理由。轨迹记录查询、lane、候选数、过滤原因、最终注入 ID 和字符数，便于区分“没写入、没召回、召回未使用”。

### 10. 记忆上下文是数据而不是指令

动态记忆块使用明确的 `<memory_context trust="data">` 包装，并声明其中内容仅作为事实参考。网页、邮件、工具输出、历史 Assistant 文本和 LLM 摘要均为不可信证据；它们不得覆盖 system rules，不得直接发布为用户偏好或程序指令。

动态上下文优先级为：当前真实用户/工具交互和安全规则 → 确定性工作状态 → 语义 checkpoint → 显式冻结核心卡片 → 其他核心卡片 → 自动召回 claims → episodic segments。超过预算时从后向前裁剪，不能截断当前用户输入或伪造缺失状态。

### 11. 在线显式操作与离线隐式整理分离

用户明确要求“记住”时，受治理工具可创建 `explicit_user` claim；明确纠正产生 correction/supersede 关系；冻结、删除和导出必须返回实际影响 ID。没有当前用户依据的模型推断只能创建 candidate，不能直接成为 active/core。

普通 turn 提交后只保存 trajectory，不调用 LLM 自动改正式记忆。离线 consolidation 按未消费 trace 范围或显式长期更新请求运行：选择消息 → 逐段提取候选 → schema/source/scope 校验 → 幂等去重 → 冲突关联 → 写 candidate → 按确定性规则或用户批准发布。一次失败不得推进消费 checkpoint。

### 12. 用户记忆与后续学习资产分流

离线分类只决定候选目标，不在本 change 发布其他资产：用户身份、偏好、目标和事件进入 Personal Memory candidate；稳定工作流进入未来 Skill candidate；经过独立评价的轨迹才可能进入评测或后训练数据。原始工具事实不附带 reward 或训练标签。

### 13. 受治理的记忆工具

保留 `memory_recall` 作为只读、多次可调用的显式检索入口。新增统一的受治理管理入口，支持 `remember`、`correct`、`freeze`、`forget`、`list` 和 `export`；写操作必须关联当前显式用户消息或由人工/离线批准主体发起。工具返回结构化状态、受影响 ID、证据引用和失败原因，不允许模型仅凭自己的历史回复制造 verified 事实。

### 14. 配置与适配器

新增或扩展配置：

- `memory.database`、`memory.enabled`、`memory.auto_retrieve_enabled`。
- `memory.core_card_limit`、`memory.core_max_chars`、`memory.retrieval_limit`、`memory.retrieval_max_chars`。
- `memory.consolidation_enabled`、批次阈值和 legacy import policy。
- `working_memory.enabled`、`working_memory.database`、`working_memory.max_chars` 和 stale policy。

`MemoryStore`、`MemoryRetriever`、`MemoryConsolidator`、`WorkingStateRepository` 和 context provider 保持协议边界，由 bootstrap 装配。SQLite schema version 高于实现支持范围、迁移失败或数据库不可写时必须报告明确错误，不静默删除重建。

### 15. 兼容迁移

旧 `MEMORY.md` 的每个可解析条目导入为带 `legacy-import` 外部证据的 claim；保留来源、时间和文件内容哈希。导入是否直接 active 由迁移策略明确配置，默认保持可召回但不自动提升为 core card。`RECENT_CONTEXT.md` 不提升为长期事实，`HISTORY.md` 不复制进 `memory.db`。

迁移先对三个 Markdown 文件生成只读备份和 manifest，再创建数据库并在单事务中导入；幂等键防止重复导入。成功后 Runtime 切换到 SQLite，但不删除旧文件。回滚时关闭 SQLite memory、恢复旧配置和只读文件；新格式产生的变更可导出，不能无损回写为旧 bullet 格式。

## Risks / Trade-offs

- [状态栏错误会被模型高度信任] → 硬状态只从已提交事件和工具结果投影；对状态投影建立一致性测试和准确率指标，投影失败时显示 unavailable 而不猜测。
- [工作 checkpoint 仍可能包含模型误判] → 与硬状态分区渲染，限制字段和长度，禁止用软 checkpoint 证明任务已完成。
- [claims/cards 两层增加模型复杂度] → 第一版限制 card 类型和关系种类，所有投影可从 claims/revisions 重建，并用 repository 隔离 SQL。
- [FTS5 对中文召回不足] → 原文加受限 CJK n-gram、显式二次检索和可观察降级；在三层记忆评测上验证后再决定 embedding。
- [核心卡片常驻导致上下文污染] → 只加载当前 user/scope 的 active card，设置数量/字符硬上限并跟踪注入命中率。
- [离线 LLM 抽取把恶意内容固化] → 隐式结果只进入 candidate，证据与指令隔离，敏感或冲突项需要批准。
- [删除个人记忆与保留审计轨迹存在张力] → `forget` 立即停止召回并留下最小 tombstone；原始 trajectory 的删除遵循独立保留策略，并向用户明确两者差异。
- [多个 SQLite 文件增加运维成本] → 统一 workspace 路径、schema/version 工具、备份 manifest 和诊断命令；保持每个库单一职责。
- [其他 active change 同时修改工具和长期演进设计] → 实施前先同步/归档已完成的工具 change，并以本 change 作为 `design-lifelong-agent-evolution` 中 memory 细化任务的实现 change，避免重复实现。

## Migration Plan

1. 固化当前 Markdown 读写、关键词召回、工作 checkpoint 和 SQLite trajectory 的回归基线。
2. 引入 working state repository、硬状态 projector 和统一动态上下文装配，在不启用新个人记忆时验证每次模型调用均看到最新状态。
3. 创建 schema-versioned `memory.db`、claims/cards/evidence/revision repository 与 FTS5/keyword shadow index，不改变默认召回结果。
4. 运行只读 Markdown 迁移预览，生成备份和 manifest；通过一致性检查后事务导入。
5. 在 shadow 模式比较旧关键词召回与新双层检索，记录 recall、注入字符、延迟和冲突用例结果。
6. 切换 SQLite 为权威个人记忆，停止 `HISTORY.md` 双写，保留 Markdown 只读备份和导出能力。
7. 启用受治理工具与离线 candidate consolidation，先只产生 candidate，再逐步允许明确用户事实自动 active。
8. 若错误率、迁移或性能不可接受，关闭新 memory 路径、恢复旧配置；working status 与 trajectory 保持独立可用。

## Open Questions

- embedding lane、reranker 和 RRF 仅在 FTS5 三层评测完成后另建 change 决定。
- 主动服务规则、确定性日期/聚合检查和通知预算由后续 proactive change 设计，本 change 只保留结构化 card 接口。
- 用户要求删除原始 trajectory 时的物理擦除、备份传播和保留期限需要在 safety-governance change 中进一步定义；本 change 保证 Personal Memory 立即停止召回。
