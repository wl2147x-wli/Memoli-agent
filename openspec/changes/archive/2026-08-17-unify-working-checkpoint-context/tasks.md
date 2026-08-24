## 1. 唯一工作状态装配

- [x] 1.1 增加 PromptRenderPhase 不预置遗留工作状态、Provider 调用仅含一个最新 `<agent_status>` 的回归测试
- [x] 1.2 移除 PromptRenderPhase 的 `render_checkpoint()` 调用及 WorkingStateStore 遗留 renderer
- [x] 1.3 保留调用前防御性去重，验证首轮、工具后续调用和无 checkpoint 场景使用同一动态装配路径

## 2. 完整软硬状态表示

- [x] 2.1 扩展 `<agent_status>` Agent section，包含 constraints、decisions 和 Agent artifacts，并与 Runtime artifacts 明确分区
- [x] 2.2 增加完整字段、确定性顺序、revision、trust、空 checkpoint 与字符上限测试

## 3. 文档与验收

- [x] 3.1 更新工作记忆与 Runtime 架构文档，移除遗留兼容块仍参与 PromptRenderPhase 的说明
- [x] 3.2 使用 Conda memoli 环境运行相关 pytest、Ruff 和 Pyright
- [x] 3.3 同步 working-memory/context-management canonical specs 并运行 change 与全量 OpenSpec strict validation
