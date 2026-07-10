# Memoli-agent 项目架构蓝图

本文档记录 Memoli-agent 的早期架构规划及模块职责。

目标不是一开始就复刻全部复杂能力，而是搭出一个可运行、可扩展、边界清晰的 agent 框架。后续可以逐步加入记忆、插件、工具、MCP、子 agent、主动任务等能力。

## 一、整体设计目标

Memoli-agent 建议采用“核心 agent runtime + 可插拔能力”的结构。

核心原则：

1. 消息入口和 agent 推理分离。
2. 工具系统和 LLM 调用分离。
3. 记忆系统独立成服务，不直接写死在 prompt 里。
4. 插件通过生命周期 hook 接入，不随意改核心循环。
5. 子 agent 通过工具调用进入，通过内部事件回流。
6. 主动任务和被动对话并行运行，但共享 session、memory、tools。

推荐主架构：

```text
main.py
  |
  v
bootstrap/AppRuntime
  |
  +-- MessageBus
  +-- AgentLoop
  +-- SessionManager
  +-- ContextBuilder
  +-- LLMProvider
  +-- ToolRegistry
  +-- MemoryRuntime
  +-- PluginManager
  +-- Scheduler
  +-- ProactiveLoop        可后续加入
  +-- SubAgentManager      可后续加入
```

## 二、推荐目录结构

建议从下面结构开始：

```text
Memoli-agent/
  README.md
  docs/
  config.example.toml
  pyproject.toml
  main.py

  memoli_agent/
    __init__.py

    bootstrap/
      __init__.py
      app.py
      config.py
      tools.py
      memory.py
      channels.py

    bus/
      __init__.py
      events.py
      queue.py
      event_bus.py

    agent/
      __init__.py
      loop.py
      runner.py
      context.py
      provider.py
      session.py
      types.py

      core/
        __init__.py
        passive_turn.py
        reasoner.py
        prompt_blocks.py
        response_parser.py

      lifecycle/
        __init__.py
        phase.py
        types.py
        phases.py

      tools/
        __init__.py
        base.py
        registry.py
        builtin.py
        tool_search.py

      memory/
        __init__.py
        runtime.py
        store.py
        retriever.py
        consolidator.py

      plugins/
        __init__.py
        base.py
        manager.py
        decorators.py
        context.py

      subagent/
        __init__.py
        manager.py
        runtime.py
        profiles.py

    channels/
      __init__.py
      cli.py
      ipc.py
      contract.py

    plugins/
      shell_safety/
        plugin.py
      memory_default/
        plugin.py

    skills/
      README.md
```

如果你想更轻一点，可以第一阶段只保留：

```text
main.py
memoli_agent/bootstrap/app.py
memoli_agent/bus/queue.py
memoli_agent/bus/events.py
memoli_agent/agent/loop.py
memoli_agent/agent/context.py
memoli_agent/agent/provider.py
memoli_agent/agent/tools/registry.py
memoli_agent/agent/memory/store.py
memoli_agent/channels/cli.py
```

## 三、核心模块职责

### 1. main.py

职责：

- 解析命令行参数。
- 加载配置。
- 调用 `build_app_runtime()`。
- 启动完整 agent 服务。

不要在 `main.py` 中写推理、工具、记忆逻辑。

推荐命令：

```text
python main.py              启动 agent
python main.py cli          打开 CLI 客户端
python main.py init         初始化 workspace
python main.py inspect      查看 lifecycle 模块
```

### 2. bootstrap/

`bootstrap` 是装配层，负责把各模块连接起来。

建议文件：

| 文件 | 职责 |
| --- | --- |
| `bootstrap/app.py` | 构建 `AppRuntime`，统一启动和关闭所有服务。 |
| `bootstrap/config.py` | 加载 `config.toml`。 |
| `bootstrap/tools.py` | 注册内置工具、插件工具、MCP 工具。 |
| `bootstrap/memory.py` | 构建 memory runtime。 |
| `bootstrap/channels.py` | 启动 CLI、IPC、其他 channel。 |

### 3. bus/

消息总线是 agent 的中心入口。

建议保留两个层次：

```text
MessageBus
  inbound queue
  outbound queue

EventBus
  lifecycle events
  plugin events
```

`MessageBus` 处理对话消息。

`EventBus` 处理观察事件和插件事件。

核心类型：

```python
InboundMessage
OutboundMessage
InternalEvent
```

### 4. agent/loop.py

主 agent loop。

职责：

- 从 `MessageBus` 取消息。
- 根据 `session_key` 找到会话。
- 创建 turn 状态。
- 调用 `Runner` 或 `PassiveTurnPipeline`。
- 将结果写回 `MessageBus`。
- 管理中断和 busy 状态。

简化结构：

```python
class AgentLoop:
    async def run(self):
        while self.running:
            item = await bus.consume_inbound()
            outbound = await self.process(item)
            await bus.publish_outbound(outbound)
```

### 5. agent/core/passive_turn.py

这是主 agent 最重要的文件。

建议把一轮用户消息拆成这些阶段：

```text
BeforeTurn
  -> BeforeReasoning
  -> PromptRender
  -> Reasoner
  -> AfterReasoning
  -> AfterTurn
```

每个阶段只做一类事：

| 阶段 | 职责 |
| --- | --- |
| `BeforeTurn` | 读取 session、历史、记忆检索。 |
| `BeforeReasoning` | 准备工具上下文、技能、额外提示。 |
| `PromptRender` | 构造模型 messages。 |
| `Reasoner` | 调 LLM、执行工具、多轮循环。 |
| `AfterReasoning` | 解析回复、保存会话。 |
| `AfterTurn` | 发布事件、发送 outbound。 |

### 6. agent/core/reasoner.py

Reasoner 负责 LLM 与工具循环。

基本流程：

```text
messages + tool schemas
  -> LLMProvider.chat()
  -> 如果是文本回复，结束
  -> 如果是 tool call，执行工具
  -> tool result 追加回 messages
  -> 再次调用 LLM
```

建议支持：

- 最大迭代次数。
- tool call trace。
- tool error 兜底。
- tool loop guard。
- 空回复 retry。
- 上下文过长 retry。

### 7. agent/context.py

负责组装 prompt。

建议组成：

```text
system prompt
  identity
  behavior rules
  memory block
  tool instructions
  skill instructions

history
context frame
current user message
```

不要让各个模块直接拼 prompt。统一走 `ContextBuilder`。

### 8. agent/provider.py

LLM provider 适配层。

职责：

- 屏蔽不同模型厂商 API 差异。
- 提供统一 `chat()` 接口。
- 解析 tool calls。
- 支持 streaming。
- 处理 retry、超时、上下文过长。

第一版可以只支持 OpenAI-compatible API。

### 9. agent/tools/

工具系统建议分三层：

```text
Tool
ToolRegistry
ToolExecutor
```

`Tool` 是工具协议。

`ToolRegistry` 负责注册、搜索、暴露 schema。

`ToolExecutor` 负责执行前后 hook。

第一批内置工具建议：

- `time`
- `filesystem_read`
- `filesystem_write`
- `memory_recall`
- `memory_write`
- `tool_search`
- `spawn`

### 10. agent/memory/

记忆系统建议先做简单，再逐步增强。

第一版：

```text
workspace/memory/MEMORY.md
workspace/memory/RECENT_CONTEXT.md
workspace/memory/HISTORY.md
```

第二版：

- 加入 SQLite。
- 加入 embedding。
- 加入 query rewrite。
- 加入 dedup。
- 加入 consolidation。

记忆接口建议保持稳定：

```python
class MemoryRuntime:
    async def query(...)
    async def mutate(...)
    def render_prompt_block(...)
```

### 11. agent/plugins/

插件系统是后期可扩展的关键。

插件建议支持：

- 注册工具。
- 注册 lifecycle hook。
- 注册 tool hook。
- 注入 prompt section。
- 提供 channel。

第一版插件接口可以很简单：

```python
class Plugin:
    async def initialize(self, context): ...
    def tools(self) -> list[Tool]: ...
    def before_turn_modules(self) -> list[object]: ...
```

### 12. subagent/

subagent 建议从一开始就按“工具接入 + 内部事件回流”的思路设计。

接入方式：

```text
主 agent 调用 spawn 工具
  -> SubAgentManager 创建子任务
  -> SubAgent 独立执行
  -> 结果包装成 InternalEvent
  -> publish_inbound 回主 MessageBus
  -> 主 agent 总结并回复用户
```

这样做的好处：

- 主 agent 仍是唯一对话出口。
- 长任务不会阻塞主会话。
- 子 agent 权限可控。
- 子任务结果可追踪。

### 13. channels/

通道层只负责消息转换，不负责推理。

建议第一版只做：

- CLI channel
- IPC channel

之后再加：

- Telegram
- QQ
- WebSocket
- API channel

统一协议：

```python
class Channel:
    async def start(...)
    async def stop(...)
    async def send(outbound)
```

## 四、最小可运行版本路线

### 阶段 1：跑通单轮 CLI 对话

目标：

```text
用户输入
  -> AgentLoop
  -> EchoProvider
  -> 输出回复
```

需要文件：

```text
main.py
bus/events.py
bus/queue.py
agent/loop.py
agent/provider.py
channels/cli.py
```

### 阶段 2：加入上下文和历史

目标：

- 支持 session。
- 保存最近 N 轮历史。
- 构造 messages。

新增文件：

```text
agent/session.py
agent/context.py
agent/core/prompt_blocks.py
```

### 阶段 3：加入工具系统

目标：

- 注册工具。
- 让模型调用工具。
- 把工具结果回填给模型。

新增文件：

```text
agent/tools/base.py
agent/tools/registry.py
agent/tools/builtin.py
agent/core/reasoner.py
```

### 阶段 4：加入记忆系统

目标：

- 写入长期记忆。
- 检索长期记忆。
- 注入 prompt。

新增文件：

```text
agent/memory/store.py
agent/memory/runtime.py
agent/memory/consolidator.py
```

### 阶段 5：加入 lifecycle 和插件

目标：

- 不改核心代码也能扩展行为。
- 插件可以挂 before_turn、after_turn、tool_hook。

新增文件：

```text
agent/lifecycle/phase.py
agent/lifecycle/types.py
agent/plugins/manager.py
agent/plugins/decorators.py
```

### 阶段 6：加入 subagent

目标：

- 主 agent 可委派复杂任务。
- 子 agent 完成后结果回流主 agent。

新增文件：

```text
agent/subagent/manager.py
agent/subagent/runtime.py
agent/tools/spawn.py
```

### 阶段 7：加入 proactive

目标：

- agent 不只被动回复，也能主动检查任务和信息源。

新增文件：

```text
agent/proactive/loop.py
agent/proactive/sensor.py
agent/proactive/decision.py
```

## 五、主 agent 与 subagent 的推荐关系

不要让 subagent 直接发消息给用户。

推荐方式：

```text
SubAgent 完成任务
  -> 生成 SubAgentCompletionEvent
  -> 投回 MessageBus inbound
  -> 主 AgentLoop 消费
  -> 主 agent 总结
  -> 主 agent 发送最终回复
```

这样主 agent 永远保持对话上下文和回复风格的一致性。

## 六、配置文件建议

`config.example.toml` 可以这样设计：

```toml
[llm]
provider = "openai-compatible"
model = "gpt-4.1-mini"
api_key = ""
base_url = ""

[agent]
name = "Memoli"
max_iterations = 8
history_window = 20

[memory]
enabled = true
engine = "markdown"
path = "workspace/memory"

[tools]
tool_search_enabled = true

[channels.cli]
enabled = true

[plugins]
enabled = ["memory_default", "shell_safety"]
```

## 七、建议优先实现的核心类

```python
class AppRuntime:
    async def start(self): ...
    async def run(self): ...
    async def shutdown(self): ...

class MessageBus:
    async def publish_inbound(self, item): ...
    async def consume_inbound(self): ...
    async def publish_outbound(self, item): ...

class AgentLoop:
    async def run(self): ...
    async def process(self, item): ...

class ContextBuilder:
    def render(self, request): ...

class LLMProvider:
    async def chat(self, messages, tools): ...

class ToolRegistry:
    def register(self, tool): ...
    def get_schemas(self): ...
    async def execute(self, name, args): ...

class MemoryRuntime:
    async def query(self, request): ...
    async def mutate(self, request): ...

class PluginManager:
    async def load_all(self): ...
```

## 八、不要一开始就做的事情

建议先不要做：

- 复杂 Dashboard。
- 多模型自动路由。
- 超复杂向量记忆。
- 多平台 channel。
- 完整 MCP 生态。
- 复杂权限系统。
- 多 agent 群组协作。

这些都应该在主链路稳定后再加。

## 九、第一版验收标准

第一版 Memoli-agent 可以这样验收：

1. `python main.py` 能启动 CLI。
2. 用户输入后能得到 LLM 回复。
3. 能保存 session 历史。
4. 能注册并调用至少 3 个工具。
5. 能写入和读取长期记忆。
6. 能通过插件增加一个 before_turn 行为。
7. 能通过 spawn 启动一个简单 subagent。
8. subagent 结果能回流主 agent。

## 十、推荐开发顺序

最推荐的实现顺序：

1. `bus`
2. `config`
3. `provider`
4. `agent loop`
5. `context`
6. `tools`
7. `memory`
8. `lifecycle`
9. `plugins`
10. `subagent`
11. `proactive`
12. `MCP / peer agent`

这个顺序能保证每一步都有可运行结果，不会一开始就陷入大系统泥潭。

## 十一、和 demo-akashic 的对应关系

| Memoli-agent 规划模块 | demo-akashic 对应目录 |
| --- | --- |
| `bootstrap/app.py` | `demo-akashic/bootstrap/app.py` |
| `bus/queue.py` | `demo-akashic/bus/queue.py` |
| `agent/loop.py` | `demo-akashic/agent/looping/core.py` |
| `agent/core/passive_turn.py` | `demo-akashic/agent/core/passive_turn.py` |
| `agent/context.py` | `demo-akashic/agent/context.py` |
| `agent/tools/registry.py` | `demo-akashic/agent/tools/registry.py` |
| `agent/memory/*` | `demo-akashic/core/memory/*`、`memory2/*` |
| `agent/plugins/*` | `demo-akashic/agent/plugins/*` |
| `agent/subagent/*` | `demo-akashic/agent/background/*`、`agent/subagent.py` |
| `agent/proactive/*` | `demo-akashic/proactive_v2/*` |

## 十二、总结

Memoli-agent 的推荐核心框架是：

```text
AppRuntime 负责装配，
MessageBus 负责消息，
AgentLoop 负责主循环，
PassiveTurnPipeline 负责一轮对话，
Reasoner 负责 LLM 和工具循环，
ContextBuilder 负责 prompt，
ToolRegistry 负责能力调用，
MemoryRuntime 负责记忆，
PluginManager 负责扩展，
SubAgentManager 负责任务委派。
```

先做小而清晰的可运行核心，再逐步把 demo-akashic 中的成熟能力搬过来，是最稳的路线。
