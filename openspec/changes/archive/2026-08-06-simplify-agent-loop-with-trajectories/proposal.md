## Why

Memoli 当前的 Reasoner 只支持一次工具回调，无法以 GenericAgent 式的极简串行循环持续执行多步任务；同时会话历史只保留用户输入和最终回复，不能完整复盘模型决策、工具调用、失败和终止原因。现在需要先建立一个小而可靠的 Agent Loop，并把每次运行保存成可回放的完整轨迹，为后续评测、记忆提炼和后训练提供证据。

## What Changes

- 将一次被动 turn 的推理执行改为单任务、单线程语义的串行 Agent Loop：模型输出工具调用时执行工具并继续下一轮，无工具调用时进入完成判定。
- 采用类似 GenericAgent `StepOutcome` 的简单控制合同，用结构化 step outcome 表达继续、完成、失败和请求用户，而不引入复杂事件图或并发调度器。
- 为循环增加最大步数、最长运行时间和无进展保护；达到边界时返回明确终止原因，不得宣称任务完成。
- 为每次 turn 分配稳定的 trace 标识，并按执行顺序持久化输入上下文、模型响应、工具调用、工具结果、错误、用量、时间及最终结果。
- 使用本地 SQLite 作为权威轨迹存储，以 append-only event ledger 保存完整执行证据，并维护可查询的 trace/span 投影；敏感字段在落盘前脱敏，不保存供应商隐藏推理内容。
- 提供确定性的 JSONL 导出格式用于调试、Benchmark fixture 和离线学习数据交换，并为后续 OpenTelemetry/OpenInference exporter 保留适配边界。
- 保持现有 Channel、PassiveTurnPipeline、Provider、Tool、Session 和最终出站消息接口兼容；AgentLoop 继续只承担消息泵职责。
- 非目标：并发 session、后台任务调度、跨进程恢复、复杂插件事件拓扑、在线 Skill/Prompt 自修改、自动训练和轨迹分析界面。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-runtime`: 将一次工具回调扩展为有边界的极简串行 Agent Loop，并增加完整、可持久化的运行轨迹合同。

## Impact

- 主要影响 `memoli_agent/agent/` 下的 Reasoner、passive turn 生命周期和 session 交互，以及 bootstrap 中轨迹 sink 的装配。
- Tool 和 Provider 适配器需要向 Runtime 返回足以记录调用、结果、错误和 usage 的结构化数据，但不改变现有公开工具 schema。
- 新增 schema-versioned 本地 SQLite 轨迹数据库及可选大 payload 目录；两者必须继续被版本控制忽略，并提供关闭或更换 store 的配置入口。
- SQLite schema migration SHALL 保持显式、可测试且失败时不得静默丢弃已有轨迹；JSONL 只作为导出格式，不作为 Runtime 权威状态。
- 对现有用户输入和最终回复协议不构成破坏性变更；旧的一次工具调用场景是新循环的单步特例。
- 轨迹可能包含个人数据和工具输出，必须本地保存、落盘前脱敏且不得默认进入训练流程。
