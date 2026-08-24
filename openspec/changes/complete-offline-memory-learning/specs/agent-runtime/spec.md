## ADDED Requirements

### Requirement: Isolated offline-memory worker lifecycle

Runtime SHALL 在个人记忆和 consolidation 显式启用且配置有效时，将离线记忆 Worker 作为独立、有序启动和停止的后台生命周期组件；在线 Agent Turn、出站回复和下一条消息处理 SHALL NOT 等待远程提取、Card 投影或 Embedding 完成。

#### Scenario: Runtime starts with offline learning enabled

- **WHEN** memory、consolidation 和有效 Extractor 配置均已启用
- **THEN** Runtime SHALL 在权威存储可用后启动离线 Worker、恢复过期租约并开始有界消费持久请求
- **AND** Worker 状态 SHALL 可通过安全诊断查看

#### Scenario: Configuration enables consolidation without an extractor

- **WHEN** consolidation 被启用但 Extractor disabled、缺少必需模型或凭证配置无效
- **THEN** Runtime SHALL 在启动阶段返回明确配置错误或按规范定义的显式 disabled 状态
- **AND** SHALL NOT 静默运行一个永远不消费请求的伪 Worker

#### Scenario: Runtime stops during offline work

- **WHEN** 应用在 Worker 正在处理请求时关闭
- **THEN** Runtime SHALL 停止领取新任务并有界等待当前非网络事务结束
- **AND** 未完成请求 SHALL 通过租约在后续启动中恢复，而不被标记为成功

### Requirement: Offline-maintenance failure isolation

离线请求、Extractor、Card、Episode 或 Semantic Index 维护失败 SHALL 保持在其持久 Job/Run 状态中并产生安全诊断，且 SHALL NOT 终止普通 Agent Loop、撤销已发布回复或改变已有正式记忆。

#### Scenario: Extractor provider times out

- **WHEN** 离线 Extractor 超时或暂时不可用
- **THEN** 当前请求 SHALL 进入有界 retry 并释放在线运行资源
- **AND** 同期和后续普通用户 turn SHALL 继续处理

#### Scenario: Derived index permanently fails

- **WHEN** 派生维护达到最大尝试次数
- **THEN** Job SHALL 进入 dead-letter 并出现在安全诊断中
- **AND** 权威 Claim、CardVersion、Trajectory 和非语义召回 SHALL 保持可用

### Requirement: Isolated governance SubAgent lifecycle

Runtime SHALL 将持久 governance job 作为 `memory.db` 中的权威审核队列，按租约调用最小权限 `memory-governor` SubAgent Profile，并 SHALL 将 SubAgent task ID 仅作为执行记录关联回来；SubAgent 推理、重试和用户升级 SHALL NOT 阻塞在线 Agent Turn。

#### Scenario: Candidate creates a governance job

- **WHEN** consolidation 事务成功提交一个新的 Candidate
- **THEN** 同一 memory 事务 SHALL 幂等登记绑定 candidate ID/revision 和 governor/policy 版本的 pending governance job
- **AND** 治理调度器 SHALL 在有界资源内领取并调用 SubAgent Runtime，而不依赖下一轮用户消息

#### Scenario: Governance SubAgent profile is started

- **WHEN** 治理调度器执行已领取的 job
- **THEN** Runtime SHALL 使用不可写文件、不可联网、不可委派且仅含治理专用工具的 `memory-governor` Profile
- **AND** SHALL 对迭代次数、耗时、上下文、工具调用、批次和并发设置独立上限

#### Scenario: Governance task crashes or times out

- **WHEN** SubAgent 在提交有效决定前崩溃、超时或 Runtime 重启
- **THEN** governance job SHALL 按租约恢复为 retry 并保持 Candidate 为 candidate
- **AND** 达到最大尝试次数后 SHALL 进入 dead-letter 或 needs-user-review，而不得自动批准

#### Scenario: User changes a candidate during governance

- **WHEN** Governance SubAgent 读取 Candidate 后用户完成了批准、拒绝或修正
- **THEN** Runtime/Policy Gate SHALL 通过 expected revision 将旧决定标记 stale/no-op
- **AND** SHALL NOT 覆盖用户状态或重复登记 Card/索引投影

### Requirement: Idle backlog draining

启用的离线 Worker SHALL 在没有新用户 turn 时按配置轮询或唤醒机制继续有界排空 pending/retry 请求，并 SHALL 遵守批次、并发、超时和资源上限。

#### Scenario: User stops sending messages with pending jobs

- **WHEN** 出站回复后仍有超过单批上限的离线提取或治理积压且没有新的入站消息
- **THEN** Worker/治理调度器 SHALL 继续按配置处理后续批次直至队列为空、暂停或达到资源边界
- **AND** SHALL NOT 依赖下一轮用户消息触发每个批次

#### Scenario: Online turn arrives during background work

- **WHEN** Worker 正在等待远程 Provider且新的用户消息到达
- **THEN** Agent Loop SHALL 能独立开始处理该 turn
- **AND** Worker SHALL 遵守配置并发和资源配额而不占用在线 turn 的必需事务锁
