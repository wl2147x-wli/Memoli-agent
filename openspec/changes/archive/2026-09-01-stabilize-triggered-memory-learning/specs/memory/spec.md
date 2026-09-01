## MODIFIED Requirements

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

## ADDED Requirements

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
