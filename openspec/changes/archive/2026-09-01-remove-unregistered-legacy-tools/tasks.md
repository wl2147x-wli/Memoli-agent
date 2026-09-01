## 1. 删除遗留实现

- [x] 1.1 删除 `CalculatorTool`、`MemoryWriteTool`、`FilesystemReadTool` 和 `LegacySpawnSubAgentTool`。
- [x] 1.2 删除仅由遗留工具使用的 AST 算术求值辅助代码、旧式委派逻辑和孤立 import。
- [x] 1.3 从当前工具用途分类中移除不再可注册的 `memory_write` 名称，并确认新版 SubAgent 工具保持不变。

## 2. 合同与回归测试

- [x] 2.1 更新工具测试，断言遗留类不再存在且请求旧工具名返回结构化 missing-tool 失败。
- [x] 2.2 运行工具、bootstrap、SubAgent 和 benchmark 相关回归测试，确认 `ingest_mode="memory_write"` 不受影响。

## 3. 文档与验证

- [x] 3.1 更新当前工具系统文档，说明遗留兼容实现已删除及替代路径；保留归档与历史轨迹原貌。
- [x] 3.2 运行 Ruff、Pyright、完整测试和 `openspec validate --all --strict`。
