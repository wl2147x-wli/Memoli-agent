## Purpose

建立可重复、可归因、可统计的端到端 Agent 任务评测体系，把最终答案、执行轨迹、工具与 Skill、记忆、压缩、子代理、缓存、token、成本和可靠性统一为版本化实验结果。

## ADDED Requirements

### Requirement: 版本化评测数据集
系统 SHALL 支持包含输入、初始工作区、对话脚本、工具回放、期望输出、黄金事实、轨迹约束、评分器和元数据的版本化数据集。

#### Scenario: 运行固定任务集
- **WHEN** 启动一个正式实验
- **THEN** 每个任务 MUST 绑定不可变的数据集版本、代码版本、配置快照、模型标识、随机种子和实验变体

### Requirement: 任务覆盖矩阵
正式数据集 SHALL 覆盖直接回答、文件读写、代码修改、搜索、浏览、MCP、记忆、Skill、长上下文、上下文溢出、并行工具、子代理、权限拒绝、取消、模型失败和恢复场景。

#### Scenario: 发布门禁运行
- **WHEN** 评估准备发布的变更
- **THEN** 运行 MUST 报告各任务类别样本数和结果，不能只用总体平均掩盖单类回归

### Requirement: 确定性工具和环境回放
评测系统 SHALL 支持冻结工作区快照、时间、工具响应、MCP 响应、网络结果和随机种子，使不同变体面对等价外部条件。

#### Scenario: 工具结果回放
- **WHEN** baseline 与 candidate 运行同一任务
- **THEN** 对等工具调用 MUST 获得相同回放结果；不在回放契约中的调用 MUST 被显式记录为轨迹偏差

### Requirement: 端到端 Trace 与子代理树
系统 SHALL 以任务运行作为根 Trace，并 SHALL 关联全部 Agent turns、Generation、工具、记忆、压缩、Skill、子代理和后台工作；并行分支 MUST 保留真实父子和时间关系。

#### Scenario: 子代理并发任务
- **WHEN** 父 Agent 同时启动多个子代理
- **THEN** 报告 MUST 分别显示每个子代理的任务、usage、工具轨迹、结果和错误，并在根任务汇总而不重复计费

### Requirement: 多维质量评分
评测系统 SHALL 支持确定性断言、轨迹断言、工件检查、规则评分、人工评分和可选 LLM judge，并 SHALL 分开保存原始输出、评分依据、评分器版本和分数。

#### Scenario: 文本正确但工件错误
- **WHEN** 最终回答声称成功但预期文件缺失或内容不符
- **THEN** 任务 MUST 判为执行失败或部分成功，不得只按最终文本评分

#### Scenario: Judge 模型失败
- **WHEN** LLM judge 超时或输出不可解析
- **THEN** 任务质量 MUST 标记未评分，且不得自动记零或影响确定性断言结果

### Requirement: 成本、效率与可靠性指标
系统 SHALL 汇总主 Agent、辅助模型、压缩、记忆、embedding 和子代理的 token、成本与延迟，并 SHALL 统计成功率、步骤数、工具数、重试、循环、溢出、降级、取消和错误分类。

#### Scenario: 单位成功任务成本
- **WHEN** 汇总实验结果
- **THEN** 系统 MUST 报告每成功任务 token、每成功任务成本和每成功任务耗时，并保留失败任务消耗

### Requirement: 配对比较与统计分析
系统 SHALL 对 baseline 与 candidate 使用相同任务进行配对比较，报告样本量、缺失率、均值、中位数、p95、效果量和置信区间，并 SHALL 对随机顺序和重复运行进行配置记录。

#### Scenario: Candidate 降低成本但质量回退
- **WHEN** candidate 总 token 降低而成功率或关键类别质量超过允许退化
- **THEN** 发布门禁 MUST 失败，并同时展示效率收益与质量回退

### Requirement: 可配置发布门禁
系统 SHALL 支持按总体和任务类别定义非劣阈值、最大成本/延迟回退、最低缓存可观测覆盖率和最大错误率，并 SHALL 输出机器可读门禁结果。

#### Scenario: 门禁通过
- **WHEN** 所有硬性阈值满足且没有必测类别缺失
- **THEN** 系统 MUST 输出通过状态、使用的规则版本和证据链接

#### Scenario: 数据不足
- **WHEN** 样本不足、Langfuse 数据尚未可见或关键指标不可观测
- **THEN** 门禁 MUST 输出 inconclusive，而不是通过

### Requirement: Langfuse Experiment 与本地证据一致
系统 SHALL 将数据集运行、Trace、Observation 和 Score 关联到 Langfuse Experiment，并 SHALL 保留可独立复算的本地 JSONL/JSON 报告。

#### Scenario: Langfuse 暂时不可查询
- **WHEN** 遥测已 flush 但远端数据存在摄取延迟
- **THEN** 分析器 MUST 有界重试，并可使用本地原始证据生成标记为 provisional 的报告

### Requirement: 可复现与审计
系统 SHALL 为每次正式实验保存代码提交、脏工作区摘要、依赖锁定、操作系统、硬件、模型 endpoint 标识、配置脱敏快照和运行命令。

#### Scenario: 后续复现实验
- **WHEN** 使用保存的实验清单重新运行
- **THEN** 系统 MUST 能重建任务顺序、变体配置和工具回放，并明确列出无法复现的外部 Provider 状态

