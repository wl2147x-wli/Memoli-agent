## MODIFIED Requirements

### Requirement: Session-aware passive turns

系统 SHALL 按消息的 session key 维护近期完整 turn、不可变上下文归档和有限兼容窗口，并通过统一生命周期生成出站消息；进程或显式 Session 恢复能力仅在相应持久上下文状态可靠可用时成立。

#### Scenario: User sends a CLI message

- **WHEN** 通道发布一条普通入站消息
- **THEN** 系统 SHALL 依次准备会话、查询动态上下文、编译有预算的 prompt、执行推理、保存历史并构造出站消息

#### Scenario: Conversation continues

- **GIVEN** 同一 session key 已有近期历史或不可变 archive
- **WHEN** 新消息到达
- **THEN** prompt SHALL 包含受 token 预算约束的相关归档和近期完整 turn
- **AND** `history_window` SHALL 仅作为兼容或安全上限而不得拆散工具关联或任意半轮消息

#### Scenario: Runtime restarts without context persistence

- **WHEN** Runtime 未启用或无法可靠读取 Session context persistence
- **THEN** 系统 SHALL 创建新的进程内 Session 上下文
- **AND** SHALL NOT 声称已恢复仅存在于旧进程内存的对话历史

### Requirement: Unified dynamic context assembly

Runtime SHALL 在每次 Provider 调用前通过统一、缓存感知且有全局预算的编译边界生成模型可见上下文：稳定基础规则和当前 Session 冻结的 Skill/tool 前缀之后依次纳入不可变任务归档、近期完整交互，再在动态尾部纳入个人记忆、插件扩展和唯一最新工作状态；动态内容或 active 指针 SHALL NOT 重写稳定前缀。

#### Scenario: Initial model decision is prepared

- **WHEN** Runtime 为新的用户 turn 准备首次模型调用
- **THEN** 模型可见上下文 SHALL 包含当前用户输入、可用的冻结 Skill catalog、核心/自动召回记忆和当前工作状态
- **AND** Skill catalog、插件段、记忆、archive 和工作状态 SHALL 使用可区分于终端用户指令和静态安全规则的边界

#### Scenario: A later tool-loop decision is prepared

- **WHEN** Skill 或通用工具结果已经提交且 Runtime 准备同一 turn 的后续模型调用
- **THEN** 模型可见上下文 SHALL 包含完整关联的工具调用/结果和其后的唯一最新工作状态
- **AND** SHALL NOT 注入过期状态、重新渲染已冻结前缀或拆散工具协议消息

#### Scenario: No Skill is available

- **WHEN** Skill Runtime 关闭、降级或当前 Session 没有可见 Skill
- **THEN** Runtime SHALL 在不伪造空 Skill 指令的情况下编译现有交互、历史归档、记忆和工作状态
- **AND** 普通 Agent Loop SHALL 保持可用

#### Scenario: Context compiler is disabled for compatibility

- **WHEN** 配置显式关闭压缩但仍启用统一编译诊断
- **THEN** Runtime SHALL 保持标准消息角色和现有 Agent Loop 行为
- **AND** 仍 SHALL 在超出模型硬输入预算前返回明确错误而不是发送已知无效请求

### Requirement: Deterministic dynamic-context budget

Runtime SHALL 在模型全局输入预算内对核心卡片、自动召回记忆、插件段、历史归档、近期轨迹和工作状态应用独立上限与确定性优先级，并记录实际注入、裁剪和压缩量。

#### Scenario: Dynamic context exceeds its budget

- **WHEN** 所有候选动态块总量超过可用模型输入预算
- **THEN** Runtime SHALL 保留当前真实交互、安全边界、确定性工作状态、用户约束、工具协议完整性和显式冻结核心记忆
- **AND** SHALL 先裁剪低优先级情景细节、插件扩展和重复工具噪声并记录原因

#### Scenario: Legacy per-component budgets are configured

- **WHEN** Memory、Working State、Skill 或工具仍配置已有字符上限
- **THEN** 这些上限 SHALL 作为对应组件候选生成的局部硬上限继续生效
- **AND** SHALL NOT 替代 Provider 前的全局 token 预算检查

## ADDED Requirements

### Requirement: Context configuration compatibility

系统 SHALL 为模型窗口、输出预留、安全余量、压缩阈值、近期 tail、archive/preview 预算和压缩失败上限提供可校验配置，并在旧配置缺少新字段时使用保守默认值。

#### Scenario: Legacy configuration is loaded
- **WHEN** 配置包含现有 Agent/Memory/Working State/Skill 字段但没有 context management 字段
- **THEN** Runtime SHALL 使用保守内置 context window 和默认压缩参数启动
- **AND** SHALL 保留现有 `history_window` 和组件字符上限的兼容语义

#### Scenario: Context thresholds are invalid
- **WHEN** 输出预留、安全余量或阈值导致可用输入预算非正，或 soft threshold 不低于 hard threshold
- **THEN** 系统 SHALL 在发出模型请求前报告配置错误
- **AND** SHALL NOT 静默禁用预算保护

