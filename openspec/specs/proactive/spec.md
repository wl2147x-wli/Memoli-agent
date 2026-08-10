# Proactive Specification

## Purpose

定义默认关闭的主动检查循环如何按配置定时感知状态、应用冷却决策、把内容重新注入主消息链路，以及应用关闭时如何安全释放后台任务。
## Requirements
### Requirement: Opt-in proactive loop

主动循环 SHALL 默认关闭，并仅在配置启用时作为后台任务运行。

#### Scenario: Proactive behavior is disabled

- **WHEN** `proactive.enabled` 为 false
- **THEN** 系统 SHALL NOT 创建主动检查后台循环

#### Scenario: Proactive behavior is enabled

- **WHEN** 应用启动且主动配置已启用
- **THEN** 系统 SHALL 按不低于一秒的配置间隔执行感知与决策

### Requirement: Cooldown-aware decision

系统 SHALL 使用冷却时间避免在过短间隔内重复发送主动消息。

#### Scenario: Cooldown has not elapsed

- **WHEN** 距离上次触发时间小于配置冷却时间
- **THEN** 当前 tick SHALL 跳过发送并记录跳过原因

### Requirement: Main-loop delivery

主动内容 SHALL 作为带事件元数据的入站消息投递到主消息总线。

#### Scenario: Decision requests a message

- **WHEN** 主动决策返回应发送内容
- **THEN** 消息 SHALL 进入配置的 chat id
- **AND** 消息 SHALL 继续经过 session、memory、reasoner 和工具链路

### Requirement: Graceful shutdown

系统 SHALL 在应用关闭时取消并等待主动后台任务结束。

#### Scenario: Runtime shuts down during wait

- **WHEN** 主动循环正在等待下一次 tick 且应用开始关闭
- **THEN** 等待任务 SHALL 被取消且不泄漏后台任务

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

