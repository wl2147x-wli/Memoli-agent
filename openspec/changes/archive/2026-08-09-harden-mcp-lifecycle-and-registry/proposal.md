## Why

MCP 在部分连接失败时可能泄漏已建立 transport，规范化工具名碰撞也可能造成静默覆盖，破坏工具来源和安全边界。

## What Changes

- 连接失败时关闭本次已建立的全部资源。
- 检测规范化名称碰撞并报告双方来源，保持无碰撞名称兼容。
- 补齐空列表、重复 connect/close、关闭异常和部分失败测试。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `mcp-tools`: 修改 MCP 生命周期和工具身份冲突处理合同。

## Impact

影响 MCP client/manager、工具注册和运行时集成测试；不引入并发连接。
