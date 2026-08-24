## ADDED Requirements

### Requirement: Durable memory-trigger classification at committed turn boundaries

Runtime SHALL 只从已提交的主用户会话 trace 识别闲聊回合和多工具长期任务完成边界，并 SHALL 把稳定 trace ID、终态和成功工具调用摘要交给离线记忆触发调度器；分类和入队不得阻塞在线回复。

#### Scenario: Completed chat turn is observed

- **WHEN** `cli:` 用户回合已写入 `trace_finished` 且不满足多工具长期任务条件
- **THEN** Runtime SHALL 将该 trace 作为一个可计数闲聊回合交给触发调度器
- **AND** SHALL NOT 在该单个回合结束时直接运行 Extractor

#### Scenario: Completed multi-tool task is observed

- **WHEN** `cli:` 用户回合完成至少 10 个具有不同 tool call ID 的成功非内部业务工具调用，并且至少涉及两个不同业务工具种类或 trace 已持续至少 60 秒，随后以 completed 终态提交
- **THEN** Runtime SHALL 将其分类为 long-task 并在 trace 提交后通知触发调度器
- **AND** 工具 delta、未正式执行的调用、失败调用重试和内部记忆/治理/工作状态工具 SHALL NOT 增加有效业务工具计数

#### Scenario: A short multi-tool turn is not a long task

- **WHEN** completed `cli:` 回合只有少于 10 个成功非内部业务工具调用，即使其中包含多个业务工具种类
- **THEN** Runtime SHALL NOT 将该 trace 分类为 long-task
- **AND** 该 trace SHALL 作为普通未消费闲聊回合参与 20 轮窗口累计

#### Scenario: Ten trivial calls lack a long-task qualifier

- **WHEN** completed `cli:` 回合恰有 10 个成功业务工具调用，但只有一种业务工具且 trace 持续时间少于 60 秒
- **THEN** Runtime SHALL NOT 将该 trace 分类为 long-task
- **AND** SHALL NOT 使用模型文本或 Working Checkpoint 猜测来绕过工具种类/持续时间条件

#### Scenario: Turn does not reach a successful terminal state

- **WHEN** 回合 failed、cancelled、needs-user、预算耗尽或进程在 trace 提交前中断
- **THEN** Runtime SHALL NOT 产生 long-task 提取触发
- **AND** 后续恢复 SHALL 只处理具有权威完成终态的 trace

### Requirement: Fully isolated memory-governor execution resources

Runtime SHALL 为 `memory-governor` 同时选择一致的非持久 Trajectory、Reasoner Hook 和 ToolRegistry Hook 边界；治理内部执行 SHALL NOT 通过共享插件 HookBus 间接写入主 Agent trajectory，治理决定的权威审计 SHALL 保存在 `memory.db`。

#### Scenario: Governance tool is executed

- **WHEN** `memory-governor` 调用绑定 Candidate 的读取或决定工具
- **THEN** Reasoner 和 ToolRegistry SHALL 使用一致的 profile-scoped 非持久轨迹/Hook 边界，无论实现采用直接 profile 条件选择还是轻量资源对象
- **AND** 工具 SHALL 正常返回而不因主轨迹缺少 SubAgent trace row 触发 IntegrityError

#### Scenario: Governance task completes

- **WHEN** Policy Gate 接受、拒绝、升级或推迟一个治理决定
- **THEN** governance Job、Decision、actor、revision、reason codes 和 task ID SHALL 由 `memory.db`/任务图记录
- **AND** `trajectories.db` SHALL NOT 包含该 `memory-governor` 的 trace、span、模型或插件 Hook 事件

#### Scenario: Ordinary SubAgent runs

- **WHEN** research、coding 或 general SubAgent 执行普通委派任务
- **THEN** 其既有轨迹与插件策略行为 SHALL 保持不变
- **AND** memory-governor 的隔离配置 SHALL NOT 全局关闭主 Agent 或普通 SubAgent Hook
