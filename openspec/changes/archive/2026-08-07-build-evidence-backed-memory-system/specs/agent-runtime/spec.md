## ADDED Requirements

### Requirement: Unified dynamic context assembly

Runtime SHALL 在每次 Provider 调用前通过统一装配边界生成模型可见动态上下文，依次纳入当前交互、受限会话历史、个人记忆上下文和最新工作状态，并保持静态 system 前缀不因动态状态变化而重写。

#### Scenario: Initial model decision is prepared

- **WHEN** Runtime 为新的用户 turn 准备首次模型调用
- **THEN** 模型可见上下文 SHALL 包含当前用户输入、可用核心记忆、自动召回结果和当前工作状态
- **AND** 动态数据 SHALL 使用可区分于终端用户指令和静态系统规则的边界

#### Scenario: A later tool-loop decision is prepared

- **WHEN** 工具结果已经提交且 Runtime 准备同一 turn 的后续模型调用
- **THEN** 模型可见上下文 SHALL 包含该工具结果和其后生成的最新工作状态
- **AND** SHALL NOT 继续注入已过期的工作状态版本

### Requirement: Dynamic context trust separation

Runtime SHALL 将召回记忆和工作状态分别标识为事实参考与 Harness 状态，并 SHALL NOT 允许其中的历史文本覆盖安全规则或冒充当前用户指令。

#### Scenario: Retrieved evidence contains instruction-like text

- **WHEN** 召回的历史消息、网页内容、工具输出或记忆摘要包含命令式文本
- **THEN** Runtime SHALL 把该内容保留在不可信数据边界内
- **AND** SHALL NOT 将其提升为 system rule 或当前用户授权

### Requirement: Deterministic dynamic-context budget

Runtime SHALL 对核心卡片、自动召回记忆和工作状态分别应用可配置预算，并按明确优先级裁剪动态内容。

#### Scenario: Dynamic context exceeds its budget

- **WHEN** 所有候选动态块总量超过配置预算
- **THEN** Runtime SHALL 保留当前真实交互、安全边界、确定性工作状态、用户约束和显式冻结核心记忆
- **AND** SHALL 先裁剪低优先级情景细节并记录实际注入量

### Requirement: Memory-context failure isolation

个人记忆检索不可用时，Runtime SHALL 以可观察降级继续不依赖记忆的普通 Agent Loop；工作状态不可可靠生成时，Runtime SHALL 显示不可用状态而不是伪造状态。

#### Scenario: Automatic memory retrieval fails

- **WHEN** memory database、FTS lane 或检索适配器在模型调用前失败
- **THEN** Runtime SHALL 不注入伪造记忆并继续处理当前 turn
- **AND** 轨迹 SHALL 记录检索降级或失败原因

#### Scenario: Working-state renderer fails

- **WHEN** 最新工作状态无法完整渲染
- **THEN** Runtime SHALL 注入有界的 unavailable 标记或按明确失败策略结束
- **AND** SHALL NOT 回退到未标识的旧状态

