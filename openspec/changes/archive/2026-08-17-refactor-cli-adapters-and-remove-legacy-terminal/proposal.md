## Why

当前增强终端和旧 plain CLI 在 `channels/cli.py` 中各自维护输入循环、输出循环、命令分发与流式状态，造成重复状态和兼容包装。需要删除旧终端实现的重复逻辑，同时保留非 TTY、管道输入和初始化失败时不可替代的最小 plain fallback。

## What Changes

- 引入共享 `CLIController`，统一命令路由、普通消息提交、有界排队、生命周期和 Outbound/表现事件分发。
- 将增强终端与 plain fallback 收敛为实现同一 Channel adapter 合同的两个薄适配器。
- 删除旧 `CLICommandRouter` 兼容包装、旧 `_render_*` 函数、重复状态字段和双套输入/输出循环。
- plain adapter 只保留逐行读取、无 ANSI 文本写出与 EOF/退出语义；不会删除 plain 能力。
- 迁移测试到公开 controller/adapter 边界，并保持本地命令不进入 LLM、Session 或 trajectory。
- 不引入宠物、多页面 TUI、运行时热切换或新的持久化格式。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `interactive-cli`: 明确 interactive/plain adapters 共享命令、排队和结果语义，plain 仅是确定性表现降级而不是独立终端实现。

## Impact

- 主要影响 `memoli_agent/channels/cli.py`、`interactive.py`、新增的共享 controller/adapter 合同及 CLI 测试。
- `memoli`、`memoli chat`、配置字段、MessageBus、AgentLoop、轨迹 schema 和用户命令保持兼容。
- 不删除 `prompt_toolkit` 或 Rich 依赖；不改变正式 Provider 默认 streaming。
