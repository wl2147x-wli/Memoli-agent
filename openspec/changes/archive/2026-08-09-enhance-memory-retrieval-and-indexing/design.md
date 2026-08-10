## Context

Memoli 当前已经以 `memory.db` 保存 Claim、Card、CardVersion 与 `trajectory_segments`，使用 FTS5/BM25（不可用时退化为有界 LIKE）检索，并由 `MemoryRuntime.pre_recall()` 在被动轮次中把当前输入、工作目标和当前步骤拼接成查询。工作状态由 `working-state.db` 管理，完整运行轨迹由独立 SQLite trajectory store 保存。现有 `TrajectorySegmentIndexer` 和 Card store API 已具备基础结构，但主要由测试或显式调用驱动，尚未形成“事实写入—派生索引—召回”的自动生命周期。

本 change 跨越查询模型、SQLite schema、检索融合、Card/Episode 投影和 runtime lifecycle。约束是继续使用串行 agent loop；远程 embedding 或派生索引失败不得阻断对话；现有数据库和无 embedding 配置必须兼容；长期事实源、工作状态、完整轨迹和检索索引必须保持职责分离。

数据流如下：

```text
当前用户输入 + WorkingSnapshot + 会话/作用域
                 │
                 ▼
       StructuredMemoryQuery
                 │
       ┌─────────┼──────────┐
       ▼         ▼          ▼
   FTS/LIKE   Vector      Metadata
       └─────────┼──────────┘
                 ▼
       硬过滤 → RRF → 类型预算
                 ▼
       可引用的 MemoryContext

Claim/Card/Episode 提交 → index_jobs → semantic_index（派生、可重建）
完整 trace 提交 → EpisodeProjector → trajectory_segments → index_jobs
生效 Claim 变化 → CardBuilder → 新 CardVersion → index_jobs
```

## Goals / Non-Goals

**Goals:**

- 把用户输入、工作目标、当前步骤、作用域和时间约束表达为类型明确、可测试的查询，而不是不可区分的字符串拼接。
- 在现有关键词召回上增加可选语义召回，并以确定性算法融合多路候选。
- 让语义索引、Card 和 Episode 都具备幂等、可追踪、可重建的生命周期。
- 保证召回结果仍包含稳定 ID、类型、证据、命中原因和降级状态，便于轨迹审计。
- 保持现有关键词、Markdown 迁移、working checkpoint 和 passive turn 行为兼容。

**Non-Goals:**

- 不实现用户反馈采集、反馈归因、LLM Judge、奖励模型、在线排序学习或自动强化。
- 不实现后训练数据生产或模型微调。
- 不在首版加入 Cross-Encoder/LLM Reranker，也不引入外部向量数据库。
- 不允许 Card Builder 将 candidate Claim 自动提升为 active/approved。
- 不改变工作记忆的 checkpoint 语义，不把 `working-state.db` 合并进长期记忆库。

## Decisions

### 1. 使用结构化查询，用户输入拥有最高语义权重

扩展 `MemoryQuery`，至少保存 `text`、`objective`、`current_step`、`session_id`、`scope`、`types`、`as_of` 和预算。关键词通道以 `text` 为主，必要时补充目标与当前步骤；向量通道构造带字段标签的规范化文本；scope/status/sensitivity/time 是检索后的硬约束，不依靠自然语言表达。

这样既吸收 GenericAgent 将工作状态及时注入当前轮次的优点，又避免工作目标覆盖用户本轮真实意图。没有 checkpoint 时只使用用户输入，不制造空白占位信息。

备选方案是继续把所有字段直接拼接为一个字符串，改动较小，但无法调整通道权重、审计字段贡献或可靠执行作用域过滤，因此不采用。

### 2. SQLite 保存语义派生索引，首版采用精确余弦扫描

在 `memory.db` 增加：

- `semantic_index(memory_type, memory_id, content_hash, embedding_model, embedding_version, dimensions, vector_blob, indexed_at)`；`vector_blob` 使用 little-endian float32 BLOB。
- `memory_index_jobs(memory_type, memory_id, content_hash, state, attempts, last_error, available_at, updated_at)`；事实写入事务只负责按稳定键 upsert `pending`。
- 必要的 schema version 与唯一索引，确保重复提交和进程重启幂等。

首版对经过 scope/type/status 元数据预过滤后的向量进行进程内精确余弦计算。个人助手的数据量在当前阶段足以支撑该方案，它没有原生扩展编译、平台适配和独立服务运维成本。达到经基准确认的规模阈值后，再考虑 sqlite-vec/HNSW；表结构和 Embedder/SearchLane 接口不绑定具体后端。

向量表和索引任务表都不是事实源。Claim/Card/Episode 删除、修订或模型版本变化时，旧向量可被标为 stale 或重建；不能从向量反向恢复事实。

备选方案包括 FAISS、Qdrant/Chroma 和 sqlite-vec。它们在大规模近似搜索上更强，但会提前引入原生依赖、额外进程或平台差异，不符合当前求职项目“可运行、可讲清、可替换”的优先级。

### 3. embedding 与 agent provider 解耦，索引不进入对话关键路径

定义异步 `Embedder` 协议和禁用实现；OpenAI-compatible adapter 通过独立 `[memory.embedding]` 配置选择 `model`、`base_url`、环境变量密钥名、维度与超时，不复用或记录明文密钥。测试使用确定性 fake embedder。

事实或投影提交时只登记 job。一个有界、串行的 `MemoryIndexWorker` 在启动后和轮次空闲点按批处理 pending job；查询只读取 `ready` 且 model/version/hash 匹配的向量，绝不等待 embedding 请求。worker 停止或网络错误时记录有限错误摘要并按退避重试，FTS/LIKE 继续工作。

这里的“串行 worker”不并发执行 agent turn，也不改变既有串行 agent loop。首版可以由 runtime lifecycle 明确 tick，避免常驻线程。

备选方案是在每次查询时同步生成全部缺失向量，虽然数据更新快，但会把网络延迟和故障传播到每轮对话，因此不采用。

### 4. 三路候选通过 RRF 确定性融合

检索分为以下阶段：

1. 规范化查询并计算总预算和 Card/Claim/Episode 类型预算。
2. 关键词通道通过 FTS5/BM25 或有界 LIKE 取候选。
3. 语义通道只在 embedder 和匹配版本索引可用时取候选。
4. 元数据通道补充满足 scope、status、时间与 core/importance 条件的近期或核心记忆。
5. 先执行 scope、sensitivity、status、valid time 等硬过滤，再按稳定键去重。
6. 采用 Reciprocal Rank Fusion：`score = Σ lane_weight / (rrf_k + rank)`；相同分数依次按类型优先级、时间、稳定 ID 排序。
7. 按类型预算选取，未使用的配额可按固定顺序回流，最后受条数和字符预算双重约束。

结果诊断记录启用/降级通道、各通道候选数、过滤数、融合原因和注入 ID，但不记录向量或密钥。RRF 不要求校准 BM25 与余弦分数，易于复现和单元测试。备选的加权原始分数相加依赖跨模型标定，首版不采用。

### 5. Card Builder 是 Claim 到 CardVersion 的受治理投影

新增 `CardBuilder` 服务，只读取 `active/approved`、未过期、作用域允许且带 evidence 的 Claim。按 `scope + subject + card_kind` 形成稳定 projection key：

- 首版由确定性规则选择 Claim、生成引用列表和结构化草稿；可选 LLM 只负责压缩表述，不能新增无 Claim 支撑的事实。
- 草稿中的每项内容必须映射 Claim ID；校验失败则拒绝提交。
- 内容 hash 与当前版本相同时不新建版本；变化时原子创建新 `CardVersion` 并移动 current 指针，旧版本保留。
- frozen/用户锁定 Card 不自动修改；相互矛盾的 Claim 保持并列和时间范围，不由 Builder 私自裁决。
- Builder 失败只记录投影状态，不改变当前 Card，不影响 Claim 写入。

备选方案是让 LLM 直接从对话总结并覆盖 Card，生成效果灵活但证据边界、幂等性和回滚都较弱，因此不采用。

### 6. 完整 trace 提交后自动生成上下文化 Episode

`EpisodeProjector` 订阅“trace 已成功提交”的生命周期点，而不是读取尚未完成的内存事件。首版以一个 turn/trace 为自然情景边界；当单段超过限制时按消息或工具事件边界拆分。每段保存：

- `trace_id`、segment ordinal、原始事件/消息引用、scope、occurred_at；
- 由 session、用户请求、working objective/current step、turn outcome 确定性生成的 `context_prefix`；
- `search_text = context_prefix + 原始片段`、`segmenter_version` 与 `content_hash`。

`segment_id` 由 `trace_id + ordinal + segmenter_version` 稳定派生。重复通知使用 upsert；版本升级时允许按 trace 重建。原始细节始终按引用从 trajectory store 解析，Episode 索引不复制或替代完整轨迹。投影失败只进入可重试状态，并在轨迹元数据中留下有界诊断，不回滚已完成回复。

上下文前缀首版不用额外 LLM，以获得低成本和确定性；后续若引入模型摘要，必须作为版本化派生字段且保留确定性 fallback。

### 7. 保持存储边界与可观测性

- `working-state.db`：短期任务状态，每轮仍按现有 checkpoint 机制更新。
- trajectory SQLite：完整原始运行记录，是 Episode 原始情景的来源。
- `memory.db`：长期 Claim/Card、Episode 检索投影、FTS 与语义派生索引。

召回轨迹只增加 `query_context_fields`、`active_lanes`、`degraded_lanes`、候选/过滤计数与注入 ID。不得存储完整 embedding、API key 或超预算召回正文。新增测试和离线基准用于行为回归与性能验收，不把它们解释为反馈评测闭环。

## Risks / Trade-offs

- [SQLite 精确向量扫描随数据量线性增长] → 先进行元数据预过滤并设置候选上限；记录 P50/P95 延迟，达到明确阈值后替换 VectorSearchLane。
- [远程 embedding 不稳定或模型下线] → 索引异步化、版本化和可重试；查询自动降级到关键词与元数据通道。
- [模型/维度变更导致新旧向量混用] → 查询必须匹配 model、version、dimensions 与 content hash；重建期间旧索引不可冒充新索引。
- [自动 Card 摘要产生无证据事实] → Claim ID 全覆盖校验、可选 LLM 仅改写、原子版本提交、frozen 保护。
- [Episode 复制敏感轨迹内容] → 延续 scope/sensitivity 策略，只保存有界检索文本和原始引用，完整内容仍在受控 trajectory store。
- [派生任务积压导致新记忆暂时无法语义召回] → FTS 同步可用、job 可观察、按批次补建；不以牺牲对话延迟换取即时向量一致性。
- [混合召回改变既有排序] → 无 embedding 配置时提供关键词兼容模式；固定 RRF 参数、并列规则和回归语料。

## Migration Plan

1. 在现有 schema migrator 中创建新表/列和唯一索引；旧表与旧数据不做破坏性修改。
2. 先上线结构化查询与兼容关键词通道，验证现有测试结果和注入预算不变。
3. 上线 Episode/Card 投影状态与 index job 登记；对已有数据执行幂等 backfill。
4. 配置可选 embedder 后分批构建语义索引；构建过程中召回仍使用关键词和元数据通道。
5. 最后开启混合融合，并以固定数据集对比兼容模式的正确性、确定性和延迟。

回滚时关闭 `[memory.embedding]` 和自动投影开关即可恢复关键词路径；新表保留不会影响旧代码。若需彻底回滚，可删除派生索引表并从事实源重建，禁止删除 Claim、CardVersion 或 trajectory。

## Open Questions

- 首个真实 embedding adapter 使用哪个模型与维度，由部署环境决定；规范只固定协议与版本隔离，不在仓库中绑定供应商。
- 精确扫描切换到 sqlite-vec/HNSW 的数据量和 P95 阈值，应在实现后的本机基准结果中确定并记录。
- Card 的 `subject/card_kind` 首版词表需在实现前结合现有个人助手样例收敛；未知类型必须落入通用卡片而不是丢弃。
