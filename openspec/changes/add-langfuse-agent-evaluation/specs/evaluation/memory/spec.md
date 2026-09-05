## Purpose

建立覆盖记忆生成、持久化、切块、embedding、索引、混合检索、排序、注入和任务贡献的评测契约，使记忆质量能够从“写入成功”延伸到“真正帮助任务”。

## ADDED Requirements

### Requirement: 记忆生命周期追踪
系统 SHALL 追踪记忆 flush、摘要、文件写入、切块、embedding、索引 upsert/delete/sync、检索和结果注入的完整生命周期。

#### Scenario: 修剪触发异步记忆写入
- **WHEN** 上下文修剪将消息异步 flush 到每日记忆
- **THEN** 系统 MUST 关联源 run、被丢弃消息范围、摘要 Generation、目标文件、索引同步和最终状态

#### Scenario: 写入成功但索引失败
- **WHEN** 记忆文件已写入而 embedding 或索引同步失败
- **THEN** Trace MUST 区分持久化成功与可检索状态失败，并记录后续重试状态

### Requirement: Embedding 调用观测
系统 SHALL 记录 embedding provider、模型、维度、输入条目数、批次数、输入大小、延迟、缓存使用、错误和回退，但默认不得上传完整记忆正文。

#### Scenario: 批量 embedding
- **WHEN** 同步任务将多个 chunk 分批提交
- **THEN** 系统 MUST 记录逻辑批次与实际 API 批次，并验证返回向量数量和维度匹配

#### Scenario: embedding 不可用
- **WHEN** provider 初始化或调用失败
- **THEN** 系统 MUST 标记 keyword-only 回退，且该状态 MUST 出现在检索评测维度中

### Requirement: 检索轨迹与排名可解释
系统 SHALL 记录检索查询指纹、用户/共享作用域、候选数、向量与关键词原始排名、融合分数、时间衰减、阈值、最终 top-k 和返回片段标识。

#### Scenario: 混合检索
- **WHEN** 同一 chunk 同时被向量和关键词搜索命中
- **THEN** 记录 MUST 能解释其向量分、关键词分、时间衰减和最终融合分，不得只保留最终排序

#### Scenario: 用户隔离
- **WHEN** 查询指定 user scope
- **THEN** 结果和遥测 MUST 不包含其他不可见用户的 chunk，并 MUST 记录隔离校验结果

### Requirement: 检索离线质量指标
评测系统 SHALL 支持带相关 chunk ID 的黄金查询集，并 SHALL 计算 Recall@K、Precision@K、MRR、nDCG、空结果率、错误作用域率和检索延迟。

#### Scenario: 黄金查询运行
- **WHEN** 一个查询包含一个或多个黄金记忆 chunk
- **THEN** 系统 MUST 保存完整排名并计算规定 K 值下的召回与排序指标

### Requirement: 记忆生成质量
系统 SHALL 评估摘要记忆的事实正确性、覆盖率、重复率、冲突率、时效性和敏感信息处理，并 SHALL 区分 LLM 摘要与规则回退。

#### Scenario: 重复 flush
- **WHEN** 相同消息集合多次触发 flush
- **THEN** 评测 MUST 验证去重行为，并记录重复写入和重复 token 消耗

#### Scenario: 新旧事实冲突
- **WHEN** 后续对话更新了先前用户偏好或事实
- **THEN** 评测 MUST 检查检索与最终回答是否优先使用有效的新事实

### Requirement: 记忆任务增益实验
系统 SHALL 使用相同任务对比无记忆、关键词记忆、混合记忆、不同 top-k/阈值以及时间衰减策略，并 SHALL 衡量最终任务质量与额外成本。

#### Scenario: 记忆消融实验
- **WHEN** 同一跨会话任务分别在关闭和开启记忆条件下运行
- **THEN** 报告 MUST 给出任务成功率差、事实召回差、误导率、额外 token、embedding 成本和延迟

### Requirement: 记忆引用与使用归因
系统 SHALL 区分“被检索”“被注入”“被模型引用”和“对答案有贡献”，避免把返回 top-k 直接视为有效记忆。

#### Scenario: 检索但未使用
- **WHEN** 相关记忆出现在 top-k 但最终答案和轨迹没有使用它
- **THEN** 系统 MUST 分别记录 retrieval hit 与 utilization，任务增益不得仅由 retrieval hit 推断

