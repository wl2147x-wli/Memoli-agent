## Context

Memoli 已有由 `main.py`、`AppRuntime`、最小 CLI channel、`MessageBus` 和 `AgentLoop` 组成的前台对话闭环，但入口依赖当前仓库位置，CLI 只识别退出命令，且通道只能拿到消息总线，无法只读检查 Runtime、Session 和工作状态。工作 checkpoint 已按 `session_key` 持久化到 `working-state.db`，Runtime 硬状态保存在 `WorkingStateStore` 的进程内投影中；当前 `render_status()` 面向模型上下文输出 XML，不适合作为稳定 UI 合同。

本 change 仍保持单 Runtime、单 CLI、主 turn 串行执行。它要形成可安装的第一版用户入口，同时建立足够小的状态展示边界，以便后续 TUI、Web UI 和桌宠复用，而不在当前阶段引入 daemon 或网络协议。

## Goals / Non-Goals

**Goals:**

- 使 `memoli` 成为安装后的默认前台聊天命令，并使 `memoli chat` 与旧 `python main.py` 复用同一实现。
- 提供稳定的参数解析、启动摘要、本地命令、最终回复、trace 展示和有序关闭体验。
- 让 `/checkpoint`、`/working` 和 `memoli checkpoint` 读取真实已提交 checkpoint，而不是让模型复述或猜测。
- 在展示合同中严格区分 Agent 语义 checkpoint 与 Runtime 硬状态。
- 保持纯文本、低依赖、单并发，并为未来表现层预留结构化快照与事件边界。

**Non-Goals:**

- 不实现常驻服务、IPC、HTTP/WebSocket、多客户端或桌面 UI。
- 不实现聊天 Session 的 SQLite 持久化或多会话管理页面。
- 不增加 checkpoint 自动生成频率、不评价 checkpoint 正确性、不写长期 Memory Card。
- 不允许本地 checkpoint 查询修改工作状态。
- 不在首版实现可跨进程取消后继续聊天；键盘中断用于有序结束前台 Runtime。

## Decisions

### 1. 使用标准库命令入口，`memoli` 默认进入 chat

在 `pyproject.toml` 注册 `memoli = "memoli_agent.cli:main"`，由同步 `main()` 使用 `argparse` 解析参数，再在需要启动 Runtime 时进入唯一 `asyncio.run()`。无子命令等价于 `chat`，使最常见路径保持 `memoli` 一个命令；`checkpoint`、`--help` 和 `--version` 不构建 AppRuntime。

`main.py` 只委托同一入口的兼容 chat 路径，不复制配置、生命周期或异常处理。`memoli-skills` 保持独立不变。

备选方案是 Typer/Click。它们能减少命令样板，但会为首版 CLI 增加运行依赖；当前命令树较小，标准库足够，并更符合轻量目标。

### 2. 参数覆盖先于 Runtime 装配，并保持路径语义明确

CLI 先加载 `--config` 指定的 TOML，再应用 `--workspace` 和 `--session`。`--session <id>` 只接受本地 chat id，运行时 session key 规范化为 `cli:<id>`；默认值为 `cli:local`。`--workspace` 覆盖 `runtime.workspace`，但不改写配置中显式声明的绝对数据库或 artifact 路径；相对受管路径继续按现有配置解析规则处理。

配置、参数或路径校验失败时，在任何 Provider、插件、MCP 或 AgentLoop 启动前返回。启动摘要只展示版本、Provider/模型标识、workspace、session 和功能开关，不展示 API Key、Header、Cookie，也不直接展示可能含查询秘密的 URL。

### 3. 本地命令在 Channel 边界截获

CLI 输入先经过 `CLICommandRouter`：

```text
terminal input
      |
      +-- /command --> CLICommandContext --> local rendering
      |
      +-- ordinary --> InboundMessage --> MessageBus --> AgentLoop
```

本地命令不构造 InboundMessage，因此不会调用 LLM、污染 Session 历史或创建被动 turn 轨迹。未知单斜杠命令直接报错；`//text` 去掉一个 `/` 后作为普通输入，保留向模型发送字面 slash 内容的能力。

`CLICommandContext` 只暴露最小能力：只读 `RuntimeInspector`、当前 session、清理当前内存 Session 的显式操作和 CLI 自己维护的 last trace。它不把完整 `AppRuntime`、Provider、ToolRegistry 或 SQLite connection 交给命令路由器。

### 4. 增加结构化工作状态快照，不复用模型 XML

新增带版本的 `WorkingStateSnapshot` 表示：

```text
WorkingStateSnapshot
  schema_version
  session_key
  availability
  checkpoint        # trust = agent
  runtime_status    # trust = runtime
  truncated / omitted fields
```

`WorkingStateStore` 提供原子只读 snapshot；终端 presenter 从结构化字段生成人类可读卡片，JSON presenter 生成确定性对象。两者不得解析 `render_status()` 的 `<agent_status>`/`<working_checkpoint>` XML，因为该文本受模型上下文预算约束且不是公共 UI API。

checkpoint 不存在时返回 `not-found`，工作记忆关闭时返回 `disabled`，存储或 schema 故障返回 `error`；不会调用模型补全。stale 和 completed 仅被展示，查询不会调用 `restore()`、`patch()` 或产生新 revision。

### 5. 在线与离线 checkpoint 查询共享 presenter，但使用不同 reader

聊天内 `/checkpoint` 使用 AppRuntime 中现有 `WorkingStateStore`，因此可同时显示持久 checkpoint 和进程内 Runtime 硬状态。

`memoli checkpoint` 不启动 AppRuntime。它加载有效配置后，以只读 SQLite 连接打开已有工作状态数据库，只读取最近已提交 revision；数据库不存在时不创建文件，未知 schema 时不重建。离线模式没有可信的当前 Runtime 投影，因此 `runtime_status` 标识为 unavailable。

约定退出码：找到 checkpoint 为 `0`，参数/配置错误为 `2`，not-found 或 disabled 为 `3`，不可恢复的存储错误为 `1`。`--json` 时 stdout 只输出一个 schema-versioned JSON 对象，诊断写 stderr，避免破坏脚本解析。

备选方案是让 `memoli checkpoint` 直接创建 `WorkingStateRepository`。当前构造器会创建目录和 schema，不满足非变更查询要求，因此采用专用只读 reader 或显式 read-only 打开模式。

### 6. 保持现有串行 MessageBus，并增加有界表现事件

本 change 不把 MessageBus 改造成多客户端发布订阅系统。普通消息继续进入现有单队列，CLI 可在输入侧继续接收并排队，AgentLoop 仍一次处理一个主 turn。

为终端进度建立进程内、观察者性质的 presentation event 边界。事件至少携带 session key、trace id、阶段和有界安全文本；Provider 的 thinking delta 和工具参数 delta 不进入终端。模型步骤如果进入工具轮次，其文本只能标识为临时模型步骤；最终 Outbound 才是权威用户回复。CLI 按已显示前缀去重最终内容，并以 Outbound metadata 更新 last trace。

Observer/presenter 故障不得改变 Agent 回答或工具执行；队列和单事件内容必须有界。未来 UI Gateway 可以替换该观察者，而不用修改 Provider 合同。

### 7. `/clear` 只清理当前内存对话历史

为 `SessionManager` 增加按 session key 清理当前进程历史的显式能力。`/clear` 不删除 working checkpoint、长期记忆、Skill binding、SubAgent 记录或轨迹，也不直接删除 SQLite 文件。该边界在提示文本和测试中固定，避免用户误认为它是隐私数据擦除命令。

### 8. 生命周期由 CLI 统一拥有

chat 命令负责 `build -> start -> run channel -> shutdown`，并保证构建后任一阶段失败都执行已创建资源的有界清理。`/exit`、`/quit`、EOF 正常退出；键盘中断传播取消语义并走 shutdown，不生成普通助手错误。单轮结构化错误只影响该轮，CLI 继续读取后续消息。

## Risks / Trade-offs

- [Streamed model text可能属于后续工具轮次] → 通过高层 presentation event 标识临时步骤，隐藏 thinking 和参数，并仅把最终 Outbound 当作权威回答。
- [CLI 与 Agent 输出并发导致提示符错位] → 所有终端写入经过单一 renderer/锁，输入恢复时重绘提示符；测试输出顺序和非交互 stdin。
- [离线 reader 与在线写事务竞争] → 使用只读连接读取完整已提交 revision；遇到 busy 返回可重试错误，不读取部分状态。
- [checkpoint 含用户敏感任务内容] → 仅响应本地显式查询，不写普通 turn 轨迹或日志；远程展示授权留给未来 Gateway change。
- [`/clear` 被误解为彻底删除] → 命令反馈明确列出未删除的 checkpoint、长期记忆和轨迹，并在帮助中避免使用“清除全部数据”。
- [过早抽象 UI 事件系统] → 首版只定义 CLI 所需的最小有界事件，不实现网络协议、多订阅持久化或通用前端框架。

## Migration Plan

1. 添加新的 console script 和统一 CLI 模块，保留 `main.py` 兼容委托。
2. 引入 snapshot/read-only inspector 与 presenter，不修改 `working-state.db` schema。
3. 接入本地命令路由和 Session 清理，再接入安全表现事件与输出去重。
4. 更新 README/启动文档，以 `memoli` 为推荐命令，同时记录 `python main.py` 兼容方式。
5. 若发布后需回滚，可移除 `memoli` console script 和新 CLI 模块并恢复旧 `main.py`；数据库无迁移，因此无需回滚用户数据。

## Open Questions

- 当前无阻塞问题。未来 daemon/UI change 需要重新定义多客户端事件路由和 Runtime 所有权，本 change 不预先固定网络协议。
