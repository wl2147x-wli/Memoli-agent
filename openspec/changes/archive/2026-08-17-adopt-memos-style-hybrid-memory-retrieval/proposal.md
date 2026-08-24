## Why

当前关键词检索把连续精确匹配和 CJK n-gram 宽松召回混在同一 FTS 查询中：短中文表达、简称或中间插词场景容易漏召回，而直接扩大 OR n-gram 又会污染 BM25 候选并放大误召回。需要参照 MemOS Local Plugin，将严格全文检索、短词 Pattern、语义和结构化元数据拆成独立通道，再用统一的排名归一化、融合、阈值和多样性策略选择最终记忆。

## What Changes

- 将现有单一 `keyword` lane 拆为严格 `fts` lane 与低信任 `pattern` lane；FTS5/BM25 负责完整词和至少三个 CJK 字符的严格全文召回，Pattern 负责 CJK bigram、短 ASCII term 和无法进入 trigram 窗口的查询。
- 引入确定性 Query Builder，分别产生 embedding 文本、FTS MATCH 表达式、受限 Pattern terms 和结构化过滤字段，避免索引侧与查询侧 n-gram 规则再次漂移。
- 对 Claim、Card 和 Episode 建立或补齐可重建的全文/Pattern 检索路径；所有 SQL 通道先应用 scope、状态、敏感度和有效时间约束，再应用候选上限。
- 保留 SQLite FTS5 `bm25()` 作为 FTS 通道内排序，但不把原始 BM25 数值与 cosine 相似度直接相加；各通道输出规范化相关性和稳定排名后，通过 MemOS 风格的“最佳通道相关性 + 加权 RRF 一致性奖励”融合。
- 在融合后增加相对相关性阈值、多通道候选保护、类型种子选择和确定性 MMR 去重，再执行现有 Card/Claim/Episode 数量与字符预算。
- 扩展检索诊断，报告 Query Builder 产物摘要、各 lane 的候选数/降级原因、候选贡献通道、规范化分数、过滤原因和最终截断；不得记录原始向量或越权正文。
- **BREAKING**：以 MemOS 风格的显式 lane 配置替换旧的单一 `keyword_weight`；默认保持 `rrf_k=60`，并为 FTS、Pattern、相对阈值、RRF 奖励和 MMR 提供独立参数。旧键不再静默映射，启动时返回可操作的配置错误。
- 通过 schema migration 重建派生搜索索引，不改变 Claim、Card、Episode 的稳定 ID、来源、状态、证据和版本历史。
- 不引入外部 `rank-bm25` 服务，不把检索交给记忆治理 SubAgent，也不在本变更中增加 LLM relevance filter；embedding 不可用时仍可通过 FTS、Pattern 和 metadata 运行。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `memory`: 将关键词与混合检索契约升级为 MemOS 风格的严格 FTS/BM25、短词 Pattern、语义和 metadata 多通道召回，以及归一化融合、阈值、多样性、诊断和索引迁移行为。

## Impact

- 主要影响 `memoli_agent/agent/memory/sqlite_store.py`、`hybrid.py`、查询模型/检索端口、`bootstrap/config.py` 和 `bootstrap/memory.py`。
- SQLite memory schema 需要提升版本并重建派生 FTS 索引；权威记忆表和轨迹证据不迁移、不改写。
- `[memory.hybrid]` 增加显式 lane 配置。未声明旧键的配置采用新默认值；显式声明 `keyword_weight` 的配置必须改为 `fts_weight` 和 `pattern_weight`，不保留双语义兼容层。
- 不增加网络依赖。FTS5/trigram 不可用时必须显式降级到受限 Pattern/metadata/semantic 通道，而不是静默改变结果语义。
- 用户可见变化是短 CJK 查询能够召回非连续但相关的记忆，同时宽松命中不会自动获得与严格 BM25 或多通道命中相同的置信度。
