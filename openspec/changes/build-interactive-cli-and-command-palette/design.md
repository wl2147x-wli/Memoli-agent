## Context

Memoli 当前已经有 `memoli`/`memoli chat` 入口、plain CLI、本地斜杠路由、`PresentationEventHub`、`RuntimeInspector` 和工作状态 presenter。该实现适合作为无额外依赖的功能基线，但输入使用阻塞 `input()`，命令只有按下回车后才可识别；输出由多个异步任务直接调用 writer，难以稳定维护提示符、活动流、工具状态和终端重绘。`LLMConfig.stream` 默认值为 false，因此未显式配置的正式 Provider 也不会产生文本增量。

GenericAgent 的完整 TUI 已证明命令 palette、流式活动区、状态栏和工具折叠的价值，但其自定义输入、布局与多页面逻辑远超 Memoli 当前需求。Hermes 的中心命令注册表、prompt toolkit completer 和 ghost suggestion 更适合借鉴。此 change 要在保持单 Runtime、单 CLI、串行主 Agent 的前提下形成一个独立、可测试、可降级的交互表现层。

主要约束：

- Windows PowerShell/Windows Terminal 与常见 Unix TTY 都必须工作，中文宽字符不得破坏布局。
- CLI 观察事件不能反压 Agent，不得显示隐藏 reasoning、原始工具参数或秘密。
- 非 TTY、测试输入和脚本管道继续使用 plain CLI，不输出 ANSI 控制序列。
- 当前 Session、Memory、Skill、轨迹和 Working State 持久化合同保持不变。
- 首版不支持在线切换 workspace/model 等 Runtime 安全边界。

## Goals / Non-Goals

**Goals:**

- 使用一个中心命令注册表同时驱动执行、帮助、候选面板、别名和测试。
- 输入 `/` 即可看到命令，支持实时过滤、方向键、Tab/Enter、Esc、ghost suggestion、历史和多行编辑。
- 在终端活动区安全流式显示文本与工具阶段，并把最终消息一次提交到终端 scrollback。
- 用单一 renderer 串行管理所有终端状态，限制刷新频率并在 resize 后可靠重绘。
- 默认启用交互式模型 streaming，保持显式关闭和 plain/non-stream 行为。
- 支持 `/stop` 取消当前 turn 后继续聊天，并保持后续排队消息的串行关联。
- 提供模型、workspace、工具、记忆、Skill、checkpoint、trace 等只读检查入口。

**Non-Goals:**

- 不实现宠物、角色动画、桌面悬浮窗或情绪状态。
- 不实现 Textual 全屏多页面、GUI、Web、daemon、IPC 或多客户端。
- 不实现运行中热切换 workspace、Provider、模型、工具授权或持久化配置。
- 不持久化 prompt_toolkit 输入历史；首版历史只存在于当前进程和 session。
- 不展示 chain-of-thought、工具原始参数、完整工具输出或未脱敏异常。
- 不把 CLI presentation event 写成新的权威轨迹或业务事件源。

## Decisions

### 1. 使用 prompt_toolkit + Rich，但保留 PlainCLI Adapter

`prompt_toolkit` 负责异步逐键输入、Buffer、Completion、Key Binding、Unicode 宽度和终端 resize；Rich 只负责已完成 Markdown 块、表格和样式渲染。交互 frontend 在 TTY 且初始化成功时启用，否则使用现有 plain frontend。

```text
ChannelRunner
  ├─ InteractiveCLIAdapter  # prompt_toolkit + Rich
  └─ PlainCLIAdapter        # input/print，管道与测试
             │
             └─ shared CommandRegistry / RuntimeInspector / MessageBus
```

选择 prompt_toolkit 而不是 Textual，是因为当前只需要单消息区、活动区、输入框、palette 和状态栏；Textual 会引入更完整的 Widget 生命周期和页面系统。选择成熟输入库而不是复制 GenericAgent 的自定义键盘扫描器，是为了减少 Windows 转义序列、IME、粘贴和 resize 的维护成本。

配置新增：

```toml
[channels.cli]
enabled = true
interactive = true
color = "auto"          # auto / always / never
refresh_hz = 12
queue_limit = 8
max_tool_rows = 6
```

`interactive=false` 强制 plain CLI；`auto` 颜色依据 TTY/NO_COLOR。所有值必须有界校验。

### 2. CommandRegistry 是唯一命令事实源

定义不可变 `CommandSpec`，至少包含 `name`、`aliases`、`category`、`description`、`args_hint`、`availability` 和异步 handler。Registry 构造时规范化名称并拒绝冲突。Router 不再维护 `if` 链，help/completer 也不再复制命令列表。

```text
CommandRegistry
  ├─ resolve(text) -> ParsedCommand
  ├─ visible(context) -> CommandSpec[]
  ├─ help(context)
  └─ complete(prefix, context)
```

命令按稳定类别和显式 registration order 排序。Completer 生成带 `display_meta` 的 prompt_toolkit `Completion`；AutoSuggest 为 slash 命令提供最短优先 ghost text，为普通输入委托进程内 history suggestion。

首版注册：现有 `/help`、`/status`、`/checkpoint`、`/working`、`/trace`、`/clear`、`/exit`、`/quit`，以及 `/stop`、`/workspace`、`/model`、`/tools`、`/memory`、`/skills`。检查类命令无参数时读取 Inspector；收到变更参数时返回 `memoli --workspace` 或 `config.toml` 指引，而不是修改已装配组件。

备选方案是在 UI 内保存一份候选列表；这会再次制造帮助、执行与补全不一致，因此拒绝。

### 3. 使用“已提交 scrollback + 可重绘 live region”的混合终端布局

交互式 Application 使用 `full_screen=False`，避免占用 alternate screen。已完成的用户消息、最终助手消息和工具摘要通过单一 renderer 一次提交到正常终端 scrollback；尚未完成的文本、工具状态、候选面板、输入框和状态栏保存在可重绘 live region。

```text
terminal scrollback (immutable)
  用户消息
  已完成助手 Markdown
  已完成工具摘要

prompt_toolkit live region (mutable)
  当前文本增量
  活动工具状态
  slash palette
  input buffer
  status bar
```

这样流式期间可以安全处理不完整 Markdown，完成时先清空 live response，再使用 Rich 将完整最终内容提交一次，不会重复答案。Plain renderer 则继续直接按文本增量/最终 Outbound 去重。

所有 UI mutation 都进入 `TerminalRenderer` 的单 asyncio queue，由一个 render task 更新 `RenderState`。事件到达只设置 dirty flag；ticker 按 `refresh_hz` 最多约 12 FPS invalidate，从而避免每 token 完整重排。文本数据仍逐事件按序追加，不因合帧丢失。

### 4. 扩展 PresentationEvent 为安全投影，而非暴露 Provider 事件

事件合同采用枚举 payload，并携带 `session_key`、`trace_id`、`turn_id`、`step_id`、时间和有限安全字段。首版事件：

- `TURN_STARTED`
- `MODEL_STARTED`
- `TEXT_DELTA`
- `TOOL_STARTED`
- `TOOL_FINISHED`
- `USAGE_UPDATED`
- `CHECKPOINT_CHANGED`
- `TURN_COMPLETED`
- `TURN_FAILED`
- `TURN_CANCELLED`

Reasoner/Tool runtime 在来源处完成安全投影：thinking/reasoning 不产生文本事件，工具参数 delta 不进入 presentation queue，工具结果只投影枚举状态、稳定工具名和耗时。Renderer 不应成为最后一道脱密边界，但仍防御性限制长度与控制字符。

队列保持有界。连续 `TEXT_DELTA` 可在同一 turn/step 内合并；usage 与状态栏事件保留最新值；最终状态事件优先于可降级进度。Observer 失败不改变回答、轨迹和工具执行。

备选方案是把 trajectory events 直接给 UI；轨迹 payload 更详细、写入时机与 UI 时机不同，也可能包含本地敏感证据，因此拒绝。

### 5. 交互式正式 Provider 默认 streaming，配置仍可关闭

将 `LLMConfig.stream` 与示例配置默认改为 true。Reasoner 继续通过统一 Provider contract 请求 streaming，Provider Adapter 规范化 SSE。用户设置 `llm.stream=false` 时完全使用现有非流式路径。Echo/测试 Provider 可以不产生增量，Renderer 依靠最终 Outbound 正常工作。

如果流在任何用户可见/工具增量之前失败，现有有界重试或兼容 fallback 仍可生效；产生部分增量后失败则标识 `partial_stream`，不得切换 Provider 拼接两个模型的响应。CLI 清除未完成 live block，显示安全错误分类。

不采用“CLI 收到完整回复后自己切字模拟流式”，因为它掩盖 Provider 延迟，也不提供真实执行进度。

### 6. `/stop` 取消 per-turn task，不取消 AgentLoop 消息泵

AgentLoop 的消息泵仍串行消费队列，但每条消息在一个被 await 的 `current_turn_task` 中处理，并通过只暴露 `is_busy`、`queue_depth`、`cancel_current_turn()` 的 `TurnController` 供 CLI 使用。

```text
message pump
  consume message
  current_turn_task = create_task(handle(message))
  await current_turn_task        <── /stop 只 cancel 这里
  finalize trace/cancel outbound
  consume next message
```

用户取消映射为 turn outcome `cancelled/user-cancelled`，关闭 Provider stream并停止后续工具/模型步骤。Runtime shutdown 对消息泵本身的取消仍向上传播，两者不可混淆。已经发生且无法撤销的工具副作用只报告事实，不宣称回滚。

普通输入在 busy 时仍进入 MessageBus，但 CLI 通过 `queue_limit` 限制本地未处理提交数；达到上限时拒绝新输入并提示等待/停止，而不是形成无界内存队列。`/stop`、`/status`、`/trace` 等允许 busy 执行的本地命令不进入该队列。

### 7. RuntimeInspector 扩展为显式只读视图

Inspector 新增稳定结构化视图：

- provider/model/streaming 状态
- workspace/session 与 turn busy/queue depth
- 已注册工具名及 available/unavailable 原因
- Memory/Embedding/Consolidation 开关
- Skill runtime 状态与当前 session catalog 摘要
- Working snapshot 与 last trace

这些视图返回 presentation DTO，不暴露 AppRuntime、Provider client、Registry 可变引用或数据库连接。字段值先在 Inspector 层限长与脱敏，再交给命令 renderer。

### 8. 键位与退出语义保持可预测

- Enter：提交单行或接受完整命令。
- Alt+Enter（并兼容可配置 Esc+Enter）：插入换行。
- Tab：候选可见时补全；否则不插入不可见控制字符。
- Up/Down：候选可见时选择，否则浏览历史/移动多行光标。
- Esc：关闭 palette 或取消当前选择，不退出程序。
- Ctrl+C：活动 turn 时请求 `/stop`；idle 时清空当前输入，连续第二次才退出可留后续扩展，首版不直接关闭 Runtime。
- Ctrl+D：空 buffer 时正常退出；非空时不吞掉内容。

Windows 启动时继续使用 UTF-8，并依赖 prompt_toolkit 的平台输入实现，不自行修改全局键盘表。终端输出对 ANSI 控制字符做过滤，`NO_COLOR` 与 `color=never` 禁用样式。

## Risks / Trade-offs

- [prompt_toolkit 与 Rich 同时写 stdout 导致画面漂移] → 只有 TerminalRenderer 可写终端，Rich 先渲染到 buffer，再由 prompt_toolkit 的安全终端边界提交。
- [不完整 Markdown 在 streaming 中闪烁或误排版] → live region 使用安全纯文本，最终完成后才做 Rich Markdown 渲染。
- [高频 token 导致 O(n²) 重绘] → delta 只追加 buffer，按 dirty flag 和有界帧率重绘；为 live text 设置最大显示窗口但保留最终 Outbound。
- [UI queue 满导致完成状态丢失] → 文本/usage 可合并，终止事件使用保留槽或直接唤醒；最终 Outbound 仍是权威兜底。
- [Ctrl+C 取消边界与 Runtime shutdown 混淆] → 分离 per-turn task 和 message-pump task，并对两种取消建立独立测试。
- [工具在取消前已产生副作用] → 轨迹记录实际状态，CLI 不承诺回滚，只阻止后续步骤。
- [默认 streaming 暴露兼容服务的 SSE 缺陷] → 保留 `llm.stream=false` 回退开关，错误中明确提示；不在部分流之后静默 fallback。
- [状态栏泄漏本地路径或配置] → workspace 只显示配置允许的规范化摘要，所有错误与动态值限长脱敏。
- [功能继续膨胀为完整 TUI] → 首版固定单 scrollback/live/input/status 布局，不引入页面路由、侧栏、鼠标系统或宠物。

## Migration Plan

1. 先固化现有 plain CLI、命令语义、流式 Provider 和取消行为的回归基线。
2. 添加依赖、CLI 配置和 CommandRegistry，先让 plain frontend 复用 Registry，确保行为不回归。
3. 扩展 PresentationEvent/TurnController/RuntimeInspector，并通过无 UI 的 reducer 测试事件顺序、安全过滤和取消。
4. 实现 InteractiveCLIAdapter、live region 与 renderer，TTY 自动选择但保留 `interactive=false` 强制降级。
5. 将 streaming 默认改为 true，更新示例配置和兼容说明，完成 OpenAI-compatible 与 Anthropic 的流式集成测试。
6. 更新 README/Runtime 文档并完成 Windows、Unicode、resize、非 TTY 和真实终端手工验收。

回滚时可设置 `[channels.cli] interactive=false` 和 `llm.stream=false` 恢复 plain/non-stream 行为；数据库没有 migration。若必须代码回滚，可移除 Interactive adapter 和新增依赖，CommandRegistry/安全事件 DTO 不改变持久数据。

## Open Questions

- 首版输入历史确定为仅进程内；如未来要跨启动保存，应另建带权限、清理和敏感数据策略的 change。
- `/model` 与 `/workspace` 首版只读；安全的在线 Runtime 重建、Session handoff 和配置落盘需要独立设计。
- `@file` completion 有价值，但会引入 workspace 索引和路径授权语义，本 change 暂不要求，后续可基于 Tool workspace policy 单独扩展。
