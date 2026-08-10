## ADDED Requirements

### Requirement: Minimal serial agent loop

系统 SHALL 在一次被动 turn 内以单一串行循环执行模型和工具步骤，直到形成终止结果或触发执行边界。

#### Scenario: Direct answer requires no tool

- **WHEN** 模型返回非空最终回复且没有工具调用
- **THEN** 系统 SHALL 接受该回复并以 `completed` 结束 turn
- **AND** SHALL NOT 为普通问答强制产生工具调用

#### Scenario: Tool result requires another model decision

- **WHEN** 模型返回一个或多个工具调用
- **THEN** 系统 SHALL 按模型声明顺序执行工具调用
- **AND** SHALL 将每个关联工具结果加入模型可见上下文
- **AND** SHALL 在仍有执行预算时继续下一次模型调用

#### Scenario: Multiple tool rounds complete a task

- **GIVEN** 完成任务需要至少两轮模型决策和工具执行
- **WHEN** 前一轮工具结果为下一轮提供新信息
- **THEN** 系统 SHALL 持续循环直至模型给出可接受的最终回复
- **AND** 最终出站消息 SHALL 仅包含该 turn 的最终用户可见回复

### Requirement: Explicit serial loop outcomes

每个 turn SHALL 产生 `completed`、`needs-user`、`failed` 或 `budget-exhausted` 之一的结构化终止原因，并关联稳定的 trace 标识。

#### Scenario: Required user input is unavailable

- **WHEN** 工具或完成判定表明继续执行需要用户提供信息或授权
- **THEN** 系统 SHALL 以 `needs-user` 结束本次 turn
- **AND** SHALL 向用户返回明确问题而不是继续猜测执行

#### Scenario: Unrecoverable execution failure occurs

- **WHEN** Provider、工具协议或 Runtime 出现不可恢复错误
- **THEN** 系统 SHALL 以 `failed` 结束本次 turn
- **AND** 终止结果 SHALL 包含可观察的错误分类而不暴露秘密

#### Scenario: Provider fallback succeeds

- **GIVEN** 主 Provider 调用失败且现有 fallback 成功
- **WHEN** 串行循环继续或完成
- **THEN** 终止结果和运行轨迹 SHALL 标识 fallback 已被使用

### Requirement: Bounded loop execution

系统 SHALL 使用最大模型迭代数和最长墙钟时间约束单次 turn，并在明显无进展时停止循环。

#### Scenario: Maximum iterations are exhausted

- **WHEN** turn 在达到最大模型迭代数后仍未形成最终结果
- **THEN** 系统 SHALL 以 `budget-exhausted` 结束
- **AND** SHALL NOT 将中间回复宣称为已完成结果

#### Scenario: Maximum elapsed time is exhausted

- **WHEN** turn 在下一次模型或工具操作前已经超过最长运行时间
- **THEN** 系统 SHALL 停止发起新的操作
- **AND** SHALL 以 `budget-exhausted` 结束

#### Scenario: Identical failing action makes no progress

- **WHEN** 相同的规范化工具调用和结果状态在没有新信息时连续达到配置阈值
- **THEN** 系统 SHALL 以 `failed` 和 `no-progress` 分类结束
- **AND** SHALL NOT 继续重复该动作

### Requirement: Lightweight completion gate

系统 SHALL 在模型未调用工具时执行确定性的轻量完成判定，并允许普通回答直接完成。

#### Scenario: Empty model response is retryable

- **WHEN** 模型既未返回工具调用也未返回非空用户可见内容
- **THEN** 系统 SHALL 在剩余预算内向下一轮加入结构化重试反馈
- **AND** SHALL NOT 以 `completed` 结束空响应

#### Scenario: Detectable truncated response is retryable

- **WHEN** Provider 元数据明确表明响应因输出限制被截断
- **THEN** 系统 SHALL 在剩余预算内请求模型继续或重新组织回复
- **AND** 该判定 SHALL 被记录到运行轨迹

### Requirement: Complete SQLite runtime trajectory

启用轨迹记录时，系统 SHALL 使用 schema-versioned SQLite 数据库为每个 turn 按发生顺序持久化完整的可观察执行步骤，并 SHALL 以 append-only 事件作为权威运行证据。

#### Scenario: Successful multi-step turn is recorded

- **WHEN** turn 经历多次模型调用和工具执行后完成
- **THEN** SQLite 轨迹 SHALL 包含 trace 开始、每次模型可见输入、模型响应、工具调用、工具结果、循环判定和 trace 结束记录
- **AND** 每个事件 SHALL 包含 schema version、trace id、单调递增顺序号和时间戳
- **AND** trace 结束事件 SHALL 包含终止原因、最终回复、累计 usage 和总时长
- **AND** 同一 trace 的顺序号 SHALL 唯一

#### Scenario: Tool execution fails

- **WHEN** 工具调用抛出异常或返回结构化失败
- **THEN** SQLite 轨迹 SHALL 记录脱敏后的工具名称、参数、错误分类、结果状态和耗时
- **AND** 后续循环判定 SHALL 明确记录继续或终止的原因

#### Scenario: Process stops before normal completion

- **WHEN** 进程在 turn 正常结束前退出
- **THEN** 已提交的 SQLite 轨迹记录 SHALL 保持事务一致且可读取
- **AND** 缺少 trace 结束事件 SHALL 可被识别为不完整运行而不是成功运行

#### Scenario: Trajectory recording is disabled

- **GIVEN** 用户显式关闭轨迹记录
- **WHEN** Agent 执行 turn
- **THEN** Runtime SHALL 继续执行相同的串行循环行为
- **AND** SHALL NOT 为该 turn 向 SQLite 轨迹数据库写入记录

#### Scenario: Unknown database schema version is found

- **WHEN** Runtime 打开的轨迹数据库 schema version 高于当前实现支持的版本或 migration 失败
- **THEN** 系统 SHALL 报告明确的 schema 错误并停止使用该数据库
- **AND** SHALL NOT 静默删除、重建或降级已有轨迹数据

### Requirement: Queryable trace, span and event relationships

持久化轨迹 SHALL 区分跨 turn 会话、单 turn trace、有时长的执行 span、瞬时事件和较大 payload，并保持它们之间可查询的关联关系。

#### Scenario: Multi-turn session is inspected

- **GIVEN** 同一 session 已完成多个 turn
- **WHEN** 使用 session id 查询轨迹
- **THEN** 系统 SHALL 按时间返回属于该 session 的各个 trace
- **AND** 每个 trace SHALL 可按顺序还原其模型、工具和循环决策记录

#### Scenario: Trace is filtered by execution outcome

- **WHEN** 使用终止原因、时间范围、Provider、模型或 span 类型筛选轨迹
- **THEN** 系统 SHALL 从本地轨迹数据库返回匹配记录
- **AND** SHALL NOT 要求扫描或解析每个独立 JSONL 文件

#### Scenario: Large observable payload is stored

- **WHEN** 模型上下文或工具结果超过配置的内联大小
- **THEN** 系统 SHALL 将内容压缩或存放到受管 payload 存储
- **AND** SQLite 轨迹 SHALL 保存受约束的引用、内容哈希、原始大小、存储大小和转换标志

### Requirement: Auditable trajectory write boundary

启用轨迹记录时，Runtime SHALL 在继续产生新的模型或工具行为前确认对应的必需 SQLite 证据已经事务提交。

#### Scenario: Required SQLite transaction fails during a turn

- **WHEN** 任一必需轨迹记录无法提交
- **THEN** Runtime SHALL 停止发起后续模型调用和工具调用
- **AND** SHALL 以 `failed` 和 `trace-write-failed` 分类结束本次 turn
- **AND** SHALL 向用户报告可操作的本地记录错误

#### Scenario: Side-effecting tool is about to execute

- **WHEN** Runtime 即将执行会改变外部状态的工具
- **THEN** 对应的工具意图 SHALL 在工具执行前成功提交
- **AND** 工具执行结果或错误 SHALL 在执行后作为新的证据记录提交

#### Scenario: Provider is about to be called

- **WHEN** Runtime 即将向 Provider 发送一次模型请求
- **THEN** 实际模型可见输入和调用配置 SHALL 在请求发出前成功提交
- **AND** Provider 响应或错误 SHALL 在调用后作为新的证据记录提交

#### Scenario: Optional export fails

- **WHEN** 已提交轨迹的 JSONL 或外部观测导出失败
- **THEN** 已提交的 SQLite 轨迹和 Agent 终止结果 SHALL 保持不变
- **AND** 系统 SHALL 报告可重试的导出错误

### Requirement: Private and bounded trajectory content

系统 SHALL 在轨迹落盘前对已知敏感字段递归脱敏，并 SHALL NOT 保存 Provider 未返回的隐藏推理内容。

#### Scenario: Sensitive fields appear in observable data

- **WHEN** 模型消息、工具参数或工具结果包含配置的敏感字段名
- **THEN** 持久化轨迹 SHALL 使用脱敏占位符替换字段值
- **AND** Provider 凭证和 Authorization 信息 SHALL NOT 写入轨迹

#### Scenario: Payload cannot be safely serialized in full

- **WHEN** 可观察值无法安全序列化、超过配置上限或属于二进制内容
- **THEN** 系统 SHALL 保存有界表示、压缩内容或受管外部引用
- **AND** 轨迹 SHALL 明确标识内容已转换、压缩、外置或截断

#### Scenario: Trajectory exists locally

- **WHEN** 轨迹成功持久化
- **THEN** 轨迹数据库和受管 payload SHALL 保存在配置的本地路径中
- **AND** SHALL NOT 在没有独立授权流程的情况下自动进入 Memory、Evolution 或 Post-training

### Requirement: Portable JSONL trajectory export

系统 SHALL 能够从已提交的 SQLite 轨迹生成确定性、schema-versioned JSONL 导出，而 SHALL NOT 将 JSONL 用作在线 Runtime 的权威状态。

#### Scenario: Completed trace is exported

- **WHEN** 用户按 trace id 导出已提交轨迹
- **THEN** JSONL SHALL 按 trace 顺序号输出 trace、span、event 和 payload 表示
- **AND** 导出 SHALL 保留脱敏、截断和外置引用标志

#### Scenario: Same trace is exported repeatedly

- **GIVEN** SQLite 中的源轨迹未发生变化
- **WHEN** 同一 trace 被重复导出
- **THEN** 两次 JSONL 导出的规范化内容 SHALL 相同
- **AND** 导出操作 SHALL NOT 修改源轨迹
