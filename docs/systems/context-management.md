# Context Management

Memoli 在每次 Provider 调用前都通过唯一的 `ContextCompiler` 编译输入。编译结果同时用于轨迹预提交和实际请求，避免审计内容与发送内容分叉。

## 五层 Context Plan

每次 Provider 调用由同一个无副作用的 Context Plan 产生最终 messages/tools，按下列稳定顺序排列：

1. **稳定前缀（Stable Prefix）**：基础安全 system、布局版本、首次会话 Skill catalog 和规范化工具 schema。首次编译后冻结并持久化哈希，普通 Skill、插件、MCP 变化不会改写前缀。
2. **有界归档前沿（Archive Frontier）**：覆盖更旧完整 turn 或旧 archive 的非重叠结构化摘要集合；受 `archive_frontier_tokens` 与 `archive_frontier_max_items` 双重上限约束。
3. **近期完整 turn（Recent Complete Turns）**：当前 epoch 内按 `recent_tail_tokens` 保留的规范化 user/assistant/tool 消息；不向模型暴露孤立 tool 或 assistant 消息，标准 assistant tool call 与 tool result 必须成对保留。
4. **冻结工具证据（Frozen Tool Evidence）**：本轮与近期 turn 中的大工具结果冻结预览；预览绑 epoch、规范化 tool message hash 与 `tool_call_id`，原始 payload 留在受管 trajectory 管理之下。
5. **受管动态尾部（Governed Dynamic Context）**：核心/召回 Memory、插件数据、最新 Working State；均为显式低权限块并有独立预算（`plugin_max_tokens` 等）。

最终 Provider 排列保持 cache 友好：`stable prefix → archive frontier → recent turns → governed dynamic tail`。层 2（Archive Frontier）与层 3（Recent Complete Turns）是逻辑保留优先级，不要求在 wire format 中破坏 tool call/result 的邻接关系——渲染到 ChatMessage 发生在计划确定之后。

`PromptRenderPhase` 不预置 Working Checkpoint 文本。Reasoner 在每次实际 Provider 调用前删除历史或 Hook 中可能残留的 `<working_checkpoint>`/`<agent_status>`，再从当前 store 重建唯一 `<agent_status>`。因此首轮、工具结果后的后续决策、重试和 fallback 使用同一条最新状态路径，不会同时携带遗留简化块。状态内将 Runtime 验证的 iteration、tool status 与 `runtime_artifacts` 标为硬状态；objective、步骤、约束、决策、SOP 与 `agent_artifacts` 保持 Agent 软状态信任边界。

所有层、工具 schema、输出预留、安全余量与 Chat 协议开销共享模型 Profile 的全局输入预算。最低必需内容（`required`：静态安全规则 + 当前用户输入 + 当前未完成工具协议 + 最小最新状态）仍超限时返回 `context-budget-exhausted`，不会静默删除当前用户输入、安全规则或工具关联。

## 跨轮事实来源

主 Agent 的跨轮事实来源是 `conversation_epoch` 与规范化 committed turn，而不是 Session 的消息列表：

- **Session 仅存身份**：`Session` 只持有 `{session_key, conversation_epoch, 瞬态控制状态}`，已删除 `history_window` 与消息副本。正在执行的 turn 继续使用 `Reasoner.working_messages`，避免刚提交事件的读后写延迟。
- **committed 事件**：`turn_input_committed` / `assistant_message_committed` / `tool_message_committed` / `turn_output_committed`。`turn_output_committed` 在 `RESPONSE_TRANSFORM` 之后记录，保证模型可见的最终文本（而非原始模型输出）成为事实。
- **RestorationLevel 四级恢复**：`EXACT`（可精确重放）/ `GOVERNED`（受治理的派生视图）/ `LEGACY_INFERRED`（旧轨迹兼容推断，`restorable=false` 须明示）/ `UNAVAILABLE`（不可恢复，显式降级）。
- **来源优先级**：优先 `TrajectoryContextSource`（durable，可跨重启）；轨迹关闭、metadata-only、内容损坏或不可达时降级到 `InProcessTurnSource`；旧轨迹只能走 `LegacyTurnSource` 并标 `legacy-inferred`，不得伪装成 exact replay。不得同时拼接 Session history 与 trajectory history。
- **Reader 约束**：跨轮 reader 只读取当前 epoch 中已经终止且顺序完整的 turn，排除当前 trace、running/cancelled/损坏记录，并按 `(turn_sequence, message_sequence)` 稳定排序。

## /clear 与 conversation epoch

每个 `session_key` 持久保存单调递增的 `conversation_epoch`。进程重启继续读取当前持久 epoch，而不依赖每次启动变化的 `session_instance_id` 截断上下文。

- **活动 turn 期间拒绝**：存在未完成的 turn 时 `/clear` 必须明确拒绝，避免损坏 tool pair 或正在写入的 envelope。
- **成功路径**：原子创建新 epoch，并重置该 session 的派生 context 状态——编译快照、archive frontier、`compaction_failure_limit` 失败计数、冻结预览可见索引。
- **失败路径**：epoch store 不可用时 `/clear` 必须明确报告未完成，不能只清内存后声称成功，旧 epoch 保持不变。
- **旧数据保留但不进新 epoch**：旧 committed turns、原始 trajectory、受管 payload、长期 Memory、Working State 按各自策略保留，但不再进入新 epoch 的上下文。冻结预览对旧 epoch 标记不可见（不删行、payload 保留），新 epoch 使用当时的 system/Skill/tool 快照。

SubAgent 默认创建独立、非恢复 epoch source，自建 Reasoner 绕过 phase 链，不获跨轮 durable source；仅显式装配相同协议 profile 才启用跨轮恢复。

## 统一压缩协调器

压缩拆为无副作用的规划阶段与异步协调阶段，soft/hard/emergency 复用同一 `TaskAwareCompactor`：

- **Plan**：加载 stable snapshot、archive frontier、完整候选 turn 与动态块；计算 pre-reduction ratio，选择压缩 batch，并给出不执行摘要时仍可发送的视图或明确失败。soft/hard 比率基于降载前的候选总量，不能基于已经丢弃 tail 后的结果。
- **Execute**：在 soft/hard/emergency 模式下调用同一个 `TaskAwareCompactor`。请求使用固定 schema，携带当前目标/约束、完整 batch、source refs 与父 archive refs；压缩模型不获得主 Agent 工具。
- **Validate**：检查 JSON schema、引用集合、预算、禁止字段、覆盖无环性和最小保留字段；不接受引用减少、伪造或跨 epoch 内容。
- **Commit**：在一个 `context-state.db` 事务中写入 archive、coverage、frontier、generation、失败计数和 outbox 事件；提交成功后再重新 plan/compile。

已删除同步机械 `_archive`（按角色把全文塞入 JSON 后从最长数组头部弹出）路径——它既非任务感知，也可能静默删除最早约束。无可用 compactor 时只允许确定性去噪、冻结预览和有诊断的候选省略；不得把机械截断标记成任务 archive。连续失败达到 `compaction_failure_limit` 后停止压缩（熔断），重置只能显式 `/clear` 清理 context state。

Provider 返回 `provider-context-length` 时，同一 trace 至多进行一次 emergency hard compile；新 context hash 必须与失败输入不同才会重试。该路径不会重新执行工具，也不会向窗口能力未知或更小的 fallback 发送同一超限输入。

任务感知 archive 使用 `[context].compaction_profile` 指定的真实模型 Profile；留空时复用 agent/default Profile。Echo Provider 不得生成正式 archive。压缩请求作为独立子 span 记录，结构校验或 Provider 调用失败时不提交 archive，也不改变当前模型视图。

## 有界 archive frontier

每个 archive 保存 `archive_id`、epoch、level、generation、content/schema version、直接 source refs、parent archive refs、transitive coverage hash、token count 和状态。活动 frontier 必须覆盖互不重叠；原始 turn 被某个 committed archive 覆盖后不再同时注入。

- **双上限**：`archive_frontier_tokens` 为跨所有注入 archive 的聚合 token 预算（区别于 per-archive `archive_tokens`）；`archive_frontier_max_items` 为 frontier 节点数上限。超预算时按 level DESC/created_at DESC 取子集，最旧最低层 archive 不注入（coverage 仍生效，永久缩减由合并路径处理）。
- **层级合并**：当 frontier 超预算或超过节点数时，把最旧相邻 archive 合并为更高 level archive；事务提交后才替换父节点，合并前后做约束/引用校验，避免语义损失累积。
- **原子提交**：archive 与 coverage/frontier 必须在同一个 `context-state.db` 事务中提交。同一事务写入幂等 outbox；提交后投递 `context_compaction_committed`，失败可重放且不回滚已成立的 context state。压缩请求/失败事件可直接写轨迹，但业务正确性不依赖观察 hook 成功。
- **generation 分配**：由事务内 `(session, epoch)` 计数器分配，不用 `len(archives)+1`。唯一约束覆盖 `(session_key, epoch, generation)`、archive id 和 source coverage，消除并发或重试造成的孤立节点与重复覆盖。

## 大工具结果与冻结预览

工具原文先进入受 trajectory 策略管理的 payload；模型只接收冻结预览，预览包含内容哈希、原始大小、转换标志和稳定引用。引用不是读取权限，重新读取仍必须经过原有 workspace/scope/tool 权限。

- **绑 epoch 与规范化哈希**：`FrozenToolPreview` 绑 `conversation_epoch`、规范化 tool message hash 与 `tool_call_id`。
- **恢复前校验**：注入前必须验证 preview hash、payload reference 与 tool_call_id；校验失败时不注入损坏 tool result，并以可观察协议错误结束或排除整个旧 turn，不能拆散 tool pair。
- **/clear 行为**：清理 epoch 只把旧 epoch 的冻结预览标记不可见，不删行、原始受管 payload 保留；新 epoch 需要时重新冻结。

## 渐进工具 schema

`[tools].tool_search_enabled = false` 是兼容默认值：所有启用工具以名称稳定排序后进入 Session snapshot。启用后，基础工具与 `tool_search` 先冻结；之后注册的插件、MCP 或其他延迟工具只在 `tool_search` 选中后披露。披露记录以 `(session_key, conversation_epoch, tool_name)` 持久化，保存规范 schema、schema hash、来源 call id 和首次披露顺序；重复搜索幂等，其他 Session/Epoch 不继承。

Context Compiler 在稳定 base snapshot 后追加当前 Session/Epoch 的披露记录，形成
effective tool schema 和独立 effective schema hash；旧前缀和首次披露位置保持不变。
Reasoner 的下一次 Provider 请求使用该有效集合，同时将其名称作为本次工具执行授权，
因此未披露延迟工具不能靠猜测名称越过 `tool_search`。

稳定快照键改为 `(session_key, conversation_epoch)`。普通能力新增仍只影响新 epoch；安全撤销始终 fail-closed，立即阻止执行并使当前 snapshot 进入失效状态，不能继续向模型宣称已撤销工具可用。新 epoch 使用当时的 system/Skill/tool 快照。

## Token 估算与诊断

Token estimator 通过模型 profile 选择；支持的模型使用 tokenizer adapter，不支持时使用 `ConservativeTokenEstimator` 并标注 `exact=false`。预算包含 messages、tool schemas 和协议固定开销。

诊断同时记录：

- epoch、恢复等级、pre/post tokens 与压缩收益；
- 每层候选/保留/省略量；
- archive frontier 状态（active count / level / budget）；
- 估算器类型（tokenizer adapter 或 conservative）；
- 恢复能力与降级原因；
- outbox pending/failed 与 frontier budget。

诊断红线：只记稳定引用（hash、计数、archive id、generation），**绝不暴露 API key、隐藏 reasoning、embedding 或未脱敏 payload**。`capture_content=redacted` 为默认脱敏模式；诊断中出现的任何 payload 片段必须经同等脱敏。

## KV/Prompt Cache 边界

Runtime 不持久化 Provider 的 KV cache。它通过稳定序列化、稳定工具排序和冻结前缀提高 Provider prompt cache 命中可能性。只有 Provider 实际返回 `input_tokens`、`cached_input_tokens` 或 `cache_creation_input_tokens` 时才记录相关指标；缺失字段不推断为命中或未命中。

## 配置与数据保留

```toml
[llm]
context_window_tokens = 131072
context_safety_margin_tokens = 4096
token_estimator = "conservative"

[context]
enabled = true
compaction_enabled = true
persistence_enabled = true
database = "workspace/context-state.db"
soft_threshold_ratio = 0.75
hard_threshold_ratio = 0.90
recent_tail_tokens = 12000
preview_tokens = 2000
archive_tokens = 4000
# §8.1 有界 archive frontier：跨所有注入 archive 的聚合 token 预算
archive_frontier_tokens = 16000
# §8.1 frontier 节点数上限
archive_frontier_max_items = 8
# §8.1 跨轮来源单次读取 turn 上限（None=不限；I/O 防护，非语义历史窗口）
source_read_max_turns = None
# §8.1 跨轮来源单次读取字节上限（None=不限）
source_read_max_bytes = None
# §8.1 单次压缩批次 token 上限：批次累计达此值即停止扩充
compaction_batch_tokens = 32000
plugin_max_tokens = 2000
emergency_retry_limit = 1   # 仅 0 或 1
compaction_failure_limit = 2
compaction_profile = ""     # 留空复用 agent/default；不得指向 Echo
```

`[agent].history_window` 已移除（§3.5）：Session 不再按消息条数提前裁剪。旧配置出现该字段时启动返回带迁移指引的明确错误，指向 `[context]` 下 `recent_tail_tokens` / `archive_tokens` / `source_read_max_turns` / `source_read_max_bytes` / `archive_frontier_tokens` / `archive_frontier_max_items`，不得静默忽略。

`context-state.db` 与 trajectory、Personal Memory、Working State、Skill 数据库相互独立。archive 不会自动写入 Personal Memory、Skill、system prompt 或训练数据。关闭持久化时使用进程内仓库（`InMemoryContextStateRepository`），重启后明确从空 context state 开始。回滚可关闭 `[context].enabled`；数据库保留供后续恢复，不应自动删除。
