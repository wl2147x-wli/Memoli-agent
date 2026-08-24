## Context

当前 `channels/cli.py` 同时承担模式选择、命令路由、plain 输入、interactive 输入、两套输出消费、旧流式状态和兼容测试函数。`interactive.py` 只封装 prompt_toolkit 输入，`TerminalRenderer` 又维护另一份渲染状态。重复边界增加了串线、重复输出和未来修改遗漏 plain 模式的风险。

plain 模式仍是管道、重定向、CI 和增强终端故障时的必要能力，因此本次删除的是旧实现而不是 fallback 行为。

## Goals / Non-Goals

**Goals:**

- 一个 `CLIController` 统一命令处理、队列背压、消息提交和退出决定。
- 一个 adapter 协议统一 `start/read/write/close`，interactive/plain 只处理终端差异。
- 一个 Outbound/event 消费路径统一 session 过滤、trace 更新和 renderer 提交。
- plain adapter 保持无 ANSI、EOF、有序关闭和可注入输入输出，便于测试与管道使用。
- 删除旧路由包装、旧 `_render_*`、`streamed_text/tool_step` 前台状态和重复循环。

**Non-Goals:**

- 不删除 plain fallback，不把 prompt_toolkit 用于非 TTY。
- 不修改 Provider、AgentLoop、MessageBus、Session、trajectory 或命令集合。
- 不引入宠物、Textual、多页面 TUI、后台 daemon 或热切换。

## Decisions

### 1. Controller 持有共享交互语义

`CLIController` 持有 `CLIState`、`CommandRegistry`、Runtime 只读依赖和 queue limit。`handle_input()` 返回带 stop/notice/published 的确定性结果；adapter 不直接理解命令或构造 `InboundMessage`。

替代方案是保留两个输入循环并抽取辅助函数，但生命周期、异常和队列判断仍会重复，因此拒绝。

### 2. Adapter 只处理终端 I/O

`PlainCLIAdapter` 使用 `asyncio.to_thread(input_reader)` 逐行读取并直接写纯文本；`InteractiveCLIAdapter` 继续负责 prompt_toolkit 的补全、键位、history 和 bottom toolbar。两者实现相同的异步合同，bootstrap 只选择一次。

plain writer 接受完整文本块，不解释表现事件，不保存流式前缀状态。这样降级路径足够小，也不会产生 ANSI。

### 3. Renderer 是唯一输出归约边界

两种 adapter 都使用 `TerminalRenderer` 的单队列和 `RenderState`。颜色、Markdown 和刷新能力由 renderer profile 决定：interactive 使用 Rich/帧率，plain 使用无颜色的一次性文本 profile。命令 notice 也进入同一写队列。

避免保留 `_render_outbound` 和 `_render_presentation` 这类第二套状态机。最终 Outbound 仍是权威结果。

### 4. 迁移测试到公开边界

测试直接覆盖 `CLIController`、两个 adapter、registry 和 reducer，不再导入私有 `_render_*` 或兼容 router。旧行为通过管道 E2E、命令旁路和流式去重测试继续固定。

## Risks / Trade-offs

- [plain 输出改由共享 renderer 后可能出现 ANSI] → plain profile 强制 `color=False`，并以重定向 stdout 回归测试检查控制字符。
- [单 controller 过度承担 UI 细节] → controller 只返回动作结果，不依赖 prompt_toolkit 或 Rich。
- [删除私有函数影响仓库外非正式调用] → 这些函数从未是 console/API 合同；README 只承诺 `memoli` 与命令行为。
- [renderer 关闭时遗漏尾部输出] → adapter 先停止输入，再取消消费者，最后 drain/close renderer。

## Migration Plan

1. 先建立 controller 与 plain adapter，并用现有 plain 回归验证等价。
2. 将 interactive adapter 接入 controller 与共享消费者。
3. 删除旧兼容包装和私有渲染函数，迁移测试导入。
4. 执行全量测试、Ruff、Pyright 与 OpenSpec strict validation。

回滚时可恢复本 change 修改的 CLI 文件；无配置或持久化迁移。

## Open Questions

无。真实 Windows/Unix PTY 人工验收继续由前一 change 的 8.7 跟踪。
