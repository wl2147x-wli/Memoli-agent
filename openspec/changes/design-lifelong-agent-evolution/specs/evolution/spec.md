## ADDED Requirements

### Requirement: Evidence-based learning signals

系统 SHALL 从经过验证的成功、失败、用户纠正和回归轨迹中产生带证据、置信度和目标能力的学习信号。

#### Scenario: Judge confidence is low

- **WHEN** 学习信号仅由低置信 LLM 判断支持
- **THEN** 系统 SHALL 将其送交第二验证器或人工复核
- **AND** SHALL NOT 自动用于候选发布

### Requirement: Isolated evolution candidates

Evolution Lab SHALL 在候选区生成 Skill、Prompt section、工具描述或检索策略变体，不得直接覆盖 stable/active 版本。

#### Scenario: Optimizer finds a higher-scoring variant

- **WHEN** 候选在优化集上取得更高分
- **THEN** 系统 SHALL 保存候选、修改假设、来源和优化成本
- **AND** SHALL 在 holdout 与回归集验证前保持未发布状态

### Requirement: Regression-gated release

候选 SHALL 同时满足目标提升、全局回归、安全约束、长度预算和人工批准后才能发布。

#### Scenario: Target score improves but regression worsens

- **WHEN** 候选提升目标评测但超过允许的回归阈值
- **THEN** 系统 SHALL 拒绝发布该候选

### Requirement: OpenSpec-governed high-impact changes

高影响进化候选 SHALL 生成或关联包含证据、影响预测、行为 delta、实现任务和评测结果的 OpenSpec change。

#### Scenario: Candidate changes system behavior

- **WHEN** 候选修改用户可观察行为、公共合同或安全边界
- **THEN** 系统 SHALL 要求对应 OpenSpec change 完成评审后才能实施
