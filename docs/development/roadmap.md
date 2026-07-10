# Memoli-agent 开发流程路线图

本文档说明 `Memoli-agent` 的推荐开发流程。整体策略是：每个阶段都产出一个可运行、可验证的小版本，不要一开始就把复杂记忆、MCP、subagent、proactive 全部塞进去。

推荐总顺序：

```text
1. bus + CLI
2. config + AppRuntime
3. session + context
4. provider + reasoner
5. passive turn pipeline
6. tools
7. memory
8. lifecycle + plugins
9. subagent
10. proactive
11. MCP
12. peer agent
```

## 0. 项目约定阶段（已完成）

先定项目规则，不急着写复杂代码。

需要确定：

- Python 版本：建议 `>=3.11`
- 配置格式：`config.toml`
- 运行入口：`main.py`
- 运行数据目录：`workspace/`
- 核心包名：`memoli_agent`
- 第一版只支持 CLI
- 每个模块先做最小可运行版本，再逐步增强

建议先维护好：

```text
config.example.toml
pyproject.toml
pyproject.toml
README.md
docs/architecture/project-blueprint.md
```

验收标准：

- 项目目录清晰。
- README 能说明项目目标。
- 蓝图文档能说明整体架构。
- 所有 Python 包目录都有 `__init__.py`。

当前完成情况：

- 已生成基础目录骨架。
- 已创建 `config.example.toml`。
- 已创建 `.env.example`。
- 已完善 `pyproject.toml`。
- 已更新 `.gitignore`，忽略本地配置和运行时数据。
- 已创建 `docs/development/conventions.md`。
- 已更新 `README.md`。

## 1. 消息总线阶段（已完成）

目标是先把最小消息流打通。

目标链路：

```text
用户输入
  -> InboundMessage
  -> MessageBus
  -> AgentLoop
  -> OutboundMessage
  -> 打印回复
```

优先实现文件：

```text
memoli_agent/bus/events.py
memoli_agent/bus/queue.py
memoli_agent/channels/cli.py
memoli_agent/agent/loop.py
main.py
```

建议实现：

- `InboundMessage`
- `OutboundMessage`
- `MessageBus.publish_inbound()`
- `MessageBus.consume_inbound()`
- `MessageBus.publish_outbound()`
- `MessageBus.consume_outbound()`
- 一个最小 CLI 输入输出循环

验收标准：

- `python main.py` 能启动。
- CLI 能输入一句话。
- agent 能返回固定回复，例如 `Echo: xxx`。
- 不依赖真实 LLM。
- 不依赖记忆和工具。

当前完成情况：

- 已实现 `InboundMessage` 和 `OutboundMessage`。
- 已实现 `InboundMessage.session_key`。
- 已实现 `MessageBus` 的 inbound/outbound 队列。
- 已实现最小 `AgentLoop`。
- 已实现最小 CLI 输入输出循环。
- 已实现 `main.py` 第一阶段启动入口。
- 固定回复格式为 `Echo: {content}`。

## 2. 配置与 Runtime 装配阶段（已完成）

目标是把对象创建从 `main.py` 移到 bootstrap 层。

目标链路：

```text
main.py
  -> load_config()
  -> build_app_runtime()
  -> runtime.run()
```

优先实现文件：

```text
memoli_agent/bootstrap/config.py
memoli_agent/bootstrap/app.py
memoli_agent/bootstrap/channels.py
```

建议实现：

- `Config`
- `load_config()`
- `AppRuntime`
- `AppRuntime.start()`
- `AppRuntime.run()`
- `AppRuntime.shutdown()`
- `build_app_runtime()`

验收标准：

- `main.py` 不直接创建一堆核心对象。
- `AppRuntime` 统一管理启动和关闭。
- 配置能控制：
  - workspace
  - agent name
  - history window
  - provider 类型

当前完成情况：

- 已实现配置数据模型：`AppConfig`、`RuntimeConfig`、`AgentConfig`、`LLMConfig`、`MemoryConfig`、`ChannelsConfig` 等。
- 已实现 `load_config()`，支持读取 `config.toml`，缺失时使用默认配置。
- 已支持读取 `runtime.workspace`、`agent.name`、`agent.history_window`、`llm.provider` 等关键配置。
- 已实现 `AppRuntime`，统一管理 `MessageBus`、`AgentLoop` 和通道运行。
- 已实现 `build_app_runtime()`，把核心对象创建集中到 bootstrap 层。
- 已实现 `run_configured_channels()`，当前根据配置启动 CLI 通道。
- 已简化 `main.py`，入口只负责加载配置、构建 runtime、启动和关闭 runtime。

## 3. Session 与 Context 阶段（已完成）

目标是让 agent 具备多轮对话上下文。

目标链路：

```text
session_key
  -> history
  -> ContextBuilder
  -> messages
```

优先实现文件：

```text
memoli_agent/agent/session.py
memoli_agent/agent/context.py
memoli_agent/agent/types.py
memoli_agent/agent/core/prompt_blocks.py
```

建议实现：

- `Session`
- `SessionManager`
- `TurnState`
- `ContextRequest`
- `ContextRenderResult`
- `ContextBuilder`
- 基础 prompt block

建议 messages 结构：

```text
system prompt
history messages
current user message
```

验收标准：

- 同一个 CLI 会话能保存最近 N 轮历史。
- system prompt 从配置读取。
- `ContextBuilder` 能输出模型可用的 messages。
- 历史窗口可配置。

当前完成情况：

- 已实现 `SessionMessage`、`Session` 和 `SessionManager`。
- 已实现按 `session_key` 管理多会话内存历史。
- 已实现 `history_window` 历史窗口裁剪，窗口大小来自 `config.agent.history_window`。
- 已实现 `ChatMessage`、`TurnState`、`ContextRequest` 和 `ContextRenderResult`。
- 已实现 `build_system_prompt()`，根据 `config.agent.name` 构建基础 system prompt。
- 已实现 `ContextBuilder.render()`，输出顺序为 system prompt、历史消息、当前用户消息。
- 已将 `SessionManager` 和 `ContextBuilder` 接入 `AgentLoop` 与 `AppRuntime`。
- Echo 回复保持不变，同时将用户消息和助手回复写入会话历史。

## 4. LLM Provider 阶段（已完成）

目标是把固定回复换成可替换 provider。

目标链路：

```text
ContextBuilder.render()
  -> LLMProvider.chat(messages)
  -> reply
```

优先实现文件：

```text
memoli_agent/agent/provider.py
memoli_agent/agent/core/reasoner.py
```

建议先做两个 provider：

- `EchoProvider`：不需要 API key，用于测试。
- `OpenAICompatibleProvider`：真实模型接口。

建议实现：

- `LLMProvider` 协议
- `LLMResponse`
- `ToolCall`
- 超时处理
- 错误兜底

验收标准：

- 无 API key 时能用 EchoProvider 跑通。
- 配置 API key 后能调用真实模型。
- provider 错误不会让主循环崩溃。
- Reasoner 能返回最终文本回复。

当前完成情况：

- 已实现 `LLMProvider` 协议。
- 已实现 `LLMResponse`、`ToolCall` 和 `ProviderError`。
- 已实现 `EchoProvider`，无 API key 时默认使用，保证本地可运行。
- 已实现 `OpenAICompatibleProvider`，使用标准库调用 `/chat/completions` 接口。
- 已实现 `Reasoner.generate()`，统一调用 provider 生成最终文本。
- 已支持真实 provider 出错时回落到 `EchoProvider`。
- 已将 `Reasoner` 接入 `AgentLoop`，替代原先的硬编码 Echo 回复。
- 已将 provider 创建逻辑接入 `AppRuntime`，根据 `[llm]` 配置选择 provider。

## 5. PassiveTurnPipeline 阶段（已完成）

目标是把一轮对话拆成清晰阶段。

推荐阶段：

```text
BeforeTurn
  -> BeforeReasoning
  -> PromptRender
  -> Reasoner
  -> AfterReasoning
  -> AfterTurn
```

优先实现文件：

```text
memoli_agent/agent/core/passive_turn.py
memoli_agent/agent/runner.py
memoli_agent/agent/lifecycle/types.py
memoli_agent/agent/lifecycle/phase.py
memoli_agent/agent/lifecycle/phases.py
```

各阶段职责：

| 阶段 | 职责 |
| --- | --- |
| `BeforeTurn` | 准备 session、历史、基础 turn 状态。 |
| `BeforeReasoning` | 准备工具上下文、额外提示、技能信息。 |
| `PromptRender` | 构造模型 messages。 |
| `Reasoner` | 调 LLM，后续执行工具循环。 |
| `AfterReasoning` | 解析回复，保存历史。 |
| `AfterTurn` | 发布出站消息和 lifecycle 事件。 |

验收标准：

- `AgentLoop` 不直接调用 provider。
- `AgentLoop` 调用 `Runner` 或 `PassiveTurnPipeline`。
- 一轮对话有清晰输入和输出。
- 后续插件能挂到 phase 上。

当前完成情况：

- 已实现 `PassiveTurnContext`，集中保存一轮对话中的输入、session、turn state、context、LLM 结果和输出。
- 已实现 `PhaseModule` 协议和 `run_phase_modules()` 顺序执行器。
- 已实现默认阶段：`BeforeTurnPhase`、`BeforeReasoningPhase`、`PromptRenderPhase`、`ReasonerPhase`、`AfterReasoningPhase`、`AfterTurnPhase`。
- 已实现 `PassiveTurnPipeline.run()`，按固定阶段顺序处理普通用户消息。
- 已实现 `AgentRunner.handle_inbound()`，当前将普通入站消息交给 `PassiveTurnPipeline`。
- 已简化 `AgentLoop`，现在只负责消费 inbound、调用 runner、发布 outbound。
- 已更新 `AppRuntime` 装配，启动时创建 `PassiveTurnPipeline` 和 `AgentRunner`。

## 6. 工具系统阶段（已完成）

目标是让模型能调用工具。

目标链路：

```text
Reasoner
  -> LLM tool_call
  -> ToolRegistry.execute()
  -> tool result
  -> LLM final reply
```

优先实现文件：

```text
memoli_agent/agent/tools/base.py
memoli_agent/agent/tools/registry.py
memoli_agent/agent/tools/builtin.py
memoli_agent/agent/tools/tool_search.py
memoli_agent/bootstrap/tools.py
```

第一批工具建议：

- `time`
- `calculator`
- `memory_write`
- `memory_recall`
- `filesystem_read`

建议实现：

- `Tool` 协议
- `ToolResult`
- `ToolRegistry.register()`
- `ToolRegistry.get_schemas()`
- `ToolRegistry.execute()`
- 工具异常兜底

验收标准：

- 工具能注册。
- 工具 schema 能提供给 provider。
- Reasoner 能执行一轮 tool call。
- 工具异常不会中断整个 agent。

当前完成情况：

- 已实现 `Tool` 协议、`ToolResult`、`ToolError` 和 `ToolSchema`。
- 已实现 `ToolRegistry.register()`、`ToolRegistry.get_schemas()`、`ToolRegistry.execute()`。
- 已实现内置工具：`time`、`calculator`、`memory_write`、`memory_recall`、`filesystem_read`。
- 已实现 `ToolSearch` 的最小关键词搜索。
- 已扩展 `ChatMessage`，支持 tool role、tool_call_id、name 和 assistant tool_calls。
- 已扩展 `LLMProvider.chat(messages, tools=None)`，OpenAI-compatible provider 会把工具 schema 发送给模型。
- 已扩展 `Reasoner.generate()`，支持执行一轮 tool call，并把工具结果交回 provider 生成最终回复。
- 已实现 `build_tool_registry()`，并在 `AppRuntime` 中把工具注册表注入 `Reasoner`。
- 工具不存在或工具执行异常时会返回失败 `ToolResult`，不会直接拖垮主循环。

## 7. 记忆系统阶段（已完成）

目标是加入长期记忆。

目标链路：

```text
用户对话
  -> memory mutate
  -> memory query
  -> prompt memory block
```

优先实现文件：

```text
memoli_agent/agent/memory/store.py
memoli_agent/agent/memory/runtime.py
memoli_agent/agent/memory/retriever.py
memoli_agent/agent/memory/consolidator.py
memoli_agent/bootstrap/memory.py
```

第一版建议使用 markdown 或 json：

```text
workspace/memory/MEMORY.md
workspace/memory/HISTORY.md
workspace/memory/RECENT_CONTEXT.md
```

建议接口：

```python
class MemoryRuntime:
    async def query(self, request): ...
    async def mutate(self, request): ...
    def render_prompt_block(self): ...
```

验收标准：

- 能手动写入记忆。
- 能按关键词检索记忆。
- 每轮对话能把相关记忆注入 prompt。
- 关闭重启后记忆仍然存在。

当前完成情况：

- 已实现 `MarkdownMemoryStore`，使用 `MEMORY.md`、`HISTORY.md`、`RECENT_CONTEXT.md` 持久化记忆。
- 已实现 `MemoryRuntime.query()`、`MemoryRuntime.mutate()` 和 `render_prompt_block()`。
- 已实现 `KeywordMemoryRetriever`，按关键词检索长期记忆。
- 已实现 `MemoryConsolidator`，每轮对话后追加流水到 `HISTORY.md`。
- 已在 `BeforeReasoningPhase` 中查询相关记忆。
- 已在 `ContextBuilder` 中注入可选 memory prompt block。
- 已将 `memory_write` 和 `memory_recall` 从进程内临时记忆改为 Markdown 长期记忆。
- 已实现 `build_memory_runtime()`，并在 `AppRuntime` 中完成记忆系统装配。
- 已新增 `docs/systems/memory.md` 说明记忆文件职责和当前限制。

## 8. Lifecycle 与插件阶段（已完成）

目标是让扩展不污染核心代码。

目标链路：

```text
PluginManager
  -> load plugin.py
  -> register tools/hooks/modules
  -> lifecycle phase 调用插件
```

优先实现文件：

```text
memoli_agent/agent/plugins/base.py
memoli_agent/agent/plugins/manager.py
memoli_agent/agent/plugins/decorators.py
memoli_agent/agent/plugins/context.py
memoli_agent/plugins/shell_safety/plugin.py
memoli_agent/plugins/memory_default/plugin.py
```

建议插件能力：

- 注册工具
- before_turn hook
- after_turn hook
- prompt_render hook
- tool pre-hook

验收标准：

- 插件能被扫描加载。
- 插件能注册工具。
- 插件能监听 before_turn/after_turn。
- 插件初始化失败不会拖垮主程序。

当前完成情况：

- 已实现 `PluginMeta`、`PluginLoadResult` 和 `Plugin` 协议。
- 已实现 `PluginContext`，向插件注入配置、workspace、tool_registry、memory_runtime、hook_registry。
- 已实现 `HookRegistry`，支持 lifecycle hooks 和 `tool_pre` hook。
- 已实现 `PluginManager`，根据 `config.plugins.enabled` 加载本地插件。
- 已将 hooks 接入默认 lifecycle phases。
- 已将 `tool_pre` hook 接入 `ToolRegistry.execute()`。
- 已实现默认插件 `memory_default` 和 `shell_safety`。
- 已在 `AppRuntime` 中装配插件加载、注册、初始化和关闭流程。
- 已新增 `docs/systems/plugins.md` 说明插件目录、hook 名称和默认插件行为。

## 9. SubAgent 阶段（已完成）

目标是加入任务委派能力，让主 agent 可以把边界清晰的子任务交给本地子 agent 执行。

目标链路：

```text
主 agent 调用 spawn_subagent
  -> SubAgentManager
  -> SubAgentRuntime
  -> SubAgentResult
  -> ToolResult
  -> 主 agent 汇总回复
```

优先实现文件：

```text
memoli_agent/agent/subagent/events.py
memoli_agent/agent/subagent/manager.py
memoli_agent/agent/subagent/runtime.py
memoli_agent/agent/subagent/profiles.py
memoli_agent/agent/tools/builtin.py
memoli_agent/bootstrap/subagent.py
memoli_agent/bootstrap/tools.py
memoli_agent/bootstrap/app.py
```

建议实现内容：

- `spawn_subagent` 工具
- `SubAgentManager`
- `SubAgentRuntime`
- `SubAgentProfile`
- `SubAgentTask`
- `SubAgentResult`
- `SubAgentCompletionEvent`
- 独立 `task_id` 和 `task_dir`
- 可选后台任务完成回流

验收标准：

- 主 agent 能创建一个同步 subagent。
- 后台 subagent 完成后能把结果投回主 MessageBus。
- subagent 有独立 task_id/task_dir。
- subagent 权限 profile 可控。
- `spawn_subagent` 工具能被 `ToolRegistry.get_schemas()` 暴露给模型。
- 子任务结果会保存到 `workspace/subagents/<task_id>/result.md`。
- 子任务失败不会拖垮主对话链路，而是返回失败 `ToolResult`。

当前完成情况：

- 已实现 `SubAgentProfile` 和默认 profile：`general`、`research`、`coding`。
- 已实现 `SubAgentTask`、`SubAgentResult`、`SubAgentCompletionEvent`。
- 已实现 `SubAgentRuntime`，支持复用 reasoner 执行独立子任务 prompt。
- 已实现 `SubAgentManager`，支持同步任务、后台任务、task_id 和 task_dir。
- 已实现 `spawn_subagent` 工具，并接入 `ToolRegistry`。
- 已新增 `bootstrap/subagent.py`，在 `AppRuntime` 中集中装配 SubAgentManager。
- 已新增 `[subagent]` 配置和 `docs/systems/subagents.md` 文档。

## 10. Proactive 阶段（已完成）

目标是让 agent 不只被动回复，也能主动检查任务和信息源。

目标链路：

```text
定时 tick
  -> sense context
  -> decide push / skip
  -> send message
```

建议新增目录：

```text
memoli_agent/agent/proactive/
  loop.py
  sensor.py
  decision.py
  state.py
```

验收标准：

- 能定时 tick。
- 能读取最近 session 状态。
- 能判断是否需要主动发消息。
- 能通过 MessageBus 或 channel 发出主动消息。

当前完成情况：

- 已实现 `ProactiveState`、`ProactiveSignal` 和 `ProactiveDecisionResult`。
- 已实现 `ProactiveSensor`，当前读取最小运行状态。
- 已实现 `ProactiveDecision`，支持按 cooldown 判断是否发送主动消息。
- 已实现 `ProactiveLoop`，支持启动、停止、定时 tick 和主动消息投递。
- 已新增 `bootstrap/proactive.py`，在 `AppRuntime` 中集中装配主动循环。
- 已新增 `[proactive]` 配置，默认关闭主动循环。
- 已调整 CLI 为输入/输出双任务模型，支持主动消息自动显示。
- 已新增 `docs/systems/proactive.md` 文档。

## 11. MCP 阶段（已完成）

目标是接入外部 MCP server 工具。

目标链路：

```text
config.toml [mcp.servers]
  -> MCPClientManager
  -> MCPClient.list_tools()
  -> MCPToolAdapter
  -> ToolRegistry.register()
  -> Reasoner 调用 MCP 工具
```

建议新增目录：

```text
memoli_agent/agent/mcp/
  client.py
  registry.py
  tool.py
```

验收标准：

- 能读取 MCP server 配置。
- 能发现 MCP 工具。
- 能把 MCP 工具注册到 ToolRegistry。
- 主 agent 能调用 MCP 工具。

当前完成情况：

- 已实现 `MCPServerConfig` 和 `MCPConfig`。
- 已实现 `MCPClient`，支持本地 stdio MCP server 的连接、工具发现、工具调用和关闭。
- 已实现 `MCPClientManager`，支持管理多个 MCP server。
- 已实现 `MCPToolAdapter`，把 MCP 工具适配为现有 `Tool` 协议。
- 已新增 `bootstrap/mcp.py`，在 `AppRuntime` 中集中装配 MCP client manager。
- 已将 MCP 工具注册到现有 `ToolRegistry`，工具名格式为 `mcp__server__tool`。
- 已新增 `[mcp]` 配置示例和 `docs/systems/mcp.md` 文档。

## 12. Peer Agent 阶段

目标是接入外部 agent。

目标链路：

```text
external agent
  -> peer registry
  -> peer tool
  -> main agent call
```

建议新增目录：

```text
memoli_agent/agent/peer_agent/
  registry.py
  tool.py
  process_manager.py
  poller.py
```

验收标准：

- 能注册 peer agent。
- 能把 peer agent 暴露成工具。
- 主 agent 能调用 peer agent。
- peer agent 出错时主 agent 能优雅降级。

## 每阶段都要做的事

每完成一个阶段，都建议补：

- 一个最小运行示例。
- 一个 README 小节。
- 一个简单测试脚本或手动验证命令。
- 一条架构说明。
- 一份 TODO 列表。

## 第一版目标

第一版不要追求复杂，做到这些就很好：

- CLI 能对话。
- 支持多轮历史。
- 支持真实 LLM 或 EchoProvider。
- 支持 3 到 5 个工具。
- 支持简单长期记忆。
- 支持插件加载。
- 支持一个简单 subagent。

## 版本规划建议

### v0.1

- CLI
- MessageBus
- AgentLoop
- EchoProvider

### v0.2

- Config
- AppRuntime
- Session
- ContextBuilder

### v0.3

- OpenAI-compatible provider
- Reasoner
- PassiveTurnPipeline

### v0.4

- ToolRegistry
- 内置工具
- tool call loop

### v0.5

- MemoryRuntime
- markdown/json 记忆
- memory tools

### v0.6

- Lifecycle phase
- PluginManager
- 基础插件

### v0.7

- SubAgentManager
- spawn 工具
- completion event 回流

### v0.8+

- proactive
- MCP
- peer agent
- 复杂 memory engine

## 总结

Memoli-agent 的开发流程应该围绕一条主线推进：

```text
先让消息流起来，
再让模型接入，
再让工具可用，
再让记忆稳定，
再用插件扩展，
最后加入 subagent、proactive、MCP 和 peer agent。
```

每一步都保持可运行，这样项目会更稳，也更容易定位问题。
