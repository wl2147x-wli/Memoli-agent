# Memoli-agent 证据化记忆系统

当前实现把五类状态明确分开：Session Context 保存短对话历史；Working State
保存可恢复任务进度；SQLite trajectory 是完整运行证据；Personal Memory 保存经
治理的用户事实与卡片；Procedural Skill 仍保持独立，本阶段只产生 skill candidate，
不会自动发布 Skill 或训练数据。

## 在线与离线双循环

在线 turn 先把当前用户消息、checkpoint objective/current step、session、scope 和
时间边界组成结构化查询。当前用户消息始终是主意图，checkpoint 只是辅助上下文。
检索通过关键词、可选向量和元数据三路取候选，先执行 scope/status/sensitivity/
valid-time 硬过滤，再使用 RRF 融合、稳定并列规则和 Card/Claim/Episode 类型预算构造
`<memory_context trust="data">`。记忆始终作为数据，历史网页、工具输出和
Assistant 文本不能冒充系统指令。完整对话只写 `trajectory.db`，不再追加
`HISTORY.md`。

离线 consolidation 按 trace 范围或 `start_long_term_update` 请求读取已提交轨迹，
逐段提取固定 schema 候选并校验证据。隐式推断默认只能进入 `candidate`；显式用户
事实或人工批准才可发布为 `active`，frozen 冲突必须人工处理。Personal Memory、
Skill、评测和后训练候选具有不同分类边界，本阶段只发布 Personal Memory。

## 数据与索引

- `working-state.db`：独立 schema-versioned 工作状态库，使用 expected revision
  原子 patch，支持 stale 标记与显式恢复；关闭个人记忆不会关闭它。
- `trajectories.db`：唯一 append-only 原始运行证据，也是 Episode 原始细节来源。
- `memory.db`：append-only claims、多对多 evidence、版本化 cards、关系、修订、
  consolidation run、可重建 trajectory segments、semantic index 和派生任务状态。
- 当前 SQLite schema 为 v3，启用外键和 `busy_timeout`。Claim 仅在同一 scope 内对
  `candidate/active/approved/frozen` 做部分唯一约束；历史的 deleted、rejected 和
  superseded 不阻止用户重新记住相同内容。
- 检索优先使用 FTS5，并为中文生成有界 1–3 gram 搜索字段；不可用时退化为有界
  LIKE/关键词检索，并在结果中返回 `degraded=true`。
- 语义向量以带 model/version/dimensions/content-hash 的 float32 BLOB 保存在 SQLite；
  当前实现先做元数据预过滤，再进行精确余弦扫描。向量和索引 job 都是派生数据，
  可以删除重建，不能替代 Claim、CardVersion 或 trajectory。

混合召回使用 `score = Σ lane_weight / (rrf_k + rank)`，不直接相加 BM25 和余弦
原始分数。关键词 lane 保留 FTS5 BM25 主顺序，只在并列时使用治理等级、时间和稳定
ID；所有 lane 都必须提供非空稳定 ID。Embedding 未配置、超时、
维度错误或索引过期时，当前 turn 不等待补建，继续使用关键词与元数据通道。

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
model = ""
version = "1"
base_url = "https://api.openai.com/v1"
api_key_env = "MEMOLI_EMBEDDING_API_KEY"
dimensions = 1536
timeout_seconds = 30.0
batch_size = 8
candidate_limit = 200

[memory.hybrid]
enabled = true
rrf_k = 60
candidate_limit = 50
keyword_weight = 1.0
semantic_weight = 1.0
metadata_weight = 0.5
card_limit = 2
claim_limit = 5
episode_limit = 2
spillover_order = ["claim", "card", "episode"]

[working_memory]
enabled = true
database = "workspace/working-state.db"
max_chars = 4000
stale_policy = "mark"
```

旧 TOML 若只有 `memory.path` 且没有 `engine`，会继续使用 Markdown，以免静默改变
既有部署；新配置应显式写 `engine = "sqlite"`。`memory.enabled = false` 时普通
Agent Loop 继续运行，工作记忆也不受影响。

Embedding key 只通过 `api_key_env` 指向的环境变量提供。开发/测试可使用
`provider = "deterministic"`，但它不适合作为真实语义模型。远程 embedding 与聊天
provider 相互独立，索引 worker 在启动和已发布回复后的空闲点串行处理有界批次，
不会并发执行 agent turn。

## 迁移、备份与恢复

`legacy_import = "preview"` 只解析 `MEMORY.md` 并报告可解析/跳过/异常条目。
`auto` 会先按三个文件的内容哈希创建 `legacy-backups/<hash>/`，完整备份
`MEMORY.md`、`HISTORY.md`、`RECENT_CONTEXT.md` 并写 manifest，然后在单事务中
幂等导入 `MEMORY.md`。后两个文件明确不会被提升为事实；失败事务不会留下部分
claim 或推进 manifest。

迁移从一次文件字节快照完成解析、哈希和备份，目标 scope 必须显式传入。数据库
v1→v2→v3 逐条执行迁移语句，只有事务完整提交后才更新 `user_version`；中断后可从
原版本幂等重试。

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
Card 和关系；失败只保留失败 run，不留下部分记忆。默认 Card 只能引用完整 Claim
文本或其确定性组合，短子串不能证明整张 Card。

## 工具与诊断

- `memory_recall` 支持类型、scope、状态、敏感等级和数量过滤，返回结构化命中、
  evidence、reason、候选/过滤计数及 degraded 状态。
- `MemoryManageTool` 实现 remember/correct/freeze/forget/list/export；为保持
  GenericAgent 九工具默认合同，它由 `tools.memory_manage_enabled=true` 显式启用。
- remember/correct 必须携带当前用户消息中的逐字依据；无依据模型推断会被拒绝，
  离线流程则只能创建 candidate。
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
