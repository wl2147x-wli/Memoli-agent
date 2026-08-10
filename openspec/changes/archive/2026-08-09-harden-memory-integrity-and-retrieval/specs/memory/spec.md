## ADDED Requirements

### Requirement: Scope-safe historical claim identity

系统 SHALL 只在同一 scope 的当前记忆之间去重，并 SHALL 保留 deleted、rejected、superseded 历史而不阻止重新记忆相同内容。

#### Scenario: Deleted content is remembered again
- **WHEN** 用户重新保存同一 scope 中已软删除的内容
- **THEN** 系统 SHALL 创建新的 Claim identity
- **AND** 原删除记录 SHALL 保持历史状态

#### Scenario: Same content exists in another scope
- **WHEN** 两个不同 scope 保存规范化后相同的内容
- **THEN** 系统 SHALL 分别保存且不得跨 scope 复用 identity

### Requirement: Atomic memory mutation and migration

记忆写入、关系改写、consolidation 批次和 schema 迁移 SHALL 原子完成，并在中断后保持可重试状态。

#### Scenario: Consolidation extraction fails midway
- **WHEN** 任一候选提取或验证失败
- **THEN** 本批 Claim、Card 与关系 SHALL NOT 部分提交
- **AND** run SHALL 记录失败原因分类

### Requirement: Explicit memory lifecycle

系统 SHALL 校验 Claim 与 Card 状态转移；历史状态不可复活，Frozen 只允许用户或人工 actor 解冻或删除。

#### Scenario: Automated actor mutates frozen memory
- **WHEN** 非用户 actor 尝试解冻或删除 Frozen 记忆
- **THEN** 系统 SHALL 拒绝状态转移

### Requirement: Ranked and scoped retrieval diagnostics

关键词召回 SHALL 保留 BM25 相关性顺序，在 scope 过滤后应用上限，并报告治理过滤与上下文截断诊断。

#### Scenario: Fallback search spans many scopes
- **WHEN** LIKE fallback 的高排名行包含其他 scope 数据
- **THEN** 系统 SHALL 先完成 scope 过滤再应用候选上限

#### Scenario: Context budget truncates recall
- **WHEN** 召回内容超过注入预算
- **THEN** 结果 SHALL 报告 truncated、omitted_items 和 omitted_chars

### Requirement: Governed personal-memory export

用户导出 SHALL 包含当前 Card 与 Claim 的 scope、状态、敏感级别、证据引用和时间，默认 SHALL NOT 包含 Episode。

#### Scenario: User exports current memory
- **WHEN** 用户请求导出个人记忆
- **THEN** 导出 SHALL 同时包含符合 scope 的当前 Card 和 Claim
- **AND** SHALL 排除 Episode，除非另行请求轨迹导出
