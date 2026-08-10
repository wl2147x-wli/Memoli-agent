## Why

主动循环默认首 tick 可能立即发送消息，且 AgentLoop、MCP、Session、Context 和完整被动轮次仍缺少关键集成回归，阻碍安全演示和稳定发布。

## What Changes

- 主动循环默认先等待，新增 run_on_start 和 initial_delay_seconds。
- 补齐消息隔离、Session、Context、MCP、quiet-hours 和完整端到端测试。
- 增加 UTF-8、workspace 临时目录的 PowerShell 测试入口。
- 弃用误导性的 WorkingStateStore.checkpoints 空快照接口。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `proactive`: 修改启动触发和首次调度合同。
- `agent-runtime`: 增加端到端运行和错误恢复的可验证合同。

## Impact

影响 ProactiveConfig、ProactiveLoop、WorkingStateStore、开发脚本及运行时集成测试；SQLite 异步化与 MCP 并发不在本 change 范围。
