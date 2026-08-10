## ADDED Requirements

### Requirement: Unified evaluation episode

评测系统 SHALL 使用统一的 reset、setup/ingest、execute、verify、close 合同评测 Memory、Runtime、Tool、Proactive、Skill、Evolution candidate 和模型版本。

#### Scenario: Stateful task is evaluated

- **WHEN** 评测任务依赖多步工具和环境状态
- **THEN** 环境 SHALL 在执行前重置并在结束后验证最终状态

### Requirement: Evidence-first evaluators

任务成功、安全和副作用 SHALL 优先由测试、环境状态或确定性规则验证；LLM Judge SHALL 仅补充难以程序化的维度并保存 rubric、证据和置信度。

#### Scenario: LLM answer conflicts with environment

- **WHEN** Agent 声称成功但环境最终状态未满足目标
- **THEN** 评测 SHALL 判定任务未成功

### Requirement: Candidate comparison and regression

评测 SHALL 在相同数据、环境、预算和模型条件下比较 baseline 与 candidate，并报告 validation、holdout、回归和消融结果。

#### Scenario: Candidate is evaluated only on optimization cases

- **WHEN** 候选没有独立 holdout 或回归结果
- **THEN** 报告 SHALL 标记为不足以支持发布

### Requirement: Reproducible evaluation report

每次运行 SHALL 保存配置快照、代码/Prompt/Skill/模型版本、随机种子、数据清单、指标、置信区间、成本、延迟和失败样例。

#### Scenario: Benchmark is rerun

- **WHEN** 使用同一版本、数据清单和种子重新运行确定性评测
- **THEN** 系统 SHALL 产生可比较结果并明确记录环境差异
