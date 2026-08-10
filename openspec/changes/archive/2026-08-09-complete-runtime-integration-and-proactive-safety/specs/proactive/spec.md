## ADDED Requirements

### Requirement: Safe proactive startup scheduling

主动循环 SHALL 默认在首次评估前等待配置延迟，只有显式 `run_on_start=true` 时才允许启动后立即评估。

#### Scenario: Default proactive loop starts
- **WHEN** 主动循环以默认配置启动
- **THEN** 系统 SHALL 在 initial_delay_seconds 到期前不发布主动入站消息

#### Scenario: Immediate evaluation is enabled
- **WHEN** 用户显式配置 run_on_start=true
- **THEN** 系统 SHALL 允许启动后的首次 tick 立即评估

### Requirement: Optional proactive quiet hours

主动循环 SHALL 支持默认关闭、带显式时区的免打扰时段，并在该时段内保持静默。

#### Scenario: Tick occurs in configured quiet hours
- **WHEN** 当前时间处于用户配置的 quiet-hours 区间
- **THEN** 系统 SHALL 不发布主动消息并记录 `quiet-hours` 跳过原因
