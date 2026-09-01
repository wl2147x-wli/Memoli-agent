## 1. 配置、触发合同与数据库迁移

- [x] 1.1 在 memory offline 配置中加入 `chat_turn_threshold=20`、`long_task_min_business_tool_calls=10`、`long_task_min_distinct_business_tools=2`、`long_task_min_elapsed_seconds=60` 和 `dead_letter_stale_after_seconds=86400`，完成正整数校验、旧配置默认值和示例配置更新，且不改动 Embedding 配置
- [x] 1.2 定义带类型的 trigger kind、trace consumption、update intent、turn classification 和触发诊断合同，固定 chat-window/long-task 的稳定身份字段以及 observed/reserved/consumed/quarantined/suppressed/released 有限状态
- [x] 1.3 增加 `memory.db` 原子迁移，创建逐 trace consumption 与 session update intent 持久表、唯一约束、状态索引、TTL 诊断和审计时间字段
- [x] 1.4 将旧成功 auto-scan checkpoint 迁移为不会回放历史的 watermark/consumed baseline，并保证新库、旧库和重复迁移幂等
- [x] 1.5 实现 trace observe/reserve/consume/quarantine/suppress/release、按 session 统计未消费闲聊、绑定 request 和查询触发状态的 repository API；force-release 仅属于独立运维入口
- [x] 1.6 为 consumption reservation 与 request 创建实现单事务幂等键和条件更新，保证并发 Worker/双触发路径只能领取同一 trace 一次
- [x] 1.7 添加 schema 版本、旧 checkpoint 迁移、唯一约束、事务回滚、并发 reservation 和重启恢复测试

## 2. 当前用户回合与长期任务分类

- [x] 2.1 在主 Agent 根 Span/trace envelope 中保存稳定 `current_user_message_id`、当前用户消息位置和 session 身份，不改变模型可见消息合同
- [x] 2.2 为 `TrajectorySourceReader` 增加 current-user-turn 读取入口，只返回请求绑定 trace 的当前用户 SourceSegment；旧 trace 缺少 envelope 时保守选择最后一条 user message并记录 legacy 诊断
- [x] 2.3 保持 Episode timeline 读取完整轨迹，使 Candidate current-turn API 不改变 Episode 构建和原始 Trajectory 审计
- [x] 2.4 为 Tool 增加非模型可见的 business/internal purpose metadata，给 memory、governance、Working Checkpoint 和用户输入控制工具标记 internal，未知自定义工具默认 business
- [x] 2.5 实现 `LongTaskCompletionClassifier`，只统计 completed trace 中具有不同 tool call ID 的成功 business `tool_finished`；要求调用数至少 10，且至少两个不同业务工具种类或 trace 持续至少 60 秒，并排除 delta、placeholder、失败、取消和内部工具
- [x] 2.6 添加最后用户消息选择、历史窗口不重复、旧 trace 回退、9 次不触发、10 次且两种工具触发、10 次单种快速调用不触发、10 次单种但持续 60 秒触发、同 ID 去重、内部工具排除、失败/取消/needs-user 不触发测试

## 3. Trigger Coordinator 与 20 轮批次

- [x] 3.1 用独立 Trigger Coordinator 替换逐回合 `_enqueue_auto_scan_request`，只查询完整 `cli:` trace并在 Offline Worker 空闲轮询中非阻塞运行
- [x] 3.2 实现按 `(started_at, trace_id)` 选择同 session 最老 20 条未消费非长期任务回合并创建固定 chat-window request，前 19 条不得入队
- [x] 3.3 实现 long-task trace 完成后的独立即时 request，只绑定该任务 trace且不消费此前不足 20 条的闲聊累计
- [x] 3.4 实现同一 trace 同时命中两条 lane 时 long-task 优先和 consumption 唯一 reservation，禁止重复 request、Candidate 和计数推进
- [x] 3.5 扩展现有 `apply_consolidation_batch()` 短事务，将 Candidate/Evidence/关系/Governance Job/Run、request completed 与 consumption consumed 原子提交；retry 保留 reservation，dead-letter 转 quarantined，无 Candidate 的 cancel 转 suppressed，任何条件更新失败整体回滚
- [x] 3.6 修改 `start_long_term_update` 为按 session/未消费边界幂等的 update hint，返回 `waiting-for-trigger`、hint ID和 pending chat count，不直接创建可执行提取请求
- [x] 3.7 把 Trigger Coordinator 纳入 Memory Runtime 启停、wake、诊断和停止顺序，保证在线回复不等待分类、提取或治理
- [x] 3.8 添加第 20 轮边界、两个连续窗口、10 工具长期任务提前触发、两 lane 竞争、重复 hint、重启计数、失败不消费、quarantined/suppressed 不回放、TTL 不自动释放和 disabled 模式测试

## 4. 原子 Extractor 输出与显式记忆去重

- [x] 4.1 升级版本化 Extractor 合同和正式适配器提示，明确输入仅为当前 user SourceSegment且允许返回零个或多个原子 Draft
- [x] 4.2 将 deterministic Extractor 升级为保守新版本：按行拆分明确 `请记住/记住/remember` 事实、为每条保存精确 quote/offset，普通无标记闲聊返回空集合
- [x] 4.3 禁止 Extractor 以整段多事实消息或问题作为兜底 Candidate，并为合法空批次返回 completed/zero-candidate
- [x] 4.4 在成功 `memory_manage remember/correct` 的工具结果与 trajectory event 中记录 current user message ID、basis quote、Claim ID、action 和成功状态
- [x] 4.5 在 Consolidator 提交前按稳定用户消息身份+basis quote、结构化事实槽位和值、exact normalized hash 的顺序匹配现有正式 Claim
- [x] 4.6 命中显式正式 Claim时复用 Claim并幂等补充缺失 Evidence/审计，不创建第二个 Candidate、governance job、Card statement 或 index job
- [x] 4.7 保持不确定语义关系为 Candidate/关系建议并进入治理，禁止仅凭文本相似度自动覆盖或合并正式事实
- [x] 4.8 添加多行四事实拆分、普通问题零 Draft、同消息部分已写入、全部已写入、同 quote 幂等、结构等价、关系不确定和批次事务回滚测试

## 5. 显式个人记忆证据强化

- [x] 5.1 实现 basis quote 确定性规范化，只移除允许的记忆指令包装并以结果作为权威 Claim 正文；模型 content 不一致时拒绝写入
- [x] 5.2 将显式当前用户 Evidence 持久化为 verified，保存 current user message ID、原始 quote、trace locator 和内容哈希
- [x] 5.3 扩展显式 remember/correct 的受管事实元数据，校验 fact type、subject/entity/predicate/value、sensitivity 和范围，并对健康/凭据等类型执行不可降低的敏感度下限
- [x] 5.4 让 correct 使用 expected revision 和同一显式依据合同原子保存新事实、旧事实 superseded、corrects/supersedes 关系与单个派生任务
- [x] 5.5 添加合法逐字依据、无关 content 借合法 quote、缺失/过期 message ID、多事实原子依据、敏感度降级、stale correction 和历史 Evidence 保留测试

## 6. Governance SubAgent 完整资源隔离

- [x] 6.1 使用真实 SQLite trajectory、`shell_safety` TOOL_BEFORE Hook、`NullTrajectoryStore` governor trace 和真实 MemoryGovernanceService，先稳定复现四个治理工具因 HookBus `_record` 外键 `IntegrityError` 全部失败
- [x] 6.2 断言故障来源是 `shell_safety` TOOL_BEFORE 的主轨迹写入而不是 `memory_default` TURN_AFTER、治理服务或 Policy Gate，并保存最小回归测试
- [x] 6.3 在构建 Reasoner 和 ToolRegistry 前按 profile 选择 trajectory/Hook 策略；为 `memory-governor` 绑定 `NullTrajectoryStore`、`reasoner_hook_bus=None`、`tool_hook_bus=None` 和严格四工具 Registry，普通 Profile 保持共享轨迹与插件 Hook 行为
- [x] 6.4 移除 SubAgentRuntime 根 trace 初始化对全局 factory trajectory store 的直接引用，确保整个治理任务统一走所选 profile store
- [x] 6.5 仅当多个内部 Profile 或装配分支仍存在资源漂移风险时提炼轻量 `ProfileExecutionResources`；不得把资源包抽象作为当前 IntegrityError 修复的前置条件
- [x] 6.6 验证四个治理工具的 Job 绑定、scope 和 Policy Gate 在无插件 Hook 时完整执行，Decision/task ID只写入 `memory.db`/task graph，`trajectories.db` 无 governor trace/span/hook event，主 Agent Hook 不受影响
- [x] 6.7 添加治理工具异常、Policy Gate 拒绝、stale revision 和观察层故障不得转化为 trajectory IntegrityError 的回归测试

## 7. Governance、Consolidation 恢复与状态诊断

- [x] 7.1 实现 `retry_governance_job` 条件 repository API，仅允许 dead-letter + candidate 未变化 + scope/revision 匹配的稳定 Job重置为 retry
- [x] 7.2 通过治理服务和受管 memory/CLI 操作暴露重试，返回 Job ID、前后状态、revision 和安全错误分类，不允许 CLI 直接写 SQLite
- [x] 7.3 保留旧 task ID、错误和任务图审计，重试只清理当前 worker/lease/attempts；用户已决定或 Candidate revision 变化时返回 stale/not-changed
- [x] 7.4 将耗尽重试的 consolidation request/consumption 转为 quarantined；`request_retry` 恢复同一稳定 request，`request_cancel` 仅在无 Candidate 时转 suppressed，二者均保留 trace binding 和审计
- [x] 7.5 提供独立运维 force-release API，仅允许无 Candidate 的 quarantined/suppressed trace 转 released，要求 actor/reason 审计且不向普通 Agent 暴露
- [x] 7.6 实现 `dead_letter_stale_after_seconds` 诊断：超时 quarantined 请求显示 `stale-dead-letter`，但不得自动 retry、release、consume 或重放
- [x] 7.7 修正 RuntimeInspector/CLI 派生状态映射，把数据库 `ready` 显示为 completed/ready-output，backlog 只统计 pending/retry/running并单列 dead-letter/quarantined/stale-dead-letter/suppressed
- [x] 7.8 在 `/memory` 和离线诊断中加入每 session pending chat count、阈值、最近 trigger kind、reserved/consumed、governance retry/dead-letter、consolidation quarantine 和安全最近错误
- [x] 7.9 添加治理重试成功、并发用户决定、重复重试、旧审计保留、ready 状态映射、quarantine retry/suppress、TTL 不自动释放、force-release 权限和离线失败不阻塞 CLI 回合测试

## 8. 文档、迁移与完整验证

- [x] 8.1 更新记忆架构与运行手册，说明 20 轮 chat-window、多工具长期任务、逐 trace consumption、current-turn Source、空批次和显式记忆即时写入的区别
- [x] 8.2 更新 SubAgent/插件文档，说明当前故障的 `shell_safety` TOOL_BEFORE Hook 写主轨迹路径、memory-governor 无主轨迹/无外部 Hook、四工具最小权限以及 `memory.db`/task graph 审计边界
- [x] 8.3 更新配置与 CLI 文档，解释 chat threshold=20、business tool count=10、distinct tools=2、elapsed=60、dead-letter stale TTL=86400、`start_long_term_update` waiting-for-trigger、Projection ready-output 和治理/整理请求恢复
- [x] 8.4 编写旧 checkpoint watermark、旧 deterministic Candidate、quarantined/suppressed request、dead-letter Job 和回滚流程；明确 deterministic 触发后零 Candidate 是正常结果、隐式学习需结构化正式 Extractor，现有无效 Candidate 只允许用户审核/治理处理，不自动删除或批准
- [x] 8.5 在 Non-goals/运维文档中区分范围外 Embedding 配置故障与历史 Episode projection `KeyError`；后者若当前仍可独立复现则建立单独 bugfix change
- [x] 8.6 使用项目 `memoli` Conda 环境运行触发、轨迹、Extractor、Memory、Governance、Plugin、SubAgent 和 CLI 定向测试
- [x] 8.7 使用项目 `memoli` Conda 环境运行完整 `python -m pytest -q`、`python -m ruff check memoli_agent benchmarks tests` 和带明确 Conda interpreter 的 Pyright
- [x] 8.8 运行 `openspec validate stabilize-triggered-memory-learning --strict` 并对照 proposal、design 和四组 delta spec 复核实现证据后再勾选完成
