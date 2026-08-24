# Interactive CLI Specification

## Purpose

定义 Memoli 增强终端、plain 降级、命令面板、流式表现、只读检查和当前 turn 取消的用户可见行为与安全边界。

## Requirements

### Requirement: Interactive terminal with deterministic fallback

系统 SHALL 在交互式 TTY 中提供增强 CLI，并 SHALL 在 stdin/stdout 非 TTY、终端能力不足或增强输入初始化失败时使用行为兼容的纯文本模式；两种模式 SHALL 共享本地命令、消息提交、串行排队、取消和最终结果语义，plain 模式 SHALL 仅降级终端表现能力。

#### Scenario: Interactive terminal is available

- **WHEN** 用户在支持的 TTY 中执行 `memoli` 或 `memoli chat`
- **THEN** 系统 SHALL 启动支持逐键输入、补全和安全异步重绘的交互式终端
- **AND** SHALL 保持现有 Runtime、session key 和串行 Agent Loop 语义

#### Scenario: Input is piped or redirected

- **WHEN** stdin 或 stdout 不是 TTY
- **THEN** 系统 SHALL 自动使用 plain CLI 并按输入顺序输出最终回复
- **AND** SHALL NOT 输出光标控制序列、候选面板或交互动画

#### Scenario: Enhanced terminal initialization fails

- **WHEN** prompt toolkit、终端模式或颜色能力无法安全初始化
- **THEN** 系统 SHALL 输出有界诊断并降级到 plain CLI
- **AND** SHALL NOT 因表现层故障阻止 Agent Runtime 启动

#### Scenario: Same command is submitted in either terminal mode

- **WHEN** 用户在 interactive 或 plain 模式提交同一个本地命令
- **THEN** 系统 SHALL 使用同一命令定义、可用性判断和只读 Runtime 投影
- **AND** SHALL NOT 因终端模式不同而调用 LLM、写入普通 Session 或产生被动 turn 轨迹

#### Scenario: Same prompt is submitted in either terminal mode

- **WHEN** interactive 或 plain 模式接受相同普通提示
- **THEN** 系统 SHALL 通过同一有界提交边界发布一条 InboundMessage
- **AND** 最终 Outbound、trace 关联、排队顺序和错误分类 SHALL 保持等价

### Requirement: Single-source local command registry

CLI SHALL 使用统一命令注册表定义命令名称、别名、分类、说明、参数提示、可用状态和 handler，并 SHALL 从该注册表生成路由、帮助和补全信息。

#### Scenario: Registered command is invoked

- **WHEN** 用户提交已注册命令或其别名
- **THEN** CLI SHALL 使用同一个规范化 Command 定义执行对应 handler
- **AND** `/help`、命令面板和执行结果中的名称与参数说明 SHALL 保持一致

#### Scenario: Duplicate command or alias is registered

- **WHEN** 两个命令声明相同的规范名称或别名
- **THEN** CLI SHALL 在启动交互前拒绝该注册表
- **AND** SHALL 报告冲突的非敏感命令标识而不采用后注册覆盖

#### Scenario: Command is unavailable in current state

- **WHEN** 用户选择一个需要活动 turn、已启用组件或交互式 TTY 的命令，但前置条件不满足
- **THEN** CLI SHALL 返回明确的 unavailable 原因
- **AND** SHALL NOT 将该命令回退发送给模型

### Requirement: Live slash command palette and completion

交互式 CLI SHALL 在当前输入为单行 slash 前缀时实时展示匹配命令，并支持键盘导航和补全，而不等待用户先提交输入。

#### Scenario: User types slash

- **WHEN** 空输入缓冲区中键入 `/`
- **THEN** CLI SHALL 展示当前可用命令的有界候选列表、说明和参数提示
- **AND** 候选 SHALL 按稳定的分类与命令顺序呈现

#### Scenario: User narrows command prefix

- **WHEN** 用户继续输入 `/st`
- **THEN** CLI SHALL 实时过滤到以该前缀匹配的命令或别名
- **AND** SHALL NOT 执行命令或向 MessageBus 发布消息

#### Scenario: User navigates and accepts completion

- **WHEN** 候选面板可见且用户使用上下键、Tab 或 Enter
- **THEN** 上下键 SHALL 移动高亮，Tab SHALL 补全命令，Enter SHALL 补全或提交当前完整命令
- **AND** Esc SHALL 关闭候选但保留可编辑输入

#### Scenario: Command prefix has one likely completion

- **WHEN** 用户输入未完整的唯一或最短优先命令前缀
- **THEN** CLI SHALL 可显示不改变缓冲区的 ghost suggestion
- **AND** 普通非 slash 输入 SHALL 继续使用会话历史建议而不是命令建议

### Requirement: Productive and safe prompt editing

交互式输入 SHALL 支持本地历史、多行编辑、光标移动和 Unicode 文本，并 SHALL 使空白输入和本地命令继续绕过 Agent turn。

#### Scenario: User edits a multiline prompt

- **WHEN** 用户输入包含换行的长提示
- **THEN** CLI SHALL 保持可见光标、中文宽字符和换行布局正确
- **AND** SHALL 只在显式提交键位触发一次普通 InboundMessage

#### Scenario: User recalls prompt history

- **WHEN** 用户在命令面板未占用方向键时浏览历史
- **THEN** CLI SHALL 按当前本地 session 提供最近提示历史
- **AND** SHALL NOT 将 API Key、隐藏工具参数或内部表现事件加入输入历史

#### Scenario: Empty input is submitted

- **WHEN** 用户提交空白输入
- **THEN** CLI SHALL 忽略输入并保持交互界面可用
- **AND** SHALL NOT 创建 Session 消息、模型请求或轨迹

### Requirement: Serialized streaming terminal renderer

CLI SHALL 通过单一 renderer 消费安全表现事件并更新终端，按顺序展示最终文本增量，限制刷新频率，并在权威 Outbound 到达时避免重复内容。

#### Scenario: Provider streams final text

- **WHEN** 当前模型步骤产生最终用户可见文本增量
- **THEN** renderer SHALL 按事件顺序逐步显示文本并周期性刷新
- **AND** 最终 Outbound SHALL 只补充尚未显示的尾部并关联 trace

#### Scenario: Streaming is disabled

- **WHEN** 用户显式配置 `llm.stream = false` 或 Provider 不产生文本增量
- **THEN** CLI SHALL 在 Outbound 完成后显示一次完整最终回复
- **AND** 其他命令、状态栏和错误行为 SHALL 保持一致

#### Scenario: Terminal is resized during streaming

- **WHEN** 文本仍在生成且终端宽度发生变化
- **THEN** renderer SHALL 在新宽度下重绘活动区域并保持已提交消息可读
- **AND** SHALL NOT 重复提交消息或重新执行 Agent turn

#### Scenario: Render updates arrive too quickly

- **WHEN** Provider 在短时间内产生大量细粒度事件
- **THEN** renderer SHALL 合并刷新到配置的有界帧率并保留文本顺序
- **AND** SHALL NOT 对 Provider 或 Agent Loop 施加无界反压

### Requirement: Bounded status bar and tool progress

交互式 CLI SHALL 使用非敏感 Runtime 投影展示当前模型、session、workspace、turn 状态、iteration、耗时与工作状态可用性，并 SHALL 将工具进度与最终回答区分。

#### Scenario: Turn is running

- **WHEN** Agent 正在等待模型或执行工具
- **THEN** 状态栏 SHALL 显示当前阶段、累计耗时和可用的 iteration 信息
- **AND** 工具卡片 SHALL 至多展示安全工具名、状态和有界耗时

#### Scenario: Tool finishes

- **WHEN** 工具成功、失败、被拒绝或超时
- **THEN** CLI SHALL 更新同一工具步骤的状态而不是追加无界重复日志
- **AND** SHALL NOT 展示原始参数、完整输出、宿主路径秘密或异常详情

#### Scenario: Runtime field is unavailable

- **WHEN** usage、checkpoint 或其他 Runtime 投影不可用
- **THEN** 状态栏 SHALL 显示 unavailable 或省略该字段
- **AND** SHALL NOT 使用模型文本猜测硬状态

### Requirement: Inspectable CLI component commands

命令注册表 SHALL 至少包含现有本地命令以及 `/stop`、`/workspace`、`/model`、`/tools`、`/memory` 和 `/skills`，并 SHALL 对检查类命令保持只读。

#### Scenario: User inspects configured components

- **WHEN** 用户执行 `/workspace`、`/model`、`/tools`、`/memory` 或 `/skills`
- **THEN** CLI SHALL 直接展示当前 RuntimeInspector 可验证的非敏感摘要
- **AND** SHALL NOT 调用 LLM、修改配置、重建 Runtime 或创建普通 turn 轨迹

#### Scenario: User passes a mutation argument to an inspection command

- **WHEN** 用户尝试用首版只读命令切换 workspace、模型或组件开关
- **THEN** CLI SHALL 拒绝在线变更并给出对应启动参数或配置文件指引
- **AND** 当前 Runtime 安全边界 SHALL 保持不变

### Requirement: Current-turn stop and serial input queue

交互式 CLI SHALL 允许用户停止当前活动 turn 而不关闭前台 Runtime，并 SHALL 继续按接收顺序串行处理有界排队输入。

#### Scenario: User stops an active turn

- **WHEN** 当前 turn 正在运行且用户执行 `/stop` 或对应取消键位
- **THEN** CLI SHALL 请求取消该 turn 并显示正在停止的非最终状态
- **AND** 取消完成后 SHALL 恢复输入并可继续处理下一条消息

#### Scenario: User stops while idle

- **WHEN** 没有活动 turn 且用户执行 `/stop`
- **THEN** CLI SHALL 返回当前没有可停止任务
- **AND** SHALL NOT 停止 AgentLoop 或关闭 Runtime

#### Scenario: User submits messages while a turn is running

- **WHEN** 活动 turn 尚未结束且用户继续提交普通消息
- **THEN** CLI SHALL 显示有界排队状态并保持消息顺序
- **AND** 主 Agent SHALL NOT 并发执行两个 turn

### Requirement: Secret-safe interactive presentation

CLI SHALL 只渲染显式允许的安全事件字段，并 SHALL 在历史、补全、状态栏、工具卡片和错误区域中排除秘密与隐藏推理。

#### Scenario: Provider emits reasoning or tool argument deltas

- **WHEN** Provider 流包含 thinking、reasoning、原始工具参数或 SDK 私有对象
- **THEN** 表现层 SHALL 丢弃这些内容或只投影安全阶段标识
- **AND** SHALL NOT 将其保存到输入历史或复制缓冲区模型

#### Scenario: Error contains sensitive material

- **WHEN** Provider、工具或 renderer 异常文本包含凭证、Header、Cookie、URL 查询秘密或宿主路径内容
- **THEN** CLI SHALL 仅显示稳定错误分类、可重试性和安全操作建议
- **AND** 原始异常 SHALL NOT 出现在交互界面

### Requirement: Stable framed prompt presentation

交互式 CLI SHALL 使用青色圆角单线边框明确标识输入区域，顶部标题“输入” SHALL 左对齐；边框 SHALL 随有效终端宽度、多行输入和窗口 resize 保持闭合，并 SHALL NOT 改变输入、补全、历史、提交、排队或取消语义。

#### Scenario: Empty prompt is ready in Windows PowerShell

- **WHEN** 用户在支持 Unicode 和颜色的 Windows PowerShell 或 Windows Terminal 中启动交互式 CLI
- **THEN** 输入区 SHALL 显示形如 `╭─ 输入 ─…─╮`、左右 `│` 和 `╰─…─╯` 的青色完整边框
- **AND** 标题 SHALL 靠左且光标 SHALL 位于边框内部

#### Scenario: User edits Chinese multiline text

- **WHEN** 用户在输入框内编辑包含中文宽字符、换行或自动折行的提示
- **THEN** 左右边框、光标和文本 SHALL 保持列对齐且输入内容 SHALL NOT 被边框覆盖
- **AND** `Esc+Enter` 换行及 Enter 提交 SHALL 保持既有语义

#### Scenario: Terminal becomes narrow or is resized

- **WHEN** 交互过程中终端宽度缩小到最小支持宽度或发生 resize
- **THEN** 输入框 SHALL 使用当前有效列数重新布局并保持四角及标题可见
- **AND** SHALL NOT 写出终端右边界、重复提交输入或破坏补全候选

#### Scenario: Prompt completion or async output is visible

- **WHEN** slash 候选、ghost suggestion、busy 状态或异步 Agent 输出与输入区同时更新
- **THEN** CLI SHALL 通过统一 prompt_toolkit 重绘保持输入框闭合且光标可恢复
- **AND** SHALL NOT 使用持久诊断文件或把内部控制序列渲染成可见文本

#### Scenario: Submitted input enters the conversation scrollback

- **WHEN** 用户在增强交互输入框中提交普通文本或 slash 命令
- **THEN** CLI SHALL 在清除临时输入框前后将完整提交内容以同风格的青色圆角输入框快照写入稳定滚动区
- **AND** 多行文本、中文宽字符和末尾字符 SHALL 保持完整且不得被后续状态重绘覆盖
- **AND** 已结束的临时 live 输入区 SHALL 被擦除，使每次提交在滚动区中恰好保留一个输入框

#### Scenario: Streaming response is committed without lost text

- **WHEN** Provider 以任意边界发送多个文本增量且输入 Application 同时重绘
- **THEN** CLI SHALL 在内部累计增量，并在权威 Outbound 到达后一次性渲染完整回答
- **AND** 回答 SHALL 保留全部中文字符、行与 Markdown 结构，不得将无换行半行片段直接 flush 到 Windows 终端

#### Scenario: Styled runtime output is rendered safely

- **WHEN** CLI 显示思考状态、token 用量、trace 或其他带样式的辅助信息
- **THEN** CLI SHALL 将样式转换为终端控制序列或无色文本，并按当前终端有效宽度排版
- **AND** Rich markup 标签（包括 `[dim]` 和 `[/]`）SHALL NOT 作为可见文本输出

#### Scenario: User selects a slash command with arrow keys

- **WHEN** slash 命令候选菜单可见且用户按上或下方向键
- **THEN** CLI SHALL 优先在可见候选之间移动当前选择，并允许 Enter 应用所选候选
- **AND** CLI SHALL 仅在候选菜单未打开时使用上下方向键导航历史或多行光标

#### Scenario: Enhanced presentation is unavailable

- **WHEN** stdin/stdout 非 TTY，或终端不支持增强 Unicode/颜色渲染
- **THEN** CLI SHALL 使用既有 plain 降级而不显示圆角边框或颜色控制序列
- **AND** 消息与命令行为 SHALL 与交互模式等价

### Requirement: Bounded prompt affordances

交互式 CLI SHALL 在输入区附近展示有界、非敏感且与实际键位一致的快捷提示，并 SHALL 在 busy 或排队时优先展示当前真实状态。

#### Scenario: CLI is idle

- **WHEN** 输入区空闲且没有活动 turn
- **THEN** CLI SHALL 显示 `Enter 发送`、`Esc+Enter 换行` 和 `/ 命令` 的紧凑提示
- **AND** 提示 SHALL NOT 占用输入内容或加入输入历史

#### Scenario: Turn is busy or messages are queued

- **WHEN** 当前 turn 正在运行或已有普通消息排队
- **THEN** 状态区 SHALL 优先显示 busy 和有界 queue depth，同时保留不冲突的快捷提示
- **AND** SHALL NOT 显示原始提示内容、Provider 秘密或内部事件字段
