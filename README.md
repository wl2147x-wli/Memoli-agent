# Memoli-agent

Memoli-agent 是一个面向长期记忆、自我沉淀和可插拔评测的 agent 项目。

当前项目已完成基础骨架、消息总线闭环、配置与 Runtime 装配、内存 Session 与 Context 构建、最小 LLM Provider 链路、PassiveTurnPipeline、最小工具系统、Markdown 长期记忆系统，以及本地插件系统。没有 API key 时会使用 EchoProvider，配置真实模型后可调用 OpenAI-compatible provider。

## 项目目标

- 构建一个可运行、可扩展的主 agent runtime。
- 支持长期记忆、会话历史、工具调用和插件扩展。
- 后续支持 subagent、proactive loop、MCP、peer agent 等高级能力。
- 为不同记忆系统的对比、替换和评测预留清晰接口。

## 当前状态

已完成第 0 阶段：项目约定阶段。

已完成第 1 阶段：消息总线阶段。

已完成第 2 阶段：配置与 Runtime 装配阶段。

已完成第 3 阶段：Session 与 Context 阶段。

已完成第 4 阶段：LLM Provider 阶段。

已完成第 5 阶段：PassiveTurnPipeline 阶段。

已完成第 6 阶段：工具系统阶段。

已完成第 7 阶段：记忆系统阶段。

已完成第 8 阶段：Lifecycle 与插件阶段。

已具备：

- 基础目录骨架。
- `config.example.toml` 配置样例。
- `pyproject.toml` 项目元数据。
- `.env.example` 环境变量样例。
- `.gitignore` 本地运行时数据忽略规则。
- `AGENT_PROJECT_BLUEPRINT.md` 架构蓝图。
- `DEVELOPMENT_ROADMAP.md` 开发路线图。
- `PROJECT_CONVENTIONS.md` 项目约定。
- `InboundMessage` / `OutboundMessage` 消息类型。
- `MessageBus` 入站和出站队列。
- 最小 `AgentLoop`。
- CLI 输入输出循环。
- 配置模型和 `load_config()`。
- `AppRuntime` 顶层运行时装配。
- 内存会话历史。
- `ContextBuilder` 上下文构建。
- 基础 system prompt。
- `LLMProvider` 抽象。
- `EchoProvider` 本地测试 provider。
- `OpenAICompatibleProvider` 真实模型 provider。
- `Reasoner` 最小推理器。
- `PassiveTurnPipeline` 被动对话流水线。
- `AgentRunner` 入站消息路由器。
- 默认生命周期阶段。
- `ToolRegistry` 工具注册表。
- 第一批内置工具：`time`、`calculator`、`memory_write`、`memory_recall`、`filesystem_read`。
- `Reasoner` 一轮 tool call 执行能力。
- Markdown 长期记忆文件。
- 记忆关键词检索。
- 每轮 prompt 记忆注入。
- 对话流水写入 `HISTORY.md`。
- 本地插件加载。
- lifecycle hooks。
- tool pre-hook。
- 默认插件：`memory_default`、`shell_safety`。

## 目录概览

```text
Memoli-agent/
  main.py
  config.example.toml
  requirements.txt
  pyproject.toml
  README.md
  AGENT_PROJECT_BLUEPRINT.md
  DEVELOPMENT_ROADMAP.md
  PROJECT_CONVENTIONS.md
  memoli_agent/
    bootstrap/
    bus/
    agent/
    channels/
    plugins/
    skills/
```

## 后续实现顺序

建议按以下顺序逐步填充代码：

1. `subagent`：任务委派和结果回流。
2. `proactive`：主动循环。
3. `MCP / peer agent`：外部能力接入。

## 本地开发约定

复制配置样例：

```powershell
Copy-Item config.example.toml config.toml
```

本地配置、运行时数据和日志不会提交：

```text
config.toml
workspace/
logs/
.env
```

更多约定见：

[PROJECT_CONVENTIONS.md](PROJECT_CONVENTIONS.md)

## 运行方式

```powershell
python main.py
```

没有配置 API key 时，当前 agent 会通过 EchoProvider 返回：

```text
Echo: 你的输入
```

如需调用 OpenAI-compatible 模型，可在 `config.toml` 中配置：

```toml
[llm]
provider = "openai-compatible"
model = "gpt-4.1-mini"
api_key = "你的 API key"
base_url = "https://api.openai.com/v1"
```

如果真实 provider 调用失败，系统会优雅回落到 EchoProvider。

## 当前内置工具

已注册的内置工具包括：

- `time`：返回当前本地时间和 UTC 时间。
- `calculator`：安全计算基础数学表达式。
- `memory_write`：写入 Markdown 长期记忆。
- `memory_recall`：按关键词检索 Markdown 长期记忆。
- `filesystem_read`：读取 `workspace/` 目录内的 UTF-8 文本文件。

## 长期记忆

默认记忆目录：

```text
workspace/memory/
  MEMORY.md
  HISTORY.md
  RECENT_CONTEXT.md
```

`MEMORY.md` 保存长期事实记忆，`HISTORY.md` 保存对话流水，`RECENT_CONTEXT.md` 预留给后续最近上下文摘要。

更多说明见：

[MEMORY_SYSTEM.md](MEMORY_SYSTEM.md)

## 插件系统

默认启用插件：

```toml
[plugins]
enabled = ["memory_default", "shell_safety"]
```

当前支持 lifecycle hooks 和工具执行前 hook。`shell_safety` 会在 `filesystem_read` 执行前拦截危险路径，`memory_default` 用于验证插件 hook 能正常参与一轮对话。

更多说明见：

[PLUGIN_SYSTEM.md](PLUGIN_SYSTEM.md)

## SubAgent 系统

第 9 阶段已加入本地进程内 SubAgent 能力。主 agent 可以通过
`spawn_subagent` 工具委派子任务，系统会为每个任务创建独立目录：

```text
workspace/subagents/<task_id>/
  task.json
  result.md
```

当前支持同步执行和最小后台回流。同步执行会把子 agent 结果作为工具结果返回；
后台执行会立即返回 task_id，并在完成后通过 MessageBus 投递 `subagent`
完成消息。

更多说明见：

[SUBAGENT_SYSTEM.md](SUBAGENT_SYSTEM.md)

## Proactive 系统

第 10 阶段已加入最小主动循环。默认关闭，可在 `config.toml` 中启用：

```toml
[proactive]
enabled = true
interval_seconds = 60
cooldown_seconds = 300
chat_id = "local"
message = "这是一次主动检查。"
```

开启后，系统会定时通过 MessageBus 向主 agent 投递主动消息，并由现有
AgentLoop 生成回复。CLI 已支持持续消费 outbound，因此主动回复可以自动显示。

更多说明见：

[PROACTIVE_SYSTEM.md](PROACTIVE_SYSTEM.md)

## MCP 系统

第 11 阶段已加入最小 MCP client。默认关闭，可在 `config.toml` 中配置本地
stdio MCP server：

```toml
[mcp]
enabled = true

[[mcp.servers]]
name = "demo"
transport = "stdio"
command = "python"
args = ["path/to/server.py"]
enabled = true
```

MCP 工具会以 `mcp__server__tool` 的名称注册到 `ToolRegistry`，主 agent
可以像调用内置工具一样调用它们。

更多说明见：

[MCP_SYSTEM.md](MCP_SYSTEM.md)
