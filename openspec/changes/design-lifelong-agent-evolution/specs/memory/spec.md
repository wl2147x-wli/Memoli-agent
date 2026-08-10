## ADDED Requirements

### Requirement: Evidence-backed personal memory

长期个人记忆 SHALL 保存类型、置信度、时间有效性、敏感等级、状态和一个或多个来源引用。

#### Scenario: Model infers an unstated preference

- **WHEN** 候选偏好不是用户明确陈述且证据不足
- **THEN** 系统 SHALL 标记为推断候选而不是 verified 事实
- **AND** SHALL NOT 在高风险决策中当作确定事实使用

### Requirement: Memory conflict and supersession

系统 SHALL 检测新旧记忆冲突，并通过更新有效期、supersede、合并或请求澄清处理冲突。

#### Scenario: User changes a preference

- **WHEN** 用户明确提供与旧偏好冲突的新偏好
- **THEN** 系统 SHALL 保留变更来源和时间
- **AND** 默认检索 SHALL 优先当前有效版本

### Requirement: Hybrid scoped retrieval

系统 SHALL 支持关键词、语义、时间、类型、用户/会话 scope 和重要性信号的可替换检索与融合，并记录检索解释。

#### Scenario: Semantic backend is unavailable

- **WHEN** embedding 或向量检索失败
- **THEN** 系统 SHALL 退化到可用检索 lane
- **AND** SHALL 在 trace 中标记退化状态

### Requirement: User memory governance

用户 SHALL 能查看、修正、删除、冻结和导出个人记忆。

#### Scenario: User corrects a memory

- **WHEN** 用户修正错误记忆
- **THEN** 系统 SHALL 停止召回错误版本并保存修正证据
