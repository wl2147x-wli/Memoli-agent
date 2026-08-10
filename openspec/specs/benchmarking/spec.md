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
