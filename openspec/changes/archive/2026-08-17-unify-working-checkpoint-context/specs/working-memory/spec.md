## MODIFIED Requirements

### Requirement: Hybrid working-state projection

系统 SHALL 为当前任务维护由 Harness 确定性硬状态和 Agent 语义 checkpoint 组成的工作记忆，并 SHALL 在模型可见表示中区分两类来源；Agent checkpoint 的目标、步骤、下一行动、关键内容、约束、决策、相关 SOP 和 Agent 声明产物 SHALL 与 Runtime 验证状态明确分区。

#### Scenario: Tool execution updates deterministic state

- **WHEN** 工具调用完成、失败、超时或产生控制信号
- **THEN** 后续工作状态 SHALL 根据实际工具结果更新最近工具、结果状态、失败计数、预算和已验证产物等确定性字段
- **AND** SHALL NOT 由模型自由文本覆盖这些字段

#### Scenario: Agent provides a semantic checkpoint

- **WHEN** `update_working_checkpoint` 提交目标、约束、当前步骤、进展、关键发现、失败方案、下一步或相关资源
- **THEN** 系统 SHALL 更新当前任务的完整语义 checkpoint，并在后续模型状态中保留已提交的非空字段
- **AND** SHALL 将 Agent 声明的决策和产物标识为 Agent 提供的工作信息而不是已验证运行事实

### Requirement: Direct latest-state injection

系统 SHALL 在当前任务的每次模型决策前直接注入最新工作状态，而 SHALL NOT 通过关键词或语义相似度检索决定是否提供工作记忆；初始 Prompt 组合阶段 SHALL NOT 预置遗留或简化的工作状态文本。

#### Scenario: Tool result requires another model decision

- **WHEN** Agent Loop 已执行工具并准备下一次 Provider 调用
- **THEN** 下一次模型可见上下文 SHALL 包含工具结果之后计算的最新工作状态
- **AND** SHALL 只包含一个明确标识为最新版本的 `<agent_status>` 工作状态块，不得同时包含遗留 `<working_checkpoint>` 块

#### Scenario: Provider retry or fallback occurs

- **WHEN** Runtime 重试模型调用或切换到 fallback Provider
- **THEN** 重试或 fallback 请求 SHALL 接收与当前已提交运行状态一致的工作状态投影
- **AND** 每次实际请求 SHALL 从同一调用前装配路径重新建立唯一状态块

#### Scenario: No checkpoint exists yet

- **WHEN** 工作记忆启用但当前 scope 尚未创建 Agent checkpoint
- **THEN** 模型可见状态 SHALL 仍包含 Runtime 硬状态和明确的 Agent checkpoint unavailable 标记
- **AND** SHALL NOT 创建空 checkpoint 或注入遗留简化块
