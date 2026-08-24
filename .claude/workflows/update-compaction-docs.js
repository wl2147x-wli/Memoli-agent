export const meta = {
  name: 'update-compaction-docs',
  description: '§9.6 重写 context-compaction 相关文档以匹配已实现行为',
  phases: [
    { title: 'Rewrite', detail: '并行重写三份文档（各持 ground-truth 代码指针 + 术语表）' },
    { title: 'Review', detail: '跨文档准确性/一致性/无密钥诊断复核并直接修正' },
  ],
}

// ── 权威来源 ──
const DESIGN = 'd:/wli/project1/Memoli-agent/openspec/changes/complete-layered-context-compaction/design.md'
const PROPOSAL = 'd:/wli/project1/Memoli-agent/openspec/changes/complete-layered-context-compaction/proposal.md'

// ── ground-truth 代码指针（文档必须匹配代码，而非仅 design 意图）──
const CODE = {
  config: 'memoli_agent/bootstrap/config.py  (ContextManagementConfig ~L211-269；history_window 迁移错误 ~L1030-1040)',
  exports: 'memoli_agent/agent/context_management/__init__.py  (canonical 导出清单)',
  compiler: 'memoli_agent/agent/context_management/compiler.py  (五层 plan、有界 frontier L62/L497/L522)',
  compaction: 'memoli_agent/agent/context_management/compaction.py  (plan→execute→commit 协调器、合并 L221)',
  cross_turn: 'memoli_agent/agent/context_management/cross_turn.py  (CommittedTurn/RestorationLevel/ContextSource/envelope_to_committed_message L201)',
  models: 'memoli_agent/agent/context_management/models.py  (ContextBlock/TurnEnvelope/ContextArchive/OutboxEvent/LayerBudget)',
  repository: 'memoli_agent/agent/context_management/repository.py  (frontier、原子事务、generation 分配)',
  clear: 'memoli_agent/channels/commands.py  (/clear：活动 turn 拒绝、advance_epoch、reset_session、旧 epoch 预览不可见)',
  trajectory: 'memoli_agent/agent/trajectory.py  (conversation_epoch、SCHEMA 迁移、current_epoch_sync 纯读)',
  inspection: 'memoli_agent/bootstrap/inspection.py  (诊断字段 L262-281：epoch/frontier/source 上限)',
  reasoner: 'memoli_agent/agent/core/reasoner.py  (预算检查 loop 顶 L316、compaction L348-422、frontier 合并 L1149)',
  phases: 'memoli_agent/agent/lifecycle/phases.py  (CrossTurnContextPhase L95-131、AfterReasoningPhase turn_output_committed)',
}

// ── 术语表（三份文档统一用词，禁止杜撰）──
const GLOSSARY = `
CANONICAL GLOSSARY（务必使用这些确切术语）：
- 五层 Context Plan：1.稳定前缀(Stable Prefix) 2.有界归档前沿(Archive Frontier) 3.近期完整 turn(Recent Complete Turns) 4.冻结工具证据(Frozen Tool Evidence) 5.受管动态尾部(Governed Dynamic Context)。最终 Provider 排列 cache 友好：stable prefix → archive frontier → recent turns → governed dynamic tail。
- conversation_epoch：每个 session_key 持久、单调递增的 epoch；/clear 推进，进程重启不推进（不靠易变的 session_instance_id 截断）。
- 规范化 committed turn：跨轮可重放事实来源；Session 仅持有 {session_key, conversation_epoch, 瞬态控制}，已删除 history_window 与消息副本。
- committed 事件（实现侧名）：turn_input_committed / assistant_message_committed / tool_message_committed / turn_output_committed；turn_output_committed 在 RESPONSE_TRANSFORM 之后记录。
- RestorationLevel（4 级恢复）：EXACT / GOVERNED / LEGACY_INFERRED / UNAVAILABLE。
- 压缩协调器：plan → execute → validate → commit；soft/hard/emergency 复用同一 TaskAwareCompactor；已删除同步机械 _archive（role-gated JSON stuff-and-pop）。
- 有界 archive frontier：archive_frontier_tokens（聚合注入 token 上限）+ archive_frontier_max_items（节点数上限）；活动 frontier 覆盖互不重叠；超限时最旧相邻 archive 合并为更高 level，事务提交后才替换父节点。
- 原子提交：context-state.db 单事务写 archive/coverage/frontier/generation/失败计数/outbox；outbox 幂等重放 context_compaction_committed，hook/轨迹失败不回滚已成立 context state。generation 由事务内 (session,epoch) 计数器分配，非 len(archives)+1。
- 稳定快照键：(session_key, conversation_epoch)；安全撤销 fail-closed（停止执行 + 记录 snapshot 失效）。
- 冻结工具预览(FrozenToolPreview)：绑 epoch + 规范化 tool message hash + tool_call_id；恢复前校验 preview hash/payload reference/tool_call_id；校验失败排除整 turn 或可观察协议错误，不拆 tool pair。
- token 估算：model profile → tokenizer adapter；无适配器用 ConservativeTokenEstimator 并标 exact=false。required 仅 = 静态安全规则 + 当前用户输入 + 当前未完成工具协议 + 最小最新状态。
- 诊断：记 epoch/恢复等级/pre-post ratio/各层候选-保留-省略量/压缩收益/frontier/估算器/恢复能力/降级原因；绝不暴露 API key、隐藏 reasoning、embedding、未脱敏 payload（capture_content=redacted 默认脱敏）。
- /clear：活动 turn 期间拒绝；成功 → 创建新 epoch + 重置派生 context 状态（编译快照/frontier/失败计数/冻结预览可见索引）；失败 → 保持旧 epoch 并明示未完成；旧 committed turn/原始 trajectory/payload/长期记忆/working-state 按各自策略保留但不进入新 epoch 上下文。
- SubAgent 隔离：默认创建独立非恢复 epoch source，自建 Reasoner 绕过 phase 链，不获跨轮 durable source；仅显式装配相同协议 profile 才启用跨轮恢复。
`

// ── [context] 配置旋钮（ground truth，config.py:211 ContextManagementConfig）──
const CONFIG_KNOBS = `
[context] 旋钮（ContextManagementConfig，memoli_agent/bootstrap/config.py:211-237，defaults 与校验见 __post_init__）：
enabled=true, compaction_enabled=true, persistence_enabled=true, database="workspace/context-state.db",
soft_threshold_ratio=0.75, hard_threshold_ratio=0.90, recent_tail_tokens=12000, preview_tokens=2000,
archive_tokens=4000,
archive_frontier_tokens=16000 (新增 §8.1：跨所有注入 archive 的聚合 token 预算，区别于 per-archive archive_tokens),
archive_frontier_max_items=8 (新增 §8.1：frontier 节点数上限),
source_read_max_turns=None (新增 §8.1：跨轮来源单次读取 turn 上限；None=不限；I/O 防护，非语义历史窗口，到达上限返回 continuation/source-truncated 诊断),
source_read_max_bytes=None (新增 §8.1：跨轮来源单次读取字节上限；None=不限),
compaction_batch_tokens=32000 (新增 §8.1：单次压缩批次 token 硬上限，达上限即停止扩充批次),
plugin_max_tokens=2000, emergency_retry_limit=1 (仅 0 或 1), compaction_failure_limit=2, compaction_profile="" (留空复用 agent/default；禁指向 Echo)
history_window：已移除（§3.5）；旧配置启动报迁移错误并给精确示例（config.py ~L1030-1040）。
`

const RULES = `
通用规则：
1. 全程中文正文，匹配现有 docs/systems/*.md 的标题风格与散文口吻（保留其代码块 toml 风格）。
2. 只文档 ground-truth 代码中真实存在的旋钮/概念/事件名（见术语表与配置清单）；禁止杜撰未实现的名字。
3. 读现有文档，保留仍准确的内容与结构；仅更新过时部分 + 补充新概念。context-management.md 需大幅重写（四区→五层）；另两份做定向更新，勿整篇替换。
4. 文件内删除你引入的死代码/重复段落；不留 TODO 占位。
5. 诊断相关章节必须遵守：不暴露 API key、隐藏 reasoning、embedding、未脱敏 payload。
6. 用 Edit/Write 落盘；改完返回「改了哪些章节 + 关键事实核对结论」简短清单。
`

phase('Rewrite')

const DOCS = [
  {
    file: 'docs/systems/context-management.md',
    scope: `大幅重写（四区布局 → 五层 Context Plan）。必须覆盖：
- 五层 Context Plan（五层名 + cache 友好最终排列）替旧"四区布局"；明确层 2/3 是逻辑优先级，不破坏 wire format 中 tool call/result 邻接。
- 跨轮事实来源：conversation_epoch + 规范化 committed turn；Session 仅存身份（删 history_window）；4 个 committed 事件（turn_output 在 RESPONSE_TRANSFORM 后）；RestorationLevel 4 级；durable TrajectoryContextSource + InProcessTurnSource/LegacyTurnSource 降级；reader 只读当前 epoch 已终止且顺序完整 turn，排除当前 trace/running/cancelled/损坏。
- /clear 与 epoch：活动 turn 拒绝；推进 epoch + 重置派生 context 状态；失败保持旧 epoch；旧 trajectory/payload/长期记忆/working-state 各自保留但不进新 epoch。
- 统一压缩协调器 plan→execute→validate→commit（soft/hard/emergency 复用 TaskAwareCompactor）；已删机械 _archive；无 compactor 时只允许确定性去噪/冻结预览/有诊断候选省略；熔断 compaction_failure_limit；Provider context-length 同 trace 至多一次 emergency 重试（新 hash + 更少 token + 不重执工具）。
- 有界 archive frontier：archive_frontier_tokens/max_items；覆盖不重叠；最旧相邻合并为更高 level；原子提交 context-state.db + outbox 幂等重放；generation 事务内分配。
- 大工具结果：冻结预览绑 epoch + canonical tool message hash + tool_call_id；恢复前校验；失败排除整 turn 或可观察协议错误不拆 pair；/clear 标旧 epoch 预览不可见不删行、payload 保留。
- 渐进工具 schema：稳定快照键 (session_key, epoch)；安全撤销 fail-closed + snapshot 失效。
- token 估算：model profile → tokenizer adapter；无适配器 ConservativeTokenEstimator exact=false；required 定义；诊断记 pre/post tokens + 各层候选/保留/省略 + 估算器。
- 诊断章节（§8.3 红线）：记 hash/计数/稳定引用/安全原因，绝不暴露 API key/隐藏 reasoning/embedding/未脱敏 payload。
- 配置与数据保留：完整 [context] toml（含 5 个新旋钮 + defaults + history_window 移除迁移说明）；context-state.db 与 trajectory/memory/working-state/skill 各库独立；关 [context].enabled 可回滚但库不自动删。
保留仍准确的 KV/Prompt Cache 边界章节。`,
  },
  {
    file: 'docs/systems/agent-runtime.md',
    scope: `定向更新（勿整篇替换）。覆盖：
- Session 简化为 {session_key, conversation_epoch, 瞬态控制}；删除 history_window/_history/SessionMessage/add_*_message/get_history/_trim_history（§3.1）；context.py get_history 循环已删；phases.py AfterReasoningPhase 死写已删。
- 生命周期提交点记录 4 个 canonical committed 事件（turn_input/assistant_message/tool_message/turn_output_committed；turn_output 在 RESPONSE_TRANSFORM 之后）；payload 复用 _message_dicts（已处理 blocks/脱敏），排除隐藏 reasoning/敏感原文/训练评价字段。
- /clear 推进 conversation_epoch（原子 current/create-next；并发由 SQLite BEGIN IMMEDIATE 串行化）；重启读当前持久 epoch 不截断。
- 预算检查在 reasoner while-loop 顶部（BUDGET_EXHAUSTED）先于工具执行（如已文档化则校准措辞）。
- SubAgent 隔离：自建 Reasoner 绕过 phase 链，默认不获跨轮 durable source；仅主被动 turn 装配 CrossTurnContextPhase（插在 PromptRenderPhase 与 ReasonerPhase 之间）。
仅改与上述相关的过时段落；保留文档其余结构。`,
  },
  {
    file: 'docs/systems/tools.md',
    scope: `定向更新（勿整篇替换）。覆盖：
- 冻结工具预览(FrozenToolPreview) 绑 conversation_epoch + 规范化 tool message hash + tool_call_id；恢复前校验 preview hash/payload reference/tool_call_id；校验失败排除整 turn 或可观察协议错误，不拆 tool call/result pair（§7.3）。
- 稳定快照键 (session_key, epoch)（§7.1）；安全撤销 fail-closed（停止暴露/执行 + 记 snapshot 失效原因，不向模型宣称已撤销工具可用）（§7.2）。
- 工具 trajectory payload 服从 trajectory 策略保留；/clear 不隐式删 payload，仅把旧 epoch 派生预览索引标记不可见/清理（§7.4）。
- 受管 payload 引用不是读取权限，重新读取仍经原有 workspace/scope/tool 权限（保留此既有正确表述）。
仅改与上述相关的过时段落；保留文档其余结构。`,
  },
]

const REWRITE_PROMPT = (d) => `你在为 OpenSpec change "complete-layered-context-compaction" 更新文档（§9.6）。

目标文件：${d.file}
更新范围：${d.scope}

权威来源（必读）：
- 设计决策：${DESIGN}
- 提案：${PROPOSAL}
- ground-truth 代码（文档须匹配代码，必读相关项）：
  - ${CODE.config}
  - ${CODE.exports}
  - ${CODE.compiler}
  - ${CODE.compaction}
  - ${CODE.cross_turn}
  - ${CODE.models}
  - ${CODE.repository}
  - ${CODE.clear}
  - ${CODE.trajectory}
  - ${CODE.inspection}
  - ${CODE.reasoner}
  - ${CODE.phases}

${GLOSSARY}
${CONFIG_KNOBS}
${RULES}

先 Read 目标文件 ${d.file} 与上述关键代码，再用 Edit 定向更新（context-management.md 允许 Write 整篇重写）。完成后返回简短清单：改了哪些章节、核对到的关键事实、是否发现代码与 design 不一致（若有，列出位置，勿改代码）。`

const rewrites = await parallel(
  DOCS.map((d) => () =>
    agent(REWRITE_PROMPT(d), {
      label: `rewrite:${d.file.split('/').pop()}`,
      phase: 'Rewrite',
      agentType: 'general-purpose',
    })
  )
)

phase('Review')

const REVIEW_PROMPT = `你是 §9.6 文档复核者。三份文档刚被重写以匹配 OpenSpec change "complete-layered-context-compaction" 的已实现行为。

目标文件：
- docs/systems/context-management.md
- docs/systems/agent-runtime.md
- docs/systems/tools.md

ground-truth 代码（复核基准，务必 Read 核对）：
- ${CODE.config}（核对每个 [context] 旋钮名/默认值/校验）
- ${CODE.exports}（核对概念名）
- ${CODE.cross_turn}（RestorationLevel 4 级、envelope_to_committed_message）
- ${CODE.clear}（/clear 语义）
- ${CODE.inspection}（诊断字段——§8.3 红线：不得暴露 API key/隐藏 reasoning/embedding/未脱敏 payload）
- ${CODE.repository}（frontier/原子事务/generation）

${GLOSSARY}
${CONFIG_KNOBS}

复核清单（逐项过，发现问题用 Edit 直接修正）：
1. 无过时引用残留：四区布局、history_window 作为有效配置、同步机械 _archive、把 source_read_max 当语义历史窗口、recent_tail 称"上游兼容硬上限"等过时措辞——若有则修正或删除。
2. 五层 Context Plan 完整且五层名正确；cache 友好最终排列正确。
3. 五个新增 [context] 旋钮（archive_frontier_tokens=16000、archive_frontier_max_items=8、source_read_max_turns=None、source_read_max_bytes=None、compaction_batch_tokens=32000）均出现且默认值正确；history_window 移除迁移说明存在。
4. /clear 语义正确：活动 turn 拒绝、推进 epoch、失败保持旧 epoch、旧 trajectory/payload/记忆保留但不进新 epoch。
5. 压缩协调器 plan→execute→validate→commit、soft/hard/emergency 复用 TaskAwareCompactor、熔断、emergency 同 trace 至多一次。
6. 有界 frontier：覆盖不重叠、最旧相邻合并为更高 level、原子事务 + outbox 幂等重放、generation 事务内分配（非 len+1）。
7. 冻结预览：绑 epoch + tool message hash + tool_callid、恢复前校验、失败不拆 pair。
8. §8.3 红线：诊断章节只记 hash/计数/稳定引用/安全原因，无 API key/隐藏 reasoning/embedding/未脱敏 payload 字样或示例。
9. 跨文档术语一致（同一概念三份文档用同一术语，见术语表）。
10. 无杜撰的未实现旋钮/概念名。

返回：逐项结论（pass/已修正+位置/仍存问题），以及任何"文档声称但代码未实现"或"代码实现但文档未提"的缺口。`

const review = await agent(REVIEW_PROMPT, {
  label: 'review:cross-doc-accuracy',
  phase: 'Review',
  agentType: 'general-purpose',
})

return {
  rewrites: rewrites.filter(Boolean),
  review,
}
