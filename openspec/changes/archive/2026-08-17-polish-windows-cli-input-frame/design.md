## Context

当前交互式 CLI 使用 `PromptSession` 提供补全、多行、历史、取消与 bottom toolbar，但输入区只有短提示符，和异步输出/候选区的视觉边界较弱。此前本地草稿尝试 monkey-patch prompt_toolkit 内部 `Frame` 并读取 renderer 私有 screen，这会绑定内部实现且在 Windows inline renderer 下不稳定，已经删除。

Windows PowerShell 5.1、PowerShell 7 与 Windows Terminal 对 Unicode、ANSI 和重绘能力不完全相同；现有 channel 选择逻辑已在非 TTY 或增强初始化失败时降级 plain，因此本 change 只增强成功进入 interactive adapter 的路径。

## Goals / Non-Goals

**Goals:**

- 使用公共 prompt_toolkit layout/container/control API 构建可测试的圆角输入框。
- 在 Windows 下正确处理 CJK 宽度、多行、自动折行、窄窗口、resize、候选与异步输出。
- 保持单一 prompt_toolkit Application 拥有光标和重绘，避免手写 ANSI 定位。
- 提供少量、真实且有界的快捷提示。

**Non-Goals:**

- 不重做全屏 TUI、消息时间线、Markdown renderer 或命令面板。
- 不改变键位、命令、消息队列、Runtime 或 Provider 行为。
- 不为边框新增配置、持久化状态或第三方依赖。
- 不保证旧版不支持 Unicode 的控制台显示圆角字符；这类环境继续 plain 降级。

## Decisions

### 1. 以公共容器组合构建一个 PromptSession 等价 Application

输入 Buffer、BufferControl、候选菜单、toolbar 与状态模型继续复用现有组件；外层使用 `HSplit`/`VSplit`、`Window` 和 `FormattedTextControl` 组合顶部、侧边与底部。布局在 adapter 内显式创建，不替换 prompt_toolkit 模块内部 `Frame`，也不读取 renderer 私有字段。

选择公共布局而不是 monkey-patch，是为了让 prompt_toolkit 小版本升级和 Windows inline renderer 具有可预测行为。若直接扩展 `PromptSession` 无法安全替换根容器，则抽取共享的 Buffer/Completer/KeyBindings 并用公共 `Application` 装配；不再 patch 内部导入符号。

### 2. 让 prompt_toolkit 负责终端列宽、CJK 和 resize

边框各行用容器的 dimension 与 `Window` 填充能力绘制，文本区设置一列左右 padding；不自行用 `unicodedata` 估算折行数。标题只占固定的短左侧 segment，水平线填充剩余空间。设置合理最小宽度；更窄或初始化异常时触发现有 plain fallback。

### 3. 边框和状态均属于同一 Application live region

异步输出继续通过 `patch_stdout` 与单写者 renderer 协调，输入框、候选和 toolbar 由同一 Application invalidate/resize 周期重绘。边框不直接 `print`，避免 scrollback 中残留半框或重复框。

### 4. 颜色与快捷提示保持克制

边框使用 ANSI cyan，标题使用 bold cyan；输入正文、候选和现有状态颜色不改变。idle toolbar 增加 `Enter 发送 · Esc+Enter 换行 · / 命令`，busy/queue 信息放在前面。所有提示来自静态键位合同和结构化状态，不含用户输入或内部事件。

### 5. Windows 验证采用纯函数、虚拟终端和人工 smoke 三层

单元测试断言边框 segment、标题和样式；prompt_toolkit pipe input + virtual output 覆盖中文、多行、候选、submit、Ctrl+C/Ctrl+D；可控尺寸 Output 覆盖 20/40/80/120 列和 resize。验收文档记录 Windows PowerShell 5.1/7 或 Windows Terminal 的人工 smoke 命令和结果。

## Risks / Trade-offs

- [公共 Application 装配比 PromptSession 快捷入口代码更多] → 抽取小型 layout builder，并保留现有 Completer、History、Suggest 和 bindings，不复制业务路由。
- [旧 Windows 字体缺少圆角字形] → 仅在增强 TTY 使用 Unicode 框；终端能力不足按现有机制降级 plain。
- [候选菜单可能扩大 live region 导致边框错位] → 候选作为输入内容区的 sibling，由布局引擎分配高度，并加入 `/` 面板虚拟终端测试。
- [窗口极窄时标题与角冲突] → 定义最小增强宽度，低于阈值降级或采用有界紧凑框，不写越右边界。
- [异步 renderer 与输入 Application 竞争输出] → 继续使用 `patch_stdout` 和单写者输出边界，增加异步 notice 后光标/边框恢复回归。

## Migration Plan

1. 先以纯函数和虚拟终端测试固化现有输入/补全/键位行为。
2. 引入公共 layout builder 和边框样式，再接入 adapter。
3. 增加 Windows resize/CJK/候选/异步输出回归及人工 smoke 记录。
4. 发布无需配置或数据迁移；回滚只需恢复原 PromptSession 装配，plain 路径不变。

## Open Questions

- 无阻塞问题。实现阶段以 prompt_toolkit 3.0.51 当前公共 API 为基线，并在受约束版本范围内验证。
