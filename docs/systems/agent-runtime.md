# Agent Runtime

Memoli 的主 Runtime 使用一个串行 Agent Loop 完成单次用户 turn。`AgentLoop`
只负责消息收发，`PassiveTurnPipeline` 负责上下文与会话生命周期，`Reasoner`
负责有边界的模型/工具循环。

## 执行流程

```text
InboundMessage
  -> PassiveTurnPipeline
  -> Reasoner
       -> 检查迭代与时间预算
       -> 调用模型
       -> 按声明顺序执行工具
       -> 把工具结果加入当前 turn 上下文
       -> 继续模型调用或结束
  -> OutboundMessage
```

同一模型响应中的多个工具按顺序执行。中间模型消息和工具结果只写入运行轨迹，
Session 仍只保存用户消息和最终助手回复。

`AgentLoop` 按消息隔离失败：单轮异常会生成不包含原始异常文本的结构化错误回复，
后续消息仍可继续处理；发布和派生维护失败只记录类型化诊断。任务取消属于控制流，
`CancelledError` 始终向上传播。缺失的 Tool Call ID 在单轮内只规范化一次，模型历史、
执行请求和 Tool Result 共用同一 ID。

模型调用由共享的无状态 Provider Router 完成。主 Agent 与 SubAgent 复用客户端，
但各自持有独立消息历史、工作状态和 trace；正式 Provider 失败时只会进入显式配置、
能力兼容的真实模型 fallback，不会生成 Echo 假成功。Provider 合同、配置、重试、
streaming 和安全边界见 [LLM Providers](llm-providers.md)。

终止原因包括：

- `completed`：得到可返回的最终回复。
- `needs-user`：继续执行需要用户信息或授权。
- `failed`：Provider、工具协议、无进展或本地轨迹写入失败。
- `budget-exhausted`：达到迭代数或墙钟时间边界。

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

SQLite 使用外键、WAL、显式事务和 schema migration。当前 trajectory schema 为 v2，
包含 `events(span_id)` 索引；旧 schema 导出会将当前版本写入 `schema_version`，并把
原版本保存在 `source_schema_version`。缺少
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
