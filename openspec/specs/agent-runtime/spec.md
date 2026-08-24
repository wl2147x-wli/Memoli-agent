# Agent Runtime Specification

## Purpose

定义 Memoli 从配置加载、组件装配、消息接入、会话管理到模型推理和生成回复的核心运行行为，以及远程模型失败和应用关闭时必须保持的边界。
## Requirements
### Requirement: Default-startable configuration

系统 SHALL 从 TOML 加载运行配置，并在配置文件缺失时使用内置默认值启动。

#### Scenario: Configuration file is absent

- **WHEN** 用户在没有指定配置文件的情况下启动 Memoli
- **THEN** 系统 SHALL 构造完整的默认配置
- **AND** 默认配置 SHALL 启用 CLI、记忆和 SubAgent，关闭 Proactive 与 MCP

#### Scenario: Configuration shape is invalid

- **WHEN** 配置中本应为 TOML table 的字段具有其他类型
- **THEN** 系统 SHALL 报告配置类型错误，而不是静默忽略该字段

### Requirement: Provider selection and fallback

系统 SHALL 支持显式 Echo Provider、OpenAI Chat Completions/OpenAI-compatible Provider 和 Anthropic Messages Provider；所有正式模型调用 SHALL 使用统一模型合同，并且 fallback SHALL 仅切换到显式配置、能力兼容的真实模型 Profile。

#### Scenario: OpenAI credentials are available

- **GIVEN** agent route 选择 OpenAI 或 OpenAI-compatible Profile 且所需凭证可用
- **WHEN** Agent 请求模型回复
- **THEN** 系统 SHALL 通过 OpenAI Chat Completions 协议发送规范化消息及可用工具 schema
- **AND** SHALL 将响应转换为统一模型合同

#### Scenario: Anthropic credentials are available

- **GIVEN** agent route 选择 Anthropic Profile 且所需凭证可用
- **WHEN** Agent 请求模型回复
- **THEN** 系统 SHALL 通过 Anthropic Messages 原生协议发送规范化内容块及可用工具 schema
- **AND** SHALL 将响应转换为与 OpenAI 相同的统一模型合同

#### Scenario: Real provider is temporarily unavailable

- **GIVEN** 已配置主 Provider 和至少一个能力兼容的真实 fallback Profile
- **WHEN** 主 Provider 的可重试请求在有界重试后仍失败
- **THEN** 系统 SHALL 按配置顺序尝试兼容 fallback
- **AND** 回复元数据与运行轨迹 SHALL 标识请求 Provider、实际 Provider、切换原因和尝试次数

#### Scenario: Real provider fails without fallback

- **WHEN** 正式 Provider 失败且没有显式配置的兼容 fallback
- **THEN** turn SHALL 以可观察的 Provider 错误失败
- **AND** 系统 SHALL NOT 使用 Echo 生成看似成功的回复

#### Scenario: Formal provider credentials are absent

- **WHEN** 配置显式选择 OpenAI、OpenAI-compatible 或 Anthropic，但缺少必需凭证
- **THEN** 系统 SHALL 在发出模型请求前报告配置错误
- **AND** SHALL NOT 静默使用 Echo Provider

#### Scenario: Echo provider is selected explicitly

- **WHEN** 配置文件缺失而使用内置本地默认值，或用户/测试显式选择 Echo Profile
- **THEN** 系统 SHALL 使用 Echo Provider 维持本地链路
- **AND** 响应元数据 SHALL 明确标识 Echo 而不伪装成正式模型

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

### Requirement: Runtime lifecycle

系统 SHALL 集中启动和关闭插件、MCP、AgentLoop、ProactiveLoop 与已启用通道。

#### Scenario: Runtime starts and stops normally

- **WHEN** 应用运行时启动后再关闭
- **THEN** 组件 SHALL 按依赖顺序启动
- **AND** 后台任务及外部连接 SHALL 被有序停止和释放

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

每个 turn SHALL 产生 `completed`、`needs-user`、`failed`、`budget-exhausted` 或 `cancelled` 之一的结构化终止原因，并关联稳定的 trace 标识；取消当前 turn SHALL NOT 隐式取消整个消息泵。

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

#### Scenario: User cancels current turn

- **WHEN** 前台通道对活动 turn 发出用户取消请求
- **THEN** 系统 SHALL 取消该 turn 的 Provider、工具等待和后续操作并以 `cancelled` 结束
- **AND** AgentLoop SHALL 保持运行并继续消费后续排队消息

#### Scenario: Runtime cancels the message pump

- **WHEN** Runtime 关闭并取消 AgentLoop 消息泵
- **THEN** 系统 SHALL 传播控制流取消并有序停止
- **AND** SHALL NOT 将其转换为某个用户 turn 的 `cancelled` 回复

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

### Requirement: Dynamic context trust separation

Runtime SHALL 将召回记忆和工作状态分别标识为事实参考与 Harness 状态，并 SHALL NOT 允许其中的历史文本覆盖安全规则或冒充当前用户指令。

#### Scenario: Retrieved evidence contains instruction-like text

- **WHEN** 召回的历史消息、网页内容、工具输出或记忆摘要包含命令式文本
- **THEN** Runtime SHALL 把该内容保留在不可信数据边界内
- **AND** SHALL NOT 将其提升为 system rule 或当前用户授权

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

### Requirement: Isolated turn failure

系统 SHALL 将不可恢复的单轮异常转换为结构化出站错误，并继续处理后续入站消息。

#### Scenario: One turn crashes
- **WHEN** 某条入站消息在准备轨迹、推理或发布前处理中出现不可恢复异常
- **THEN** 系统 SHALL 返回不含原始异常和秘密的错误分类
- **AND** AgentLoop SHALL 继续消费下一条消息

#### Scenario: Loop is cancelled
- **WHEN** Runtime 取消 AgentLoop
- **THEN** 系统 SHALL 传播取消并有序停止，而不是转换为普通错误回复

### Requirement: Stable tool-call correlation

一次模型响应中的每个工具调用 SHALL 在进入消息历史前获得非空稳定 ID，且执行请求、轨迹和 Tool Result SHALL 使用同一 ID。

#### Scenario: Provider omits tool call ID
- **WHEN** Provider 或测试响应返回缺少 ID 的工具调用
- **THEN** Runtime SHALL 生成一次确定性轮内 ID
- **AND** 后续所有关联记录 SHALL 复用该 ID

### Requirement: Bounded no-progress termination

系统 SHALL 对空响应、截断响应和连续全部失败的工具轮次执行有界恢复，并在无进展预算耗尽时终止。

#### Scenario: Failed tools alternate errors
- **WHEN** 连续工具轮次均无成功结果，即使错误文本或参数交替变化
- **THEN** 系统 SHALL 计入无进展预算并在阈值处停止

### Requirement: Verifiable end-to-end passive turn

系统 SHALL 通过可重复集成测试验证 Inbound、Session、Context、Memory、Skill、Provider、Tool、Trajectory 与 Outbound 的完整串行闭环。

#### Scenario: Deterministic end-to-end turn completes
- **WHEN** 测试 Provider 先请求工具再返回最终答案
- **THEN** 出站消息、Session 历史、工具结果和轨迹 SHALL 可由同一 trace 关联

#### Scenario: First message fails and second succeeds
- **WHEN** 同一 AgentLoop 的首条消息失败而第二条消息有效
- **THEN** 第二条消息 SHALL 仍完成并发布出站结果

### Requirement: Skill context trust and budget separation

Runtime SHALL 将 catalog 视为 Harness 提供的路由元数据，将成功加载的 Skill 正文视为低于静态安全规则和当前用户授权的版本化程序性说明，并 SHALL 对 catalog、Skill 正文和 reference 分别应用明确预算与来源边界。

#### Scenario: Skill text requests policy override

- **WHEN** Skill 正文或 reference 包含覆盖安全规则、扩大权限或冒充当前用户授权的文本
- **THEN** Runtime SHALL 保持静态规则、工具策略和用户授权优先
- **AND** SHALL NOT 因 Skill active 或 approved 状态执行越权动作

#### Scenario: Loaded Skill exceeds content budget

- **WHEN** 绑定 Skill 正文或请求的 reference 超过配置预算
- **THEN** Runtime SHALL 拒绝加载或返回明确的有界失败结果
- **AND** SHALL NOT 静默截断关键程序性说明后将其标记为成功加载

### Requirement: Structured safe presentation events

Runtime SHALL 为前台表现层投影结构化、有界、非权威事件，并 SHALL 将事件与 session、trace、turn 和 step 关联，而不暴露 Provider SDK 对象或隐藏内容。

#### Scenario: Turn progresses through model and tool steps

- **WHEN** turn 开始、模型产生文本、工具开始或结束、usage 更新且 turn 最终结束
- **THEN** Runtime SHALL 按发生顺序发出对应的安全事件类型与稳定关联标识
- **AND** 最终 Outbound/终止结果 SHALL 继续作为用户可见完成状态的权威来源

#### Scenario: Provider emits hidden content

- **WHEN** 原始 Provider 事件包含 reasoning、thinking 或工具参数增量
- **THEN** Runtime SHALL 在进入 presentation channel 前过滤或转换为无内容的安全阶段事件
- **AND** SHALL NOT 依赖终端 renderer 再清除秘密

#### Scenario: Presentation observer fails or lags

- **WHEN** 表现事件队列已满、观察者抛错或 renderer 消费缓慢
- **THEN** Runtime SHALL 丢弃或合并可降级表现事件并继续 Agent 行为
- **AND** 最终 Outbound、轨迹证据和工具副作用 SHALL 不受影响

### Requirement: Interactive chat streams by default

正式 Provider 支持 streaming 且用户未显式关闭时，交互式 chat SHALL 请求流式模型响应；非交互调用和显式关闭 SHALL 保持确定性一次性响应能力。

#### Scenario: Streaming-capable provider starts interactive turn

- **WHEN** TTY chat 使用声明 streaming 能力的正式 Provider 且配置未关闭 streaming
- **THEN** 每次模型请求 SHALL 启用 Provider 的流式协议并产生规范化文本/usage/工具事件
- **AND** 最终统一模型响应 SHALL 与已接收增量语义一致

#### Scenario: User explicitly disables streaming

- **WHEN** 配置设置 `llm.stream = false`
- **THEN** Runtime SHALL 使用非流式 Provider 调用并只在完成后返回统一响应
- **AND** Agent Loop、轨迹和终止判定 SHALL 保持等价

#### Scenario: Stream fails after partial output

- **WHEN** Provider 在已经产生用户可见文本或工具增量后中断
- **THEN** Runtime SHALL 将错误标识为 partial-stream 并停止透明 fallback 拼接
- **AND** SHALL 向表现层发出安全失败状态且不把部分文本宣称为完成答案

### Requirement: Isolated active-turn cancellation

AgentLoop SHALL 维护可寻址的当前 turn 取消边界，使通道可以取消活动处理而不并发执行消息、不丢失整个消息泵或错误关联后续回复。

#### Scenario: Cancellation arrives during provider request

- **WHEN** 用户停止请求发生在活动 Provider stream 中
- **THEN** Runtime SHALL 关闭 Provider stream、完成必要轨迹终止记录并释放 turn 资源
- **AND** SHALL NOT 启动 fallback 或继续工具调用

#### Scenario: Cancellation arrives during tool execution

- **WHEN** 用户停止请求发生在可取消的活动工具等待中
- **THEN** Runtime SHALL 请求取消并阻止后续模型步骤
- **AND** 对无法安全撤销的已发生副作用 SHALL 只报告真实状态而不声称回滚

#### Scenario: Queued message follows cancelled turn

- **WHEN** 当前 turn 被取消且队列中已有下一条消息
- **THEN** AgentLoop SHALL 在取消清理完成后处理下一条消息
- **AND** 下一条 Outbound SHALL 使用自己的 trace 和输入关联
