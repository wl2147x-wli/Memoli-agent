## ADDED Requirements

### Requirement: Persistent task lifecycle

系统 SHALL 为跨多轮或跨进程执行的任务保存唯一标识、目标、状态、checkpoint、预算、等待条件和更新时间。

#### Scenario: Runtime restarts during a task

- **WHEN** 应用在未完成任务执行期间重启
- **THEN** 系统 SHALL 从最近有效 checkpoint 恢复任务状态
- **AND** SHALL NOT 把未验证的步骤标记为已完成

### Requirement: Explicit waiting and termination states

任务 SHALL 使用可查询的状态区分运行、等待审批、等待事件、完成、失败、取消和预算耗尽。

#### Scenario: Task needs user approval

- **WHEN** 下一步动作要求用户批准
- **THEN** 任务 SHALL 进入等待审批状态并保存待批准动作
- **AND** 未获得批准前 SHALL NOT 执行该动作

### Requirement: Idempotent recovery

系统 SHALL 在恢复或重试任务前判断已发生的副作用，并避免重复执行不可安全重试的动作。

#### Scenario: Previous action outcome is uncertain

- **WHEN** 任务恢复时无法确认外部动作是否已经生效
- **THEN** 系统 SHALL 查询或请求确认实际状态
- **AND** SHALL NOT 直接重复提交该动作
