# agent-task-graph Specification

## Purpose
TBD - created by archiving change build-durable-subagent-graph. Update Purpose after archive.
## Requirements
### Requirement: Durable agent and task identities

系统 SHALL 为每个委派任务分配稳定 task id 和 agent id，并在 SQLite 中分别保存 Agent 父子关系、任务依赖关系、控制消息和产物引用。一个 Agent SHALL 至多有一个父 Agent，任务依赖 SHALL 允许多个前置任务但不得形成环。

#### Scenario: Root agent creates a child task

- **WHEN** 主 Agent 创建一个有效子任务
- **THEN** 系统 SHALL 持久化 root agent、parent agent、child agent、task 和 trace 关联
- **AND** 返回稳定 task id 供后续查询和控制

#### Scenario: Cyclic dependency is requested

- **WHEN** 新依赖边会使 Task DAG 形成环
- **THEN** 系统 SHALL 拒绝该依赖
- **AND** 已有任务图 SHALL 保持不变

### Requirement: Explicit task lifecycle

任务 SHALL 使用 `pending`、`blocked`、`runnable`、`running`、`waiting_input`、`completed`、`failed`、`cancelled` 或 `interrupted` 状态，并 SHALL 只允许经过定义的状态转换。每次转换 SHALL 持久记录时间和原因。

#### Scenario: Runnable task is claimed

- **WHEN** Scheduler 获得一个依赖已满足的 runnable 任务
- **THEN** 系统 SHALL 原子地把该任务转换为 running
- **AND** 同一任务不得被第二个执行器重复领取

#### Scenario: Invalid transition is attempted

- **WHEN** 调用方尝试把终态任务直接转换为 running，且未创建合法恢复 attempt
- **THEN** 系统 SHALL 拒绝转换并保留原状态

### Requirement: Dependency-aware scheduling

Scheduler SHALL 只执行依赖已成功完成的任务。存在未完成依赖的任务 SHALL 保持 blocked；全部依赖成功后 SHALL 自动变为 runnable。第一阶段默认并发上限 SHALL 为一，但配置提高上限后仍 SHALL 遵守同一依赖规则。

#### Scenario: Task waits for two dependencies

- **WHEN** 一个任务依赖两个任务且仅一个已经完成
- **THEN** 该任务 SHALL 保持 blocked 且不得被执行

#### Scenario: All dependencies complete

- **WHEN** blocked 任务的全部依赖成功完成
- **THEN** Scheduler SHALL 将其转换为 runnable

#### Scenario: A dependency fails

- **WHEN** 任一前置任务进入 failed、cancelled 或 interrupted 且未恢复
- **THEN** 下游任务 SHALL 保持 blocked 并记录阻塞原因
- **AND** 系统不得自动把依赖失败解释为下游成功

### Requirement: Bounded graph execution

系统 SHALL 同时约束活跃 SubAgent 数量和委派深度。默认最大并发与最大深度 SHALL 均为一；达到任一边界时，系统 SHALL 拒绝新的超界执行或让合法任务等待，不得绕过限制或无限重试。

#### Scenario: Concurrency capacity is occupied

- **WHEN** 活跃任务数达到配置上限且另一个 runnable 任务存在
- **THEN** 后续任务 SHALL 保持 runnable 等待容量
- **AND** 不得启动额外 Runtime

#### Scenario: Delegation exceeds depth limit

- **WHEN** 一个 Agent 尝试创建超过配置最大深度的后代
- **THEN** 系统 SHALL 拒绝创建并返回可诊断的深度限制结果

### Requirement: Task inspection and control

系统 SHALL 允许主 Agent 按 task id 查询单个任务、列出当前会话任务、请求取消和显式恢复 interrupted 任务。查询 SHALL 返回稳定状态、profile、父子关系、依赖、任务目录、时间和结果/错误摘要。

#### Scenario: Main agent lists tasks

- **WHEN** 主 Agent 请求当前根会话的任务列表
- **THEN** 系统 SHALL 返回该会话可见任务及其稳定状态
- **AND** 不得泄露其他根会话的私有任务内容

#### Scenario: Running task is cancelled

- **WHEN** 主 Agent 对 running 任务发出取消请求
- **THEN** 系统 SHALL 持久记录取消意图并停止对应 Runtime
- **AND** 任务最终 SHALL 进入 cancelled
- **AND** 完成/取消通知 SHALL 至多发布一次

#### Scenario: Unknown task is controlled

- **WHEN** 查询、取消或恢复使用不存在或当前会话不可见的 task id
- **THEN** 系统 SHALL 返回失败而不改变任何任务

### Requirement: Task-level recovery

系统 SHALL 在启动时检测没有活跃执行所有权的遗留 running 或 waiting_input 任务，并将其标记为 interrupted。恢复 SHALL 创建新的执行 attempt 和 trace，保留原 attempt，不得假装从模型生成中间位置继续。

#### Scenario: Process restarts during execution

- **WHEN** 应用启动时发现持久状态为 running 但没有对应活跃执行器
- **THEN** 任务 SHALL 转换为 interrupted 并记录重启恢复原因
- **AND** 原 trajectory 与产物 SHALL 保留

#### Scenario: Safe task is explicitly resumed

- **WHEN** 主 Agent 显式恢复一个允许重试的 interrupted 任务
- **THEN** 系统 SHALL 创建新的 attempt/trace 并重新排队
- **AND** 原 attempt SHALL 继续可查询

#### Scenario: Side-effecting task requires confirmation

- **WHEN** interrupted 任务可能已产生不可安全重复的外部副作用
- **THEN** 系统 SHALL 拒绝无确认自动恢复
- **AND** 返回需要主 Agent 或用户确认的状态

### Requirement: Parent-owned result delivery

任务图中的 SubAgent SHALL 只把进度、输入请求和终态结果投递给其父控制链路；只有主 Agent SHALL 面向最终用户输出。后台终态事件 SHALL 路由回创建任务的根会话，并包含 task id、agent id、状态和结果引用。

#### Scenario: Background child completes

- **WHEN** 后台 SubAgent 进入终态
- **THEN** 系统 SHALL 把完成事件投递到原根会话
- **AND** SubAgent 不得绕过主 Agent 直接发送用户消息

#### Scenario: Completion event is replayed

- **WHEN** 同一终态因重试、取消竞争或消息重放被再次处理
- **THEN** 系统 SHALL 保持任务终态不变
- **AND** 不得产生重复用户回复所需的第二个完成通知

