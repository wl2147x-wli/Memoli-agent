## Context

当前 `AgentLoop` 是异步 MessageBus 消费者，`AgentRunner` 将普通消息交给 `PassiveTurnPipeline`，六阶段生命周期最终调用 `Reasoner`。现有 `Reasoner` 最多执行一批工具并补充调用一次模型，适合验证链路，但不能处理“观察结果后再决定下一工具”的任务。Session 只保存用户消息和最终回复，工具交互及中间失败不会形成可持久化证据。

本设计参考 GenericAgent 的极简方式：一个串行循环、少量明确的 outcome、一个最大轮数。Memoli 保留已有分层和异步 I/O，同时增加 append-only 完整轨迹；不采用 Akashic 式的并发 active-task、复杂事件总线或阶段 slot 图。

## Goals / Non-Goals

**Goals:**

- 用一个容易阅读、测试和调试的串行循环完成多轮 model/tool 交互。
- 明确每一步和整个 turn 的继续、完成、失败、请求用户及预算耗尽语义。
- 在进程异常前尽可能保存已经发生的每个模型和工具事件。
- 保持 `AgentLoop`、Channel、Provider、Tool、Session 与 PassiveTurnPipeline 的现有边界。
- 使轨迹能直接用于调试、确定性回放、评测样本构造和后续离线学习。

**Non-Goals:**

- 不支持多个 turn 并发执行或同一 session 的并发调度。
- 不实现跨进程任务恢复、等待外部事件或 Durable Task 状态机。
- 不实现复杂 DAG、planner/executor、多 Agent 编排或插件拓扑。
- 不从轨迹自动修改 Memory、Prompt、Skill、代码或模型参数。
- 不保存供应商隐藏 reasoning，也不保证对任意非结构化工具输出识别全部敏感信息。

## Decisions

### 1. 保持外层 AgentLoop 极薄，由 Reasoner 拥有串行循环

调用链保持为：

```text
MessageBus → AgentLoop → AgentRunner → PassiveTurnPipeline
                                      → Reasoner.run_turn()
                                          ├─ Provider.complete()
                                          ├─ ToolRuntime.execute()
                                          └─ TrajectoryStore.commit()
```

`AgentLoop` 仍只消费入站消息并发布出站消息；`PassiveTurnPipeline` 仍负责 turn 前后的上下文、记忆和历史处理；只有 `Reasoner` 负责单次唤醒内的循环。这避免消息生命周期、模型循环和未来任务持久化互相嵌套。

替代方案是直接在 `AgentLoop` 中加入工具循环。它的文件数量更少，但会把消息泵、会话、推理和工具执行混在一起，降低可测试性，因此不采用。

### 2. 使用一个顺序 while 循环，不引入并发调度

每次迭代执行以下固定流程：

```text
检查预算 → 记录模型输入 → 调用模型 → 记录模型输出
    ├─ 有 tool_calls：按模型声明顺序逐个执行并记录结果 → CONTINUE
    └─ 无 tool_calls：CompletionGate 判定
                       ├─ 接受 → COMPLETE
                       └─ 可重试 → 把反馈加入上下文 → CONTINUE
```

单个模型响应中的多个工具调用也顺序执行。这样牺牲工具并行性能，但保证轨迹顺序、状态变化和失败行为容易解释，符合当前“不做并发”的范围。

### 3. 用小型结构化 outcome 取代文本驱动控制

内部采用类似 GenericAgent `StepOutcome` 的简单数据合同，但状态必须是枚举而不是依赖 `next_prompt` 是否为空推断：

- `continue`：工具结果或完成门反馈已经加入模型上下文，继续下一轮。
- `completed`：存在可返回给用户的最终回复。
- `needs_user`：缺少授权或必要信息，结束本次 turn 并向用户提问。
- `failed`：Provider、Tool、协议或轨迹写入出现不可恢复错误。
- `budget_exhausted`：最大迭代数或最长运行时间已用尽。

最终 `TurnResult` 包含 `trace_id`、最终回复、终止原因、迭代数、总 usage、最后错误和是否使用 provider fallback。既有出站消息仍取其中的最终回复，避免改变 Channel 协议。

替代方案是保留 `next_prompt=None`、`should_exit=True` 等隐式组合。其代码略短，但容易形成矛盾状态，也不利于轨迹和测试断言，因此不采用。

### 4. 无工具输出通过轻量 CompletionGate 结算

无工具调用不自动等于异常。普通问答可以直接完成；空响应、可识别的截断响应或缺失必要最终文本时，CompletionGate 返回一次结构化重试反馈。语义性的“外部任务是否真的完成”仍由具体工具结果或以后单独的 verifier change 负责，本 change 不加入第二个 LLM Judge。

该方案保留 GenericAgent `no_tool` 的实用价值，但不把伪工具注册到公开工具 schema，也不让完成控制散落在业务工具 handler 中。

### 5. 预算只实现最大迭代数和墙钟时间

第一版配置：

```toml
[agent]
max_iterations = 12
max_elapsed_seconds = 300
no_progress_limit = 3
```

每次模型调用算一次 iteration。循环在发起下一次模型调用或工具调用前检查时间边界。Token 和费用仍记录到轨迹和汇总中，但本 change 不把不同 Provider 的不一致 usage 字段提升为强制预算，后续可在统一 usage 合同成熟后扩展。

达到预算时必须返回 `budget_exhausted`，不得把模型最近的中间文本包装为已完成回复。

### 6. 用确定性指纹阻止显然无进展的循环

每批工具执行后计算指纹，至少包含规范化工具名、参数、结果状态、错误类型及结果摘要哈希。连续达到 `no_progress_limit` 次相同指纹且没有新模型可见信息时，循环以 `failed/no_progress` 结束。

第一版只阻止完全相同的失败模式，不尝试用 LLM 判断抽象语义进展，从而保持确定性和低成本。

### 7. SQLite 保存权威轨迹，JSONL 只作为导出格式

默认启用本地轨迹：

```toml
[trajectory]
enabled = true
database = "workspace/trajectories.db"
capture_content = "redacted"
max_inline_bytes = 65536
payload_directory = "workspace/trajectory-payloads"
```

一个用户 turn 对应一个 trace，多轮对话通过 `session_id` 关联多个 trace；每次模型、工具、记忆或完成检查对应一个 span，瞬时循环决策对应 event。数据库使用四类逻辑记录：

- `traces`：trace/session/task 标识、起止时间、终止原因、最终回复引用、累计 usage、Provider/模型和 Runtime 版本。
- `spans`：父子关系、顺序号、`AGENT/LLM/TOOL/MEMORY/GUARDRAIL` 类型、输入输出引用、状态、错误和耗时。
- `events`：append-only 原始证据，保存全局于 trace 的单调顺序号、事件类型、时间戳和 payload 引用。
- `payloads`：脱敏后的模型消息、工具参数/结果和其他较大内容，带 MIME type、大小、哈希、压缩和截断信息。

`events` 是不可覆盖的权威 ledger，`traces/spans` 是便于查询的投影，可在同一事务中随事件追加更新。`UNIQUE(trace_id, sequence)` 防止重复或乱序；schema 使用显式版本和 migration，不得在版本不兼容时静默重建数据库。

SQLite 由单个串行 store 管理，启用 foreign keys、WAL、`synchronous=FULL` 和 busy timeout。当前 Runtime 不做并发，因此不引入连接池或后台写队列。每个必需事件及其投影更新在一个事务中提交；进程异常后，已提交前缀保持一致，缺少 `trace_finished` 的 trace 可被识别为 incomplete。

最小事件集合为：

- `trace_started`：session key、用户输入、循环限制、Provider/模型标识。
- `model_requested`：该 iteration 实际提供给模型的完整可见 messages 和工具定义引用/快照。
- `model_responded`：文本、结构化 tool calls、usage、fallback 和延迟。
- `tool_intent_recorded`：在执行前保存 tool call id、名称、脱敏参数及副作用分类。
- `tool_finished`：完整脱敏结果或结构化错误、状态和延迟。
- `loop_decided`：outcome、原因、iteration 和进展指纹。
- `trace_finished`：最终终止原因、最终回复、累计 usage、总时长和错误摘要。

Session 继续只保存对话所需的用户消息和最终助手回复；完整中间上下文只进入 trajectory，避免长期会话历史被工具噪声污染。

小 payload 直接保存在 SQLite；超过 `max_inline_bytes` 的内容使用标准库压缩后保存为 BLOB，仍超出上限或属于二进制的内容写入 payload 目录，数据库只保存受约束的相对 URI、哈希和大小。工具返回已有文件时优先保存引用和哈希，不复制整个文件。

`TrajectoryStore` 保持可替换，首版提供 SQLite、内存和 Null 实现。JSONL exporter 从已提交的 trace/span/event/payload 生成确定性、schema-versioned 导出，用于人工检查、Benchmark fixture 和离线数据交换；JSONL 不参与在线执行状态判定。内部 schema 保持稳定，后续 OpenTelemetry/OpenInference exporter 负责映射到外部 trace/span 语义，而不是让实验中的外部属性命名直接决定内部表结构。

### 8. 必需 SQLite 证据 fail-closed，可选导出不阻塞 Runtime

当 `trajectory.enabled=false` 时使用 Null store，Runtime 行为与普通循环一致。启用记录时，trace 开始、模型请求、模型响应、工具意图、工具结果、循环判定和 trace 结束均为必需证据。模型请求必须在调用 Provider 前提交，工具意图必须在执行工具前提交；如果任一必需事务无法提交，Runtime 必须停止发起新的模型调用或工具调用，并返回 `failed/trace_write_failed`。已完成的外部副作用不会被回滚，但不会继续产生无法审计的新副作用。

JSONL 或未来 OTLP exporter 只消费已提交记录；导出失败不得改变已提交 trace，也不得把成功任务改成失败，但必须返回可观察导出错误并允许重试。这样将执行证据可靠性与外部观测平台可用性解耦。

### 9. 明确隐私与序列化边界

Provider Authorization、API key 和环境凭证永不进入事件。工具参数、工具结果和消息在写入前经过递归 key redaction；默认敏感 key 包括 `api_key`、`authorization`、`token`、`password`、`secret` 和 `cookie`，允许配置追加。

轨迹保存模型可见内容和结构化响应，不请求或保存 Provider 未返回的隐藏 reasoning。无法安全序列化的值转换为有长度上限的文本表示；过大或外置内容记录 compression、truncation、哈希和 URI 标志。“完整”表示完整的运行步骤、顺序和可观察协议内容，而不是无限制复制二进制、工作区文件或秘密。

轨迹仅保存在本地，不得被 Memory、Evolution 或 Post-training 默认读取；进入学习流程必须由后续独立 spec 定义显式授权和脱敏门禁。

### 10. 保持 Provider、Tool 和 Channel 公共协议兼容

现有 Provider 返回的内容、tool calls、usage 和 fallback 元数据由适配层规范化后记录；不要求 Provider 暴露内部推理。现有 Tool schema 不变，Runtime 在调用边界包装计时和错误捕获。Channel 仍只接收最终出站消息，不暴露内部 step event。

因此旧的一轮问答和一次工具调用是新循环的自然子集，不需要迁移用户会话数据。

## Risks / Trade-offs

- **[串行工具降低复杂任务速度]** → 当前优先保证确定性；以后只有在轨迹和工具幂等合同成熟后再提并行 change。
- **[完整轨迹占用磁盘并包含个人信息]** → 本地数据库、递归脱敏、capture mode、payload 上限和可关闭 store；保留和清理策略另立 change。
- **[SQLite schema 演进破坏已有轨迹]** → schema version、顺序 migration、迁移前备份和失败即停止启动；禁止自动删除或重建未知版本数据库。
- **[SQLite 锁定或损坏中断 Agent]** → 当前单 writer、WAL、busy timeout、事务和健康检查；提供一致性检查与 JSONL 导出备份，后续保持 PostgreSQL 替换边界。
- **[数据库被大模型上下文和工具结果快速撑大]** → 元数据/大 payload 分离、压缩、内容寻址哈希和明确的 inline/总大小限制。
- **[简单 CompletionGate 接受虚假完成]** → 本 change 只解决循环控制；需要环境验证的任务必须依赖工具证据，通用 verifier 后续单独设计。
- **[轨迹写失败导致用户任务提前结束]** → 仅必需本地证据 fail-closed，并提供清晰错误；可选 JSONL/OTLP 导出失败只报告和重试。
- **[内部 schema 与外部 OTel GenAI 规范演进不一致]** → 内部合同版本化，单独 exporter 做映射，外部属性变化不触发核心数据库重构。

## Migration Plan

1. 增加 outcome、turn result、trajectory record 和 store 合同，不改变既有调用路径。
2. 定义 schema-versioned SQLite migration，以及 trace/span/event/payload 表、约束和索引。
3. 实现内存、SQLite 与 Null store，先用测试确认事务、事件顺序、脱敏、异常前缀和失败语义。
4. 实现从已提交轨迹到确定性 JSONL 的只读 exporter，不允许 exporter 反向影响 Runtime。
5. 将现有一次工具回调重构为串行循环，并让旧的一次工具测试继续通过。
6. 在 bootstrap 中默认装配 SQLite store；数据库和 payload 目录加入版本控制忽略和运维文档。
7. 使用脚本化 fake Provider 验证多步工具、无工具完成、预算耗尽、无进展、事务失败和 JSONL 导出。
8. 如需回滚，关闭 `trajectory.enabled` 并恢复旧 Reasoner 装配；已有 SQLite 数据库保持只读，不影响 Session 和 Memory。schema migration 发布后必须提供数据库备份和版本回退说明。

## Open Questions

- 默认 `max_iterations=12`、`max_elapsed_seconds=300` 和 `no_progress_limit=3` 是否需要在首轮实现后通过 benchmark 调整？
- 工具定义在 `model_requested` 中保存完整 schema，还是保存 schema 哈希并只在 `trace_started` 记录一次完整快照，以降低重复体积？
- `max_inline_bytes`、压缩后 BLOB 上限及外置 payload 上限应采用什么默认值？
- 首版只提供按 `trace_id` 查询与 JSONL 导出的库级接口，还是同时提供只读 CLI？
- 第一个外部 exporter 选择通用 OTLP/OpenInference，还是优先适配 Phoenix 进行作品集演示？
