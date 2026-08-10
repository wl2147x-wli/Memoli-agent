## ADDED Requirements

### Requirement: Persistent evidence-backed SQLite memory

启用个人记忆后，系统 SHALL 使用 schema-versioned 本地 SQLite 数据库持久化 claims、card versions、证据关系、修订、整理批次和可重建检索索引，并 SHALL 将每条正式或候选记忆绑定到当前用户 scope 和至少一个可审计来源。

#### Scenario: Memory starts for the first time

- **WHEN** 配置的 memory database 尚不存在
- **THEN** 系统 SHALL 原子创建受支持版本的 schema 和检索索引
- **AND** SHALL NOT 修改或删除已有 trajectory 数据

#### Scenario: Runtime restarts

- **GIVEN** claims、cards 和修订已经提交
- **WHEN** Agent 关闭后重新启动
- **THEN** 当前 active 版本、历史 claim 和证据关系 SHALL 仍可查询

#### Scenario: Unknown schema version is found

- **WHEN** memory database schema 高于当前实现支持的版本或 migration 失败
- **THEN** 系统 SHALL 报告明确 schema 错误并停止使用该数据库
- **AND** SHALL NOT 静默删除、重建或降级已有个人记忆

### Requirement: Append-only claims and versioned cards

系统 SHALL 以追加 claim 保存观察到的个人事实演化，并以版本化 card 表达少量当前用户、人物、关系、项目和目标概览；纠正 SHALL 通过新 claim、关系和 card version 表达而不是破坏旧记录。

#### Scenario: New evidence supports an existing card

- **WHEN** 新 claim 与已有 card 一致且通过发布条件
- **THEN** 系统 SHALL 保留新 claim 及其独立来源
- **AND** SHALL 通过新 card version 或支持关系更新当前投影

#### Scenario: A later statement contradicts an older fact

- **WHEN** 用户提供与旧 claim 冲突的当前信息
- **THEN** 系统 SHALL 保存新旧 claim、时间和来源
- **AND** SHALL 通过 corrects、contradicts 或 supersedes 关系标识演化

### Requirement: Bounded core memory overview

系统 SHALL 从当前有效 card 中选择少量核心用户画像作为有界概览，并 SHALL 按 user/scope、状态、冻结优先级、card 数量和字符预算限制常驻内容。

#### Scenario: Core cards are available

- **WHEN** 当前用户存在 active 或 frozen 核心 cards
- **THEN** 当前回合 SHALL 获得不超过配置上限的结构化概览
- **AND** 每个概览项 SHALL 可关联稳定 card ID 和支持 claim

#### Scenario: Core cards exceed the budget

- **WHEN** 候选核心 cards 超过数量或字符预算
- **THEN** 系统 SHALL 优先保留 scope 匹配的 frozen 和明确用户事实
- **AND** SHALL NOT 将被裁剪内容表示为不存在或已失效

### Requirement: Contextual episodic trajectory index

系统 SHALL 能够从已提交的 SQLite trajectory 构建可重建的情景检索片段，并为片段保存 trace 范围、时间、scope、上下文前缀和原始证据解析信息。

#### Scenario: An ambiguous conversation fragment is indexed

- **WHEN** 原始消息脱离其人物、主题、时间或任务背景会产生歧义
- **THEN** 派生索引 SHALL 为搜索文本增加明确标识为派生内容的上下文前缀
- **AND** 实际检索结果 SHALL 仍能解析到未被前缀改写的原始轨迹消息

#### Scenario: Episodic index is rebuilt

- **WHEN** 管理操作删除并重建情景检索索引
- **THEN** 已提交 trajectory SHALL 保持不变
- **AND** 同一索引规则 SHALL 不重复创建相同 trace 范围的片段

### Requirement: Candidate-only offline consolidation

系统 SHALL 在在线 turn 之外按未消费轨迹范围或显式长期整理请求执行幂等 consolidation，并 SHALL 将隐式提取结果先保存为 candidate 而不是直接发布为正式核心记忆。

#### Scenario: A consolidation batch succeeds

- **WHEN** 离线整理选择一组尚未消费的已提交轨迹
- **THEN** 系统 SHALL 逐段提取候选、绑定原始证据、执行 schema/scope/source 校验并记录稳定批次键
- **AND** 隐式偏好、关系或归纳事实 SHALL 保持 candidate 直至满足批准条件

#### Scenario: Consolidation is retried

- **GIVEN** 相同轨迹范围已有成功的 consolidation 批次
- **WHEN** 该批次被重复请求
- **THEN** 系统 SHALL 返回既有结果或幂等跳过
- **AND** SHALL NOT 重复创建相同来源的 claim

#### Scenario: Consolidation fails before commit

- **WHEN** 提取、校验或数据库事务失败
- **THEN** 系统 SHALL NOT 推进已消费 checkpoint
- **AND** 已发布 memory 和原始 trajectory SHALL 保持不变

### Requirement: Temporal conflict and lifecycle filtering

系统 SHALL 支持 candidate、active、frozen、superseded、rejected 和 deleted 生命周期，并在检索阶段结合有效时间、明确纠正、scope 和版本关系选择当前可用记忆。

#### Scenario: User changes a preference

- **WHEN** 用户明确提供与旧偏好冲突的新偏好
- **THEN** 默认检索 SHALL 优先显式、当前有效的新版本
- **AND** 旧版本 SHALL 保留来源但 SHALL NOT 作为当前偏好注入

#### Scenario: A memory is expired or deleted

- **WHEN** claim/card 已超过有效期或状态为 deleted、rejected 或 superseded
- **THEN** 默认检索 SHALL 排除该项
- **AND** 审计查询 SHALL 仍能区分其历史状态和修订原因

### Requirement: User memory governance

用户 SHALL 能按自身 scope 查看、纠正、冻结、删除和导出个人记忆，并 SHALL 获得操作的实际影响范围和来源说明。

#### Scenario: User corrects a memory

- **WHEN** 用户纠正错误记忆
- **THEN** 系统 SHALL 停止默认召回错误版本并保存修正证据
- **AND** SHALL 返回新旧 memory ID 或 version 关系

#### Scenario: User freezes a memory

- **WHEN** 用户冻结一条 active 记忆
- **THEN** 自动 consolidation SHALL NOT 替换或删除该记忆
- **AND** 后续更改 SHALL 需要用户操作或允许的批准主体

#### Scenario: User deletes a memory

- **WHEN** 用户删除其有权管理的个人记忆
- **THEN** 该记忆 SHALL 立即停止默认召回并从普通导出中排除或标记 deleted
- **AND** 系统 SHALL 说明来源 trajectory 是否仍遵循独立保留策略

### Requirement: Safe and idempotent Markdown migration

系统 SHALL 为现有 `MEMORY.md` 提供预览、备份、manifest 和幂等导入，并 SHALL 将 legacy 文件哈希作为外部证据而不伪造 trajectory 引用。

#### Scenario: Legacy memory is imported

- **WHEN** 用户批准从可解析的 `MEMORY.md` 导入
- **THEN** 每个导入 claim SHALL 保存原内容、来源、可解析时间、文件哈希和 `legacy-import` 标记
- **AND** 原 Markdown 文件 SHALL 保持可恢复

#### Scenario: Legacy import is repeated

- **GIVEN** 同一文件内容已成功导入
- **WHEN** migration 再次运行
- **THEN** 系统 SHALL 根据 manifest 和幂等键跳过重复条目

#### Scenario: Legacy history and recent context are encountered

- **WHEN** migration 发现 `HISTORY.md` 或 `RECENT_CONTEXT.md`
- **THEN** 系统 SHALL 备份并在报告中列出它们
- **AND** SHALL NOT 自动把其中的 Assistant 文本、流水或摘要提升为长期用户事实

## MODIFIED Requirements

### Requirement: Explicit fact mutation

系统 SHALL 仅在存在明确用户依据、人工操作或获准离线发布主体时改变个人记忆的正式状态，并 SHALL 为每次操作保存稳定 ID、scope、来源、时间和修订记录。

#### Scenario: Agent writes a fact

- **WHEN** 受治理记忆操作收到关联当前用户消息的非空事实
- **THEN** 系统 SHALL 保存 explicit-user claim、证据引用和相关元数据
- **AND** SHALL 返回稳定 claim ID 和实际发布状态

#### Scenario: Model infers an unstated preference

- **WHEN** 模型推断用户未明确陈述的偏好且没有允许的批准主体
- **THEN** 系统 SHALL 拒绝正式写入或保存为 candidate
- **AND** SHALL NOT 在高风险决策中把该 candidate 当作确定事实

#### Scenario: Memory is disabled

- **WHEN** 个人记忆写入在 memory 系统未启用时被请求
- **THEN** 系统 SHALL 返回 disabled 结果
- **AND** SHALL NOT 创建或修改 memory database

### Requirement: Keyword retrieval and prompt injection

系统 SHALL 通过可替换检索端口对核心 cards、active claims 和情景轨迹片段执行 scope/状态/时间过滤及 FTS5/BM25 检索，并在有匹配时按类型配额和字符预算注入带 ID、来源和召回解释的有限结果。

#### Scenario: Relevant memory exists

- **WHEN** 当前用户消息或任务 checkpoint 与当前有效个人记忆存在相关匹配
- **THEN** 当前回合 SHALL 接收有界的核心概览和/或检索记忆块
- **AND** 每个注入项 SHALL 可解析到 card、claim 或原始 trajectory 证据

#### Scenario: No memory matches

- **WHEN** 检索没有返回当前 scope 下的有效条目
- **THEN** 系统 SHALL NOT 注入空记忆标题、其他用户记忆或伪造记忆

#### Scenario: FTS5 is unavailable

- **WHEN** SQLite 运行环境不支持 FTS5 或主要检索 lane 失败
- **THEN** 系统 SHALL 退化到有界规范化关键词 lane 或返回明确检索不可用状态
- **AND** 检索结果和轨迹 SHALL 标记 degraded 原因

#### Scenario: Sensitive or out-of-scope memory matches textually

- **WHEN** 一条记忆字面相关但不属于当前用户/scope 或调用者无权查看其敏感等级
- **THEN** 检索层 SHALL 在该内容进入模型上下文前将其过滤

## REMOVED Requirements

### Requirement: Persistent Markdown memory

**Reason**: Markdown bullet 无法可靠表达多证据、版本、冲突、scope、时效、事务和用户治理，并会形成无法验证的第二事实源。

**Migration**: 使用受管 migration 将 `MEMORY.md` 幂等导入 schema-versioned `memory.db`；保留原文件备份和 manifest，Markdown 后续只作为兼容导入或可读导出。

### Requirement: Conversation history consolidation

**Reason**: 每轮追加 `HISTORY.md` 与更完整的 SQLite trajectory 重复，且缺少工具调用和循环决策，不能作为权威情景记忆。

**Migration**: 停止在线双写；以已提交 SQLite trajectory 作为唯一原始运行历史，按需构建可重建情景索引或确定性 Markdown 导出，并且普通对话仍不得自动转化为正式长期事实。
