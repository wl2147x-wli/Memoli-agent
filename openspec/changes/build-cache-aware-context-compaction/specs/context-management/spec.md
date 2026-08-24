## ADDED Requirements

### Requirement: Cache-aware context layout

Runtime SHALL 在每次 Provider 调用前按稳定静态前缀、不可变任务归档、近期完整轨迹和动态尾部的顺序编译模型可见上下文；静态安全规则 SHALL 位于插件、记忆、工具内容和压缩摘要之前，动态内容 SHALL NOT 改写稳定前缀。

#### Scenario: First decision in a session is compiled
- **WHEN** Runtime 为新 Session 的首次模型决策编译上下文
- **THEN** 基础 system prompt、Session Skill catalog 和工具 schema SHALL 形成确定性稳定前缀
- **AND** 当前用户消息、相关记忆和最新工作状态 SHALL 出现在具有明确来源与信任边界的后续区域

#### Scenario: Later tool decision is compiled
- **WHEN** 同一 turn 已追加 assistant tool call 和关联工具结果并准备下一次模型决策
- **THEN** Runtime SHALL 保持已有稳定前缀和完整 tool call/result 关联不变
- **AND** SHALL 在轨迹之后仅提供一个最新工作状态表示

#### Scenario: Plugin contributes context
- **WHEN** 插件为当前 turn 贡献上下文 section
- **THEN** section SHALL 位于基础静态安全规则之后并带来源和低于 system/user 授权的信任标记
- **AND** 插件 SHALL NOT 把内容插入稳定安全前缀之前

### Requirement: Deterministic stable-prefix snapshots

Runtime SHALL 为每个 Session 冻结并复用静态 prompt 版本、Skill catalog、规范化工具 schema 和布局版本，并 SHALL 为这些材料生成稳定哈希。

#### Scenario: Runtime state changes during a session
- **WHEN** 普通 Skill active 指针、插件注册状态或 MCP 发现顺序在 Session 中途变化
- **THEN** 已冻结 Session 前缀 SHALL 保持字节级稳定
- **AND** 非安全性变更 SHALL 仅影响后续新 Session

#### Scenario: Capability is revoked for safety
- **WHEN** 已冻结 snapshot 中的 Skill 或工具被安全撤销
- **THEN** Runtime SHALL 拒绝使用被撤销能力并记录 snapshot 失效原因
- **AND** SHALL NOT 静默替换为其他版本或重排其余稳定工具 schema

### Requirement: Model-aware global token budget

Runtime SHALL 根据模型输入窗口、最大输出预留、安全余量以及 messages、tools 和协议开销计算统一输入预算，并 SHALL 在 Provider 调用前保证编译结果不超过该预算或产生明确失败。

#### Scenario: Tokenizer is available
- **WHEN** 当前模型存在受支持的 token 计数适配器
- **THEN** Runtime SHALL 使用该适配器计算各上下文块和完整请求 token
- **AND** 编译诊断 SHALL 标识计数为模型适配结果

#### Scenario: Tokenizer is unavailable
- **WHEN** 当前模型没有受支持的 token 计数适配器
- **THEN** Runtime SHALL 使用配置的保守估算和安全余量
- **AND** 编译诊断 SHALL 标识估算策略而不得宣称为精确 token

#### Scenario: Required content alone exceeds budget
- **WHEN** 静态安全规则、当前用户输入、合法工具关联和最小最新状态已经超过可用输入预算
- **THEN** Runtime SHALL 以 `context-budget-exhausted` 停止新的 Provider 调用
- **AND** SHALL NOT 截断安全规则、当前用户输入或拆散 tool call/result 结构

### Requirement: Priority-preserving context reduction

Runtime SHALL 按确定性优先级减少上下文，优先保留静态安全规则、当前用户目标和约束、工具协议完整性、最新真实状态、显式冻结核心记忆、关键决策与验证证据，并优先删除重复噪声和低价值细节。

#### Scenario: Dynamic candidates exceed budget
- **WHEN** 记忆、插件段、历史和工具结果候选的总量超过可用预算
- **THEN** Runtime SHALL 先省略或压缩低优先级情景细节和重复噪声
- **AND** SHALL 记录每个被裁剪块的类型、来源、数量和原因

#### Scenario: Conversation tail is selected
- **WHEN** Runtime 只能保留部分近期对话
- **THEN** SHALL 以完整 turn 和完整 tool call/result 组为选择单位
- **AND** SHALL NOT 产生从孤立 assistant/tool 消息开始的无效历史

### Requirement: Recoverable large-result previews

大型工具结果 SHALL 分离为受管本地原文和模型可见冻结预览；预览 SHALL 包含稳定来源引用、内容哈希、原始大小、可见大小和转换标志，且引用 SHALL NOT 授予额外权限。

#### Scenario: Tool result exceeds its model budget
- **WHEN** 脱敏后的工具结果超过模型可见预算
- **THEN** 完整结果 SHALL 写入受管 payload 或 artifact
- **AND** 模型 SHALL 接收带稳定引用和明确截断/压缩标记的有界预览

#### Scenario: Context is recompiled or restored
- **GIVEN** 某工具结果已经生成冻结预览
- **WHEN** 同一 Session 重编译上下文或从持久状态恢复
- **THEN** Runtime SHALL 复用字节级相同的预览和引用
- **AND** SHALL NOT 使用新的非确定性摘要替换它

### Requirement: Layered task-aware compaction

Runtime SHALL 在配置阈值触发时批量压缩尚未压缩的旧内容，生成带来源引用的结构化、任务感知且不可变的归档，并 SHALL 防止相同源内容被重复压缩。

#### Scenario: Soft threshold is crossed
- **WHEN** 编译输入超过配置的 soft compaction threshold
- **THEN** Runtime SHALL 先执行确定性去噪并批量归档符合条件的旧工具结果或完整 turn
- **AND** archive SHALL 保留目标/约束、关键决策及理由、事实引用、文件或产物、验证状态、失败路径、TODO 和 remaining work

#### Scenario: Archived content is encountered again
- **WHEN** 后续编译发现源消息已经关联某一 archive generation
- **THEN** Runtime SHALL 复用不可变 archive 并排除已归档原文的模型可见副本
- **AND** SHALL NOT 再次摘要相同源内容

#### Scenario: Compaction model fails
- **WHEN** 压缩 Provider 失败、返回无效结构或无法提交 archive
- **THEN** 原有上下文视图和受管原文 SHALL 保持不变
- **AND** Runtime SHALL 记录失败并在连续达到阈值时打开有界熔断器

### Requirement: Context-length recovery

Provider 报告输入上下文超限时，Runtime SHALL 将其视为可通过重编译处理的语义错误，在同一 trace 内最多执行一次紧急压缩和 Provider 重试。

#### Scenario: Emergency compaction succeeds
- **WHEN** 首次 Provider 请求返回 context length error 且当前 turn 尚未执行紧急恢复
- **THEN** Runtime SHALL 强制 hard compaction、记录前后上下文哈希并重新发起一次模型请求
- **AND** 重试 SHALL 继续使用相同 trace 且不得重复已提交的工具副作用

#### Scenario: Emergency compaction cannot fit
- **WHEN** 紧急压缩失败、熔断器已打开或最小必需内容仍超过预算
- **THEN** turn SHALL 以 `context-budget-exhausted` 或稳定压缩错误结束
- **AND** SHALL NOT 使用相同超限输入循环重试

### Requirement: Context compilation audit

启用轨迹时，每次实际 Provider 请求前的上下文编译 SHALL 可审计，且压缩摘要 SHALL 作为派生视图与原始 trajectory/payload 明确区分。

#### Scenario: Compiled context is sent
- **WHEN** Runtime 准备发送一次 Provider 请求
- **THEN** trace SHALL 记录布局版本、块类型/来源/trust、token 计数策略、预算、稳定前缀与工具 schema 哈希、archive generation 和裁剪诊断
- **AND** 实际发送的 messages/tools SHALL 与已提交编译结果一致

#### Scenario: Provider reports cache usage
- **WHEN** Provider 返回 cached input 或 cache creation usage
- **THEN** Runtime SHALL 保存供应商返回的原始规范化数值并在数据充分时计算 cache hit ratio
- **AND** 未返回的缓存 usage SHALL 保持 unknown 而不是记录为零

### Requirement: Compaction and durable-memory separation

上下文 archive、工具预览和压缩诊断 SHALL 仅用于当前任务的模型视图，不得自动成为 Personal Memory、Skill、Prompt 更新或训练标签；其原始来源 SHALL 继续遵循独立 trajectory/payload 保留与权限策略。

#### Scenario: A context archive is committed
- **WHEN** Runtime 成功生成任务内 archive
- **THEN** archive SHALL 保存来源引用和派生标记
- **AND** SHALL NOT 自动创建或更新 Claim、Card、Skill、system prompt 或训练数据

#### Scenario: Source memory is deleted or access changes
- **WHEN** archive 引用的原始内容因独立治理变为不可访问
- **THEN** Runtime SHALL 遵守最新权限和删除边界处理后续重读
- **AND** archive 引用 SHALL NOT 绕过原始数据的 scope 或权限

