## MODIFIED Requirements

### Requirement: Layered memory-learning evaluation

评测系统 SHALL 为记忆写入与离线整理闭环提供分层评估指标，区分更新器能力与受益能力，而不得仅以端到端回答分数反推更新器好坏。分层指标 SHALL 读取既有 `memory.db` 治理审计与 trajectory 召回证据，不新增侵入式用户数据埋点。

#### Scenario: Adherence rate classifies contract rejections as failures

- **WHEN** 评测聚合 `memory_manage remember/correct` 调用结果
- **THEN** 报告 SHALL 计算“遵循成功率”为通过逐字证据合同的调用比例
- **AND** SHALL 将 `missing-explicit-basis` 与 `basis-content-mismatch` 拒绝计为遵循失败，而非规则错误
- **AND** 报告 SHALL 将该比例与端到端分数分开呈现

#### Scenario: Candidate validity rate measures offline consolidation

- **WHEN** 评测聚合离线整理产出的 Candidate
- **THEN** 报告 SHALL 计算“候选修改有效率”为经 Governance 批准并成功投影为 Card 或语义索引的 Candidate 比例
- **AND** SHALL 以 governance decision 与 projection 状态为证据，而非以 Candidate 总数掩盖质量

#### Scenario: Activation rate measures retrieval at the right time

- **WHEN** 评测聚合 `memory_recall` 召回轨迹
- **THEN** 报告 SHALL 计算“产物激活率”为被召回记忆在正确场景被命中并使用的比例
- **AND** SHALL 以召回命中 ID 与命中位置为证据

#### Scenario: Held-out gain is reported separately

- **WHEN** 评测在未参与整理的留出样本上运行
- **THEN** 报告 SHALL 计算“留出任务增益”为召回相关记忆后的回答质量相对基线的增益
- **AND** SHALL 与既有 LoCoMo/LongMemEval 官方分数并列呈现，而不得替换或影响官方评分

#### Scenario: Layered metrics are optional and non-interfering

- **WHEN** 分层记忆评估未启用
- **THEN** 评测 SHALL 仍产出既有 LoCoMo/LongMemEval 官方分数与报告
- **AND** SHALL NOT 因缺少分层指标而失败或降级官方评分合同
