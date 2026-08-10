## ADDED Requirements

### Requirement: Append-only execution trajectory

系统 SHALL 为每个 Agent 任务记录 append-only 轨迹，覆盖模型步骤、工具调用、工具结果、状态变化、审批和最终结果。

#### Scenario: Tool step completes

- **WHEN** Agent 完成一次工具调用
- **THEN** 轨迹 SHALL 保存 trace、task、step、tool call 与 result 的关联标识
- **AND** SHALL 保存时间、耗时、成功状态和可用的错误信息

### Requirement: Evidence-linked feedback

用户反馈、评测结论、记忆和学习候选 SHALL 能引用产生它们的轨迹或步骤。

#### Scenario: User corrects an answer

- **WHEN** 用户指出某次回答或动作错误
- **THEN** 系统 SHALL 将纠正关联到原任务和相关步骤
- **AND** 后续学习材料 SHALL 保留该来源引用

### Requirement: Privacy-aware trajectory access

轨迹 SHALL 支持敏感字段脱敏、访问控制、保留期限、导出和删除策略。

#### Scenario: Trajectory is considered for training

- **WHEN** 数据构建器读取真实使用轨迹
- **THEN** 未获得训练授权或未通过脱敏检查的轨迹 SHALL 被排除

### Requirement: Query and replay

系统 SHALL 允许按任务、时间、工具、结果和错误查询轨迹，并在隔离环境重放可重放步骤。

#### Scenario: Failure is reproduced

- **WHEN** 开发者选择一条支持重放的失败轨迹
- **THEN** 系统 SHALL 在隔离环境运行并记录与原轨迹的结果差异
