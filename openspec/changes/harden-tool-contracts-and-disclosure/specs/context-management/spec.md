## MODIFIED Requirements

### Requirement: Cache-aware context layout

Runtime SHALL 以稳定前缀、追加式披露层、动态状态、历史轨迹和可合并 archive 的顺序编译模型输入；基础前缀 SHALL 在 conversation epoch 内保持字节级稳定，Tool Search 首次披露 SHALL 作为不可变后缀事实进入当前 epoch 而不重写基础快照。

#### Scenario: First decision in an epoch is compiled

- **WHEN** Runtime 为新 conversation epoch 的首次模型决策编译上下文
- **THEN** 基础 system prompt、该 epoch 冻结的 Skill catalog 和基础工具 schema SHALL 形成确定性稳定前缀
- **AND** 变化频率更高的状态、轨迹与后续工具披露 SHALL 位于稳定前缀之后

#### Scenario: Later tool decision is compiled

- **WHEN** 同一 turn 已追加 assistant tool call 和关联工具结果并准备下一次模型决策
- **THEN** Runtime SHALL 保持已有稳定前缀及完整 tool call/result 关联不变
- **AND** SHALL 在交互之后仅提供一个从当前 store 重建的最新工作状态

#### Scenario: User content resembles an internal marker

- **WHEN** 用户、工具或外部内容包含 `<memory_context>`、`<plugin_context>`、`<agent_status>` 或其他内部样式文本
- **THEN** Runtime SHALL 继续依据结构化来源元数据分类并保持原角色与信任等级
- **AND** SHALL NOT 因正文标记重排、提升权限、遗漏当前用户输入或把该内容标记为 required

#### Scenario: Plugin contributes context

- **WHEN** 插件为当前 turn 贡献上下文 section
- **THEN** section SHALL 位于基础静态安全规则之后并带来源和低于 system/user 授权的信任标记
- **AND** 插件 SHALL NOT 把内容插入稳定安全前缀之前，且任何状态样式文本 SHALL NOT 替代 Runtime 重建的最新工作状态

#### Scenario: A tool schema is disclosed later

- **WHEN** `tool_search` 在当前 epoch 首次披露一个 deferred tool
- **THEN** Runtime SHALL 保持基础 stable-prefix hash 不变并追加持久披露记录
- **AND** effective tool schema hash SHALL 反映新增工具且后续编译保持稳定

### Requirement: Deterministic stable-prefix snapshots

Runtime SHALL 为每个 `(session key, conversation epoch)` 冻结并复用静态 prompt 版本、Skill catalog、规范化基础工具 schema 和布局版本，并 SHALL 为这些材料生成稳定哈希；按需披露工具 SHALL 位于独立追加层，新 epoch SHALL 获取新的快照和空披露范围，安全撤销 SHALL 使受影响快照或披露层 fail closed。

#### Scenario: Runtime state changes during an epoch

- **WHEN** 普通 Skill active 指针、插件注册状态或 MCP 发现顺序在 epoch 中途变化
- **THEN** 已冻结基础 snapshot SHALL 保持不变
- **AND** 除显式 Tool Search 披露和安全撤销外，非安全性变更 SHALL 仅影响后续新 epoch

#### Scenario: Capability changes before a later turn

- **WHEN** 一个 turn 已终止，且下一 turn 开始时有效 system prompt、Skill catalog、工具 schema 或布局版本的规范化指纹不同
- **THEN** Runtime SHALL 在同一 conversation epoch 中创建新的不可变 revision 并用于新 turn
- **AND** SHALL 保留旧 revision 供轨迹审计，不得要求用户执行 `/clear` 或丢弃既有对话历史

#### Scenario: Runtime restarts without capability changes

- **WHEN** Runtime 重启后恢复已有 session/epoch，且当前有效能力指纹与最新 revision 相同
- **THEN** Runtime SHALL 复用该 revision 及稳定哈希
- **AND** SHALL NOT 仅因进程实例变化制造新 revision 或无效化 Provider 前缀缓存

#### Scenario: Runtime restarts after capability changes

- **WHEN** Runtime 重启后恢复已有 session/epoch，且当前有效能力指纹与最新 revision 不同
- **THEN** 首个新 turn SHALL 自动创建并使用反映当前能力的新 revision
- **AND** 诊断和轨迹 SHALL 记录新增、删除或 schema 变化的能力差异

#### Scenario: A disclosed schema is restored

- **WHEN** Runtime 在同一 Session/epoch 重编译或重启恢复
- **THEN** ContextCompiler SHALL 按首次披露顺序恢复持久 schema 并验证其规范哈希
- **AND** SHALL NOT 依赖进程级 Registry 使用历史或其他 Session 的披露状态

#### Scenario: A new epoch starts

- **WHEN** 用户清理对话或 Runtime 显式创建下一 conversation epoch
- **THEN** 新 epoch SHALL 使用当时有效的 system、Skill 和基础工具 schema 创建独立快照
- **AND** SHALL NOT 复用旧 epoch 的披露记录、失效原因、archive frontier 或冻结动态内容

#### Scenario: A frozen capability is revoked for safety

- **WHEN** 已冻结 snapshot 或当前披露层中的工具被安全撤销
- **THEN** Runtime SHALL 立即拒绝使用并记录 snapshot 失效原因
- **AND** SHALL NOT 继续暴露或执行已撤销能力

#### Scenario: Capability is revoked for safety

- **WHEN** 已冻结 snapshot 中的 Skill 或工具被安全撤销
- **THEN** Runtime SHALL 立即拒绝使用并记录 snapshot 失效原因
- **AND** SHALL NOT 继续向模型声明该能力可用或静默替换为其他版本
