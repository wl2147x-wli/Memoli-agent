# Benchmarking Specification

## Purpose

定义 Memoli 及外部 Agent 在 LoCoMo、LongMemEval 数据上的可插拔评测行为。

## Requirements

### Requirement: TOML-driven benchmark runs

评测运行器 SHALL 从 TOML 读取 dataset、agent、metrics 与 output 配置，并支持命令行字段覆盖。

#### Scenario: Dataset section is missing

- **WHEN** 评测配置不包含 `[dataset]`
- **THEN** 运行器 SHALL 拒绝启动并报告缺失配置

#### Scenario: Override is provided

- **WHEN** 用户传入 `--section.field value`
- **THEN** 运行器 SHALL 按目标字段现有类型解析并覆盖该值

### Requirement: Common dataset model

系统 SHALL 将 LoCoMo 与 LongMemEval 原始数据转换为统一的 sample、session、message、question 和 prediction 合同。

#### Scenario: Dataset is loaded

- **WHEN** 适配器读取受支持的数据集
- **THEN** 问题、答案、证据、类型与会话消息 SHALL 被保留在统一对象中
- **AND** sample size、seed、question type 和 session limit 配置 SHALL 按数据集能力生效

### Requirement: Pluggable agent adapters

评测系统 SHALL 支持 Memoli、HTTP、CLI 和 Python/custom Agent 适配器的 reset、ingest、answer 与 close 生命周期。

#### Scenario: Memoli evaluates a sample

- **WHEN** 每样本重置已启用
- **THEN** Memoli adapter SHALL 为样本使用隔离的 workspace、memory 和 SubAgent 目录

#### Scenario: External adapter answers

- **WHEN** HTTP、CLI 或 Python adapter 返回答案
- **THEN** 系统 SHALL 将其规范化为包含 prediction、retrieved context 和 metadata 的统一预测对象

### Requirement: Configurable history ingestion

Memoli adapter SHALL 支持直接写入长期记忆或通过普通 Agent turn 注入历史。

#### Scenario: Memory-write ingestion

- **WHEN** `ingest_mode` 为 `memory_write`
- **THEN** 每条历史消息 SHALL 连同 sample、session、message 与时间标识写入长期记忆

#### Scenario: Agent-turn ingestion

- **WHEN** `ingest_mode` 为 `agent_turn`
- **THEN** 历史消息 SHALL 通过正常入站消息链路交给 Agent

### Requirement: Reproducible benchmark artifacts

评测系统 SHALL 将预测、聚合指标、配置快照和人类可读报告写入按 dataset、split 和 run id 隔离的输出目录。

#### Scenario: Run completes

- **WHEN** 评测完成且对应输出开关已启用
- **THEN** 系统 SHALL 生成 `predictions.jsonl`、`metrics.json` 和 `report.md`
- **AND** LongMemEval SHALL 额外生成兼容官方评分的 hypotheses 文件

### Requirement: Official metric interoperability

系统 SHALL 使用 LoCoMo 官方评测脚本计算回答分数与检索 recall，并为 LongMemEval 生成官方评分输入。

#### Scenario: Echo provider is used

- **WHEN** 评测预测来自 Echo provider
- **THEN** 报告 SHALL 将其视为链路验证而非真实 Agent 能力分数

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
