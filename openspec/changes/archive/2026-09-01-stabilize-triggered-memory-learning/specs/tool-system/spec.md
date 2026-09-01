## MODIFIED Requirements

### Requirement: Deferred long-term update request

`start_long_term_update` SHALL 只持久化当前会话的长期整理意图并唤醒触发调度器，不得在当前工具调用中运行记忆整理，也不得绕过“20 个完成闲聊回合”或“成功完成多工具长期任务”的自动触发边界。

#### Scenario: Long-term update is requested before a trigger boundary

- **WHEN** 普通 Agent 在同一会话不足 20 个未消费闲聊回合且当前 trace 尚未满足长期任务完成条件时调用 `start_long_term_update`
- **THEN** 工具 SHALL 返回稳定 hint/request identity 和 waiting-for-trigger 状态
- **AND** SHALL NOT 立即运行 Extractor、创建 Candidate 或声称记忆已经更新

#### Scenario: Trigger boundary becomes eligible

- **WHEN** 已记录整理意图的会话随后达到 20 个完成闲聊回合，或当前多工具长期任务成功提交 trace 终态
- **THEN** 触发调度器 SHALL 幂等创建对应的持久 consolidation request 并唤醒 Worker
- **AND** 当前用户回复 SHALL NOT 等待 Candidate、Governor、Card 或索引完成

#### Scenario: Repeated update hints are submitted

- **WHEN** 同一 session 和未消费边界内重复调用 `start_long_term_update`
- **THEN** 系统 SHALL 合并为同一个持久整理意图
- **AND** SHALL NOT 重置闲聊计数、重复绑定 trace 或创建并行提取请求

#### Scenario: Offline consolidation is disabled

- **WHEN** consolidation 关闭时调用 `start_long_term_update`
- **THEN** 工具 SHALL 返回明确 disabled 状态和原因
- **AND** SHALL NOT 保存一个永远无法满足的伪运行请求

### Requirement: Governed personal-memory tools

启用个人记忆时，系统 SHALL 区分只读召回、显式正式写入、Candidate 治理操作与离线整理请求恢复操作，并支持显式记住、纠正、冻结、删除、查看、导出、有条件重试治理任务，以及对 consolidation dead-letter 执行有审计的 retry/suppress；显式正式写入 SHALL 以当前用户逐字依据为权威事实来源。

#### Scenario: Agent explicitly recalls memory

- **WHEN** 模型调用 `memory_recall` 并提供查询、可选类型或时间过滤及数量上限
- **THEN** 工具 SHALL 返回有界的结构化命中、稳定记忆 ID、当前性、证据引用和召回解释
- **AND** 该调用 SHALL NOT 修改记忆状态

#### Scenario: User explicitly asks the agent to remember a fact

- **WHEN** 受治理管理工具收到关联当前显式用户消息的 `remember` 操作及逐字 `basis_quote`
- **THEN** 系统 SHALL 从该 quote 确定性移除记忆指令包装并保存原子权威事实、verified Evidence、稳定用户消息身份、事实类型、敏感度和允许的结构槽位
- **AND** 模型提供的规范化 content 与 basis 不一致或不能由其确定性支持时 SHALL 拒绝写入，而不得借合法 quote 保存无关事实

#### Scenario: User explicitly corrects a fact

- **WHEN** `correct` 操作提供当前用户逐字依据、目标 Claim ID 和 expected revision
- **THEN** 系统 SHALL 使用同一显式证据合同创建修正事实并原子保存 corrects/supersedes 关系
- **AND** 旧事实、Evidence 和修订历史 SHALL 保持可审计

#### Scenario: Agent attempts an unsupported implicit write

- **WHEN** 模型请求把推断、网页文本、工具输出或 Assistant 回复直接发布为正式个人记忆且没有允许的批准主体
- **THEN** 管理工具 SHALL 拒绝正式写入或仅创建明确标记的 candidate
- **AND** SHALL 返回拒绝或候选原因

#### Scenario: User retries a governance job

- **WHEN** 有权用户或操作者请求重试当前 scope 内仍绑定未变化 Candidate 的 dead-letter governance job
- **THEN** 工具 SHALL 通过治理服务执行条件状态迁移并返回实际 Job ID、旧状态、新状态和 revision
- **AND** SHALL NOT 直接执行 SQL、清除历史审计或重试 stale Job

#### Scenario: Operator retries a consolidation dead-letter

- **WHEN** 有权操作者对当前 scope 内尚未提交 Candidate 的 quarantined consolidation request 执行 `request_retry`
- **THEN** 管理工具 SHALL 通过记忆服务将同一稳定 request 和 trace binding 恢复为 retry 并唤醒 Worker
- **AND** SHALL NOT 创建新的 request ID、清除历史错误审计或释放 trace 给其他触发 lane

#### Scenario: Operator cancels a consolidation dead-letter

- **WHEN** 有权操作者对当前 scope 内尚未提交 Candidate 的 quarantined consolidation request 执行 `request_cancel`
- **THEN** 管理工具 SHALL 将 request 和 consumption 转为 suppressed，并返回实际 request ID 与前后状态
- **AND** SHALL NOT 暴露 force-release、自动重放 suppressed trace 或取消已提交 Candidate 的请求

#### Scenario: User freezes or forgets a memory

- **WHEN** 管理工具收到当前用户对允许 scope 内目标 ID 的 `freeze` 或 `forget` 操作
- **THEN** 系统 SHALL 更新合法生命周期并返回实际受影响 ID
- **AND** 原始 Claim、来源和修订历史 SHALL 保持可审计

#### Scenario: Memory subsystem is disabled

- **WHEN** 任一个人记忆工具在 memory 关闭时被调用
- **THEN** 工具 SHALL 返回结构化 disabled 结果
- **AND** SHALL NOT 创建 memory database 写入
