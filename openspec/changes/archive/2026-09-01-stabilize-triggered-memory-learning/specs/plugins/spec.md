## ADDED Requirements

### Requirement: Profile-scoped hook persistence boundary

插件 Hook 执行与持久化 SHALL 遵守当前 Agent Profile 的轨迹策略；当内部 Profile 禁止保存轨迹时，HookBus SHALL 使用同一非持久 sink 或被明确禁用，不得把 Hook 事件写入另一个 Agent 的 trajectory。

#### Scenario: Internal profile suppresses trajectory persistence

- **WHEN** `memory-governor` 或其他明确禁用轨迹的内部 Profile 执行模型或工具步骤
- **THEN** 其 Reasoner Hook 和 ToolRegistry Hook SHALL NOT 使用绑定主 SQLite trajectory 的共享 HookBus
- **AND** Hook 记录失败 SHALL NOT 阻断治理读取工具或确定性 Policy Gate

#### Scenario: Governance tool policy hook would write an unknown trace

- **WHEN** 主插件注册表包含 `shell_safety` `TOOL_BEFORE` Hook，而 `memory-governor` trace 仅存在于 `NullTrajectoryStore`
- **THEN** governor 的 ToolRegistry SHALL 在 Hook 调度前使用 profile-scoped disabled HookBus 边界
- **AND** 系统 SHALL NOT 尝试以 governor trace ID 向主 `trajectories.db` 写 `plugin_hook_started` 或把该外键错误转换为治理工具失败

#### Scenario: Main Agent executes plugin hooks

- **WHEN** 主 Agent 或允许保存轨迹的普通 SubAgent 执行已注册插件 Hook
- **THEN** 插件策略、observer 顺序和既有轨迹事件 SHALL 保持原行为
- **AND** 内部 Profile 的非持久配置 SHALL NOT 改变全局 Hook 注册表
