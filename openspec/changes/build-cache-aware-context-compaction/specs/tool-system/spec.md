## MODIFIED Requirements

### Requirement: Unified tool registration and execution

系统 SHALL 通过统一注册表向模型暴露当前启用工具的确定性 schema snapshot、按名称串行执行工具，并将成功、失败或控制信号表示为关联原始 tool call id 的工具结果；同一 Session 的普通运行 SHALL NOT 因注册发现顺序或使用频率改变工具 schema 顺序。

#### Scenario: Registered tool is called

- **WHEN** 模型返回一个已注册且当前启用工具的名称和参数
- **THEN** 系统 SHALL 按模型提供的原始参数执行该工具
- **AND** SHALL 将关联原始 tool call id 的结果作为 tool-role 消息返回模型

#### Scenario: Tool is missing or fails

- **WHEN** 工具不存在、未启用、参数无效或执行期间发生异常
- **THEN** 系统 SHALL 返回结构化失败的工具结果
- **AND** 单次工具失败 SHALL NOT 自动终止 Agent 主循环

#### Scenario: Multiple tools are requested together

- **WHEN** 同一次模型响应按顺序声明多个工具调用
- **THEN** 系统 SHALL 按声明顺序逐个执行并记录每个工具调用
- **AND** SHALL NOT 在本 change 中并发执行这些工具

#### Scenario: Tool schemas are requested repeatedly

- **GIVEN** 同一 Session 的工具能力未被安全撤销
- **WHEN** Runtime 多次构造 Provider 请求
- **THEN** 工具 schema SHALL 使用相同规范化字段、稳定排序和 schema hash
- **AND** SHALL NOT 按调用频率、最后使用时间或非确定性注册顺序重排

### Requirement: Faithful raw tool trajectory

启用轨迹记录时，系统 SHALL 保存足以按顺序还原模型所见内容、模型工具意图、实际工具执行和模型所收结果的客观事实；大型结果 SHALL 同时保留原始脱敏 payload 与实际模型可见的冻结预览/引用，并 SHALL 将评价与训练派生数据排除在原始事件之外。

#### Scenario: Tool call completes

- **WHEN** 已注册工具成功、失败、超时或产生控制信号
- **THEN** 原始轨迹 SHALL 保存模型可见 schema、tool call id、工具名、模型原始参数、实际执行参数、开始与结束时序、执行状态和错误
- **AND** SHALL 保存原始脱敏输出以及实际返回模型的有界输出或稳定受管引用

#### Scenario: Large tool result is previewed

- **WHEN** 工具原始脱敏结果超过模型可见预算
- **THEN** 轨迹 SHALL 保存原文 payload 引用、内容哈希、原始/可见大小、转换标志和冻结预览
- **AND** 后续上下文恢复 SHALL 能证明模型所见预览与首次提交版本一致

#### Scenario: Explicit argument expansion occurs

- **WHEN** 文件引用或其他已声明机制把模型原始参数展开为实际执行参数
- **THEN** 轨迹 SHALL 分别保存原始表示和实际执行表示
- **AND** 工具结果 SHALL 明确告知发生了该转换

#### Scenario: Raw trajectory is persisted

- **WHEN** 工具事实成功提交到 SQLite
- **THEN** 原始事件 SHALL NOT 包含 reward、Rubric、成功标签、正确工具标签、失败归因或 SFT/RL 标签
- **AND** SHALL NOT 自动进入 Memory、Evolution 或 Post-training

#### Scenario: Required trace write fails before a side effect

- **WHEN** 副作用工具的意图无法在执行前成功提交
- **THEN** 系统 SHALL NOT 执行该副作用
- **AND** 当前 turn SHALL 以可观察的轨迹写入失败结束

## ADDED Requirements

### Requirement: Progressive schema disclosure preserves cache stability

可选 Tool Search 启用时，Runtime SHALL 只在稳定前缀暴露基础工具与确定性发现入口，并将按需加载的工具 schema 作为不可变轨迹内容首次追加；禁用时 SHALL 继续使用完整的确定性 schema snapshot。

#### Scenario: Tool Search is enabled
- **WHEN** 当前 Session 需要发现未预载的插件或 MCP 工具
- **THEN** Runtime SHALL 返回有界、确定性排序的候选并仅加载选定工具完整 schema
- **AND** 已加载 schema SHALL 在首次位置冻结而不是每轮搬到上下文末尾

#### Scenario: Tool Search is disabled
- **WHEN** 配置关闭 Tool Search
- **THEN** 当前启用工具 SHALL 继续通过确定性完整 schema snapshot 暴露
- **AND** 默认工具名称和调用合同 SHALL 保持兼容
