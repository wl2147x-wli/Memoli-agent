## ADDED Requirements

### Requirement: Proactive opportunity decision

系统 SHALL 根据外部信号、用户目标、最近交互、紧迫性、新颖性、个性相关度和打扰成本决定 silent、prepare、ask 或 notify。

#### Scenario: Signal is relevant but not urgent

- **WHEN** 信息可能有价值但当前打扰成本较高
- **THEN** 系统 SHALL 静默准备或延迟处理，而不是立即通知

### Requirement: Interruption policy

主动消息 SHALL 受 quiet hours、每日预算、冷却、重复抑制和高优先级例外约束。

#### Scenario: Daily notification budget is exhausted

- **WHEN** 普通优先级机会出现且当日预算已耗尽
- **THEN** 系统 SHALL 不发送即时通知

### Requirement: Explainable proactive message

主动消息 SHALL 能说明触发来源、与用户的相关性和建议动作，并避免暴露不必要的敏感记忆。

#### Scenario: User asks why a reminder appeared

- **WHEN** 用户查询主动提醒原因
- **THEN** 系统 SHALL 提供可理解且可追溯的解释

### Requirement: Proactive feedback signal

系统 SHALL 记录用户接受、忽略、推迟、关闭或纠正主动消息的反馈，用于评测和候选策略优化。

#### Scenario: User marks notification as annoying

- **WHEN** 用户明确负反馈一类提醒
- **THEN** 系统 SHALL 记录该信号
- **AND** SHALL NOT 未经门禁直接重写稳定策略
