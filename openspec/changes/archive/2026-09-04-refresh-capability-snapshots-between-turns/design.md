## Context

见 `proposal.md`。当前 `ContextCompiler._snapshot()` 只按 `(session_key, epoch)` 查找快照，命中后立即返回；持久化的 `session_instance_id` 与当前 system、Skill、工具哈希均不参与协调。因此进程重启可以恢复缓存稳定性，但也会无限期恢复已经过期的能力集合。当前安全撤销只能处理进程内显式 revoke，无法完整覆盖重启后的配置新增、删除或 schema 修改。

现有 conversation epoch 同时承担用户清理语义、历史读取、archive/frontier、冻结预览和能力快照边界。工具稳定性实际只要求覆盖一个串行 turn/Provider 工具循环；把能力更新绑定 `/clear` 会无必要地退出当前历史上下文。

## Goals / Non-Goals

**Goals:**

- 普通工具、Skill 和静态前缀变化在下一 turn 自动生效。
- 同一 turn 的多次 Provider 调用固定使用完全相同的基础能力 revision。
- 不改变 conversation epoch、既有消息恢复和 `/clear` 的用户语义。
- 保留每个历史 revision，使轨迹能够解释当时实际发送的 schema。
- 旧数据库自动迁移且不需要删除 `context-state.db`。

**Non-Goals:**

- 不允许工具在一个活动 turn 中热替换。
- 不改变 Tool Search 的显式披露授权，也不让模型凭名称调用未披露工具。
- 不保存或恢复跨进程未完成的 Provider 工具循环。
- 不改变工具自身参数合同、权限或副作用策略。

## Decisions

### 1. 快照增加单调 revision，epoch 保持历史边界

SQLite `snapshots` 增加 `revision`，主键调整为
`(session_key, conversation_epoch, revision)`。每个 epoch 的 revision 从 1 开始，旧行迁移为 revision 1。读取接口区分“最新 revision”和“按 revision 精确读取”，保存采用事务内 `MAX(revision)+1` 与唯一约束，冲突时重读并按指纹幂等收敛。

不选择自动推进 epoch，因为那会让工具配置变化等同于清空对话；不选择原位覆盖旧快照，因为会破坏历史审计和并发 turn 的固定引用。

### 2. 在 turn 第一次编译时协调，随后显式 pin

Reasoner 为每个 `run_turn` 保存局部 `capability_revision`。第一次 compile 传入未绑定状态，Compiler 规范化当前 system、Skill、base tools 与 layout 并计算指纹：与最新 revision 相同则复用，否则追加新 revision。编译结果返回 revision，Reasoner 后续普通重编译、压缩后重编译和 emergency 重试都显式传回该 revision。

精确读取已 pin revision 时，如果其被安全撤销则 fail closed；普通配置变化不修改当前 revision，只会被下一 turn 的未绑定协调观察到。

不以 `session_instance_id` 是否变化作为刷新条件，因为无配置变化的重启不应制造缓存抖动；该字段继续作为创建来源诊断。

### 3. 指纹基于规范内容，差异基于名称与单项 schema hash

能力指纹沿用规范 JSON、system hash、Skill hash、tool hash 和 layout version。新旧不同后，诊断计算：

- `added_tools`
- `removed_tools`
- `changed_tools`
- `system_prompt_changed`
- `skill_catalog_changed`
- `layout_changed`

轨迹保存 revision、聚合 hash 与上述名称级差异，不额外复制可能含敏感描述的完整 schema。实际 `model_requested.tools` 仍按现有 capture 策略审计。

### 4. Tool Search 披露与能力 revision 对齐

`tool_disclosures` 增加 revision 维度。新基础 revision 创建时，仅继承仍存在、名称和 schema hash 均相同且当前仍允许披露的记录；删除或变更项不继承。活动 turn 新披露只附着到其 pin 的 revision，后续 Provider 步骤可看到该披露，其他并发 turn 不被中途改变。

这比继续仅按 epoch 保存披露更安全，避免新基础快照与旧披露同名重叠，也防止被移除的延迟工具通过旧披露复活。

### 5. 过期快照绝不静默降级

如果检测到不同指纹但新 revision 无法持久化，Compiler 在联网前返回专用 context state 错误。它不能退回旧 revision，因为旧 revision 已被确认不代表当前能力；也不能临时使用未审计 schema。

安全撤销继续优先：执行层立即拒绝，活动 revision 标记 invalidated，当前 turn 停止；下一 turn 可从当前有效集合生成新 revision。

## Risks / Trade-offs

- [首次能力变化会降低 Provider 前缀缓存命中] → revision 仅在规范指纹变化时创建，普通重启继续复用。
- [并发 turn 同时发现变化可能竞争 revision] → SQLite 事务和唯一约束分配 revision，指纹相同的竞争者重读后复用同一结果。
- [SQLite 主键迁移失败可能阻止启动] → 在单事务中建新表、复制 revision 1、校验行数后换表；失败整体回滚。
- [Tool Search 披露迁移复杂] → 旧披露迁移到其 epoch 的 revision 1；新 revision 只复制当前可验证的相同 schema。
- [历史 revision 增长] → 只在 hash 变化时追加，暂不删除；未来可单独增加保留策略，但不得破坏轨迹引用。

## Migration Plan

1. 提升 context-state schema version，在事务中把旧 snapshot 与 disclosure 行迁移到 revision 1。
2. 发布支持 revision 的 Repository 与 Compiler；旧数据库首次打开自动迁移，新数据库直接创建新 schema。
3. 为 Reasoner、生命周期 phase、压缩和 emergency 路径接入 turn-local pin，并把 revision 写入编译诊断和轨迹。
4. 用旧版 fixture 验证升级后首次未变化 turn 复用 revision 1；能力变化则创建 revision 2 且历史仍可见。
5. 回滚应用代码前必须回滚数据库备份；旧二进制不能读取新复合主键 schema，因此该迁移属于需要备份的存储升级。
