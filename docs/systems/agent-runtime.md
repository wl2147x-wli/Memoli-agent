# Agent Runtime

上下文预算、五层上下文、工具预览、压缩与紧急恢复见 [Context Management](context-management.md)。

Memoli 的主 Runtime 使用一个串行 Agent Loop 完成单次用户 turn。`AgentLoop`
只负责消息收发，`PassiveTurnPipeline` 按阶段链组织一轮处理——BeforeTurn →
CrossTurnContext → BeforeReasoning → PromptRender → Reasoner → AfterReasoning →
AfterTurn——`Reasoner` 负责有边界的模型/工具循环。

## 执行流程

```text
InboundMessage
  -> PassiveTurnPipeline
       -> BeforeTurn（获取/创建 Session 瞬态身份）
       -> CrossTurnContext（读持久 epoch + 近期完整 turn；SubAgent 默认隔离）
       -> BeforeReasoning（长期记忆召回）
       -> PromptRender（组装 messages）
       -> Reasoner
            -> 检查迭代与时间预算
            -> 调用模型
            -> 按声明顺序执行工具
            -> 把工具结果加入当前 turn 上下文
            -> 继续模型调用或结束
       -> AfterReasoning（RESPONSE_TRANSFORM + turn_output_committed）
       -> AfterTurn
  -> OutboundMessage
```

同一模型响应中的多个工具按顺序执行。中间模型消息和工具结果只写入运行轨迹。
Session 仅持有 `{session_key, conversation_epoch, session_instance_id}` 的瞬态身份
与控制状态，不再维护消息历史副本；跨轮上下文事实由 canonical committed turn
持久化在 trajectory store，`CrossTurnContextPhase` 在每轮起始从 store 读取当前
epoch 内已终止的完整 turn。

## CLI 启动与本地命令

安装项目后，推荐使用 `memoli` 启动前台聊天；`memoli chat` 与之等价，
`python main.py` 保留为兼容入口。`--config`、`--workspace` 和 `--session`
可写在 `chat` 前后。CLI 启动摘要只展示版本、Provider/模型、workspace、session
和主要功能开关，不展示 Key、Header、Cookie 或敏感 URL。

本地命令由唯一的 `CommandRegistry` 定义，路由、`/help` 和交互补全都读取同一份
名称、别名、分类、参数提示、可用性和 handler 元数据。除原有命令外还包含
`/stop`、`/workspace`、`/model`、`/tools`、`/memory` 和 `/skills`。检查类命令首版
只读，切换参数只返回 `config.toml` 与重启指引。

这些命令由 Channel 在创建 `InboundMessage` 前处理，因此不调用
Provider、工具或长期记忆，也不产生普通被动 turn 轨迹。以 `//` 开头可以把
字面 `/` 发送给模型。`/clear` 在活动 turn 期间被拒绝；成功后原子推进
`conversation_epoch`（`BEGIN IMMEDIATE` 串行化并发），并重置该 session 的派生
上下文状态（编译快照、archive frontier、失败计数、冻结预览可见索引）；checkpoint、
长期记忆、Skill binding、原始轨迹与 payload 不删除，但旧 epoch 的 committed
turn 不再进入新 epoch 上下文。失败时保持旧 epoch 并显式报告，不只清内存后
声称已清理。进程重启继续读取当前持久 epoch，不用每次启动变化的
`session_instance_id` 截断上下文。

`memoli checkpoint --session <id>` 通过 SQLite 只读连接离线读取
`cli:<id>` 的工作 checkpoint；`--json` 输出带 schema version 的单个确定性 JSON
对象。离线路径不构建 Runtime，也不会创建目录、数据库或修改 revision。在线
`/checkpoint` 还会分开展示 Agent 自报的软 checkpoint 与 Runtime 投影的硬状态，
离线查询则将 Runtime 状态明确标记为 unavailable。

CLI 由共享 `CLIController`、可替换 adapter 和单写者 renderer 组成。Controller
统一处理命令、空白输入、queue limit、`InboundMessage` 发布和退出决定；
`InteractiveCLIAdapter` 只负责 prompt_toolkit 输入能力，`PlainCLIAdapter` 只负责
逐行读取和无 ANSI 文本写出。两种模式共用相同 Outbound/表现事件消费者，不再维护
旧的第二套流式状态或命令条件链。

交互终端由 prompt_toolkit 输入层和单写者 renderer 组成。Reasoner 只投影有界的
turn/model/text/usage/tool/checkpoint/终止事件，不投影 thinking、工具参数或 SDK
对象；最终 `OutboundMessage` 始终是权威结果。Renderer 以配置帧率合并增量、按
step id 更新工具状态，并在提交最终 Rich Markdown 时去除已经展示的流式前缀。

增强 TTY 的输入区使用青色圆角单线框，顶部左侧标题为“输入”；框内支持中文、
自动折行和 `Esc+Enter` 多行编辑，框下显示 `Enter 发送 · Esc+Enter 换行 · / 命令`。
边框、候选和状态栏由同一个 prompt_toolkit Application 使用公共 layout API 重绘，
窗口 resize 或异步输出后会恢复边框与光标。Windows 启动时先将控制台输入/输出
code page 设为 UTF-8；设置失败、非 TTY 或增强初始化失败时使用无边框、无 ANSI 的
plain CLI，消息、命令、排队和取消语义保持不变。

表现队列满、renderer 异常或终端能力不足都不会改变 Agent 行为，系统会降级到
plain CLI。plain 降级只改变终端表现，不改变命令旁路、消息排队、取消、trace 或
错误分类语义。

`AgentLoop` 将长期 message pump 与当前 per-turn task 分离。`/stop` 或活动时 Ctrl+C
仅取消当前 Provider/工具等待，写入 `cancelled/user-cancelled` 终态后继续消费下一条
排队消息；Runtime shutdown 取消 message pump 时仍传播控制流取消。

`AgentLoop` 按消息隔离失败：单轮异常会生成不包含原始异常文本的结构化错误回复，
后续消息仍可继续处理；发布和派生维护失败只记录类型化诊断。任务取消属于控制流，
`CancelledError` 始终向上传播。缺失的 Tool Call ID 在单轮内只规范化一次，模型历史、
执行请求和 Tool Result 共用同一 ID。

模型调用由共享的无状态 Provider Router 完成。主 Agent 与 SubAgent 复用客户端，
但各自持有独立工作状态和 trace。SubAgent 自建 `Reasoner` 绕过被动 turn 阶段链，
默认不装配跨轮 durable source（`ContextSource`/`PreviewIntegrityLookup` 均为空），
因此不获得主 Agent 的 canonical committed turn；仅当显式装配相同协议 profile 时
才启用跨轮恢复。正式 Provider 失败时只会进入显式配置、能力兼容的真实模型
fallback，不会生成 Echo 假成功。Provider 合同、配置、重试、streaming 和安全边界
见 [LLM Providers](llm-providers.md)。

终止原因包括：

- `completed`：得到可返回的最终回复。
- `needs-user`：继续执行需要用户信息或授权。
- `failed`：Provider、工具协议、无进展或本地轨迹写入失败。
- `budget-exhausted`：达到迭代数、墙钟时间或上下文预算边界。上下文预算检查位于
  Reasoner while-loop 顶部（`BUDGET_EXHAUSTED`），先于工具执行；时间/迭代预算
  同样在循环顶部检查。
- `cancelled`：用户停止当前 turn；不会停止 Runtime。

## 生命周期提交点

主 Agent 在每轮被动 turn 中记录四类 canonical committed 事件，构成跨轮可重放的
规范化 turn 事实来源：

- `turn_input_committed`：trace 落盘后、循环脚手架之前，记录当前用户输入。
- `assistant_message_committed`：模型返回 tool-call 后记录 assistant 消息（不含
  completion-retry 脚手架与纯文本响应，后者由 `turn_output_committed` 记录）。
- `tool_message_committed`：每个 tool result 落盘后记录，保留 `tool_call_id`/
  `name` 以维持工具协议配对。
- `turn_output_committed`：`AfterReasoningPhase` 在 `RESPONSE_TRANSFORM` hook 之后
  记录最终用户可见输出及终止状态。

提交 envelope 复用 `_message_dicts`（已处理 blocks 展开与脱敏），排除隐藏
reasoning、敏感原文和训练评价字段。记录包含 `session_key`、持久
`conversation_epoch`、`trace_id`、turn 序号、消息序号、标准 role、tool
correlation、可见 blocks/文本、capture/degradation 标记和内容哈希。提交失败
不阻断主控制流——committed 事件缺失由 reader 降级处理。当前正在执行的 turn
继续使用 `Reasoner.working_messages`，避免刚提交事件的读后写延迟。

## SQLite 轨迹

默认轨迹数据库为 `workspace/trajectories.db`。一个用户 turn 对应一个
trace，多轮对话通过 session id 关联；模型、工具和检查过程保存为 span，
循环决策保存为 append-only event。

数据库包含四类记录：

- `traces`：turn 的状态、终止原因、Provider、模型、usage 和最终结果。
- `spans`：Agent、LLM、Tool、Memory 和 Guardrail 操作。
- `events`：带 trace 内唯一顺序号的原始运行证据。
- `payloads`：脱敏后的模型消息、工具参数和工具结果。

工具事件同时保存模型原始参数与实际执行参数，以及完整脱敏输出与返回模型的
有界输出。模型上下文发生裁剪时，完整结果仍通过本地 payload 保留；这些字段
都是原始执行事实，不包含工具质量评价或训练标签。

SQLite 使用外键、WAL、显式事务和 schema migration。当前 trajectory schema 为 v4，
包含 `events(span_id)` 索引、`session_epochs` 表（持久 conversation epoch）与
canonical committed turn/message 表；旧 schema 导出会将当前版本写入
`schema_version`，并把原版本保存在 `source_schema_version`。缺少
`trace_finished` 的 trace 表示运行被异常中断，不得视为成功。未知 schema
version 或 migration 失败时，Runtime 不会删除或重建已有数据库。

模型请求在调用 Provider 前提交，工具意图在执行工具前提交。必需本地证据
无法提交时，Runtime 停止后续模型和工具操作；JSONL 等可选导出失败不会修改
已提交轨迹或 Agent 结果。

## Payload 与隐私

轨迹默认使用 `redacted` 内容采集模式。脱敏递归覆盖字段名、字符串、Header、URL
查询参数、Cookie、Bearer token 和常见 Key 前缀；已知凭证和隐藏 reasoning 不会
落盘。小 payload 内联保存，较大内容使用 zlib 压缩 BLOB，超过上限或二进制
内容写入受管 payload 目录，SQLite 保存相对引用、大小和哈希。

事务失败会清理本次创建的外部 payload。运维可使用带数量上限、宽限期且默认
dry-run 的 orphan payload GC；解压、反序列化和文件错误统一包装为不泄漏路径或内容
的 `TrajectoryError`。

可用采集模式：

- `metadata-only`：只保存数据类型和执行元数据。
- `redacted`：保存递归脱敏后的可观察输入输出，默认模式。
- `full-local`：保存更多本地内容，但仍清除凭证和隐藏 reasoning。

轨迹不会自动进入 Memory、Evolution 或 Post-training。任何学习用途都需要后续
独立授权与数据治理流程。

## 配置

```toml
[agent]
max_iterations = 12
max_elapsed_seconds = 300
no_progress_limit = 3

[trajectory]
enabled = true
database = "workspace/trajectories.db"
capture_content = "redacted"
max_inline_bytes = 65536
max_payload_bytes = 4194304
payload_directory = "workspace/trajectory-payloads"
sensitive_keys = []

[tools]
code_timeout_seconds = 60
code_max_output_chars = 10000
file_read_max_lines = 2000
file_max_output_chars = 15000
browser_enabled = false
subagent_tool_enabled = false
```

将 `trajectory.enabled` 设为 `false` 会使用 Null store，不创建轨迹数据库。

## 查询、导出与备份

Runtime 提供按 trace、session、时间、终止原因、Provider、模型和 span kind 的
本地查询。JSONL 是从已提交 SQLite 数据生成的确定性导出格式，只用于调试、
Benchmark fixture 和离线交换，不作为在线权威状态。

备份前应先正常关闭 Runtime，或同时复制 SQLite 主文件及其 `-wal`、`-shm`
sidecar。数据库和 payload 目录均属于本地敏感数据，不应提交到版本控制。
## Offline-memory lifecycle

Startup order is Trajectory store, SubAgent manager, then memory worker. Shutdown
stops new offline claims first, allows a bounded worker finish, and then stops the
SubAgent runtime and Trajectory store. Expired request, governance, Card/Episode,
and semantic-index leases are recovered on the next start. The one-shot
`MemoryRuntime.maintenance_tick()` remains available for tests and operations.

The governance queue in `memory.db` is authoritative. A SubAgent task ID is only an
execution record; task loss cannot approve a Candidate, and a stale expected
revision cannot overwrite a concurrent user decision.
