# Tool System Specification

## Purpose

定义模型发现工具 schema、按统一协议调用工具并安全接收结果的行为，同时约束工具失败、推理往返次数、基础工具能力和 workspace 文件访问边界。
## Requirements

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

系统 SHALL 保持 `code_run`、`file_read`、`file_patch`、`file_write`、`update_working_checkpoint`、`ask_user`、`start_long_term_update`、`time` 和 `memory_recall` 九个 GenericAgent 风格默认工具；当 Skill Runtime 启用时 SHALL 额外注册只读 `skill_load` 作为第十个内置工具，并 SHALL NOT 提供已被替代的 `calculator`、`memory_write`、`filesystem_read` 或旧版 SubAgent 工具实现。

#### Scenario: Default tool schemas are requested

- **WHEN** Runtime 使用默认工具配置构造一次模型请求
- **THEN** 模型可见工具 SHALL 至少包含九个默认工具
- **AND** SHALL NOT 包含 `calculator`、`memory_write`、`filesystem_read`、`web_scan`、`web_execute_js` 或 `spawn_subagent`

#### Scenario: Default tool schemas are requested with Skills enabled

- **WHEN** Runtime 使用默认工具配置且 Skill Runtime 可用
- **THEN** 模型可见工具 SHALL 包含九个既有默认工具和 `skill_load`
- **AND** SHALL NOT 包含 `calculator`、`memory_write`、`filesystem_read`、`web_scan`、`web_execute_js`、`spawn_subagent` 或任何 Skill 管理工具

#### Scenario: Default tool schemas are requested with Skills disabled

- **WHEN** Skill Runtime 被配置关闭或未可靠装配
- **THEN** 模型可见工具 SHALL 保持九个既有默认工具
- **AND** SHALL NOT 暴露不可工作的 `skill_load`

#### Scenario: Optional SubAgent tool is enabled

- **WHEN** SubAgent 工具通过配置显式启用且管理器可用
- **THEN** 当前持久任务图版本的 `spawn_subagent` SHALL 在默认工具之外注册
- **AND** SHALL NOT 注册或回退到旧版 SubAgent 委派实现

#### Scenario: Removed legacy tool is requested

- **WHEN** 模型或调用方请求 `calculator`、`memory_write` 或 `filesystem_read`
- **THEN** 当前工具注册表 SHALL 将其作为不存在的工具返回结构化失败
- **AND** Runtime SHALL NOT 提供兼容实现或隐式改写为替代工具

### Requirement: Workspace read confinement

文件读取工具 SHALL 只读取已配置 workspace 内的 UTF-8 普通文件。

#### Scenario: Path escapes workspace

- **WHEN** 请求路径解析到 workspace 之外
- **THEN** 工具 SHALL 拒绝读取

#### Scenario: Target is absent or non-text

- **WHEN** 目标不存在、不是文件或不能按 UTF-8 解码
- **THEN** 工具 SHALL 返回明确的失败结果

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

`start_long_term_update` SHALL 只持久化当前会话的长期整理意图并唤醒触发调度器，不得在当前工具调用中运行记忆整理，也不得绕过“20 个完成闲聊回合”或“成功完成多工具长期任务”的自动触发边界。

#### Scenario: Long-term update is requested before a trigger boundary

- **WHEN** 普通 Agent 在同一会话不足 20 个未消费闲聊回合且当前 trace 尚未满足长期任务完成条件时调用 `start_long_term_update`
- **THEN** 工具 SHALL 返回稳定 hint/request identity 和 waiting-for-trigger 状态
- **AND** SHALL NOT 立即运行 Extractor、创建 Candidate 或声称记忆已经更新

#### Scenario: Trigger boundary becomes eligible

- **WHEN** 已记录整理意图的会话随后达到 20 个完成闲聊回合，或当前多工具长期任务成功提交 trace 终态
- **THEN** 触发调度器 SHALL 幂等创建对应的持久 consolidation request 并唤醒 Worker
- **AND** 当前用户回复 SHALL NOT 等待 Candidate、Governor、Card 或索引完成

#### Scenario: Repeated update hints are submitted

- **WHEN** 同一 session 和未消费边界内重复调用 `start_long_term_update`
- **THEN** 系统 SHALL 合并为同一个持久整理意图
- **AND** SHALL NOT 重置闲聊计数、重复绑定 trace 或创建并行提取请求

#### Scenario: Offline consolidation is disabled

- **WHEN** consolidation 关闭时调用 `start_long_term_update`
- **THEN** 工具 SHALL 返回明确 disabled 状态和原因
- **AND** SHALL NOT 保存一个永远无法满足的伪运行请求

#### Scenario: Long-term update is requested

- **WHEN** 模型调用 `start_long_term_update`
- **THEN** 系统 SHALL 持久化并返回包含稳定请求标识、关联 trace、scope 和 `pending` 状态的结果
- **AND** 重复的同一工具调用 SHALL 返回同一请求身份而不创建重复请求

#### Scenario: Runtime restarts after request creation

- **WHEN** 请求已提交但 Runtime 在 Worker 消费前重启
- **THEN** 请求 SHALL 继续可查询并在离线能力启用时恢复处理
- **AND** SHALL NOT 退化为仅存在进程内存的状态

#### Scenario: Request is accepted

- **WHEN** 持久请求创建成功
- **THEN** 当前工具调用 SHALL 在不等待 Extractor、Candidate、Card 或 Embedding 的情况下返回
- **AND** SHALL NOT 自动修改 Prompt、Skill、工具实现、训练数据或模型参数

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

启用轨迹记录时，系统 SHALL 保存足以按顺序还原模型所见内容、模型工具意图、实际工具执行和模型所收结果的 canonical 客观事实；大型结果 SHALL 同时保留原始脱敏 payload 与绑定 conversation epoch 的冻结预览/引用，并 SHALL 将评价、隐藏 reasoning 与训练派生数据排除在原始事件之外。

#### Scenario: Tool call completes

- **WHEN** 已注册工具成功、失败、超时或产生控制信号
- **THEN** 原始轨迹 SHALL 保存 epoch、turn/message 序号、模型可见 schema、tool call id、工具名、模型原始参数、实际执行参数、时序、状态和错误
- **AND** SHALL 保存原始脱敏输出以及实际返回模型的有界输出或稳定受管引用

#### Scenario: Large tool result is previewed

- **WHEN** 工具原始脱敏结果超过模型可见预算
- **THEN** 轨迹 SHALL 保存原文 payload 引用、epoch、tool call id、内容哈希、原始/可见大小、转换标志和冻结预览
- **AND** 后续上下文恢复 SHALL 验证模型所见预览与首次提交版本一致

#### Scenario: Preview validation fails during restoration

- **WHEN** 冻结预览的 epoch、tool call id、内容哈希或 payload reference 与 canonical turn 不一致
- **THEN** Runtime SHALL 排除整个受影响 turn 或以可观察 tool-protocol 错误结束
- **AND** SHALL NOT 只注入 tool call、只注入 result 或重新生成不一致预览

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

### Requirement: Governed personal-memory tools

启用个人记忆时，系统 SHALL 区分只读召回、显式正式写入、Candidate 治理操作与离线整理请求恢复操作，并支持显式记住、纠正、冻结、删除、查看、导出、有条件重试治理任务，以及对 consolidation dead-letter 执行有审计的 retry/suppress；显式正式写入 SHALL 以当前用户逐字依据为权威事实来源。

#### Scenario: Agent explicitly recalls memory

- **WHEN** 模型调用 `memory_recall` 并提供查询、可选类型或时间过滤及数量上限
- **THEN** 工具 SHALL 返回有界的结构化命中、稳定记忆 ID、当前性、证据引用和召回解释
- **AND** 该调用 SHALL NOT 修改记忆状态

#### Scenario: User explicitly asks the agent to remember a fact

- **WHEN** 受治理管理工具收到关联当前显式用户消息的 `remember` 操作及逐字 `basis_quote`
- **THEN** 系统 SHALL 从该 quote 确定性移除记忆指令包装并保存原子权威事实、verified Evidence、稳定用户消息身份、事实类型、敏感度和允许的结构槽位
- **AND** 模型提供的规范化 content 与 basis 不一致或不能由其确定性支持时 SHALL 拒绝写入，而不得借合法 quote 保存无关事实

#### Scenario: User explicitly corrects a fact

- **WHEN** `correct` 操作提供当前用户逐字依据、目标 Claim ID 和 expected revision
- **THEN** 系统 SHALL 使用同一显式证据合同创建修正事实并原子保存 corrects/supersedes 关系
- **AND** 旧事实、Evidence 和修订历史 SHALL 保持可审计

#### Scenario: Agent attempts an unsupported implicit write

- **WHEN** 模型请求把推断、网页文本、工具输出或 Assistant 回复直接发布为正式个人记忆且没有允许的批准主体
- **THEN** 管理工具 SHALL 拒绝正式写入或仅创建明确标记的 candidate
- **AND** SHALL 返回拒绝或候选原因

#### Scenario: User retries a governance job

- **WHEN** 有权用户或操作者请求重试当前 scope 内仍绑定未变化 Candidate 的 dead-letter governance job
- **THEN** 工具 SHALL 通过治理服务执行条件状态迁移并返回实际 Job ID、旧状态、新状态和 revision
- **AND** SHALL NOT 直接执行 SQL、清除历史审计或重试 stale Job

#### Scenario: Operator retries a consolidation dead-letter

- **WHEN** 有权操作者对当前 scope 内尚未提交 Candidate 的 quarantined consolidation request 执行 `request_retry`
- **THEN** 管理工具 SHALL 通过记忆服务将同一稳定 request 和 trace binding 恢复为 retry 并唤醒 Worker
- **AND** SHALL NOT 创建新的 request ID、清除历史错误审计或释放 trace 给其他触发 lane

#### Scenario: Operator cancels a consolidation dead-letter

- **WHEN** 有权操作者对当前 scope 内尚未提交 Candidate 的 quarantined consolidation request 执行 `request_cancel`
- **THEN** 管理工具 SHALL 将 request 和 consumption 转为 suppressed，并返回实际 request ID 与前后状态
- **AND** SHALL NOT 暴露 force-release、自动重放 suppressed trace 或取消已提交 Candidate 的请求

#### Scenario: User freezes or forgets a memory

- **WHEN** 管理工具收到当前用户对允许 scope 内目标 ID 的 `freeze` 或 `forget` 操作
- **THEN** 系统 SHALL 更新合法生命周期并返回实际受影响 ID
- **AND** 原始 Claim、来源和修订历史 SHALL 保持可审计

#### Scenario: Memory subsystem is disabled

- **WHEN** 任一个人记忆工具在 memory 关闭时被调用
- **THEN** 工具 SHALL 返回结构化 disabled 结果
- **AND** SHALL NOT 创建 memory database 写入

#### Scenario: Agent requests summary-level recall

- **WHEN** `memory_recall` 使用 `detail_level=summary` 或省略细节层级且 auto 路由命中稳定 Card statement
- **THEN** 工具 SHALL 优先返回有界 Card statement 摘要而不默认展开全部 Claim/Evidence
- **AND** SHALL 返回可供后续 fact/evidence 展开的 statement 和 Claim refs

#### Scenario: Agent requests fact or evidence expansion

- **WHEN** `memory_recall` 使用 `detail_level=fact|evidence` 并引用已命中的 Card/statement 或提供精确、高风险查询
- **THEN** 工具 SHALL 通过受管关系有界展开当前 Claim，并仅在 evidence 层返回 scope-safe Evidence 摘要/引用
- **AND** 工具 SHALL 重新执行 scope、敏感度、生命周期和字符预算，不得返回越权原文

#### Scenario: Caller selects a retrieval route

- **WHEN** 调用者选择 auto、card-first、claim-first、episode-first 或 hybrid
- **THEN** 工具 SHALL 使用请求路由或返回明确的安全降级/不支持结果，并在响应中报告实际执行路由
- **AND** card-first SHALL 保留规范定义的 Claim 回退，episode-first SHALL NOT 把事件直接提升为正式 Claim

#### Scenario: User lists offline candidates

- **WHEN** 有权用户请求查看其 scope 内待审 Candidate
- **THEN** 工具 SHALL 返回有界 Candidate ID、结构化内容、状态、来源摘要、Evidence reference、冲突诊断和提取版本
- **AND** SHALL 过滤其他 scope 或超过调用者敏感权限的正文

#### Scenario: User approves or rejects a candidate

- **WHEN** 管理工具收到有权用户或人工主体对目标 Candidate 的 `approve` 或 `reject` 操作
- **THEN** 系统 SHALL 执行合法状态转移并返回实际影响 ID、前后状态和修订
- **AND** Extractor、自动 Worker 或普通 Assistant 身份 SHALL NOT 自行批准其提取结果；Governance SubAgent 只能通过专用受限决定合同请求 Policy Gate 执行转换

#### Scenario: User corrects or freezes a memory

- **WHEN** 管理工具收到关联显式用户消息的 `correct` 或 `freeze` 操作及目标 ID
- **THEN** 系统 SHALL 创建修正版本或更新冻结状态并返回实际受影响 ID
- **AND** 原始 claim、来源和修订历史 SHALL 保持可审计

#### Scenario: Tool description states the two-phase write contract

- **WHEN** 模型读取 `memory_manage` 工具描述或 `remember`/`correct` 参数描述
- **THEN** 描述 SHALL 说明 `remember`/`correct` 是在线证据层、`content` 必须与当前用户逐字 `basis_quote` 一致（可去“请记住/记住/remember”指令包装），并禁止改写人称、加注或润色
- **AND** 描述 SHALL 指出归纳、抽象、消歧与冲突合并属于离线整理层、不由本工具完成
- **AND** 描述 SHALL NOT 回显任何用户正文样本、embedding 向量或安全合同实现细节

#### Scenario: Rejection names the violation and points to self-correction

- **WHEN** `remember`/`correct` 因缺少当前用户逐字依据被拒绝
- **THEN** 工具结果 SHALL 返回稳定错误码 `missing-explicit-basis`
- **AND** 结果信息 SHALL 指出缺少当前用户消息中的逐字依据并要求逐字引用，而不得回显越权正文或包含 embedding 或 API key

#### Scenario: Content mismatch rejection points to verbatim copy

- **WHEN** `remember`/`correct` 的 `content` 与逐字 `basis_quote` 经 NFKC 加空白归一后不一致被拒绝
- **THEN** 工具结果 SHALL 返回稳定错误码 `basis-content-mismatch`
- **AND** 结果信息 SHALL 指出 `content` 与依据不一致、要求逐字引用当前用户原话且不得改写人称或加注
- **AND** 判定逻辑 SHALL 保持 `_same_fact` 精确相等与 `basis not in context.user_content` 检查不变

#### Scenario: Single explicit statement is accepted as evidence

- **WHEN** 模型对一条此前仅出现一次的显式用户陈述提供合法逐字 `basis_quote` 并以一致 `content` 调用 `remember`
- **THEN** 系统 SHALL 接受该证据写入
- **AND** SHALL NOT 仅因“该事实此前只出现一次”而拒绝
- **AND** 是否升级为稳定语义记忆 SHALL 由离线整理层决定，而非由同步写入工具决定

#### Scenario: Verbatim write still succeeds unchanged

- **WHEN** 模型逐字引用当前用户原话（仅去“请记住”指令包装）并调用 `remember`
- **THEN** 系统 SHALL 按既有合同创建权威事实、verified Evidence 与稳定身份
- **AND** 本变更对工具描述与拒绝信息的改动 SHALL NOT 改变该成功路径的返回结构

### Requirement: Personal-memory deletion and export results

个人记忆管理操作 SHALL 对删除和导出返回明确范围，并区分个人记忆索引与原始 trajectory 的保留边界。

#### Scenario: User forgets selected memories

- **WHEN** `forget` 操作指定用户可管理的一个或多个 memory ID
- **THEN** 目标 SHALL 立即停止默认召回并产生最小审计 tombstone
- **AND** 工具结果 SHALL 说明原始 trajectory 是否仍受独立保留策略管理

#### Scenario: User exports personal memory

- **WHEN** `export` 操作成功
- **THEN** 导出 SHALL 包含当前 cards、claims、状态、时间和可公开证据引用
- **AND** SHALL 遵守脱敏、scope 和权限边界

### Requirement: Required evidence failure boundary

必需轨迹证据写入失败时，系统 SHALL 停止新的模型和工具操作；Observer 插件失败不得改变已产生的正常业务结果，Policy 插件失败 SHALL 在工具副作用前阻止执行。

#### Scenario: Checkpoint side effect was committed
- **WHEN** 工作 checkpoint 已更新但对应必需轨迹写入失败
- **THEN** turn SHALL 以 `trace-write-failed` 终止
- **AND** SHALL NOT 发起后续模型或工具调用

#### Scenario: Observer recording fails
- **WHEN** 只读 Observer hook 或其诊断记录失败
- **THEN** 主对话 SHALL 继续使用未被 Observer 修改的结果

### Requirement: Read-only Skill loading tool

`skill_load` SHALL 只通过已装配 Skill Runtime 解析当前 Session 绑定版本并读取允许内容，不得接受物理 artifact 路径、执行脚本、修改 Registry、写入 package 或改变工具权限。

#### Scenario: Model supplies a physical path

- **WHEN** 模型尝试用 `skill_load` 传入绝对路径、artifact path 或未定义参数
- **THEN** 工具 SHALL 按严格 schema 拒绝调用
- **AND** SHALL NOT 将该请求转交通用文件读取器

#### Scenario: Model asks to execute a Skill

- **WHEN** 模型加载 Skill 后需要执行其步骤
- **THEN** 模型 SHALL 使用当前已授权的通用、浏览器、MCP 或 SubAgent 工具完成动作
- **AND** `skill_load` SHALL 只返回说明内容而不产生业务副作用

### Requirement: Least-privilege governance SubAgent tools

系统 SHALL 为 `memory-governor` Profile 提供专用、最小权限的 Candidate 读取、Evidence 读取、同 scope 相关记忆读取和结构化决定工具；这些工具 SHALL NOT 允许任意 Claim 状态写入、跨 scope 查询、文件/网络/代码能力或再次委派。

#### Scenario: Governance SubAgent reviews a candidate

- **WHEN** Runtime 以 `memory-governor` Profile 启动治理任务
- **THEN** SubAgent SHALL 只能读取任务绑定的 Candidate、已验证 Evidence 和允许 scope 内的相关 Claim
- **AND** 提交决定 SHALL 包含 candidate ID、expected revision、固定 decision 枚举、reason codes、置信度和 governor/prompt/policy 版本

#### Scenario: Governance SubAgent attempts an arbitrary status update

- **WHEN** SubAgent 请求未绑定 Candidate、任意目标状态、跨 scope 目标或通用 `memory_manage` 写操作
- **THEN** 工具层 SHALL 拒绝调用并记录不含敏感正文的 denied 审计
- **AND** Claim、governance job 和派生投影 SHALL 保持不变

#### Scenario: Policy Gate applies a governance decision

- **WHEN** 专用决定工具收到格式有效的 approve、reject、needs-user-review 或 defer 决定
- **THEN** Policy Gate SHALL 按证据、风险、冲突、frozen、策略版本和 expected revision 校验允许的实际转换
- **AND** 工具 SHALL 返回决定 ID、前后状态、实际影响 ID及 approved/rejected/escalated/stale/denied 结果

### Requirement: CLI candidate review experience

交互式 CLI SHALL 在不阻塞普通输入和回复渲染的前提下显示当前用户 scope 内 `needs-user-review` 的有界数量，并 SHALL 提供候选列表、详情、批准和拒绝入口；CLI SHALL 复用治理服务/工具合同而不得直接读写 SQLite。

#### Scenario: CLI shows pending user reviews

- **WHEN** 当前 scope 存在一个或多个 `needs-user-review` governance job
- **THEN** CLI 状态区或记忆状态视图 SHALL 显示待用户审核数量
- **AND** `/memory candidates` 或等价命令 SHALL 返回有界列表，包括 Candidate ID、事实摘要、风险/冲突原因和审核状态

#### Scenario: User inspects and approves a candidate in CLI

- **WHEN** 用户通过 CLI 打开 Candidate 详情并确认 approve
- **THEN** CLI SHALL 展示 scope-safe Evidence 摘要和自动治理理由，并通过同一治理服务提交带 actor/revision 的用户决定
- **AND** 成功结果 SHALL 显示实际前后状态，stale/forbidden 结果 SHALL 不伪装成批准成功

#### Scenario: CLI remains usable while governance runs

- **WHEN** Governance SubAgent 正在审核或治理队列暂时不可用
- **THEN** CLI SHALL 继续接受用户输入并显示 running/retry/unavailable 的安全状态
- **AND** SHALL NOT 阻塞在线 turn、重复输入框或破坏历史会话渲染

### Requirement: Offline-memory request diagnostics

系统 SHALL 提供只读、scope-safe 的长期整理请求状态查询，至少区分 pending、running、retry、completed、failed/dead-letter 和 cancelled，并报告有界尝试、时间、版本与错误分类而不暴露敏感正文、凭证或向量。

#### Scenario: User checks a request

- **WHEN** 调用者查询其有权访问的长期整理 request ID
- **THEN** 工具 SHALL 返回当前状态、关联 trace、候选数量、尝试次数、版本和安全错误分类
- **AND** 查询 SHALL NOT 触发新的提取或状态修改

#### Scenario: Caller checks another scope

- **WHEN** 调用者查询不属于其 scope 或无权限访问的 request ID
- **THEN** 系统 SHALL 返回 not-found/forbidden 的安全结果
- **AND** SHALL NOT 泄露请求是否存在、来源正文或 Candidate 内容
