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

系统 SHALL 按消息的 session key 维护有限窗口的对话历史，并通过统一生命周期生成出站消息。

#### Scenario: User sends a CLI message

- **WHEN** 通道发布一条普通入站消息
- **THEN** 系统 SHALL 依次准备会话、查询上下文、渲染 prompt、执行推理、保存历史并构造出站消息

#### Scenario: Conversation continues

- **GIVEN** 同一 session key 已有历史消息
- **WHEN** 新消息到达
- **THEN** prompt SHALL 包含受 `history_window` 限制的相关会话历史

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

每个 turn SHALL 产生 `completed`、`needs-user`、`failed` 或 `budget-exhausted` 之一的结构化终止原因，并关联稳定的 trace 标识。

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

Runtime SHALL 在每次 Provider 调用前通过统一装配边界生成模型可见上下文：静态基础规则之后纳入当前 Session 稳定且有界的 Skill catalog，再依次纳入当前交互、受限会话历史、个人记忆上下文和最新工作状态；同一 Session 的静态 system 前缀和 Skill catalog SHALL 不因每轮动态状态或 active 指针变化而重写。

#### Scenario: Initial model decision is prepared

- **WHEN** Runtime 为新的用户 turn 准备首次模型调用
- **THEN** 模型可见上下文 SHALL 包含当前用户输入、可用 Skill catalog、核心记忆、自动召回结果和当前工作状态
- **AND** Skill catalog、动态数据 SHALL 使用可区分于终端用户指令和静态安全规则的边界

#### Scenario: A later tool-loop decision is prepared

- **WHEN** Skill 或通用工具结果已经提交且 Runtime 准备同一 turn 的后续模型调用
- **THEN** 模型可见上下文 SHALL 包含该工具结果和其后生成的最新工作状态
- **AND** SHALL NOT 继续注入已过期的工作状态版本或运行中重写 Session Skill catalog

#### Scenario: No Skill is available

- **WHEN** Skill Runtime 关闭、降级或当前 Session 没有可见 Skill
- **THEN** Runtime SHALL 在不伪造空 Skill 指令的情况下装配现有交互、历史、记忆和工作状态
- **AND** 普通 Agent Loop SHALL 保持可用

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

