## ADDED Requirements

### Requirement: Failure-safe MCP connection ownership

MCP 连接 SHALL 仅在完整初始化成功后转移资源所有权；部分失败 SHALL 关闭本次已建立的全部 transport。

#### Scenario: Later server fails to initialize
- **WHEN** 前一 server 已连接而后一 server 初始化失败
- **THEN** 系统 SHALL 关闭前一连接及失败连接的局部资源

### Requirement: Collision-free MCP tool identity

规范化后的 MCP 工具名 SHALL 唯一；不同原始来源映射为同一名称时系统 SHALL 拒绝注册并报告双方来源。

#### Scenario: Safe names collide
- **WHEN** 两个 server/tool 组合规范化为同一工具名
- **THEN** 系统 SHALL NOT 静默覆盖任一工具
- **AND** 启动诊断 SHALL 标识两个原始来源
