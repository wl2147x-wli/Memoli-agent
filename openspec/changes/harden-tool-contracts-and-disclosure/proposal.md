## Why

当前工具 schema 与实际执行合同存在可观察漂移：记忆参数被声明在错误工具上、容器执行器暴露不可用的 PowerShell 选项，且 Registry 未统一校验模型参数。与此同时，Tool Search 的全局披露状态无法进入按会话和 conversation epoch 冻结的 ContextCompiler 工具快照，启用后会出现“Registry 已解锁但模型仍看不到 schema”的断裂。

## What Changes

- 修正 `memory_recall` 与 `memory_manage` 的参数归属，保证所有模型可见参数都被执行、所有执行所需参数都能由模型合法传入。
- 在 Tool Registry 执行前统一校验 JSON Schema，未知字段、类型、枚举和必填约束失败时返回结构化错误，且不进入 Policy Hook 或工具副作用。
- 按 `code_run` 实际 runner profile 构建模型可见 schema：容器只暴露 Python，可信宿主仅在实际支持时暴露 PowerShell，disabled profile 不注册不可工作的工具。
- **BREAKING**：Tool Search 披露状态改为 conversation epoch 内、按 Session 隔离；不再使用 Registry 全局已披露集合。
- 将首次披露的完整工具 schema 作为不可变、可恢复的动态上下文事实保存，并在同一 epoch 后续请求中继续可见和可执行，同时保持稳定基础前缀不变。
- 增加 Registry、ContextCompiler、Provider 集成和多 Session 隔离回归测试。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `tool-system`: 强化工具输入合同、profile-aware schema 和会话级渐进披露行为。
- `context-management`: 支持在冻结基础工具前缀之外追加、恢复并校验 conversation epoch 内首次披露的工具 schema。

## Impact

- 影响 `agent/tools`、`bootstrap/tools.py`、ContextCompiler/Repository、Reasoner 工具调用上下文及对应测试。
- 工具参数错误将更早失败；此前被静默忽略的未知参数不再继续执行。
- Tool Search 的披露状态需要少量持久化结构；不迁移旧的进程级 `_disclosed_tool_names`，旧会话在新 epoch 或首次搜索时重新建立披露记录。
- 增加 `jsonschema` 作为运行时依赖以执行 Draft 2020-12 输入校验；仅实现当前 P0 合同，不拆分 `memory_manage`、不增加输出 schema，也不扩展 MCP、事件驱动或并行工具执行。
