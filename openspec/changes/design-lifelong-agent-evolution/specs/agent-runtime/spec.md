## ADDED Requirements

### Requirement: Bounded multi-step execution

主 Agent SHALL 在一次任务唤醒中支持多轮 observe、model、tool、result 和 verify 步骤，并受迭代、时间、Token 和费用预算约束。

#### Scenario: Tool result requires another action

- **WHEN** 首次工具结果表明任务仍需后续操作
- **THEN** Reasoner SHALL 在剩余预算内继续下一步骤
- **AND** SHALL NOT 被固定为一次工具回调后强制结束

### Requirement: Explicit termination reason

每次 Agent 执行 SHALL 产生 completed、failed、interrupted、needs-user、cancelled 或 budget-exhausted 等可观察终止原因。

#### Scenario: Iteration budget is exhausted

- **WHEN** 任务达到允许的最大步骤且尚未完成
- **THEN** 系统 SHALL 以 budget-exhausted 结束本次唤醒
- **AND** SHALL 保存可恢复的任务状态而不是宣称完成

### Requirement: Step lifecycle and progress detection

系统 SHALL 在每个推理/工具步骤前后发布生命周期信息，并检测重复调用、无状态变化和无进展循环。

#### Scenario: Identical failing action repeats

- **WHEN** Agent 在没有新信息时重复相同失败动作达到阈值
- **THEN** 系统 SHALL 阻止继续循环并转为失败、请求用户或替代策略
