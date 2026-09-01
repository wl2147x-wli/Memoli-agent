## Context

当前运行链路先由 `ContextBuilder` 读取 `Session._history`，再由 `Reasoner` 在每次模型调用前追加最新工作状态并调用 `ContextCompiler`。随后编译器按正文标记把消息划为 plugin、dynamic 与 trajectory，去掉空白/相邻重复消息，用 `recent_tail_tokens` 保留完整 user 分组，并把更早消息写成 archive。大型工具结果另由 `ToolResultPreviewer` 冻结为有界预览；只有 Provider 已返回 context-length error 时，`TaskAwareCompactor` 才调用真实模型生成结构化 archive，并触发一次 emergency compile/retry。

这条链路表面上可分为多级降载，但存在权威来源和提交边界不一致：`Session.history_window` 会在编译器看到消息前删除内容且只保存 user/assistant 最终文本；确定性 `_archive` 与 LLM `TaskAwareCompactor` 是两套语义；soft ratio 在近期 tail 已裁剪后才判断，hard ratio 仅在 emergency 使用；所有 archive generation 都被重新注入且 `archive_tokens` 只是单份上限；snapshot/archive 仅按稳定 `session_key` 保存，忽略新的 `session_instance_id`，而 `/clear` 只删除内存 Session。

约束包括：标准 assistant tool call 与 tool result 必须成对保留；原始轨迹/payload 是审计事实，archive 只是可重建派生视图；压缩失败不能执行新的工具副作用；动态记忆、插件、工具输出与 archive 不得获得静态安全规则的权限；主 Agent 的跨轮策略不得静默应用到 memory-governor 或普通 SubAgent。

## Goals / Non-Goals

**Goals:**

- 建立唯一的跨轮可重放 turn 来源，并在任何不可逆裁剪前完成分层选择或归档。
- 把上下文分为五层并用一个预算计划决定保留、预览、归档、合并或拒绝。
- 让 soft、hard、provider-error 三种触发复用同一压缩协调器和原子提交合同。
- 限制当前 archive frontier 的总 token、generation/节点数和覆盖关系，使长会话空间复杂度有界。
- 用显式类型与信任元数据代替正文标记分类，保证当前用户输入和工具协议不可被误分类。
- 使 `/clear`、重启、禁用轨迹、不同 capture mode 与 SubAgent 场景具有明确可测试语义。

**Non-Goals:**

- 不修改 Personal Memory 的 Claim/Card、召回、审核或离线学习策略。
- 不把 archive 当作长期记忆、原始证据、Skill、Prompt 更新或训练样本。
- 不保存或恢复 Provider 隐藏 reasoning。
- 不要求 Provider 支持服务端会话、Prompt Cache 控制或上下文编辑 API。
- 不在本变更中改变公开业务工具的名称、参数或执行权限。

## Decisions

### 1. 五层模型视图与单一 Context Plan

每次 Provider 调用由同一个 Context Plan 产生最终 messages/tools：

1. **Stable Prefix**：基础安全 system、冻结 Skill catalog、规范化工具 schema。
2. **Governed Dynamic Context**：核心/召回记忆、插件数据、最新工作状态；均为显式低权限块并有独立预算。
3. **Frozen Tool Evidence**：本轮与近期 turn 中的 tool call/result；大结果使用已冻结预览和受管 payload 引用。
4. **Recent Complete Turns**：当前 epoch 内按 turn token 预算保留的规范化 user/assistant/tool 消息。
5. **Archive Frontier**：覆盖更旧完整 turn 或旧 archive 的非重叠结构化摘要集合。

最终 Provider 排列保持 cache 友好：stable prefix、archive frontier、recent turns、governed dynamic tail；层 2/3 是逻辑保留优先级，不要求在 wire format 中破坏 tool call/result 的邻接关系。Context Plan 先对所有候选计数，再做选择；soft/hard 比率基于降载前的候选总量，不能基于已经丢弃 tail 后的结果。

不采用继续扩展正文 XML marker 的方案，因为任何角色的普通文本都可能包含这些字符串，marker 不能可靠表达来源、required 或 trust。引入结构化 `ContextBlock`/`TurnEnvelope`，渲染为 ChatMessage 只发生在计划确定之后。

### 2. 规范化 committed turn 是跨轮事实，Session 仅保存身份

主 Agent 在生命周期提交点记录规范化可见消息：输入提交、assistant tool-call 消息、tool-result 消息、最终用户可见输出及终止状态。记录包含 `session_key`、持久 `conversation_epoch`、`trace_id`、turn 序号、消息序号、标准 role、tool correlation、可见 blocks/文本、capture/degradation 标记和内容哈希。

跨轮 reader 只读取当前 epoch 中已经终止且顺序完整的 turn，排除当前 trace、running/cancelled/损坏记录，并按 `(turn_sequence, message_sequence)` 稳定排序。当前正在执行的 turn 继续使用 `Reasoner.working_messages`，避免刚提交事件的读后写延迟。

优先使用可读取内容的 durable trajectory adapter；轨迹关闭、metadata-only 或内容损坏时使用显式的进程内 turn store，并把 `restorable=false`/degradation reason 写入诊断。不得同时拼接 Session history 与 trajectory history。`Session` 仅持有 session/epoch 身份及瞬态控制状态，删除 `history_window` 和消息副本。

不直接从现有 `model_requested`/`model_responded`/`tool_finished` 猜测新 turn，因为 response transform 可能改变最终用户所见文本，且旧事件中的 tool call/blocks 结构不足以无损恢复。旧轨迹只允许走标记为 `legacy-inferred` 的兼容读取，不得伪装成 exact replay。

### 3. conversation epoch 定义清理边界

为每个 `session_key` 持久保存单调递增的 `conversation_epoch`。`/clear` 在没有活动 turn 时原子创建新 epoch，并重置新旧 epoch 的编译快照、frontier、失败计数和冻结预览可见索引；旧 committed turns、原始 trajectory、payload、长期记忆和 working-state 按各自策略保留，但不再进入新 epoch 的上下文。

进程重启继续读取当前持久 epoch，而不是用每次启动变化的 `session_instance_id` 截断上下文。若 epoch store 不可用，`/clear` 必须明确报告未完成，不能只清内存后声称成功。SubAgent 默认创建独立、非恢复 epoch source；只有显式装配相同协议的 profile 才启用跨轮恢复。

### 4. 压缩协调器采用 plan → execute → commit

Context Compiler 拆为无副作用的规划阶段与异步协调阶段：

- **Plan**：加载 stable snapshot、archive frontier、完整候选 turn 与动态块；计算 pre-reduction ratio、选择压缩 batch，并给出不执行摘要时仍可发送的视图或明确失败。
- **Execute**：在 soft/hard/emergency 模式下调用同一个 `TaskAwareCompactor`。请求使用固定 schema，携带当前目标/约束、完整 batch、source refs 与父 archive refs；压缩模型不获得主 Agent 工具。
- **Validate**：检查 JSON schema、引用集合、预算、禁止字段、覆盖无环性和最小保留字段；不接受引用减少、伪造或跨 epoch 内容。
- **Commit**：在一个 `context-state.db` 事务中写入 archive、coverage、frontier、generation、失败计数和 outbox 事件。提交成功后再重新 plan/compile。

soft threshold 批量压缩最旧、未覆盖的完整 turn；hard threshold 扩大 batch 并允许合并旧 frontier；Provider context-length error 强制 emergency 模式，但同一 trace 最多重试一次且必须产生更小、不同 hash 的请求。压缩失败在 soft 阶段保留原视图并记录重试状态；在 hard/emergency 无法满足预算时显式结束，不发送已知超限请求。

不保留当前同步 `_archive` 的“按角色把全文塞入 JSON 后从最长数组头部弹出”方案，因为它既非任务感知，也可能静默删除最早约束。没有可用 compaction provider 时，只允许确定性去噪、冻结预览和有诊断的候选省略；不得把机械截断标记成任务 archive。

### 5. archive frontier 有界且覆盖不重叠

每个 archive 保存 `archive_id`、epoch、level、generation、content/schema version、直接 source refs、parent archive refs、transitive coverage hash、token count 和状态。活动 frontier 必须覆盖互不重叠；原始 turn 被某个 committed archive 覆盖后不再同时注入。

配置新增 `archive_frontier_tokens`、`archive_frontier_max_items`、`source_read_max_turns`、`source_read_max_bytes` 与 `compaction_batch_tokens`。读取上限是 I/O 防护，不是语义历史窗口：到达上限时必须返回 continuation/truncation 诊断，协调器可分批推进，不能假装更老内容不存在。当 frontier 超预算或超过节点数时，把最旧相邻 archive 合并为更高 level archive，事务提交后才替换父节点。

不采用“始终注入所有 generation”，因为其输入成本随会话无限增长；也不原地改写旧 archive，因为不可变节点和 frontier 替换便于审计、回滚与幂等重试。

### 6. 原子提交使用本地事务与 outbox

archive 与 coverage/frontier 必须在同一个 `context-state.db` 事务中提交。轨迹审计跨数据库，不能假装支持分布式原子事务，因此同一事务写入幂等 outbox；提交后投递 `context_compaction_committed`，失败可重放且不回滚已成立的 context state。压缩请求/失败事件可直接写轨迹，但业务正确性不依赖观察 hook 成功。

generation 由事务内 session/epoch 计数器分配，不用 `len(archives)+1`。唯一约束覆盖 `(session_key, epoch, generation)`、archive id 和 source coverage，消除并发或重试造成的孤立节点与重复覆盖。

### 7. 快照、工具 schema 与工具预览按 epoch 管理

Stable snapshot 的键改为 `(session_key, epoch)`。普通能力新增仍只影响新 epoch；安全撤销立即阻止执行，并使当前 snapshot 进入 fail-closed 状态，不能继续向模型宣称已撤销工具可用。新 epoch 使用当时的 system/Skill/tool 快照。

冻结预览也绑定 epoch 和规范化 tool message hash。清理 epoch 只删除派生索引或将其标记不可见，原始受管 payload 的保留仍遵循 trajectory 策略。恢复时必须验证 preview hash、payload reference 和 tool_call_id；校验失败时不注入损坏 tool result，并以可观察协议错误结束或排除整个旧 turn，不能拆散 tool pair。

### 8. 模型感知计数与优先级必须真实生效

Token estimator 通过模型 profile 选择；支持的模型使用 tokenizer adapter，不支持时使用保守 estimator 并标注 `exact=false`。预算包含 messages、tool schemas 和协议固定开销。

required 仅包括静态安全规则、当前用户输入、当前未完成工具协议及最小真实状态。Memory、plugin、旧 archive 和旧 turn 按显式 priority/budget 降载；不能因为它们采用 system role 就自动成为 required。诊断同时记录 pre/post tokens、每层候选/保留/省略量、压缩收益、frontier、估算器、恢复能力与降级原因。

## Risks / Trade-offs

- [规范化 turn 与轨迹 schema 增加写入量] → 只保存模型可见、已脱敏的 canonical envelope，大 payload 继续外置；为 session/epoch/sequence 建索引并限制 reader 字节数。
- [旧 redacted/metadata-only 轨迹无法精确恢复] → 标记 `legacy-inferred` 或 `unavailable`，绝不宣称 exact；新 epoch 开始使用新事件合同。
- [LLM 压缩增加延迟与费用] → soft 阈值批量、幂等 coverage、低成本独立 profile；只在有足够预期 token 收益时执行。
- [archive 合并再次摘要可能累积语义损失] → 保留原始 source coverage、固定关键字段、近期开窗、层级上限与回溯引用；合并前后做约束/引用校验。
- [跨库 outbox 带来审计延迟] → context state 事务是正确性边界；outbox 幂等重放并在诊断中暴露 pending/failed，而不让 hook 失败破坏压缩决定。
- [移除 history_window 是配置破坏性变更] → 启动时检测旧字段并给出精确迁移示例，不静默忽略；文档同时说明新的 turn/token/byte 上限。
- [主 Agent 与 SubAgent 行为分叉] → 抽象可选 ContextSource，由 bootstrap 显式装配；默认仅主被动 turn 使用 durable source，SubAgent 保持隔离。

## Migration Plan

1. 先加入 additive schema：epoch、canonical turns/messages、archive coverage/frontier、outbox；旧表与数据不删除。
2. 双写新 committed-turn envelope 和现有事件，通过读取诊断验证顺序、tool correlation 与最终 transformed output。
3. 上线只读的新 ContextSource 与影子 Context Plan，对比旧请求但仍发送旧路径结果。
4. 启用 epoch-aware snapshot/frontier 和统一压缩协调器；新 epoch 使用新路径，旧 session 可通过 `/clear` 或显式 migration 开启新 epoch。
5. 切换主 Agent 为新 ContextSource，停止 Session message history 写入；随后删除 `history_window` 代码与配置。
6. 启用 archive frontier 合并和 outbox 重放，最后移除同步机械 `_archive` 路径。
7. 回滚时可关闭 durable source/compaction coordinator，退化为当前进程内完整 turn + 硬预算拒绝；不得回滚数据库 schema 或删除新事件，旧代码应忽略新增表。

## Open Questions

无。默认采用“只有 durable readable canonical content 才支持跨重启恢复；其余模式显式进程内降级”的保守策略。
