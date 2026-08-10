# working-memory Specification

## Purpose
TBD - created by archiving change build-evidence-backed-memory-system. Update Purpose after archive.
## Requirements
### Requirement: Hybrid working-state projection

系统 SHALL 为当前任务维护由 Harness 确定性硬状态和 Agent 语义 checkpoint 组成的工作记忆，并 SHALL 在模型可见表示中区分两类来源。

#### Scenario: Tool execution updates deterministic state

- **WHEN** 工具调用完成、失败、超时或产生控制信号
- **THEN** 后续工作状态 SHALL 根据实际工具结果更新最近工具、结果状态、失败计数、预算和已验证产物等确定性字段
- **AND** SHALL NOT 由模型自由文本覆盖这些字段

#### Scenario: Agent provides a semantic checkpoint

- **WHEN** `update_working_checkpoint` 提交目标、约束、当前步骤、进展、关键发现、失败方案、下一步或相关资源
- **THEN** 系统 SHALL 更新当前任务的语义 checkpoint
- **AND** SHALL 将其标识为 Agent 提供的工作信息而不是已验证运行事实

### Requirement: Direct latest-state injection

系统 SHALL 在当前任务的每次模型决策前直接注入最新工作状态，而 SHALL NOT 通过关键词或语义相似度检索决定是否提供工作记忆。

#### Scenario: Tool result requires another model decision

- **WHEN** Agent Loop 已执行工具并准备下一次 Provider 调用
- **THEN** 下一次模型可见上下文 SHALL 包含工具结果之后计算的最新工作状态
- **AND** SHALL 只包含一个明确标识为最新版本的工作状态块

#### Scenario: Provider retry or fallback occurs

- **WHEN** Runtime 重试模型调用或切换到 fallback Provider
- **THEN** 重试或 fallback 请求 SHALL 接收与当前已提交运行状态一致的工作状态投影

### Requirement: Bounded and precedence-aware status rendering

系统 SHALL 以有界、人类可读且可区分来源的格式渲染工作状态，并 SHALL 保证状态截断不会伪造完成、成功或不存在的约束。

#### Scenario: Working state exceeds its configured budget

- **WHEN** 工作状态内容超过配置的字符预算
- **THEN** 系统 SHALL 优先保留确定性硬状态、用户约束、当前步骤和下一步
- **AND** SHALL 明确标识被省略的低优先级内容

#### Scenario: Deterministic projection is unavailable

- **WHEN** Runtime 无法可靠计算某个硬状态字段
- **THEN** 状态栏 SHALL 将该字段标识为 unavailable 或省略
- **AND** SHALL NOT 使用模型猜测值补全

### Requirement: Scoped checkpoint persistence and recovery

系统 SHALL 使用 schema-versioned 本地存储按 task 和 session scope 持久化语义 checkpoint、revision、状态和更新时间，并 SHALL 使其独立于个人长期记忆开关。

#### Scenario: Runtime restarts during an unfinished task

- **GIVEN** 未完成任务已有已提交 checkpoint
- **WHEN** 用户显式恢复该任务
- **THEN** 系统 SHALL 恢复最新 revision 的 checkpoint
- **AND** 新生成的确定性硬状态 SHALL 从当前运行证据重新计算

#### Scenario: User starts an unrelated task

- **WHEN** 新任务没有显式声明继承或恢复旧 task
- **THEN** 系统 SHALL 创建新的工作 scope
- **AND** SHALL NOT 把旧任务进度作为当前进度注入

#### Scenario: Personal memory is disabled

- **WHEN** 个人长期记忆关闭但工作记忆启用
- **THEN** checkpoint 更新、恢复和直接注入 SHALL 继续可用

### Requirement: Optimistic checkpoint updates

工作 checkpoint 更新 SHALL 具有有界替换或结构化 patch 语义，并使用 revision 防止过期调用覆盖较新状态。

#### Scenario: Checkpoint update uses the current revision

- **WHEN** 更新请求携带当前 expected revision 且内容有效
- **THEN** 系统 SHALL 原子提交新 revision
- **AND** 后续模型决策 SHALL 使用新 revision

#### Scenario: Checkpoint update is stale

- **WHEN** 更新请求的 expected revision 早于当前 revision
- **THEN** 系统 SHALL 拒绝覆盖并返回当前 revision
- **AND** 已提交 checkpoint SHALL 保持不变

### Requirement: Working-state trajectory audit

工作状态的语义更新和每次实际注入的状态版本 SHALL 可通过当前 trace 审计，但 SHALL NOT 自动成为个人长期记忆或程序经验。

#### Scenario: Checkpoint is updated and later injected

- **WHEN** 模型成功更新 checkpoint 且 Agent Loop 继续执行
- **THEN** 原始轨迹 SHALL 能区分更新意图、提交结果和后续模型实际可见的状态版本
- **AND** SHALL NOT 为该状态附加 reward、正确性标签或训练标签

