## ADDED Requirements

### Requirement: Governed MCP connection

每个 MCP server SHALL 声明 transport、信任级别、环境与网络权限、超时、健康状态和允许的能力类型。

#### Scenario: Untrusted server requests broad access

- **WHEN** server 权限超过当前策略允许范围
- **THEN** 系统 SHALL 拒绝连接或限制其可注册能力

### Requirement: MCP capability metadata

MCP 工具 SHALL 进入统一 Tool Runtime，并继承风险、副作用、审批、trace 和结果验证合同。

#### Scenario: MCP tool changes external state

- **WHEN** MCP 工具声明或观察到外部副作用
- **THEN** 系统 SHALL 按对应风险级别执行审批和验证

### Requirement: Transport extensibility

系统 SHALL 通过可替换连接适配器支持未来远程 transport，而不改变上层统一工具调用合同。

#### Scenario: Remote transport is not configured

- **WHEN** 用户请求连接未启用或不受支持的远程 transport
- **THEN** 系统 SHALL 明确拒绝且不回退到不安全连接方式
