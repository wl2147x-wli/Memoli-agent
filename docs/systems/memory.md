# Memoli-agent 证据化记忆系统

当前实现把六类状态明确分开：Session Context 保存近期完整对话与不可变任务内
archive；Working State 保存可恢复任务进度；SQLite trajectory 与受管 payload 是
完整运行证据；Personal Memory 保存经治理的用户事实与卡片；Procedural Skill 仍
保持独立，本阶段只产生 skill candidate，不会自动发布 Skill 或训练数据。Context
archive、冻结工具预览和压缩诊断都是派生模型视图，不会自动写入 Personal Memory。

## 在线与离线双循环

在线 turn 先把当前用户消息、checkpoint objective/current step、session、scope 和
时间边界组成结构化查询。当前用户消息始终是主意图，checkpoint 只是辅助上下文。
检索通过关键词、可选向量和元数据三路取候选，先执行 scope/status/sensitivity/
valid-time 硬过滤，再使用 RRF 融合、稳定并列规则和 Card/Claim/Episode 类型预算构造
`<memory_context trust="data">`。记忆始终作为数据，历史网页、工具输出和
Assistant 文本不能冒充系统指令。完整对话只写 `trajectory.db`，不再追加
`HISTORY.md`。

离线 consolidation 不再逐回合扫描。Trigger Coordinator 只在同一 `cli:` session
累积到 20 条未消费普通回合，或单条已完成 trace 至少包含 10 次成功 business 工具
调用且满足“至少两种业务工具或持续 60 秒”时创建请求。`start_long_term_update`
只保存 `waiting-for-trigger` hint，不能绕过触发边界。提取只读取每条 trace 的当前
用户 SourceSegment；Episode 仍读取完整 timeline。隐式推断默认只能进入 `candidate`；显式用户
事实或人工批准才可发布为 `active`，frozen 冲突必须人工处理。Personal Memory、
Skill、评测和后训练候选具有不同分类边界，本阶段只发布 Personal Memory。

### 在线证据层与离线整理层的写入合同

`remember`/`correct` 属于**在线证据层**：`content` 必须与当前用户消息中逐字
`basis_quote` 一致（可去掉“请记住/记住/remember”指令包装），模型不得改写人称、
加注或润色；无 `basis_quote` 或 `content` 与逐字依据不一致会被拒绝，错误码分别为
`missing-explicit-basis` 与 `basis-content-mismatch`，拒绝信息会指明“逐字复制原话”
的自纠正指引。单条显式用户陈述即可作为证据写入，但**是否沉淀为稳定语义记忆由离线
整理层决定**——归纳、抽象、消歧与冲突合并不属本工具职责，离线 consolidation 才把
隐式推断默认归入 `candidate`、把显式事实或人工批准发布为 `active`。

这条合同防止“同一个模型既当裁判又直接改写正式记忆”：在线只锚定真实用户原话作
证据，离线才在治理门槛下聚合/诊断/生成候选修改并经验证发布。其实现规则位于
`memoli_agent/agent/tools/builtin.py`（`remember`/`correct` 校验与 `_same_fact`），
触发边界与候选有效率由 `stabilize-triggered-memory-learning`、离线 Worker/
Extractor/Governance SubAgent/consolidation 闭环由 `complete-offline-memory-learning`
各自负责；本合同只澄清工具描述与拒绝信息如何传达这两层分工，不放松逐字合同、
不改变 `correct` 的 versioned supersede，也不触碰触发阈值或离线整理层。

## 数据与索引

- `working-state.db`：独立 schema-versioned 工作状态库，使用 expected revision
  原子 patch，支持 stale 标记与显式恢复；关闭个人记忆不会关闭它。
- `trajectories.db`：唯一 append-only 原始运行证据，也是 Episode 原始细节来源。
- `context-state.db`：独立 schema-versioned Session snapshot、不可变 archive、source
  refs、冻结 preview 和压缩熔断状态；不迁移或改写 trajectory、memory 或 working state。
- `memory.db`：append-only claims、多对多 evidence、版本化 cards、关系、修订、
  consolidation run、可重建 trajectory segments、semantic index 和派生任务状态。
- 当前 SQLite schema 为 v7，启用外键和 `busy_timeout`。Claim 仅在同一 scope 内对
  `candidate/active/approved/frozen` 做部分唯一约束；历史的 deleted、rejected 和
  superseded 不阻止用户重新记住相同内容。

Working State 的模型表示只有一条调用前装配路径：`PromptRenderPhase` 不生成遗留
`<working_checkpoint>`，Reasoner 每次调用 Provider 前从当前 revision 重建唯一
`<agent_status>`。其中 Runtime 状态和 `runtime_artifacts` 是硬状态；Agent 提交的
objective、current step、next action、key info、constraints、decisions、related SOP
与 `agent_artifacts` 是软 checkpoint，不能覆盖 Runtime 已验证事实。
- 检索使用统一 `memory_search` 表（trigram tokenizer + `bm25()`）为 Claim、当前
  Card statement 与 Episode 提供严格 FTS 召回；schema 7 迁移会从权威表回填该
  派生 sparse 索引并在发布成功后才移除旧搜索表，失败回滚不改写权威记忆。FTS5/
  trigram 不可用时探测为 unavailable，Pattern（有界 LIKE OR，≤16 term，转义
  `%`/`_`）、semantic 与 metadata lane 继续独立工作，结果标记 `degraded=true`。
- 语义向量以带 model/version/dimensions/content-hash 的 float32 BLOB 保存在 SQLite；
  当前实现先做元数据预过滤，再进行精确余弦扫描。向量和 sparse 索引都是派生数据，
  可以删除重建，不能替代 Claim、CardVersion 或 trajectory。

MemOS 风格混合召回把 FTS、Pattern、semantic、metadata 视作四条独立 lane：各 lane
先在 SQL 内下推 scope/状态/敏感度/有效时间 hard filter 再取 lane 内 top-K，按 stable
identity 去重聚合后融合 `fused = max(norm) + rrf_bonus_weight × Σ(weight/(rrf_k+rank))`
（默认 `rrf_k=60`、`bonus=0.4`）。各 lane 用自己的规范化：FTS/Pattern 为 `1/rank`、
semantic 为裁剪到 `[0,1]` 的余弦、metadata 为固定低相关分；raw BM25 标量仅用于安全
诊断，不进入跨 lane 加法。随后依次施加相对阈值（默认 0.2）、多 lane 保护、按类型
smart seed、确定性 MMR（优先复用同版本缓存向量，否则 token/CJK bigram Jaccard，绝不
在线请求 embedding）与类型/数量/字符预算。`keyword_weight` 已移除：严格全文召回改用
`fts_weight`，宽松 Pattern 召回改用 `pattern_weight`。所有 lane 都必须提供非空稳定 ID；
Embedding 未配置、超时、维度错误或索引过期时，当前 turn 不等待补建，继续使用其他 lane
并在 `degraded_lanes` 中记录降级原因。

claim/card 状态包括 `candidate`、`active`、`approved`、`frozen`、`superseded`、`rejected`
和 `deleted`；关系包括 `supports`、`corrects`、`contradicts`、`supersedes` 和
`derived-from`。召回会在检索前过滤 user/session/project scope、有效时间、状态与
敏感等级，每个命中返回稳定 ID、current 状态、证据引用和 recall reason。
`approved` 属于 current；历史状态不能被自动复活，Frozen 只能由用户或人工 actor
解冻/删除。查询诊断还返回 `truncated`、`omitted_items` 和 `omitted_chars`。

## 配置

```toml
[memory]
enabled = true
engine = "sqlite"
path = "workspace/memory"       # 仅用于 legacy Markdown 迁移
database = "workspace/memory.db"
auto_recall = true
core_card_limit = 8
core_card_chars = 4000
recall_limit = 8
recall_chars = 8000
consolidation_enabled = false
legacy_import = "preview"       # off / preview / auto
max_cjk_ngram = 3
card_builder_enabled = true
episode_projection_enabled = true
maintenance_batch_size = 4

[memory.embedding]
enabled = false
provider = "openai-compatible"
api_key = ""                  # 与 api_key_env 二选一
model = ""
version = "1"
base_url = "https://api.openai.com/v1"
api_key_env = "MEMOLI_EMBEDDING_API_KEY"
dimensions = 1536
timeout_seconds = 30.0
batch_size = 8
candidate_limit = 200

# MemOS 风格混合检索：FTS/Pattern/semantic/metadata 四 lane 独立召回后融合。
# 旧键 `keyword_weight` 已移除（严格全文用 fts_weight，宽松 Pattern 用 pattern_weight）。
[memory.hybrid]
enabled = true
rrf_k = 60
rrf_bonus_weight = 0.4
candidate_limit = 50
fts_candidate_limit = 64
pattern_candidate_limit = 32
pattern_term_limit = 16
fts_weight = 1.0
pattern_weight = 0.4
semantic_weight = 1.0
metadata_weight = 0.5
relative_threshold = 0.2
multi_lane_protection = true
smart_seed_ratio = 0.7
mmr_lambda = 0.7
card_limit = 2
claim_limit = 5
episode_limit = 2
spillover_order = ["claim", "card", "episode"]

[memory.offline]
auto_scan_enabled = false
chat_turn_threshold = 20
long_task_min_business_tool_calls = 10
long_task_min_distinct_business_tools = 2
long_task_min_elapsed_seconds = 60
dead_letter_stale_after_seconds = 86400

[working_memory]
enabled = true
database = "workspace/working-state.db"
max_chars = 4000
stale_policy = "mark"
```

旧 TOML 若只有 `memory.path` 且没有 `engine`，会继续使用 Markdown，以免静默改变
既有部署；新配置应显式写 `engine = "sqlite"`。`memory.enabled = false` 时普通
Agent Loop 继续运行，工作记忆也不受影响。

OpenAI-compatible Embedding 与离线 Extractor 均支持直接 `api_key` 或
`api_key_env` 指向的环境变量，二者必须且只能选择一种非空来源。本地无认证服务可用
`api_key = "EMPTY"`；生产密钥仍建议使用环境变量。两类凭据都不会进入配置 repr、
运行轨迹、诊断、错误或记忆导出。开发/测试也可使用 `provider = "deterministic"`，
但它不适合作为真实语义模型。远程 embedding 与聊天 provider 相互独立，索引 worker
在启动和已发布回复后的空闲点串行处理有界批次，不会并发执行 agent turn。

## 迁移、备份与恢复

`legacy_import = "preview"` 只解析 `MEMORY.md` 并报告可解析/跳过/异常条目。
`auto` 会先按三个文件的内容哈希创建 `legacy-backups/<hash>/`，完整备份
`MEMORY.md`、`HISTORY.md`、`RECENT_CONTEXT.md` 并写 manifest，然后在单事务中
幂等导入 `MEMORY.md`。后两个文件明确不会被提升为事实；失败事务不会留下部分
claim 或推进 manifest。

迁移从一次文件字节快照完成解析、哈希和备份，目标 scope 必须显式传入。数据库
v1→v2→v3→v4→v6 逐条执行迁移语句，只有事务完整提交后才更新 `user_version`；中断后可从
原版本幂等重试。

v6 新增逐 trace consumption ledger 与 session update intent。旧
`trajectory-auto-scan` checkpoint 会迁移成 `trace-consumption-baseline`，升级后不会
因新 ledger 为空而回放旧轨迹。状态为 `observed / reserved / consumed /
quarantined / suppressed / released`；request 创建和 reservation 同事务，Candidate、
Evidence、关系、Governance Job、run/request 完成与 consumed 提交也在同一短事务。

删除记忆后会立即停止召回并留下最小 revision/tombstone；原始 trajectory 按自身
保留策略独立存在。工作状态通过 session/task key 显式恢复，系统不会把其他任务的
进度自动继承到新任务。情景片段索引可随时删除重建，原始消息仍从 trajectory 解析。

完整 trace durable completion 后，Episode projector 以 turn 为默认边界生成
`context_prefix + 原始片段` 搜索文本；前缀来自 session、用户请求、工作目标、当前
步骤和结果，不调用额外 LLM。segment ID 由 trace、ordinal 和 segmenter version
稳定派生，重复通知不会产生重复数据。索引解析时沿 source reference 返回原始轨迹，
不会把上下文前缀冒充原始证据。

Card Builder 仅消费有效、同 scope、带 evidence 的 active/approved Claim，并按
`scope + subject + card_kind` 投影。默认生成器逐条保留 Claim 原文和 ID；内容改变
时原子生成 CardVersion，相同内容不写新版本，frozen Card 不自动覆盖，candidate、
rejected 和过期 Claim 不会进入卡片。
Consolidator 会先在内存完成全部提取与证据校验，再在一个事务中提交 run、Claim、
Evidence、关系、治理任务、派生任务入队及 consumption；失败不留下部分权威记忆。
默认 Card 只能引用完整 Claim
文本或其确定性组合，短子串不能证明整张 Card。

## 工具与诊断

- `memory_recall` 支持类型、scope、状态、敏感等级和数量过滤，返回结构化命中、
  evidence、reason、候选/过滤计数及 degraded 状态。
- `MemoryManageTool` 实现 remember/correct/freeze/forget/list/export；为保持
  GenericAgent 九工具默认合同，它由 `tools.memory_manage_enabled=true` 显式启用。
- remember/correct 必须携带当前用户消息中的逐字依据；无依据模型推断会被拒绝，
  离线流程则只能创建 candidate。
- remember/correct 的 Claim 正文由 `basis_quote` 去掉允许的记忆指令包装后确定；模型
  `content` 不一致会拒绝。Evidence 保存 message ID、原始 quote、trace locator、hash
  和 verified 状态；健康与凭据事实不能把敏感度降到 public/private。correct 使用
  expected revision 原子保存新 Claim、旧 Claim superseded 及关系。
- export 默认只包含当前 Card 与 Claim，并保留 scope、状态、敏感级别、证据和时间；
  Episode 是轨迹派生数据，默认不纳入个人记忆导出。

诊断时先检查工具结果的 `disabled/degraded/rejected`，再查看 trajectory 中的
`memory_retrieved`、`active_lanes`、`degraded_lanes`、候选/过滤计数、
`working_state_revision`、注入 ID 和工具事件。`MemoryRuntime.diagnostics()` 可查看
schema、FTS、索引积压和向量数量；`MemoryIndexWorker.rebuild()` 与
`TrajectorySegmentIndexer.backfill()` 提供幂等维护入口。不要直接编辑 SQLite；导出
应经过 scope 与敏感等级过滤，诊断不会包含向量、API key 或超预算召回正文。

本阶段的固定回归集和延迟基准只验证确定性、预算与工程性能，不采集用户反馈、不训练
排序器，也不构成反馈评测闭环。
## Offline memory learning pipeline

Offline learning is disabled by default. When `memory.consolidation_enabled=true`,
the runtime validates a separately configured extractor and starts an
`OfflineMemoryWorker`. Online turns only persist a long-term-update request or an
Episode projection job and wake the worker; they never wait for extraction,
governance, Card rebuilding, or embeddings.

The authoritative flow is:

1. A request references completed SQLite Trajectory IDs through a persistent
   consumption ledger; it never stores caller
   supplied transcript text.
2. `TrajectorySourceReader` creates one immutable, scope-authorized current-user
   Source Segment per trace. Missing legacy envelope metadata falls back to the last
   user message and is marked `legacy-last-user`; Episode projection uses the full
   timeline API instead.
3. A versioned `CandidateExtractor` emits structured drafts. `EvidenceVerifier`
   re-reads quote/offset/hash/role/scope data before an atomic Candidate batch is
   committed.
4. Explicit Claim dedup first matches message ID + quote, then structured fact slots
   and value, then exact normalized hash. A match reuses the formal Claim and only
   fills missing Evidence. Other semantic similarity remains a governed relation.
   Same-slot facts record `supports`,
   `contradicts`, `corrects`, or `supersedes` proposals. Candidate, governance job,
   request completion, consolidation run, and auto-scan checkpoint share one
   transaction.
5. A leased governance job invokes the `memory-governor` SubAgent profile. Its only
   tools read the bound Candidate, verified Evidence, same-scope Claims, and submit
   a fixed decision. A deterministic Policy Gate rechecks risk, independent
   evidence, conflicts, time, frozen targets, policy version, and expected revision.
6. Approved facts enqueue recoverable Card and semantic-index jobs. Candidate,
   rejected, superseded, expired, unsupported, and unresolved-conflict Claims do
   not enter a current Card.

`memory-governor` cannot read or write files, access the network, execute code, or
delegate. Sensitive, conflicting, frozen-target, or otherwise uncertain Candidates
remain `needs-user-review`. Users inspect them with `/memory candidates` and
`/memory show <id>`, then use the confirmation form
`/memory approve|reject <id> <revision> confirm`.

The governor uses exactly four bound tools and a `NullTrajectoryStore`. Its Reasoner
and ToolRegistry have no shared plugin HookBus, so `shell_safety` `TOOL_BEFORE` cannot
write an unknown governor trace into `trajectories.db`. Governance decisions, task
IDs, Policy Gate outcomes, and retry audit remain authoritative in `memory.db` and
the SubAgent task graph.

Deterministic Extractor v2 only splits explicit `请记住/记住/remember` lines and
returns zero candidates for ordinary chat or questions. Zero candidates is a normal
completed batch. Deployments that need implicit learning must configure and validate
the structured OpenAI-compatible Extractor; existing noisy Candidates are reviewed
or governed, never auto-deleted or auto-approved.

### Card-first retrieval

Cards are versioned materialized views. Each current `card_statement` stores its
ordered Claim references; retrieval never parses display Markdown to discover
provenance. `auto` routes profile/preference/overview questions to Card-first,
exact/current/source/high-risk questions to Claim-first, event/process questions to
Episode-first, and uncertain questions to bounded hybrid retrieval. `summary` stops
at statements, `fact` expands to governed Claims, and `evidence` retains their
authorized Evidence references. Missing or stale Card projections safely fall back
to Claims and report the actual route and degradation reason.

Prompt use and embedding use are independent policy decisions at Source Segment,
Claim, Card, statement, and Episode boundaries. Remote extractor and embedding
calls recheck those flags before sending content.
