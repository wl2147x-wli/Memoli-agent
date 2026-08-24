## Why

当前增强 CLI 的输入提示与输出、候选和状态栏缺少清晰的视觉边界，长文本、多行编辑或异步输出时用户不容易确认输入焦点。需要提供在 Windows PowerShell/Windows Terminal 下稳定的输入框，并在不增加终端噪声的前提下补充常用操作提示。

## What Changes

- 为交互式 TTY 的输入区域增加青色圆角单线框：顶部左侧标题为“输入”，使用 `╭─ 输入 ─…─╮`、左右 `│` 和底部 `╰─…─╯`。
- 输入框随终端宽度和多行内容重排，正确处理中文宽字符、窄窗口、窗口 resize、补全菜单和异步输出重绘。
- 仅使用 prompt_toolkit 的公共 layout/container/control 接口组织输入区，不修改库内部类、不写诊断日志，也不依赖 ANSI 字符串手工定位光标。
- 保持 plain/管道模式无边框、无颜色控制序列；终端不支持 Unicode/颜色时沿用现有 plain 降级。
- 在输入区下方提供有界快捷提示：`Enter 发送`、`Esc+Enter 换行`、`/ 命令`，busy/queue 状态继续优先显示且不暴露敏感数据。
- 不改变命令、消息提交、历史、取消、队列、Provider 或 Runtime 行为。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `interactive-cli`：增加可见输入边框、Windows PowerShell 渲染稳定性、窄窗口/中文/resize 行为和有界快捷提示要求。

## Impact

- 主要影响 `memoli_agent/channels/interactive.py` 的 prompt_toolkit 布局与样式，以及 `tests/test_interactive_cli.py` 的虚拟终端渲染覆盖。
- 更新 Interactive CLI 规格与运行文档；不新增配置、依赖、数据库或持久化迁移。
- Windows PowerShell 5.1、PowerShell 7/Windows Terminal 为重点兼容目标；非 TTY 和现有 plain CLI 保持兼容。
