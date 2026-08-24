## Context

当前 `OfflineMemoryWorker._enqueue_auto_scan_request()` 会在每次轮询时选择下一条已完成 trace，因此实际行为是“每个 CLI 回合结束后立即提取”。`TrajectorySourceReader` 又从 root span 的完整 messages 列表构造 user segments，使历史窗口可能在后续 trace 中被重复读取。正式配置启用了 deterministic Extractor，而该适配器把每条用户消息整体当作一个 `explicit-user/profile` Candidate，造成多事实合并、普通问题候选化以及与在线 `memory_manage` 显式写入重复。

治理侧已经让 `memory-governor` Reasoner 使用 `NullTrajectoryStore`，但 `SubAgentRuntimeFactory` 和 `ProfileToolRegistryFactory` 仍分别注入共享 HookBus。当前实测触发路径是 `shell_safety` 的 `TOOL_BEFORE` Hook 在执行回调前，以不存在于主轨迹库的治理 trace ID 写事件，触发 SQLite 外键 `IntegrityError`；ToolRegistry 将该轨迹错误转换为失败结果，四个治理工具因此均无法完成决定。`memory_default` 当前注册的是 `TURN_AFTER`，不是本故障的 `TOOL_BEFORE` 来源。现有 Card/Episode projection 的内部 `ready` 是成功终态而不是 backlog；CLI 诊断未表达这层语义。Embedding 密钥和本地 Endpoint 已由部署侧修复，本设计不修改 Embedding 配置或 Provider 合同。

## Goals / Non-Goals

**Goals:**

- 只有在同一 session 累计 20 个完整闲聊回合，或一个至少完成 10 个成功非内部业务工具调用且满足工具种类/最小耗时条件的长期任务成功结束后，才触发离线轨迹提取。
- 让两个触发路径共享稳定、持久且可恢复的 trace consumption 身份，失败不越过、重启不重复。
- 只把每条 trace 的当前用户回合送入 Candidate Extractor；Extractor 可以输出零个或多个原子事实。
- 不增加单独 Eligibility Gate；“是否有长期事实”继续属于版本化 Extractor 合同。
- 消除在线显式记忆与离线 Candidate 的重复，并强化显式依据的权威性和结构化元数据。
- 完整隔离 memory-governor 的 Trajectory/Hook/ToolRegistry 资源，同时保留 `memory.db` 治理审计与普通 Agent 插件行为。
- 提供治理 dead-letter 的安全重试、consolidation dead-letter 的 quarantine/suppress 生命周期和无歧义的派生状态诊断。

**Non-Goals:**

- 不修改 Embedding 密钥、Endpoint、模型、维度或索引 Provider 实现。
- 不以修复历史 Episode projection `KeyError` 为本变更验收目标；若当前版本仍可独立复现，则通过单独 bugfix change 修复。本变更只保证该错误可诊断、可重试且不阻塞在线对话。
- 不新增独立的规则/模型 Eligibility Gate，也不在触发前检查对话正文是否值得记忆。
- 20 轮是提取调度阈值，不是 Candidate 批准阈值、上下文窗口或对话保留上限。
- 不删除现有正式 Claim、Card、Trajectory 或历史治理任务。
- 不让普通 Assistant、Extractor 或 Worker 绕过 Policy Gate 发布隐式事实。

## Decisions

### 1. 使用逐 trace consumption ledger，而不是单一时间 checkpoint

在 `memory.db` 增加持久 trace consumption 记录，稳定身份至少包含 scope、session ID、trace ID、trigger kind、request ID、state 和时间。`trace_id` 在同一 consumer 下唯一；状态覆盖 observed/reserved/consumed/quarantined/suppressed/released，或实现中等价的有限集合。

单一 checkpoint 无法同时表达两条独立触发 lane：长期任务应立即只消费自己的 trace，而此前不足 20 条的闲聊仍应继续累计。逐 trace ledger 允许：

```text
session cli:local

chat #1 ─┐
chat #2 ─┼── 保持未消费，继续累计到 20
task #3 ─┼── long-task request 立即只绑定 task #3
chat #4 ─┘
```

触发调度器先在短事务中以稳定幂等键创建 request 并 reserve trace；Candidate/Relation/Run/request/consumption 在成功提交时一起改为 completed/consumed。请求 retry 保留 reservation；达到 dead-letter 时转为 quarantined，继续排除其他 lane 的自动重放。操作者可将无 Candidate 的 quarantined 请求 retry 或 suppress；suppressed 是不占活跃 reservation、但仍禁止自动重放的终态。只有独立运维接口显式 force-release 且尚未提交 Candidate 时才能转为 released，普通 Agent 不得执行 force-release。

替代方案是为 chat 和 long-task 各保存一个 cursor；两个 cursor 会交叉重复消费且难以处理失败缝隙，故不采用。

### 2. 闲聊窗口固定取同一 session 最老的 20 个合格未消费回合

每轮 Worker 轮询先查询 `cli:`、具有权威 completed `trace_finished`、尚未出现在 consumption ledger 的 trace。被识别为 long-task 的 trace进入长期任务 lane；其余 trace 按 `(started_at, trace_id)` 稳定排序。达到配置默认 `chat_turn_threshold=20` 时，固定选择最老 20 条创建一个 chat-window request，不把阈值到达后同时出现的无限尾部并入该批次。

这样批次大小稳定、重试输入不变化、版本指纹可复现。完成后下一批重新累计剩余 trace。诊断动态计算每个 session 的 pending chat count，不需要维护容易漂移的独立整数。

旧 `offline_memory_checkpoints` 的最大成功 cursor 在迁移时转为“此前 trace 已消费”的基线，或写入一条 migration watermark；不得因新 ledger 为空而回放旧历史。

### 3. 长期任务用已执行工具事实分类，不使用对话文本猜测

新增 `LongTaskCompletionClassifier`，只读取已提交 trace 的结构事件：

- trace termination 必须是 completed；
- 统计具有稳定 tool call ID 且 `tool_finished` 为成功的调用；
- 去重同一 tool call ID 的重复表现事件；
- 默认至少 10 个业务工具调用；
- 默认至少涉及两个不同业务工具种类，或 trace 已持续至少 60 秒；
- `memory_recall`、`memory_manage`、`start_long_term_update`、Working Checkpoint、请求用户输入和 governance 工具标记为 internal，不计入业务工具数量；
- streamed ToolCall delta、not-executed placeholder、失败/取消调用不计数。

工具类别通过 Tool 的非模型可见 metadata/trait 或中心注册表提供，默认未知自定义工具按 business 处理；不能只靠 UI 文本或工具名散落判断。默认分类条件为 `successful_business_calls >= 10 AND (distinct_business_tool_kinds >= 2 OR elapsed_seconds >= 60)`。分类发生在 trace 完成后，由离线调度器扫描，不增加在线回复延迟。

替代方案是用 Working Checkpoint `active` 或 LLM 文本判断“长期任务”；这些状态可能缺失、过期或不可验证，故不作为权威触发条件。

### 4. `start_long_term_update` 变成触发 hint，不再是立即提取旁路

普通 Agent 调用该工具只写一个按 session/未消费边界幂等的 update intent，并唤醒 Trigger Coordinator。Coordinator 仍必须观察到 20 条闲聊或完成的多工具任务才能创建实际 consolidation request。工具返回 `waiting-for-trigger`、当前 pending chat count 和稳定 hint ID，不声称 Candidate 已生成。

显式用户 `memory_manage remember/correct` 仍是即时、证据约束的正式记忆操作，不受 20 轮阈值限制。运维强制重建属于独立管理接口，不通过模型可见的 `start_long_term_update` 绕过边界。

### 5. Candidate Source 只暴露当前用户回合

Trajectory 保持完整记录，但离线 Candidate Source 新增 current-turn 读取合同。Reasoner 在根 span 属性或输入 envelope 中持久化稳定 `current_user_message_id` 和当前用户消息位置；Source Reader据此只生成当前回合 user SourceSegment。若旧 trace 缺少该元数据，则对 `cli:` trace保守选择模型输入中最后一条 user message，并记录 legacy-selection 诊断。

Episode 投影继续使用完整 timeline，不复用 Candidate current-turn API。远程 Extractor 也只接收选定 user SourceSegment；Assistant、system、Card、历史消息和工具结果不得混入事实提取输入。

### 6. 原子性与“无 Candidate”由 Extractor 合同表达

不增加 Eligibility Gate。Extractor 合同本身负责返回：

- `()`：本批没有长期事实；
- 一个 Draft：单个原子事实；
- 多个 Draft：同一消息中的多个独立事实。

Deterministic Extractor 保持测试/保守适配器，但升级版本后只拆分明确的 `请记住/记住/remember` 原子语句；没有明确标记的普通闲聊返回空集合。正式隐式学习应使用结构化 OpenAI-compatible Extractor。Evidence Verifier 继续逐 Draft 回查精确 quote、offset、hash、role 和 scope。

一个被触发但返回空 Draft 的批次是成功消费，不是错误。Extractor 不得把整段多事实输入或整句问题作为兜底 Candidate。

当前 deterministic 部署升级后经常会产生零 Candidate：显式标记事实通常已经由 `memory_manage remember/correct` 即时写入，而无标记闲聊会返回空集合。这是保守适配器的预期行为，不代表 Trigger Coordinator 故障。需要隐式学习的部署应同步评估结构化 OpenAI-compatible Extractor，并在切换前验证独立凭据、隐私边界、敏感度策略和结构化输出合同。

### 7. 显式写入去重以当前用户证据和事实身份为先

`memory_manage remember/correct` 成功后已经保存 `user_message_id + basis_quote + Claim ID`。Reasoner/Trajectory Tool 事件补齐这一关联，使离线 Source 能知道同一当前用户依据已被处理。Consolidator 在创建 Candidate 前按以下顺序处理：

1. 同 scope、相同稳定用户消息身份和规范化 Evidence quote；
2. 同 scope、同结构事实槽位和值；
3. 同 scope exact normalized content hash；
4. 其余语义相似只生成关系建议，不自动覆盖。

命中已正式 Claim 时复用 Claim并补充缺失 Evidence/审计，不创建 Candidate 或 Governance Job。多个事实共享一条原始用户消息时按各自 `basis_quote` 区分，不能因为一个事实已写入而跳过整条 trace。

### 8. 显式 Claim 以 basis quote 派生权威正文

`MemoryManageTool` 不再信任模型任意提供的 `content`。系统从当前用户逐字 `basis_quote` 确定性去除“请记住”等包装，得到权威事实正文；模型 content 仅可与该规范化结果一致。Evidence 标记 verified，并保留原 quote、current user message ID 和 trace locator。

工具可接受 fact type、subject/entity/predicate/value、sensitivity 等可选结构，但服务端执行枚举、范围和敏感度下限校验；无法确定的字段保持空或保守值，不允许模型把健康/凭据类内容降级为 public。该结构用于去重与治理，不改变用户显式记住事实立即可用的既有语义。

### 9. memory-governor 使用一致的 profile-scoped 非持久化资源边界

SubAgent Runtime 在构建 Reasoner 和 ToolRegistry 前先按 Profile 选择 trajectory store、Reasoner HookBus 和 ToolRegistry HookBus。首版以最小 profile 条件隔离实现，不要求先引入新的 resource bundle 类型：

```text
memory-governor resources
├─ trajectory_store = NullTrajectoryStore
├─ reasoner_hook_bus = None
├─ tool_hook_bus = None
└─ tools = 四个绑定治理工具
```

治理 Profile 不继承外部插件 Hook 注册；其安全边界由四工具 allowlist、绑定 Job、scope 检查和确定性 Policy Gate 提供。Job/Decision/task ID 写入 `memory.db` 和 task graph，足以审计治理结果。普通 SubAgent 和主 Agent继续使用共享 SQLite trajectory 与插件 HookBus。只有在多个内部 Profile 或多条装配路径使资源选择可能漂移时，才提炼轻量 `ProfileExecutionResources`；该抽象不是修复当前 IntegrityError 的前置条件。

替代方案是克隆全部 Hook 注册但替换为 Null sink；这仍让外部插件代码进入最小权限治理进程并增加故障面，故首版选择无 Hook 的专用 Registry。

### 10. dead-letter 重试与诊断使用条件状态迁移

新增治理服务/repository 操作，仅当 Job 为 dead-letter、Candidate 仍是 candidate、scope 匹配且 revision 等于 expected revision 时，才能把同一个 Job重置为 retry。清空 worker/lease、attempts 和当前错误，但保留历史 task graph 与治理失败审计。用户已决定或 revision 变化时返回 stale/not-changed。

Projection 数据库内部 `ready` 保持兼容，不迁移表值；RuntimeInspector/CLI 映射为 `completed` 或 `ready-output`。Backlog 只统计 pending/retry/running，dead-letter 单列，避免把成功 Card/Episode 误报为待处理。

Consolidation request 达到 dead-letter 时转为 quarantined 并保留 trace binding。配置 `dead_letter_stale_after_seconds=86400` 只控制诊断告警：过期请求显示为 `stale-dead-letter`，不得自动 release 或重放。`request_retry` 可将 quarantined 请求恢复为 retry；`request_cancel` 仅在尚未提交 Candidate 时将其转为 suppressed。强制 release 属于独立运维接口，必须保留审计并禁止普通 Agent 调用。

### 11. 权威提交复用现有短事务边界

轨迹读取、current-turn 选择、Extractor 调用、Evidence 校验和提交条目构造在事务外完成。随后复用并扩展现有 `apply_consolidation_batch()` 短事务，在校验 request lease/reservation revision 后一起提交 Candidate、Evidence、关系、Governance Job、Consolidation Run、request completed 和 consumption consumed。任一条件更新失败时整体回滚，request 不完成、consumption 不消费、窗口计数不推进，也不留下部分 Candidate 或 Governance Job。

Episode、Card 构建和 semantic embedding 是可重建派生执行，不要求与 Candidate 权威提交在同一事务内运行；但使派生工作变得必要的 Job 入队记录必须与对应权威状态变化在同一 `memory.db` 事务中写入。替代方案是重写整个 Consolidator 提交边界；现有代码已经具备短事务骨架，因此不采用该高风险重构。

## Risks / Trade-offs

- **[20 轮内的隐式事实不会立即进入离线学习]** → 显式 `remember` 仍即时生效；长期任务完成可提前触发其自身轨迹；CLI 显示距离 chat window 阈值的 pending count。
- **[仅按工具数量误把短任务视为长期任务]** → 默认至少统计 10 个成功业务工具，并要求至少两个工具种类或 60 秒持续时间；排除内部工具，使用 trace 结构而非文本猜测。
- **[长期任务触发与闲聊窗口竞争同一 trace]** → consumption ledger 对 trace 建立唯一 reservation，长期任务 lane 优先，chat lane只选择未保留 trace。
- **[dead-letter reservation 永久占用 trace]** → dead-letter 转为 quarantined；TTL 只告警，运维可 retry 或将无 Candidate 请求 suppress，force-release 仅由独立运维接口执行，避免静默重复提取。
- **[Deterministic Extractor 无法提取隐式偏好]** → 它定位为保守测试/显式标记适配器；需要隐式学习的部署使用结构化正式 Extractor，不用 Eligibility Gate 替代 Extractor。
- **[治理无插件 Hook 降低统一观察性]** → `memory.db` governance audit 和 task graph 作为专用观察面；避免为观察性重新引入主轨迹依赖。
- **[旧 Candidate 已由错误 Extractor 生成]** → 不自动删除或批准；迁移后通过 CLI 用户审核或修复后的治理重试处理，保留证据和审计。
- **[显式 content 规范化改变展示措辞]** → 保留原 basis quote，规范化只去除明确指令包装；Card 可使用确定性正文，历史 Claim 不原地重写。

## Migration Plan

1. 停止 OfflineMemoryWorker 领取新任务，备份 schema 元数据并应用 trace consumption/update intent 迁移。
2. 把旧 auto-scan 成功 checkpoint 转为 migration watermark，使其之前的 trace 视为已消费；现有 pending/retry request 保持原绑定，禁止全历史回放。
3. 部署 current-user trace envelope、长期任务分类器和 Trigger Coordinator，但先保持自动触发暂停，验证计数诊断。
4. 先用真实 SQLite trajectory、`shell_safety` TOOL_BEFORE Hook 和 governor trace 稳定复现外键 `IntegrityError`，再部署 Reasoner/ToolRegistry 双 HookBus 最小隔离；仅在装配确有漂移风险时提炼资源包。
5. 通过治理服务对仍有效的 dead-letter Job进行显式重试；旧 deterministic 误提取 Candidate 不自动批准，由用户审核或治理拒绝。
6. 启用默认 `chat_turn_threshold=20`、`long_task_min_business_tool_calls=10`、`long_task_min_distinct_business_tools=2`、`long_task_min_elapsed_seconds=60` 和 `dead_letter_stale_after_seconds=86400`，确认前 19 个闲聊不入队、第 20 个形成固定批次，少于 10 个业务工具调用不触发长期任务。
7. 明确 deterministic 部署的零 Candidate 批次属于正常成功结果；需要隐式学习的部署在完成隐私与结构化输出验证后切换正式 OpenAI-compatible Extractor。
8. 重建或继续现有派生维护；Embedding 使用已经修复的部署配置，本变更不修改其密钥或 Endpoint。历史 Episode projection `KeyError` 若仍可复现则转入单独 bugfix change。
9. 回滚时停止 Trigger Coordinator；保留 consumption ledger、quarantined/suppressed 审计和 watermark，恢复旧代码时不得删除它们或重新扫描已消费历史。

## Open Questions

- 无。默认闲聊阈值固定为 20，长期任务的默认最小成功业务工具数固定为 10，并要求至少两个不同业务工具种类或 60 秒持续时间；实现必须暴露对应配置但不得改变默认语义。
