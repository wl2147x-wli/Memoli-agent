## MODIFIED Requirements

### Requirement: Deterministic stable-prefix snapshots

Runtime SHALL 为每个 `(session key, conversation epoch)` 保存不可变、单调递增的能力快照 revision；每个 revision SHALL 冻结静态 prompt 版本、Skill catalog、规范化工具 schema 和布局版本并生成稳定哈希。一次 turn 首次编译 SHALL 根据当时有效能力选择或创建 revision，该 turn 的后续模型与工具步骤 SHALL 固定使用同一 revision；后续 turn SHALL 在能力指纹变化时创建新 revision，而不要求创建新 conversation epoch。安全撤销 SHALL 立即使受影响快照 fail closed。

#### Scenario: Runtime state changes during an epoch

- **WHEN** 普通 Skill active 指针、插件注册状态、MCP 工具或基础工具 schema 在活动 turn 中途变化
- **THEN** 该 turn 已冻结的前缀和工具 schema SHALL 保持字节级稳定
- **AND** 非安全性变更 SHALL 仅在下一 turn 创建或选择新的能力 revision 后生效

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

#### Scenario: A new epoch starts

- **WHEN** 用户清理对话或 Runtime 显式创建下一 conversation epoch
- **THEN** 新 epoch SHALL 从 revision 1 使用当时有效的 system、Skill 和工具 schema 创建独立快照
- **AND** SHALL NOT 复用旧 epoch 的失效原因、archive frontier、披露记录或冻结动态内容

#### Scenario: Capability is revoked for safety

- **WHEN** 活动 revision 中的 Skill 或工具被安全撤销
- **THEN** Runtime SHALL 立即拒绝使用并记录 snapshot 失效原因
- **AND** SHALL NOT 继续向模型声明该能力可用或静默替换为其他版本

## ADDED Requirements

### Requirement: Capability snapshot revision audit

每次实际 Provider 请求 SHALL 标识所使用的 conversation epoch、能力 revision、稳定前缀哈希和工具 schema 哈希；revision 协调 SHALL 产生不包含工具秘密或完整敏感 schema 的有界差异诊断。

#### Scenario: A later turn activates a changed tool set

- **WHEN** 新 turn 因工具新增、删除或 schema 修改而创建能力 revision
- **THEN** 编译结果与轨迹 SHALL 记录旧/新 revision、旧/新工具哈希和分类后的工具名称差异
- **AND** 实际发送的工具集合 SHALL 与新 revision 保存的规范化 schema 完全一致

#### Scenario: Capability reconciliation cannot be persisted

- **WHEN** Runtime 检测到能力指纹变化但无法原子保存新 revision
- **THEN** 新 turn SHALL 在 Provider 调用前以稳定的 context state 错误结束
- **AND** SHALL NOT 静默复用已确认过期的工具快照或覆盖最后一个有效 revision
