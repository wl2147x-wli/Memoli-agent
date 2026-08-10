## ADDED Requirements

### Requirement: Governed personal-memory tools

启用个人记忆时，系统 SHALL 区分只读召回与受治理管理操作，并支持显式记住、纠正、冻结、删除、查看和导出个人记忆。

#### Scenario: Agent explicitly recalls memory

- **WHEN** 模型调用 `memory_recall` 并提供查询、可选类型或时间过滤及数量上限
- **THEN** 工具 SHALL 返回有界的结构化命中、稳定记忆 ID、当前性、证据引用和召回解释
- **AND** 该调用 SHALL NOT 修改记忆状态

#### Scenario: User explicitly asks the agent to remember a fact

- **WHEN** 受治理管理工具收到关联当前显式用户消息的 `remember` 操作
- **THEN** 系统 SHALL 创建可追踪的显式用户 claim 并返回稳定 ID 和状态
- **AND** SHALL NOT 把 Assistant 自己的历史陈述用作用户依据

#### Scenario: Agent attempts an unsupported implicit write

- **WHEN** 模型请求把推断、网页文本、工具输出或 Assistant 回复直接发布为正式个人记忆且没有允许的批准主体
- **THEN** 管理工具 SHALL 拒绝正式写入或仅创建明确标记的 candidate
- **AND** SHALL 返回拒绝或候选原因

#### Scenario: User corrects or freezes a memory

- **WHEN** 管理工具收到关联显式用户消息的 `correct` 或 `freeze` 操作及目标 ID
- **THEN** 系统 SHALL 创建修正版本或更新冻结状态并返回实际受影响 ID
- **AND** 原始 claim、来源和修订历史 SHALL 保持可审计

#### Scenario: Memory subsystem is disabled

- **WHEN** 任一个人记忆工具在 memory 关闭时被调用
- **THEN** 工具 SHALL 返回结构化 disabled 结果
- **AND** SHALL NOT 创建 memory database 写入

### Requirement: Personal-memory deletion and export results

个人记忆管理操作 SHALL 对删除和导出返回明确范围，并区分个人记忆索引与原始 trajectory 的保留边界。

#### Scenario: User forgets selected memories

- **WHEN** `forget` 操作指定用户可管理的一个或多个 memory ID
- **THEN** 目标 SHALL 立即停止默认召回并产生最小审计 tombstone
- **AND** 工具结果 SHALL 说明原始 trajectory 是否仍受独立保留策略管理

#### Scenario: User exports personal memory

- **WHEN** `export` 操作成功
- **THEN** 导出 SHALL 包含当前 cards、claims、状态、时间和可公开证据引用
- **AND** SHALL 遵守脱敏、scope 和权限边界

