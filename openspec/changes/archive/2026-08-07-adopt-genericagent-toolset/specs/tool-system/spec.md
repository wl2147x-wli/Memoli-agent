## MODIFIED Requirements

### Requirement: Unified tool registration and execution

系统 SHALL 通过统一注册表向模型暴露当前启用工具的 schema、按名称串行执行工具，并将成功、失败或控制信号表示为关联原始 tool call id 的工具结果。

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

### Requirement: Bounded reasoning loop

系统 SHALL 在最大模型迭代数、最长墙钟时间和无进展检测约束内，串行执行完成任务所需的多轮模型与工具往返。

#### Scenario: Model requests tools

- **WHEN** 模型响应包含一个或多个工具调用
- **THEN** 系统 SHALL 执行这些调用并将结果加入模型可见上下文
- **AND** 在仍有执行预算时 SHALL 继续下一次模型决策，而不是强制下一次响应必须结束

#### Scenario: Loop budget is exhausted

- **WHEN** 当前 turn 达到模型迭代、墙钟时间或无进展边界
- **THEN** 系统 SHALL 停止发起新的模型或工具操作
- **AND** SHALL 返回可区分的非完成终止结果

### Requirement: Built-in utility tools

系统 SHALL 默认向模型提供 `code_run`、`file_read`、`file_patch`、`file_write`、`update_working_checkpoint`、`ask_user`、`start_long_term_update`、`time` 和 `memory_recall` 九个工具，并 SHALL NOT 默认同时暴露被替代或需要显式启用的同义工具。

#### Scenario: Default tool schemas are requested

- **WHEN** Runtime 使用默认工具配置构造一次模型请求
- **THEN** 模型可见工具 SHALL 包含九个默认工具
- **AND** SHALL NOT 包含 `calculator`、`memory_write`、`filesystem_read`、`web_scan`、`web_execute_js` 或 `spawn_subagent`

#### Scenario: Optional SubAgent tool is enabled

- **WHEN** SubAgent 工具通过配置显式启用且管理器可用
- **THEN** `spawn_subagent` SHALL 在九个默认工具之外注册

#### Scenario: Calculator evaluates allowed syntax

- **GIVEN** 兼容用 `calculator` 被显式注册，而不是作为默认工具暴露
- **WHEN** 输入只包含数值、括号以及受支持的算术运算符
- **THEN** `calculator` SHALL 返回计算结果

#### Scenario: Calculator receives unsupported syntax

- **GIVEN** 兼容用 `calculator` 被显式注册，而不是作为默认工具暴露
- **WHEN** 表达式包含函数调用、变量或不受支持的 AST 节点
- **THEN** `calculator` SHALL 拒绝计算并返回失败结果

## ADDED Requirements

### Requirement: Workspace file operations

`file_read`、`file_patch` 与 `file_write` SHALL 只操作已配置 workspace 内的 UTF-8 普通文件，并 SHALL 保持模型参数的文本、空白、Unicode 字符和换行语义。

#### Scenario: File is read by line range

- **WHEN** 模型调用 `file_read` 并提供一基起始行与读取行数
- **THEN** 工具 SHALL 返回对应的有界文本范围
- **AND** 启用行号时 SHALL 以可区分于文件正文的方式标识行号

#### Scenario: Read result exceeds output bound

- **WHEN** 读取内容超过模型可见输出上限
- **THEN** 工具 SHALL 返回明确标记为截断的有界结果
- **AND** 原始脱敏内容 SHALL 仍可通过本地轨迹 payload 还原

#### Scenario: Patch has one exact match

- **WHEN** `file_patch.old_content` 非空且在目标文件中恰好精确出现一次
- **THEN** 工具 SHALL 将该匹配替换为 `new_content`
- **AND** SHALL 返回成功状态和变更摘要

#### Scenario: Patch match is absent or ambiguous

- **WHEN** `old_content` 在目标文件中出现零次或多于一次
- **THEN** 工具 SHALL 拒绝修改文件并返回可恢复错误
- **AND** SHALL NOT 静默调整空白、缩进、引号或换行以制造匹配

#### Scenario: File content is explicitly written

- **WHEN** 模型调用 `file_write` 并显式提供 `content` 及受支持的 `overwrite`、`append` 或 `prepend` 模式
- **THEN** 工具 SHALL 按指定模式写入并返回实际写入结果
- **AND** SHALL NOT 从 Assistant 普通回复或代码块隐式推断写入内容

#### Scenario: Path escapes workspace

- **WHEN** 任一文件工具的规范化目标位于 workspace 外或通过链接逃逸 workspace
- **THEN** 工具 SHALL 拒绝该操作
- **AND** SHALL NOT 读取或修改目标

#### Scenario: Target is absent or not supported

- **WHEN** 读取或修改目标不存在、不是普通文件或不能按 UTF-8 解码
- **THEN** 工具 SHALL 返回明确的失败结果

### Requirement: Bounded code execution

`code_run` SHALL 通过受约束的子进程执行显式提供的 Python 或 PowerShell 脚本，并返回 stdout、stderr、退出码和执行状态的有界表示。

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

### Requirement: Working checkpoint control

`update_working_checkpoint` SHALL 替换当前任务的短期工作信息和相关 SOP 引用，并使最新投影可用于后续 turn，而不写入长期记忆。

#### Scenario: Checkpoint is updated

- **WHEN** 模型调用 `update_working_checkpoint` 提供 `key_info` 和可选 `related_sop`
- **THEN** 系统 SHALL 更新当前任务的工作 checkpoint
- **AND** 后续 turn SHALL 能够获得最新 checkpoint

#### Scenario: A new checkpoint replaces old progress

- **GIVEN** 当前任务已经存在工作 checkpoint
- **WHEN** 工具再次成功更新 checkpoint
- **THEN** 当前投影 SHALL 使用新内容替换旧内容
- **AND** 两次调用事实 SHALL 在 append-only 轨迹中保持可区分

### Requirement: Explicit user input request

`ask_user` SHALL 通过通道无关的结构化控制结果请求用户输入，而不是在工具实现内直接读取交互式终端。

#### Scenario: Tool asks the user

- **WHEN** 模型调用 `ask_user` 并提供问题及可选候选项
- **THEN** 当前 turn SHALL 以 `needs-user` 结束
- **AND** 用户可见结果 SHALL 包含该问题和候选项

#### Scenario: Non-CLI channel invokes ask_user

- **WHEN** `ask_user` 从 API、Web 或其他非 CLI 通道触发
- **THEN** 工具 SHALL 返回相同的结构化控制结果
- **AND** SHALL NOT 尝试从进程 stdin 读取答案

### Requirement: Deferred long-term update request

`start_long_term_update` SHALL 只创建可追踪的待处理长期整理请求，不在当前工具调用中执行记忆、Prompt、Skill、程序或模型参数更新。

#### Scenario: Long-term update is requested

- **WHEN** 模型调用 `start_long_term_update`
- **THEN** 系统 SHALL 返回包含稳定请求标识和 `pending` 状态的结果
- **AND** SHALL 将该请求关联到当前 trace

#### Scenario: Request is recorded but not consumed

- **WHEN** 本 change 范围内产生一个长期整理请求
- **THEN** 系统 SHALL NOT 自动把当前轨迹写入长期记忆或训练数据
- **AND** SHALL NOT 自动修改 Prompt、Skill、工具实现或模型参数

### Requirement: Optional browser toolset

系统 SHALL 仅在浏览器能力显式启用且 Browser adapter 可用时成对注册 `web_scan` 与 `web_execute_js`。

#### Scenario: Browser toolset is enabled

- **WHEN** 浏览器配置启用且 adapter 成功初始化
- **THEN** `web_scan` 与 `web_execute_js` SHALL 同时成为模型可见工具

#### Scenario: Browser toolset is disabled or unavailable

- **WHEN** 浏览器配置关闭、adapter 缺失或初始化失败
- **THEN** 两个浏览器工具 SHALL 都不注册
- **AND** 默认九工具 SHALL 保持可用

#### Scenario: Browser output is saved to a file

- **WHEN** `web_execute_js` 请求把长文本结果保存到文件
- **THEN** 保存目标 SHALL 遵守相同的 workspace 文件边界
- **AND** 工具结果 SHALL 返回有界摘要和保存位置

### Requirement: Faithful raw tool trajectory

启用轨迹记录时，系统 SHALL 保存足以按顺序还原模型所见内容、模型工具意图、实际工具执行和模型所收结果的客观事实，并 SHALL 将评价与训练派生数据排除在原始事件之外。

#### Scenario: Tool call completes

- **WHEN** 已注册工具成功、失败、超时或产生控制信号
- **THEN** 原始轨迹 SHALL 保存模型可见 schema、tool call id、工具名、模型原始参数、实际执行参数、开始与结束时序、执行状态和错误
- **AND** SHALL 保存原始脱敏输出以及实际返回模型的有界输出或其受管引用

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
