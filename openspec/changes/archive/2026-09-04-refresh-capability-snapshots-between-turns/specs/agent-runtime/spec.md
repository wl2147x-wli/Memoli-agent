## ADDED Requirements

### Requirement: Turn-bound capability activation

Runtime SHALL 在新用户 turn 的模型调用前自动协调当前有效能力，并在该 turn 的整个 Provider 工具循环中固定同一个能力快照 revision；普通能力变化 SHALL 不清除会话历史，安全撤销 SHALL 保持立即拒绝语义。

#### Scenario: A configured tool is enabled between turns

- **WHEN** 某工具在上一 turn 后启用且新 turn 开始时已成功注册
- **THEN** 新 turn 的首个模型请求 SHALL 包含该工具的当前 schema
- **AND** 用户 SHALL NOT 需要重启、执行 `/clear` 或猜测旧快照状态

#### Scenario: A configured tool is removed between turns

- **WHEN** 某工具在上一 turn 后被禁用或不再成功注册
- **THEN** 新 turn 的模型请求 SHALL NOT 继续声明该工具可用
- **AND** 工具执行层 SHALL 继续拒绝任何不属于该 turn 冻结 revision 的调用

#### Scenario: Capability changes during a tool loop

- **WHEN** 模型已经在当前 turn 中产生工具调用，随后 Runtime 的普通能力集合发生变化
- **THEN** 工具结果续接及当前 turn 后续模型请求 SHALL 继续使用 turn 开始时冻结的 revision
- **AND** 变化 SHALL 在下一 turn 生效，不得破坏现有 tool call/result 关联

