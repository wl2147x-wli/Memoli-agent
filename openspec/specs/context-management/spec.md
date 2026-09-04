# context-management Specification

## Purpose

定义 Memoli Agent 在 Provider 调用前的缓存感知上下文布局、全局 token 预算、可恢复预览、分层压缩、超限恢复、审计与数据治理边界。

## Requirements

### Requirement: Cache-aware context layout

Runtime SHALL 在每次 Provider 调用前从结构化 Context Plan 生成模型可见上下文，逻辑上区分稳定静态前缀、受治理动态材料、冻结工具证据、近期完整 turn 与 archive frontier；最终排列 SHALL 保持稳定前缀在前、archive 与近期交互居中、唯一最新动态状态在尾部，且正文内容不得决定块类型、required、priority 或 trust。

#### Scenario: First decision in an epoch is compiled

- **WHEN** Runtime 为新 conversation epoch 的首次模型决策编译上下文
- **THEN** 基础 system prompt、该 epoch 冻结的 Skill catalog 和工具 schema SHALL 形成确定性稳定前缀
- **AND** 当前用户消息、相关记忆和唯一最新工作状态 SHALL 以显式来源、类型与信任边界进入后续区域

#### Scenario: Later tool decision is compiled

- **WHEN** 同一 turn 已追加 assistant tool call 和关联工具结果并准备下一次模型决策
- **THEN** Runtime SHALL 保持已有稳定前缀及完整 tool call/result 关联不变
- **AND** SHALL 在交互之后仅提供一个从当前 store 重建的最新工作状态

#### Scenario: User content resembles an internal marker

- **WHEN** 用户、工具或外部内容包含 `<memory_context>`、`<plugin_context>`、`<agent_status>` 或其他内部样式文本
- **THEN** Runtime SHALL 继续依据结构化来源元数据分类并保持原角色与信任等级
- **AND** SHALL NOT 因正文标记重排、提升权限、遗漏当前用户输入或把该内容标记为 required

#### Scenario: Plugin contributes context

- **WHEN** 插件为当前 turn 贡献上下文 section
- **THEN** section SHALL 位于基础静态安全规则之后并带来源和低于 system/user 授权的信任标记
- **AND** 插件 SHALL NOT 把内容插入稳定安全前缀之前，且任何状态样式文本 SHALL NOT 替代 Runtime 重建的最新工作状态

### Requirement: Deterministic stable-prefix snapshots

Runtime SHALL 为每个 `(session key, conversation epoch)` 保存不可变、单调递增的能力快照 revision；每个 revision SHALL 冻结静态 prompt 版本、Skill catalog、规范化工具 schema 和布局版本并生成稳定哈希。一次 turn 首次编译 SHALL 根据当时有效能力选择或创建 revision，该 turn 的后续模型与工具步骤 SHALL 固定使用同一 revision；后续 turn SHALL 在能力指纹变化时创建新 revision，而不要求创建新 conversation epoch。安全撤销 SHALL 立即使受影响快照 fail closed。

#### Scenario: Runtime state changes during an epoch

- **WHEN** 普通 Skill active 指针、插件注册状态、MCP 工具或基础工具 schema 在活动 turn 中途变化
- **THEN** 该 turn 已冻结的前缀和工具 schema SHALL 保持字节级稳定
- **AND** 非安全性变更 SHALL 仅在下一 turn 创建或选择新的能力 revision 后生效

#### Scenario: Capability changes before a later turn

- **WHEN** 一个 turn 已终止，且下一 turn 开始时有效 system prompt、Skill catalog、工具 schema 或布局版本的规范化指纹不同
- **THEN** Runtime SHALL 在同一 conversation epoch 中创建新的不可变 revision 并用于新 turn
- **AND** SHALL 保留旧 revision 供轨迹审计，不得要求用户执行 `/clear` 或丢弃既有对话历史

#### Scenario: Runtime restarts without capability changes

- **WHEN** Runtime 重启后恢复已有 session/epoch，且当前有效能力指纹与最新 revision 相同
- **THEN** Runtime SHALL 复用该 revision 及稳定哈希
- **AND** SHALL NOT 仅因进程实例变化制造新 revision 或无效化 Provider 前缀缓存

#### Scenario: Runtime restarts after capability changes

- **WHEN** Runtime 重启后恢复已有 session/epoch，且当前有效能力指纹与最新 revision 不同
- **THEN** 首个新 turn SHALL 自动创建并使用反映当前能力的新 revision
- **AND** 诊断和轨迹 SHALL 记录新增、删除或 schema 变化的能力差异

#### Scenario: A new epoch starts

- **WHEN** 用户清理对话或 Runtime 显式创建下一 conversation epoch
- **THEN** 新 epoch SHALL 从 revision 1 使用当时有效的 system、Skill 和工具 schema 创建独立快照
- **AND** SHALL NOT 复用旧 epoch 的失效原因、archive frontier、披露记录或冻结动态内容

#### Scenario: Capability is revoked for safety

- **WHEN** 活动 revision 中的 Skill 或工具被安全撤销
- **THEN** Runtime SHALL 立即拒绝使用并记录 snapshot 失效原因
- **AND** SHALL NOT 继续向模型声明该能力可用或静默替换为其他版本

### Requirement: Model-aware global token budget

Runtime SHALL 根据模型输入窗口、最大输出预留、安全余量以及 messages、tools 和协议开销计算统一输入预算；预算判断 SHALL 基于降载前候选和降载后请求分别记录，并 SHALL 在 Provider 调用前保证最终请求不超过可用预算或产生明确失败。

#### Scenario: Tokenizer is available

- **WHEN** 当前模型存在受支持的 token 计数适配器
- **THEN** Runtime SHALL 使用该适配器计算各上下文层和完整请求 token
- **AND** 编译诊断 SHALL 标识模型、适配器及精确计数状态

#### Scenario: Tokenizer is unavailable

- **WHEN** 当前模型没有受支持的 token 计数适配器
- **THEN** Runtime SHALL 使用配置的保守估算与安全余量
- **AND** 编译诊断 SHALL 标识 `exact=false` 而不得宣称为精确 token

#### Scenario: Required content alone exceeds budget

- **WHEN** 静态安全规则、当前用户输入、当前未完成工具协议和最小最新状态已经超过可用输入预算
- **THEN** Runtime SHALL 以 `context-budget-exhausted` 停止新的 Provider 调用
- **AND** SHALL NOT 截断安全规则、当前用户输入或拆散 tool call/result 结构

### Requirement: Priority-preserving context reduction

Runtime SHALL 按确定性优先级减少上下文，依次采用冻结工具预览、可证明去噪、有界动态块选择、近期完整 turn 选择和任务感知 archive；soft/hard 阈值 SHALL 使用降载前候选比率，所有省略或压缩 SHALL 保留可审计来源且不得在压缩前永久删除 committed turn。

#### Scenario: Soft threshold is reached

- **WHEN** 降载前候选输入达到 soft threshold 但仍低于 hard threshold
- **THEN** Runtime SHALL 对最旧未覆盖的完整 turn 批量规划任务感知压缩，并在成功提交后重新编译
- **AND** 压缩失败时 SHALL 保持原可发送视图、记录失败且不得删除或标记源 turn 已覆盖

#### Scenario: Hard threshold is reached

- **WHEN** 降载前候选输入达到 hard threshold 或普通选择无法满足可用预算
- **THEN** Runtime SHALL 同步扩大完整 turn/archive 合并批次并重新编译
- **AND** 无法生成满足预算的合法请求时 SHALL 明确失败而不得发送已知超限输入

#### Scenario: Dynamic candidates exceed their budgets

- **WHEN** 记忆、插件、历史 archive 或旧 turn 候选超过各层或全局预算
- **THEN** Runtime SHALL 按显式 required/priority 省略低优先级块并记录候选、保留、省略 token 与原因
- **AND** SHALL NOT 仅因块被渲染为 system role 就把它视为不可裁剪

#### Scenario: Conversation tail is selected

- **WHEN** Runtime 只能保留部分近期对话
- **THEN** SHALL 以完整 committed turn 和完整 tool call/result 组为选择单位
- **AND** SHALL NOT 产生从孤立 assistant/tool 消息开始或缺少关联 result 的历史

### Requirement: Recoverable large-result previews

大型工具结果 SHALL 分离为受管本地原文和绑定 conversation epoch 的模型可见冻结预览；预览 SHALL 包含稳定来源引用、tool call 关联、内容哈希、原始大小、可见大小和转换标志，且引用 SHALL NOT 授予额外权限。

#### Scenario: Tool result exceeds its model budget

- **WHEN** 脱敏后的工具结果超过模型可见预算
- **THEN** 完整结果 SHALL 写入受管 payload 或 artifact
- **AND** 模型 SHALL 接收带稳定引用和明确截断/压缩标记的有界预览

#### Scenario: Context is recompiled or restored

- **GIVEN** 某工具结果已经生成冻结预览
- **WHEN** 同一 epoch 重编译上下文或从持久状态恢复
- **THEN** Runtime SHALL 验证 epoch、tool call id、内容哈希和引用并复用字节级相同的预览
- **AND** 校验失败时 SHALL 排除完整受影响 turn 或返回可观察协议错误，不得只保留孤立 tool call/result

#### Scenario: Conversation is cleared

- **WHEN** 用户创建新的 conversation epoch
- **THEN** 旧 epoch 的冻结预览 SHALL 不再进入新上下文
- **AND** 原始 payload 的保留或删除 SHALL 继续服从 trajectory 数据策略而不是由 `/clear` 隐式决定

### Requirement: Layered task-aware compaction

Runtime SHALL 通过同一个异步压缩协调器执行 soft、hard 与 emergency 压缩，按 plan、execute、validate、commit 顺序生成带完整来源覆盖的结构化不可变 archive，并 SHALL 以原子 coverage/frontier 防止相同源被重复或交叉压缩。

#### Scenario: A source batch is compacted

- **WHEN** 协调器选择一批尚未覆盖的旧完整 turn
- **THEN** archive SHALL 保留目标与约束、关键决策及理由、事实引用、文件或产物、验证状态、失败路径、TODO 和 remaining work
- **AND** SHALL 保存直接 source refs、conversation epoch、schema version、token count 与覆盖哈希

#### Scenario: Archived content is encountered again

- **WHEN** 后续编译发现源 turn 已由 committed frontier 节点覆盖
- **THEN** Runtime SHALL 注入非重叠 frontier archive 并排除已覆盖原文的模型可见副本
- **AND** SHALL NOT 再次把相同 source ref 纳入另一个活动 frontier 节点

#### Scenario: Archive frontier exceeds its budget

- **WHEN** 活动 archive frontier 超过配置的总 token 或节点上限
- **THEN** Runtime SHALL 把最旧相邻 frontier 节点合并为更高层不可变 archive
- **AND** 新节点原子提交成功前 SHALL 保持父节点为活动 frontier，成功后 SHALL 仅注入新的非重叠 frontier

#### Scenario: Compaction validation or commit fails

- **WHEN** 压缩 Provider 失败、结构/引用/预算校验失败或事务无法提交
- **THEN** 原有 frontier、coverage、源 turn 与当前视图 SHALL 保持不变
- **AND** Runtime SHALL 记录有界失败、重试/熔断状态且不得留下孤立 archive

#### Scenario: Compression provider is unavailable

- **WHEN** context compaction 启用但没有可用的正式压缩 Provider
- **THEN** Runtime SHALL 仅执行确定性预览、去噪和有诊断的候选选择
- **AND** SHALL NOT 把机械截断或按角色拼接的 JSON 宣称为任务感知 archive

### Requirement: Context-length recovery

Provider 报告输入上下文超限时，Runtime SHALL 将其视为最后一道语义恢复信号，在同一 trace 内通过统一协调器最多执行一次 emergency 压缩、重新规划和 Provider 重试。

#### Scenario: Emergency compaction succeeds

- **WHEN** 首次 Provider 请求返回 context length error 且当前 turn 尚未执行 emergency 恢复
- **THEN** Runtime SHALL 记录错误、强制更高强度的合法压缩并生成 token 更少且 hash 不同的请求
- **AND** 重试 SHALL 使用相同 trace 且不得重复已提交的工具副作用

#### Scenario: Emergency compaction cannot improve the request

- **WHEN** 压缩失败、熔断器已打开、最小必需内容仍超限或新请求没有变小
- **THEN** turn SHALL 以稳定的 context budget/compaction 错误结束
- **AND** SHALL NOT 使用相同输入循环重试或透明切换到窗口更小的 Provider

### Requirement: Context compilation audit

启用轨迹时，每次实际 Provider 请求前的 Context Plan、压缩事务和恢复决定 SHALL 可审计；压缩状态的正确性 SHALL 由 context-state 原子事务保证，跨库审计事件 SHALL 通过幂等 outbox 投递，且 archive SHALL 与原始 turn/payload 明确区分。

#### Scenario: Compiled context is sent

- **WHEN** Runtime 准备发送一次 Provider 请求
- **THEN** trace SHALL 记录 epoch、布局版本、各层候选/保留 token、block 类型/来源/trust、计数策略、稳定前缀与工具 schema 哈希、frontier 和裁剪诊断
- **AND** 实际发送的 messages/tools SHALL 与已提交编译结果一致

#### Scenario: Archive transaction commits but audit delivery is delayed

- **WHEN** archive、coverage 与 frontier 已在 context-state 事务中提交但轨迹写入暂时失败
- **THEN** Runtime SHALL 保留可重放 outbox 记录并继续以已提交 frontier 为正确状态
- **AND** 重放 SHALL 幂等且不得再次创建 archive generation 或重复 source coverage

#### Scenario: Provider reports cache usage

- **WHEN** Provider 返回 cached input 或 cache creation usage
- **THEN** Runtime SHALL 保存供应商返回的原始规范化数值并在数据充分时计算 cache hit ratio
- **AND** 未返回的缓存 usage SHALL 保持 unknown 而不是记录为零

### Requirement: Bounded archive frontier and source reading

Runtime SHALL 分别限制 archive frontier 的总 token/节点数以及 committed-turn reader 的单次 turn/byte 读取量；读取上限 SHALL 是可继续推进的 I/O 防护而不是隐式语义历史窗口。

#### Scenario: Source reader reaches an I/O bound

- **WHEN** 当前 epoch 的可用 committed turns 超过单次读取 turn 或 byte 上限
- **THEN** reader SHALL 返回稳定 continuation 与 `source-truncated` 诊断
- **AND** 压缩协调器 SHALL 能分批推进覆盖，不能把未读取内容标记为不存在或已归档

#### Scenario: Long-running conversation accumulates archives

- **WHEN** conversation 持续产生新的 archive generation
- **THEN** 每次 Provider 请求注入的 frontier SHALL 始终满足配置的总 token 与节点上限
- **AND** 历史 generation SHALL 保留审计引用但不得全部永久注入模型

### Requirement: Context restoration fidelity

跨轮 Context Source SHALL 只从当前 conversation epoch 中顺序完整且已终止的 canonical turn 恢复模型可见消息，并 SHALL 明确区分 exact、governed、legacy-inferred 与 unavailable 恢复等级。

#### Scenario: A completed tool turn is restored

- **WHEN** 当前 epoch 中存在包含 assistant tool call、关联 tool result 和最终输出的完整 committed turn
- **THEN** reader SHALL 按稳定 turn/message 序号恢复标准 role、tool call id、名称、参数、可见结果和最终 transformed output
- **AND** SHALL 排除当前 trace，避免本轮消息重复注入

#### Scenario: A trace is partial or corrupted

- **WHEN** turn 未终止、消息序号缺失、payload 损坏或 tool correlation 不完整
- **THEN** reader SHALL 排除整个 turn 并记录可观察降级原因
- **AND** SHALL NOT 猜测缺失消息或向 Provider 发送损坏协议

#### Scenario: Durable content is unavailable

- **WHEN** 轨迹关闭、capture mode 不保存可读内容或 durable reader 不可用
- **THEN** Runtime SHALL 使用隔离的进程内完整 turn source 继续当前进程会话
- **AND** 诊断 SHALL 标记 `restorable=false` 且重启后不得声称已恢复旧内容

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

### Requirement: Capability snapshot revision audit

每次实际 Provider 请求 SHALL 标识所使用的 conversation epoch、能力 revision、稳定前缀哈希和工具 schema 哈希；revision 协调 SHALL 产生不包含工具秘密或完整敏感 schema 的有界差异诊断。

#### Scenario: A later turn activates a changed tool set

- **WHEN** 新 turn 因工具新增、删除或 schema 修改而创建能力 revision
- **THEN** 编译结果与轨迹 SHALL 记录旧/新 revision、旧/新工具哈希和分类后的工具名称差异
- **AND** 实际发送的工具集合 SHALL 与新 revision 保存的规范化 schema 完全一致

#### Scenario: Capability reconciliation cannot be persisted

- **WHEN** Runtime 检测到能力指纹变化但无法原子保存新 revision
- **THEN** 新 turn SHALL 在 Provider 调用前以稳定的 context state 错误结束
- **AND** SHALL NOT 静默复用已确认过期的工具快照或覆盖最后一个有效 revision
