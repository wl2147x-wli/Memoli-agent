## MODIFIED Requirements

### Requirement: Cache-aware context layout

Runtime SHALL 以稳定前缀、追加式披露层、动态状态、历史轨迹和可合并 archive 的顺序编译模型输入；基础前缀 SHALL 在 conversation epoch 内保持字节级稳定，Tool Search 首次披露 SHALL 作为不可变后缀事实进入当前 epoch 而不重写基础快照。

#### Scenario: First decision in an epoch is compiled

- **WHEN** Runtime 为新 conversation epoch 的首次模型决策编译上下文
- **THEN** 基础 system prompt、该 epoch 冻结的 Skill catalog 和基础工具 schema SHALL 形成确定性稳定前缀
- **AND** 变化频率更高的状态、轨迹与后续工具披露 SHALL 位于稳定前缀之后

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
