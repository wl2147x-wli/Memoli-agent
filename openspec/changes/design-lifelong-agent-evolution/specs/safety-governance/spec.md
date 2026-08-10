## ADDED Requirements

### Requirement: Data purpose and consent enforcement

系统 SHALL 区分运行、记忆、评测、进化和训练的数据用途，并在超出原用途前取得适用授权。

#### Scenario: Memory data is requested for optimization

- **WHEN** 离线优化器希望使用个人记忆或相关轨迹
- **THEN** 系统 SHALL 检查用途授权、敏感等级和脱敏状态
- **AND** 不满足条件的数据 SHALL 被拒绝

### Requirement: Risk-based action approval

系统 SHALL 根据工具副作用、可逆性、幂等性和数据敏感度执行权限检查、预览和批准策略。

#### Scenario: Irreversible external action is requested

- **WHEN** Agent 准备执行不可逆或不可幂等的外部动作
- **THEN** 系统 SHALL 提供动作预览并要求授权
- **AND** SHALL 保存批准者、范围和时间

### Requirement: Governed artifact release

Skill、Prompt、策略、代码和模型候选 SHALL 通过版本化审批、canary、审计和回滚流程发布。

#### Scenario: Candidate lacks evaluation evidence

- **WHEN** 候选没有完整 holdout 和回归报告
- **THEN** 系统 SHALL 阻止其成为 active/stable 版本

### Requirement: User data control

用户 SHALL 能查看、导出、修正和删除其个人记忆及适用轨迹，并了解删除对训练产物的边界。

#### Scenario: User deletes a verified memory

- **WHEN** 用户请求删除一条个人记忆
- **THEN** 系统 SHALL 从 active retrieval 中移除该记忆并记录治理事件
- **AND** SHALL 按数据政策处理相关派生候选和未发布数据集
