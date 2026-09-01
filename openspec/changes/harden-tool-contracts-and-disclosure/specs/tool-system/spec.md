## MODIFIED Requirements

### Requirement: Unified tool registration and execution

系统 SHALL 通过统一注册表向模型暴露当前启用工具的确定性 schema snapshot、按名称串行执行工具，并将成功、失败或控制信号表示为关联原始 tool call id 的工具结果；同一 Session 的普通运行 SHALL NOT 因注册发现顺序或使用频率改变基础工具 schema 顺序。Registry SHALL 验证注册 schema 及模型原始参数，并在 Policy rewrite 后重新验证实际参数。

#### Scenario: Registered tool is called

- **WHEN** 模型返回一个已注册且当前启用工具的名称和符合 schema 的参数
- **THEN** 系统 SHALL 按模型提供的原始参数执行该工具
- **AND** SHALL 将关联原始 tool call id 的结果作为 tool-role 消息返回模型

#### Scenario: Tool arguments violate the schema

- **WHEN** 参数包含未知字段、缺少必填字段或违反类型、枚举、数值及嵌套 JSON Schema 约束
- **THEN** Registry SHALL 在 Policy Hook 和工具副作用前返回结构化 `ToolArgumentsInvalid`
- **AND** 结果 SHALL 指明有界字段路径与约束原因而不静默删除、转换或补写参数

#### Scenario: Policy rewrites arguments

- **WHEN** Policy Hook 明确返回 rewrite 参数
- **THEN** Registry SHALL 对 rewrite 后参数执行相同 schema 校验并在轨迹中区分原始参数与实际参数
- **AND** 非法 rewrite SHALL fail closed，工具 SHALL NOT 执行

#### Scenario: Tool is missing or fails

- **WHEN** 工具不存在、未启用、参数无效或执行期间发生异常
- **THEN** 系统 SHALL 返回结构化失败的工具结果
- **AND** 单次工具失败 SHALL NOT 自动终止 Agent 主循环

#### Scenario: Multiple tools are requested together

- **WHEN** 同一次模型响应按顺序声明多个工具调用
- **THEN** 系统 SHALL 按声明顺序逐个执行并记录每个工具调用
- **AND** SHALL NOT 在本 change 中并发执行这些工具

#### Scenario: Tool schemas are requested repeatedly

- **GIVEN** 同一 Session/epoch 的基础工具和披露账本未变化且能力未被安全撤销
- **WHEN** Runtime 多次构造 Provider 请求
- **THEN** 工具 schema SHALL 使用相同规范化字段、稳定排序和 schema hash
- **AND** SHALL NOT 按调用频率、最后使用时间或非确定性注册顺序重排

### Requirement: Bounded code execution

`code_run` SHALL 通过受约束的子进程执行显式提供且当前 runner profile 支持的脚本，并返回 stdout、stderr、退出码和执行状态的有界表示；模型可见 schema SHALL NOT 声明当前 profile 无法执行的语言。

#### Scenario: Container runner schema is exposed

- **WHEN** Runtime 使用 container runner 注册 `code_run`
- **THEN** `type` 枚举 SHALL 只包含 `python`
- **AND** 直接请求 PowerShell SHALL 在创建子进程前失败

#### Scenario: Trusted-host runner schema is exposed

- **WHEN** Runtime 使用合法 trusted-host runner 注册 `code_run`
- **THEN** schema SHALL 包含 Python，并仅在宿主实际探测到 PowerShell 时包含 `powershell`
- **AND** epoch 内 SHALL 冻结该能力集合而不随 PATH 临时变化漂移

#### Scenario: Code execution is disabled

- **WHEN** runner profile 为 disabled
- **THEN** Runtime SHALL NOT 向模型注册不可工作的 `code_run`

#### Scenario: Script completes normally

- **WHEN** 模型提供受支持的脚本类型、workspace 内工作目录和显式脚本
- **THEN** 工具 SHALL 在子进程中执行脚本
- **AND** SHALL 返回退出码以及 stdout 和 stderr

#### Scenario: Script exceeds timeout

- **WHEN** 脚本执行超过配置的超时时间
- **THEN** 工具 SHALL 终止当前执行并返回 timeout 状态
- **AND** Agent Loop SHALL NOT 将超时结果表示为成功

#### Scenario: Runtime internals are requested

- **WHEN** 脚本尝试依赖仅能通过进程内 `eval`、`exec` 或对象注入获得的 Runtime 内部对象
- **THEN** `code_run` SHALL NOT 提供这些对象
- **AND** SHALL NOT 在 Agent 主进程内执行该脚本

#### Scenario: Code output exceeds model bound

- **WHEN** stdout 或 stderr 超过模型可见输出上限
- **THEN** 返回模型的工具结果 SHALL 显式标记截断
- **AND** 原始脱敏输出 SHALL 进入受管本地轨迹 payload

### Requirement: Progressive schema disclosure preserves cache stability

可选 Tool Search 启用时，Runtime SHALL 只在稳定前缀暴露基础工具与确定性发现入口，并将按需加载的工具 schema 作为绑定 `(session key, conversation epoch)` 的不可变披露事实首次追加；禁用时 SHALL 继续使用完整的确定性 schema snapshot。

#### Scenario: Tool Search is enabled

- **WHEN** 当前 Session/epoch 需要发现未预载的插件或 MCP 工具
- **THEN** Runtime SHALL 返回有界、确定性排序的候选及完整 schema，并仅加载选定工具
- **AND** 已加载 schema SHALL 在首次位置和披露账本中冻结，而不是每轮搬移或写入 Registry 全局状态

#### Scenario: Disclosed tool is used later in the epoch

- **WHEN** 同一 Session/epoch 后续模型决策或 Runtime 重启恢复上下文
- **THEN** Provider 请求 SHALL 包含该 epoch 已披露工具的字节级等价 schema
- **AND** Registry SHALL 仅允许本次模型请求实际可见的基础或已披露工具执行

#### Scenario: Sessions disclose different tools

- **WHEN** 两个 Session 或两个 conversation epoch 搜索不同能力
- **THEN** 各自 Provider 工具集和执行授权 SHALL 只包含自身披露记录
- **AND** 一个范围的搜索 SHALL NOT 改变另一个范围的 schema hash 或可执行集合

#### Scenario: Tool Search is disabled

- **WHEN** 配置关闭 Tool Search
- **THEN** 当前启用工具 SHALL 继续通过确定性完整 schema snapshot 暴露
- **AND** 默认工具名称和调用合同 SHALL 保持兼容

## ADDED Requirements

### Requirement: Personal-memory tool schemas are faithful

模型可见记忆工具 SHALL 只声明实际消费的参数，并 SHALL 声明完成允许操作所需的全部模型输入。

#### Scenario: Recall schema is requested

- **WHEN** Runtime 暴露 `memory_recall`
- **THEN** schema SHALL 包含构造 `MemoryQuery` 实际支持的查询、路由、细节、scope、状态、敏感度、时间和展开边界
- **AND** SHALL NOT 暴露不会影响检索的写入事实元数据字段

#### Scenario: Managed explicit memory is written

- **WHEN** Runtime 暴露 `memory_manage` 的 remember/correct 操作
- **THEN** schema SHALL 允许实现实际消费的 fact type、subject、entity、predicate、value 和 sensitivity 元数据
- **AND** 每个合法传入字段 SHALL 进入对应 mutation 或明确返回拒绝，不得被静默忽略
