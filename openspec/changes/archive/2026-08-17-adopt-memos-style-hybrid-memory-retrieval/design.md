## Context

Memoli 当前由 `LayeredMemoryRetriever` 先选择 Card-first、Claim-first、Episode-first 或 hybrid 路由。Hybrid 路径在 `hybrid.py` 中运行 keyword、metadata、semantic 三个 lane，并以 `weight / (rrf_k + rank)` 做纯 RRF；keyword lane 又调用 `SQLiteMemoryStore.search()`，其中 Claim 使用 FTS5/BM25，Card 和 Episode 使用独立 LIKE 逻辑。Card-first 还会绕开 hybrid，直接执行 Card statement 子串计数。

当前 `_search_text()` 在索引侧生成 1..N 的 CJK n-gram，而 `_fts_query()` 在查询侧主要生成完整 term 和 N-gram。把 bigram OR 继续并入这个查询虽然可以让“清华源”召回“清华镜像源”，但会使严格 BM25 与宽松 substring 共享候选池和信任等级，无法诊断召回来源，也无法单独约束误召回。

MemOS Local Plugin 的可复用核心不是某个 BM25 参数，而是通道分工：FTS5 trigram 负责严格全文候选，Pattern LIKE 补足短词窗口，vector/structural 通道并行，通道结果按排名归一化后以 RRF 奖励多通道一致性，再经过相对阈值、类型种子和 MMR。该设计将此结构适配到 Memoli 的 Card/Claim/Episode、scope 治理和 SQLite 单机约束。

## Goals / Non-Goals

**Goals:**

- 让短 CJK、简称和中间插词查询获得有界的补充召回，同时保持严格 FTS/BM25 的可解释性。
- 让 Card、Claim、Episode 和 Card-first statement 使用同一 Query Builder 和一致的 hard filter 语义。
- 不混合 BM25 与 cosine 原始数值，以规范化通道相关性加加权 RRF 奖励形成确定性总排序。
- 在 embedding 完全关闭或暂时失败时保持可用，并明确记录 lane 降级。
- 通过派生索引重建迁移现有数据库，不改变权威记忆、证据和历史版本。

**Non-Goals:**

- 不逐字复制 MemOS 的 trace 数据模型、tier 名称或云端未公开实现。
- 不增加 LLM query rewrite、LLM relevance filter 或 cross-encoder reranker。
- 不改变记忆提取、治理、Card 构建和长期更新触发流程。
- 不修复 embedding 服务部署、Episode 投影或其他离线作业的既有故障。
- 不保留旧 `keyword_weight` 的运行时兼容分支。

## Decisions

### 1. 使用一个确定性 Query Builder 产生分离的查询产物

新增不可变查询计划，至少包含：

- `primary_text`：仅当前用户查询，用于严格 FTS 和 Pattern；
- `embedding_text`：现有带字段边界的 query/objective/current-step 文本，最大 1500 字符；
- `fts_match`：规范化后的完整 term 与适合 trigram 的 term，不包含 bigram OR 放宽；
- `pattern_terms`：CJK bigram、长度为 2 的短 ASCII term，以及低于 trigram 窗口的 term，去重后最多 16 个；
- scope、status、sensitivity、at_time、item types 等 hard filters 的原样引用；
- 可安全持久化的摘要，例如 term 数、是否截断和启用的字段，不记录 query 正文副本。

Query Builder 复用单一的 normalization、CJK run 和短词生成助手。严格 lane 不使用 working objective/current-step 扩词，避免辅助上下文削弱当前用户意图；语义 lane 仍可使用结构化辅助字段。

备选方案是只修改 `_fts_query()` 生成 bigram OR。拒绝原因是无法区分精确与宽松候选，且一个常见 bigram 就能占满 keyword candidate limit。

### 2. 将 sparse retrieval 拆成 `fts` 与 `pattern` 两个独立 lane

`fts` lane：

- 对 Claim、当前 Card/Card statement 和 Episode 派生内容使用可重建 FTS5 表；
- 优先使用 SQLite FTS5 trigram tokenizer，运行时在临时表上探测 tokenizer 与 `bm25()` 支持；
- 执行 `MATCH` 后使用 `bm25()` 排列 lane 内候选，SQL 层先约束 scope 和可连接的状态字段，再限制数量；无法在虚表内完成的敏感度/时间过滤必须在扩大但有界的预过滤窗口内完成，并报告过滤计数；
- 输出原始 BM25 仅供安全诊断，融合只消费 rank-derived relevance。

`pattern` lane：

- 最多消费 16 个已转义 pattern term，以 `LIKE '%term%' ESCAPE '\\'` 做 OR 召回；
- 所有记忆类型都先按 scope、状态、敏感度和有效时间过滤，再应用 lane limit；
- 默认按命中 term 数、最新时间和稳定 ID 排序；命中项以 `1 / rank` 形成规范化相关性；
- Pattern 是补充通道，默认权重低于 FTS，单独命中不得伪装成 BM25 命中。

FTS 不可用不意味着整个 memory 不可用：该 lane 标为 degraded，Pattern、semantic 和 metadata 继续运行。Pattern SQL 失败时则独立标记 `pattern:error`。

备选方案是依赖 Python `rank-bm25` 或新增搜索服务。拒绝原因是本项目已使用 SQLite、需要离线可用，且外部实现不能解决短词通道分工问题。

### 3. 用统一 `ChannelHit` 契约承载通道结果

内部 lane 不再只返回 `MemoryItem`，而返回包含 stable identity、item、lane、rank、normalized relevance、可选 raw score 和 safe reason 的 `ChannelHit`。规范化规则为：

- FTS 与 Pattern：`1 / rank`；
- semantic：将有限 cosine 值裁剪到 `[0, 1]`，非法值丢弃并记为 lane 错误；
- metadata/structural：只有明确的结构化匹配才给固定相关性；“最近或重要的任意记忆”不再作为与文本召回同等的相关性证据。

这样可避免 raw BM25、cosine 和 importance 直接相加，也使相同 stable ID 在多通道间可无损聚合。

### 4. 采用 MemOS 风格的最佳通道相关性加 RRF 一致性奖励

候选融合公式固定为：

```text
base = max(normalized_relevance_i)
rrf_bonus = rrf_bonus_weight * Σ(lane_weight_i / (rrf_k + rank_i))
fused_relevance = base + rrf_bonus
```

默认值：

| 配置 | 默认值 |
|---|---:|
| `rrf_k` | 60 |
| `rrf_bonus_weight` | 0.4 |
| `fts_weight` | 1.0 |
| `pattern_weight` | 0.4 |
| `semantic_weight` | 1.0 |
| `metadata_weight` | 0.5 |
| `fts_candidate_limit` | 64 |
| `pattern_candidate_limit` | 32 |
| `pattern_term_limit` | 16 |

同分时依次按多通道命中数、类型顺序 Card→Claim→Episode、时间倒序和 stable ID 排序。原始 BM25 绝不进入跨 lane 公式。

纯 RRF 是现状备选方案。它可比性好，但忽略“某通道第一名是否真正强相关”，也不利于相对阈值，因此改为 MemOS 风格的 base + RRF bonus。

### 5. 融合后执行相对阈值、多通道保护、类型种子和 MMR

处理顺序固定为：

```text
hard filters → lane top-K → identity dedupe/fusion
→ relative threshold → multi-lane protection
→ per-type seed → deterministic MMR
→ type/count/character budgets
```

- `relative_threshold=0.2`：单 lane 候选低于当前最高 fused relevance 的 20% 时丢弃；该值与当前 MemOS Local 排序器默认保持一致，但可配置为 `[0,1]`。
- 多通道保护：命中至少两个独立 lane 的候选即使略低于相对阈值仍可保留，但 hard filters 永不绕过。
- `smart_seed_ratio=0.7`：在相关候选存在时，为请求包含且配额非零的每个记忆类型保留最多一个达到“该类型最高分 × ratio”的种子，防止单一类型吞没结果；不相关类型不强塞结果。
- `mmr_enabled=true`、`mmr_lambda=0.7`：在候选超过最终预算时执行确定性 MMR。优先使用已就绪且同版本的缓存向量计算候选相似度；没有可比向量时使用规范化 token/CJK bigram Jaccard。MMR 不触发新的 embedding 请求。

类型配额和字符预算保持最终硬边界。MMR 只改变候选顺序，不改变 scope、状态、敏感度和时间资格。

### 6. 所有路由共享查询与 sparse lane，不允许 Card-first 旁路

`LayeredMemoryRetriever` 继续决定 Card-first、Claim-first、Episode-first 或 hybrid，但路由只改变 `item_types`、详情展开和最终配额，不再选择另一套文本匹配算法。Card-first 首先检索 current Card statements；若无结果且允许 fallback，再运行 Claim-first。两次都复用相同 Query Plan、FTS/Pattern lane 和诊断结构。

这样既保留“先检索 Card，再按需展开 Claim”的已有策略，也避免 Card statement 的 substring 计数与 hybrid BM25/Pattern 产生不同语义。

### 7. 将所有 sparse 索引视为可重建派生数据

memory schema 从 6 升到 7：

- 为 Claim、当前 Card/Card statement、Episode 建立版本化 FTS 派生表或统一 FTS 表；
- 记录 sparse index format/version，使 tokenizer 或 Query Builder 规则变化能够触发重建；
- migration 在事务内创建新索引结构，从权威表回填，通过计数/外键与抽样解析检查后切换 schema version；
- 原 `claim_search`/`card_search` 等旧派生表只在新索引成功后删除，不修改权威表；
- FTS5 trigram 不受当前 SQLite 支持时，数据库仍可打开，索引状态标记 unavailable，运行时使用 Pattern/semantic/metadata。

回滚应用代码时，旧版本会拒绝 schema 7，而不会误读；回滚需要先恢复旧二进制支持的数据库副本或运行单独的“仅重建旧派生索引”降级工具。由于权威数据未改变，该工具不得删除 Claim、Card、Episode 或证据。

### 8. 配置采用新语义，不保留旧 lane 映射

`[memory.hybrid]` 新增上述参数及：

```toml
relative_threshold = 0.2
multi_lane_protection = true
smart_seed_ratio = 0.7
mmr_enabled = true
mmr_lambda = 0.7
```

所有 limit 必须大于 0，weight 必须非负，比例参数必须位于 `[0,1]`，至少一个召回 lane 权重大于 0。显式出现 `keyword_weight` 时配置加载失败，并提示改为 `fts_weight` 与 `pattern_weight`；不设置任何新键时采用新默认值。现有 Card/Claim/Episode 配额、spillover 和 embedding 配置继续有效。

### 9. 诊断分离召回、过滤与选择阶段

`MemoryQueryResult` 及 trajectory 诊断增加：

- `fts`、`pattern`、`semantic`、`metadata` 的候选数与 degraded reason；
- 查询计划中启用的字段、FTS term 数、Pattern term 数和截断标志；
- 每个最终项的贡献 lane、lane rank、规范化分数、fused relevance 和选择原因；
- hard-filter、relative-threshold、MMR、type/count/char budget 的聚合过滤计数。

诊断不得写入 query 正文副本、记忆正文副本、embedding 向量、API key 或越权候选内容。对主流程而言诊断写入失败仍不得改变检索排序。

## Risks / Trade-offs

- [trigram tokenizer 在某些 Python/SQLite 构建中不可用] → 启动时能力探测，独立降级 `fts` lane，Pattern/semantic/metadata 保持可用并展示原因。
- [Pattern OR 召回误报] → 独立低权重 lane、16 term/32 candidate 上限、相对阈值、多通道奖励和 MMR；绝不把 Pattern 命中标成 BM25。
- [Pattern LIKE 在大库中变慢] → hard filter 先行、term/candidate 上限、只查询派生规范化列，并在实施时检查查询计划；若仍超预算则返回 bounded degraded，而非无界扫描。
- [base + RRF 改变现有排序] → 固定公式、稳定 tie-break、快照测试和迁移说明；不承诺旧排序兼容。
- [metadata lane 把近期无关事实抬高] → 仅明确结构匹配产生 relevance，普通 importance/recency 只作 tie-break 或 Card 核心概览，不作为文本相关性。
- [MMR 在无向量时结果漂移] → 使用版本化的确定性文本 Jaccard fallback，固定遍历和 tie-break，禁止在线补 embedding。
- [schema 7 迁移耗时] → 在事务内构建派生索引、显示重建状态并允许安全重试；权威数据不变。
- [Card-first 行为与旧 substring 排名不同] → 用同一 sparse 查询契约统一语义，并用路由、statement 展开和 evidence 回归场景覆盖。

## Migration Plan

1. 先实现 Query Plan、ChannelHit 和新配置校验，但保持 schema 6 只读测试夹具可构造。
2. 新增 schema 7 派生 sparse 索引及能力探测，在临时数据库验证新建、6→7 升级、失败回滚和 FTS 不可用降级。
3. 回填 Claim、当前 Card/Card statement 和 Episode 的新索引，核对 stable ID 数量与权威表，不回填已删除/过期投影为可检索状态。
4. 接入 FTS/Pattern lane 与 base + RRF 融合，再接入阈值、种子、MMR 和最终预算。
5. 将 Layered/Card-first 接到统一 Query Plan，并扩展安全诊断。
6. 更新示例配置和记忆系统文档，明确删除 `keyword_weight`、新默认值和 degraded 行为。
7. 若部署后需要回滚，保留 schema 7 数据库并回滚应用前先运行受控派生索引降级工具或恢复数据库副本；不得直接降低 `PRAGMA user_version`。

## Open Questions

无阻塞问题。具体 SQL 索引布局可在实现阶段在“每类型独立 FTS 表”和“统一 FTS 表”之间选择，但必须满足相同的 stable identity、hard-filter-before-limit、可重建和降级契约。
