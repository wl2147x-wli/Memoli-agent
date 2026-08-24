## ADDED Requirements

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
