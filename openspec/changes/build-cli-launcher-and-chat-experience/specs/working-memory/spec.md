## ADDED Requirements

### Requirement: User-inspectable working-state snapshot

系统 SHALL 为授权的本地 CLI 提供当前 session 的只读工作状态快照，并 SHALL 在结构和人类可读表示中明确区分 Agent 维护的语义 checkpoint 与 Runtime 根据真实执行投影的硬状态。

#### Scenario: Active checkpoint is inspected during a task

- **WHEN** CLI 查询当前 session 且存在 active checkpoint
- **THEN** 快照 SHALL 包含 session key、objective、current step、next action、key info、constraints、decisions、artifacts、related SOP、revision、状态、stale 标记和更新时间
- **AND** Runtime 状态 SHALL 独立包含可验证的 iteration、elapsed、last tool、last tool status 和 artifacts

#### Scenario: Checkpoint and runtime projection disagree

- **WHEN** Agent checkpoint 声称任务已完成但 Runtime 状态没有相应完成证据
- **THEN** 快照 SHALL 保留两种来源及其原始状态并明确标识信任来源
- **AND** SHALL NOT 使用 Agent 字段覆盖或推导 Runtime 硬状态

#### Scenario: Checkpoint content exceeds terminal budget

- **WHEN** 工作 checkpoint 超过人类可读终端表示的预算
- **THEN** 渲染器 SHALL 优先保留 session、revision、状态、stale、目标、当前步骤、下一步和用户约束
- **AND** SHALL 明确标识省略内容而不是静默截断成看似完整的卡片

### Requirement: Non-mutating checkpoint inspection

工作状态检查 SHALL 读取最近已提交的 checkpoint 快照，不得更新 revision、恢复 stale 状态、改变生命周期或产生模型与工具行为。

#### Scenario: Stale or completed checkpoint is inspected

- **WHEN** CLI 查询 stale 或 completed checkpoint
- **THEN** 系统 SHALL 返回该状态和最近已提交 revision
- **AND** SHALL NOT 自动将 checkpoint 改回 active 或写入新的 revision

#### Scenario: No checkpoint exists

- **WHEN** 当前 session 尚未提交 checkpoint
- **THEN** 系统 SHALL 返回明确的 not-found/unavailable 表示
- **AND** SHALL NOT 根据聊天历史、长期记忆或模型输出伪造 checkpoint

#### Scenario: Inspection occurs while a checkpoint update commits

- **WHEN** CLI 查询与 checkpoint 更新在时间上重叠
- **THEN** 查询 SHALL 返回一个完整已提交 revision 或可重试的受控忙碌状态
- **AND** SHALL NOT 返回跨 revision 拼接的部分字段

### Requirement: Stable checkpoint presentation contract

工作状态快照 SHALL 具有稳定、带版本的人类可读和 JSON 表示，使 CLI、未来 TUI 与桌面客户端可共享相同语义而不解析模型注入用 XML。

#### Scenario: Human-readable card is rendered

- **WHEN** CLI 请求默认 checkpoint 表示
- **THEN** 系统 SHALL 以字段化工作卡片显示 checkpoint，并将 Runtime 硬状态放在独立区域
- **AND** SHALL NOT 直接把模型上下文中的 `<working_checkpoint>` 或 `<agent_status>` 文本当作 UI 合同

#### Scenario: Machine-readable snapshot is rendered

- **WHEN** 调用者请求 JSON 表示
- **THEN** 输出 SHALL 包含 presentation schema version、session key、availability、checkpoint 和 runtime status 字段
- **AND** 相同已提交快照的规范化 JSON 字段语义 SHALL 保持稳定

