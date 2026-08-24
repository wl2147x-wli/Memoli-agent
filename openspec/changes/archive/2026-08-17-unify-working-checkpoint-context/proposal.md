## Why

当前工作状态在 `PromptRenderPhase` 先生成遗留 `<working_checkpoint>`，随后 Reasoner 又删除它并生成 `<agent_status>`，形成两条并存的上下文装配路径。遗留路径只包含 `key_info` 与 `related_sop`，在简化装配或未来重构中可能绕过最新状态、硬状态信任边界与完整 checkpoint 字段。

## What Changes

- 删除 turn 级 Prompt 渲染阶段对遗留 `render_checkpoint()` 文本的注入，工作状态只由每次 Provider 调用前的动态装配器生成。
- 保证每次模型决策、工具后续决策、重试和 fallback 只接收一个最新、带 revision 和 trust 标记的 `<agent_status>`。
- 在 Agent 软状态表示中补齐 objective、current step、next action、key info、related SOP、constraints、decisions、Agent artifacts、status 和 stale；Runtime artifacts 继续单独标识为硬状态。
- 保留结构化 snapshot/UI 合同和 SQLite schema，不改变 `update_working_checkpoint` 工具参数或既有 checkpoint 数据。
- 移除仅供遗留 Prompt 注入使用的 `render_checkpoint()` 接口及对应旧格式测试，更新架构文档。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `working-memory`：工作状态改为唯一的调用前动态注入，并要求完整呈现 Agent checkpoint 字段及软硬产物边界。
- `context-management`：明确 Prompt 初始渲染不得预置遗留工作状态块，动态尾部在每次 Provider 调用前只包含一个最新状态表示。

## Impact

- 影响 `memoli_agent/agent/lifecycle/phases.py`、`memoli_agent/agent/tools/control.py`、Reasoner 上下文装配测试及 working checkpoint pipeline 测试。
- 不修改 SQLite schema、配置、工具 schema、长期记忆或 UI snapshot 格式，不需要数据迁移。
- 模型可见工作状态内容更完整；移除旧的内部 `render_checkpoint()` Python 方法属于仓库内部清理，不是用户 CLI/API breaking change。
