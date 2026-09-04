## Why

Memoli 当前按 `(session key, conversation epoch)` 永久复用稳定前缀快照，启动后即使工具、Skill 或 system prompt 已变化也不重新核对；结果是已启用的 `memory_manage` 不会出现在旧会话中，而删除或改版后的能力也可能继续被模型看到。稳定性真正需要覆盖的是一次活动 turn/工具循环，而不应要求用户通过 `/clear` 丢弃当前对话上下文才能获得下一轮的最新能力。

## What Changes

- 在每个新用户 turn 开始时，以规范化 system prompt、Skill catalog、工具 schema 和布局版本计算当前能力指纹并与活动快照核对。
- 指纹变化时创建不可变的能力快照 revision；新 revision 只从下一 turn 生效，活动 turn/工具循环继续使用其开始时冻结的 revision。
- conversation epoch 继续管理对话清理、archive 与历史边界；能力更新不再隐式执行 `/clear`，也不删除已有历史。
- 对新增、删除和 schema 变化生成可审计差异与 revision/hash；安全撤销仍立即 fail closed。
- 迁移旧数据库快照为 revision 1，并在首次新 turn 时与当前能力自动协调，无需用户手工删除数据库。
- 不改变 `memory_manage` 的公开参数合同，不根据模型输出猜测可用能力，也不允许同一活动 turn 中途漂移工具集合。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `context-management`：将稳定能力快照的冻结边界从整个 conversation epoch 调整为带 revision 的 turn 间协调，同时保留 turn 内稳定性、缓存哈希和审计能力。
- `agent-runtime`：新 turn 自动采用最新有效能力，配置变化无需 `/clear`，活动 turn 继续使用已冻结能力。

## Impact

- 影响 ContextSnapshot 合同、ContextStateRepository/SQLite schema、ContextCompiler、turn 启动协调和上下文诊断。
- `context-state.db` 需要向后兼容迁移；trajectory、memory、working-state 与 Provider 协议不迁移。
- 稳定前缀发生变化时 Provider 缓存将按新 hash 自然失效；未变化的启动仍复用原 revision。
- 安全性提高：已删除工具不会继续被下一 turn 宣传，执行边界仍独立验证工具实际存在且未撤销。
