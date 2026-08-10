## ADDED Requirements

### Requirement: Governed trajectory dataset construction

后训练流水线 SHALL 只使用获得授权、完成脱敏、通过 schema 校验并具有结果标签的轨迹构建数据集。

#### Scenario: Private trajectory lacks consent

- **WHEN** 真实个人轨迹没有明确的训练使用授权
- **THEN** 数据构建器 SHALL 排除该轨迹

### Requirement: Leakage-safe dataset splits

训练、验证和 holdout SHALL 按用户、任务族、时间和近重复关系进行隔离，防止同源答案泄漏。

#### Scenario: Near-duplicate appears across splits

- **WHEN** 数据检查发现跨 split 的近重复任务或轨迹
- **THEN** 系统 SHALL 移动或删除冲突样本并重新生成数据清单

### Requirement: SFT and rejection-sampling baseline

第一阶段后训练 SHALL 支持用高质量示范进行 SFT，并支持从多个候选轨迹中保留验证成功轨迹的 RFT 数据构建。

#### Scenario: Candidate trajectory has correct text but failed state

- **WHEN** 模型输出看似正确但环境最终状态验证失败
- **THEN** 该轨迹 SHALL NOT 作为成功 SFT/RFT 样本

### Requirement: Verifiable RL boundary

RLVR SHALL 仅在奖励可由隔离环境状态、测试或确定性规则可靠计算的任务中启用。

#### Scenario: Reward relies only on subjective judge

- **WHEN** 任务成功无法由状态或规则验证且只有主观 LLM 分数
- **THEN** 系统 SHALL NOT 将该分数作为自动 RL 的主要奖励

### Requirement: Versioned model release

训练模型 SHALL 以不可变版本注册，并与基座模型在相同评测、成本和安全门禁下比较后才能成为 Runtime 可选模型。

#### Scenario: Fine-tuned model regresses on safety

- **WHEN** 微调模型提高工具成功率但降低安全审批命中率
- **THEN** 系统 SHALL 拒绝将其设为稳定默认模型
