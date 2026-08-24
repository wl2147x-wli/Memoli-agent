## 1. 基线与回归保护

- [x] 1.1 为当前 Session 消息条数裁剪早于 archive 的行为添加失败回归测试，证明旧 turn 会在编译前丢失
- [x] 1.2 为 soft/hard 阈值、机械 archive 与仅在 Provider 超限后调用 TaskAwareCompactor 的现状添加行为刻画测试
- [x] 1.3 为 archive generation 全量注入、`/clear` 后旧 snapshot/archive 复现和新 session instance 复用旧快照添加回归测试
- [x] 1.4 为正文 marker 误分类当前用户消息、动态 block 被误设 required 和工具协议边界添加安全回归测试
- [x] 1.5 记录变更前关键 prompt fixture、context-state schema 与配置加载结果，供迁移阶段对照

## 2. conversation epoch 与 canonical turn 合同

- [x] 2.1 定义 conversation epoch、canonical turn/message、恢复等级、稳定顺序和终止资格的数据合同
- [x] 2.2 为 trajectory/context state 增加 additive schema migration，持久化 epoch、turn/message sequence、tool correlation、可见内容哈希与 capture/degradation 元数据
- [x] 2.3 在生命周期提交点记录输入、assistant tool-call、tool result 和最终 transformed user-visible output 的 canonical envelope
- [x] 2.4 确保 canonical envelope 排除隐藏 reasoning、敏感原文和训练/评价字段，并复用现有 payload 脱敏与外置策略
- [x] 2.5 实现按当前 epoch、已终止状态和稳定序号读取的 durable turn source，排除当前 trace、partial/cancelled/corrupt turn
- [x] 2.6 实现隔离的 in-memory complete-turn source，并在轨迹关闭、metadata-only 或不可读时返回 `restorable=false` 降级
- [x] 2.7 为旧事件实现仅标记为 `legacy-inferred` 的有界兼容读取，无法保持 tool/response fidelity 时排除完整 turn
- [x] 2.8 添加重启恢复、最终响应 transform、provider blocks、tool name/id/arguments/result 和损坏 payload 的 reader 测试

## 3. Session 与清理边界迁移

- [x] 3.1 将 Session 简化为 session key、conversation epoch 与瞬态控制状态，停止写入和读取消息历史副本
- [x] 3.2 实现 epoch repository 的原子 `current/create-next` 操作并处理并发 clear/turn 边界
- [x] 3.3 修改 `/clear`：拒绝活动 turn 期间清理，成功时创建新 epoch 并重置派生 context 状态，失败时保持旧 epoch
- [x] 3.4 使新 epoch 不再读取旧 turns、snapshot、frontier 或 preview，同时验证 trajectory、payload、memory 和 working-state 保留策略
- [x] 3.5 从 AgentConfig 和 bootstrap 删除 `history_window`，对旧字段返回含 `[context]` 迁移示例的专用配置错误
- [x] 3.6 添加 `/clear`、重启延续、epoch store 失败、并发 clear 和旧配置迁移测试

## 4. 结构化 Context Plan 与五层编译

- [x] 4.1 扩展 ContextBlock/TurnEnvelope，显式表达 kind、source、trust、priority、required、epoch、source refs 与 token metadata
- [x] 4.2 用结构化 block producer 替换正文 XML marker 分类，同时保留最终 provider wire format 的兼容渲染
- [x] 4.3 实现 stable prefix、archive frontier、recent complete turns、frozen tool evidence 与 governed dynamic tail 的统一 Context Plan
- [x] 4.4 将 pre-reduction candidate tokens 与 post-reduction request tokens 分开计算，并把 messages、tools 与协议开销纳入同一预算
- [x] 4.5 修正 required 集合，仅强制安全规则、当前用户输入、当前未完成工具协议和最小最新状态
- [x] 4.6 实现各层显式预算与确定性优先级，记录每层 candidate/kept/omitted tokens 和原因
- [x] 4.7 将模型 profile 连接 tokenizer adapter；无适配器时使用保守 estimator 并标记 `exact=false`
- [x] 4.8 添加 marker 注入、dynamic 降载、中文/JSON/tool schema token、稳定 prefix hash 与完整 tool group 的测试

## 5. 统一压缩协调器

- [x] 5.1 将编译拆为无副作用 plan 与异步 execute/validate/commit 协调器，定义 normal、soft、hard、emergency 模式
- [x] 5.2 按降载前候选比率实现 soft/hard 触发，并只选择最旧未覆盖的完整 turn/archive 批次
- [x] 5.3 统一 TaskAwareCompactor 输入 schema，携带当前目标/约束、完整 batch、direct source refs 和 parent archive refs
- [x] 5.4 校验压缩 JSON 固定字段、引用集合、epoch、禁止字段、token 预算、覆盖无环性与最小任务信息
- [x] 5.5 删除同步机械 `_archive` 路径；压缩 Provider 不可用时仅允许确定性预览、去噪和可观察候选省略
- [x] 5.6 使 soft 失败保留原可发送视图，hard/emergency 失败显式结束，并按 session/epoch 实现失败计数与熔断重置
- [x] 5.7 统一 Provider context-length 恢复：同 trace 最多一次，要求新请求 token 更少且 context hash 不同，不重复工具副作用
- [x] 5.8 添加 soft 成功/失败、hard 成功/拒绝、invalid JSON/ref、熔断、无 compactor 和 emergency 幂等测试

## 6. 有界 archive frontier 与原子提交

- [x] 6.1 扩展 context-state schema，保存 immutable archive level/generation、direct/parent refs、coverage hash、状态与活动 frontier
- [x] 6.2 在事务内分配 `(session, epoch)` generation，并原子提交 archive、coverage、frontier、失败状态和 outbox
- [x] 6.3 对 source coverage、frontier 非重叠和 archive id 添加唯一约束，处理并发/重试冲突为幂等结果
- [x] 6.4 实现 `archive_frontier_tokens` 与 `archive_frontier_max_items`，Provider 请求只注入有界活动 frontier
- [x] 6.5 实现最旧相邻 frontier 节点的分层合并，新节点成功前保留父节点、成功后原子替换
- [x] 6.6 实现 context audit outbox 的幂等投递、重试和 pending/failed 诊断，不让 hook/trajectory 故障回滚已提交 context state
- [x] 6.7 实现 source reader 的 turn/byte 上限、稳定 continuation 与分批压缩推进，禁止把读取截断等同于历史不存在
- [x] 6.8 添加 frontier 长时间有界、重叠拒绝、合并失败回滚、并发 generation、outbox 重放和 source continuation 测试

## 7. 工具预览、快照与隔离

- [x] 7.1 将 stable snapshot 主键与查找迁移为 `(session key, conversation epoch)`，新 epoch 重新冻结有效 system/Skill/tool schema
- [x] 7.2 实现安全撤销 fail-closed：停止暴露和执行已撤销能力并记录 snapshot invalidation
- [x] 7.3 将 FrozenToolPreview 绑定 epoch、canonical tool message hash 与 tool call id，恢复前验证引用完整性
- [x] 7.4 实现 preview 派生索引的 epoch 清理/不可见状态，同时保持原始 payload 独立保留策略
- [x] 7.5 通过可选 ContextSource 依赖只为主被动 turn 装配 durable 恢复，保持 memory-governor 与普通 SubAgent 默认隔离
- [x] 7.6 添加快照跨 epoch、工具新增/撤销、preview 损坏/清理、payload 权限和 SubAgent 隔离测试

## 8. 配置、诊断与操作界面

- [x] 8.1 在 `[context]` 增加 source read turn/byte、compaction batch、archive frontier token/item 配置与严格校验
- [x] 8.2 更新 runtime inspection/CLI context 诊断，显示 epoch、恢复等级、pre/post ratio、各层预算、frontier、压缩模式、熔断与 outbox 状态
- [x] 8.3 确保诊断只记录哈希、计数、稳定引用和安全原因，不暴露 API key、隐藏 reasoning、embedding 或未脱敏 payload
- [x] 8.4 更新 `config.example.toml` 与配置测试，覆盖默认值、边界值、旧 `history_window` 迁移错误和 compaction disabled 行为

## 9. 集成验证与文档

- [x] 9.1 添加端到端长会话测试，覆盖多轮工具调用、soft archive、frontier 合并、重启恢复、`/clear` 后从零开始和最终 Provider 请求一致性
- [x] 9.2 添加 capture full-local/redacted/metadata-only、trajectory disabled、context persistence disabled 和数据库损坏的降级矩阵测试
- [x] 9.3 添加 cache 稳定性测试，验证 stable prefix/tool schema hash 不被动态尾部、archive 合并或重编译无故改写
- [x] 9.4 运行相关 context/session/trajectory/tool/CLI/SubAgent 测试并修复回归
- [x] 9.5 运行 `python -m pytest -q`、`python -m ruff check memoli_agent benchmarks tests` 和 `python -m pyright`
- [x] 9.6 更新上下文管理、Agent Runtime、工具轨迹、配置迁移与 `/clear` 运维文档
- [x] 9.7 运行 `openspec validate --all --strict` 并确认本 change 与 canonical specs 无冲突
