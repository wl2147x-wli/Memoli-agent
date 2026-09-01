## Why

`calculator`、`memory_write`、`filesystem_read` 和旧版 SubAgent 委派实现已经退出 Runtime 装配，但实现代码与兼容性规范仍然存在，容易让维护者误以为这些能力仍受支持，并持续保留无效依赖和测试面。现在应删除这些不可达实现，让源码与实际工具合同保持一致。

## What Changes

- **BREAKING**：删除未注册的 `calculator`、`memory_write`、`filesystem_read` 工具实现，不再支持调用方手工导入并注册这些兼容工具。
- **BREAKING**：删除已被持久任务图版 `SpawnSubAgentTool` 替代的 `LegacySpawnSubAgentTool`。
- 清理仅由上述实现使用的表达式求值、路径和旧式委派辅助代码及 import。
- 更新工具规范，移除“兼容用 calculator 可显式注册”的合同，改为确认被移除工具不存在于受支持工具集合。
- 保持默认九工具、显式启用的 `memory_manage`、新版 SubAgent 工具及 benchmark 的 `ingest_mode="memory_write"` 数据导入模式不变；benchmark 模式名称不是模型工具。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `tool-system`：删除遗留兼容工具的可注册行为，并明确受支持 Runtime 不再提供其实现。

## Impact

- 主要修改 `memoli_agent/agent/tools/builtin.py`、工具系统测试和工具文档。
- 不修改数据库 schema、已存轨迹或个人记忆数据；历史轨迹中的旧工具名仍作为不可变历史文本保留。
- 不改变当前主 Agent 的模型可见 Schema，因为这些工具原本就未注册。
- `benchmarks` 中名为 `memory_write` 的直接导入策略不受影响，它不依赖 `MemoryWriteTool`。
