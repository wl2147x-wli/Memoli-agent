# MCP Tools Specification

## Purpose

定义 Memoli 通过本地 stdio MCP server 建立连接、发现外部工具、使用命名空间注册和调用工具、适配调用结果以及隔离连接失败和释放资源的行为。
## Requirements
### Requirement: Optional stdio MCP connections

系统 SHALL 在 MCP 启用时连接配置中启用的 stdio server，并拒绝不支持的 transport。

#### Scenario: Enabled stdio server is valid

- **WHEN** runtime 启动并存在有效的 stdio server 配置
- **THEN** 系统 SHALL 启动 server、完成 MCP 会话初始化并发现工具

#### Scenario: Transport is unsupported

- **WHEN** server transport 不是 `stdio`
- **THEN** 系统 SHALL 报告该 transport 暂不支持

### Requirement: Namespaced MCP tools

MCP 工具 SHALL 以 `mcp__<server>__<tool>` 名称注册到统一工具注册表。

#### Scenario: Two servers expose the same tool name

- **WHEN** 多个 server 暴露同名工具
- **THEN** 每个工具 SHALL 通过 server 名命名空间保持可区分

### Requirement: MCP result adaptation

系统 SHALL 将 MCP 调用输出及错误状态转换为统一工具结果。

#### Scenario: External tool is called

- **WHEN** Agent 调用已注册的 MCP 工具
- **THEN** 系统 SHALL 把参数转发给对应 server
- **AND** 文本结果 SHALL 可作为 tool-role 内容返回模型

### Requirement: Connection failure isolation

单个 MCP server 连接失败 SHALL NOT 阻止主应用启动。

#### Scenario: One server is unavailable

- **WHEN** 配置中的某个 server 无法连接或发现工具
- **THEN** 该 server 的工具 SHALL 不被注册
- **AND** 其他运行时能力 SHALL 保持可用

### Requirement: MCP resource cleanup

系统 SHALL 在关闭时释放所有已建立的 MCP 会话及子进程资源。

#### Scenario: Runtime shuts down

- **WHEN** 应用运行时关闭
- **THEN** 所有已连接 MCP client SHALL 被关闭

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

