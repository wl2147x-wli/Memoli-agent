## 1. 查询与通道契约

- [x] 1.1 在 memory 模型层定义不可变 Query Plan，包含 primary/embedding 文本、FTS MATCH、Pattern terms、hard filters 和安全摘要字段
- [x] 1.2 提取共享 normalization、CJK run、bigram 和短 ASCII term 助手，确保 term 去重、稳定排序、16 项上限和截断标记
- [x] 1.3 实现 Query Builder，使 FTS/Pattern 只消费当前用户 query，embedding 文本保留 query/objective/current-step 字段边界并截断到 1500 字符
- [x] 1.4 定义统一 `ChannelHit` 契约，携带 stable identity、lane、rank、规范化相关性、可选 raw score 和安全 reason
- [x] 1.5 添加 Query Builder 单元测试，覆盖空查询、2 字 CJK、3+ 字 CJK、中间插词、短 ASCII、term 上限、辅助 working context 隔离和确定性重复结果

## 2. 配置与组装

- [x] 2.1 扩展 `MemoryHybridConfig`，加入 FTS/Pattern candidate limit、Pattern term limit、各 lane weight、RRF bonus、相对阈值、multi-lane protection、smart seed 和 MMR 参数
- [x] 2.2 删除 `keyword_weight` 的运行时语义并对旧键返回包含 `fts_weight`/`pattern_weight` 迁移提示的配置错误
- [x] 2.3 为 limit、weight、比例范围和“至少一个 lane 权重大于零”实现边界校验
- [x] 2.4 更新 memory bootstrap，使所有检索路由共享 Query Builder 和显式 `fts`、`pattern`、`semantic`、`metadata` lane 实例
- [x] 2.5 添加默认配置、自定义配置、旧键拒绝、非法边界和 embedding-disabled 组装测试

## 3. Sparse 索引与数据库迁移

- [x] 3.1 将 memory schema 提升到 7，并设计 Claim、当前 Card/Card statement、Episode 的统一或分表 FTS stable identity 与 index format/version 元数据
- [x] 3.2 实现 SQLite FTS5、trigram tokenizer 和 `bm25()` 的启动能力探测，区分 unavailable 与普通 SQL failure
- [x] 3.3 实现新数据库 schema 7 的 sparse 索引创建和 Claim/Card/Episode 写入、更新、失效同步
- [x] 3.4 实现 schema 6→7 事务迁移，从权威表回填新 sparse 索引、验证 stable identity/记录计数后再发布版本
- [x] 3.5 确保新索引发布成功后才移除旧派生搜索表，任何创建、回填或验证失败均回滚且不改写权威记忆
- [x] 3.6 实现幂等 sparse index rebuild 操作，tokenizer/index format 变化时只重建派生索引且不触发治理或事实写入
- [x] 3.7 添加空库初始化、schema 6 升级、重复升级、迁移失败回滚、显式重建、stable ID 保持和 FTS/trigram 不可用测试

## 4. FTS 与 Pattern 召回

- [x] 4.1 实现 Claim、Card/Card statement、Episode 的严格 FTS lane，使用 Query Plan 的 FTS MATCH 和 `bm25()` lane 内排序
- [x] 4.2 将 BM25 结果转换为 `1/rank` 规范化相关性，保留 raw score 仅用于安全诊断且禁止进入跨 lane 加法
- [x] 4.3 实现通用 Pattern lane，转义 `%`、`_`、escape 字符，以最多 16 个 term 执行有界 LIKE OR 召回
- [x] 4.4 在 FTS 与 Pattern SQL 中尽量下推 scope、状态、敏感度和有效时间过滤，并保证过滤发生在各 lane candidate limit 之前
- [x] 4.5 为不能完全 SQL 下推的约束提供有界预过滤窗口、过滤计数和 degraded reason，禁止返回越权候选
- [x] 4.6 删除主 FTS 查询中的宽松 bigram OR 和 Card/Episode/Card statement 的旁路文本匹配，使宽松召回只来自 Pattern lane
- [x] 4.7 添加“清华源→清华镜像源”、连续精确 CJK、1/2 字边界、ASCII 短词、LIKE 转义、跨 scope、敏感度、过期/失效状态及 lane limit 测试
- [x] 4.8 添加 FTS 不可用时 Pattern/semantic/metadata 继续工作、Pattern 失败仅独立降级以及所有可用 lane 为空的测试

## 5. MemOS 风格融合与选择

- [x] 5.1 将各 lane 输出按 stable memory identity 去重并聚合贡献 lane、rank、normalized relevance 和 reason
- [x] 5.2 实现 `max(normalized relevance) + rrf_bonus_weight × Σ(weight/(rrf_k+rank))`，默认 `rrf_k=60`、bonus weight=0.4
- [x] 5.3 实现多通道数、Card→Claim→Episode、时间倒序和 stable ID 的固定同分决胜顺序
- [x] 5.4 实现默认 0.2 的相对相关性阈值和可配置 multi-lane protection，确认两者均不能绕过 hard filter
- [x] 5.5 实现按请求类型和配额的 smart seed，只为达到该类型最高分比例的候选保留种子
- [x] 5.6 实现确定性 MMR：优先使用已就绪同版本缓存向量，否则使用 normalization token/CJK bigram Jaccard，且不得在线请求 embedding
- [x] 5.7 保持现有类型配额、spillover、总数量和字符预算为最终硬边界
- [x] 5.8 添加 FTS-only、Pattern-only、semantic-only、多 lane 重合、raw score 尺度隔离、相对阈值、多 lane 保护、无关类型不补位、MMR 去重和重复查询稳定性测试

## 6. 分层路由与 Card 展开

- [x] 6.1 重构 `LayeredMemoryRetriever`，使 card-first、claim-first、episode-first 和 hybrid 只改变 item types、详情展开和配额并共享同一 Query Plan
- [x] 6.2 让 Card-first 通过共享 FTS/Pattern lane 搜索 current Card statement，移除旧的 substring term-count 排名旁路
- [x] 6.3 保持 Card-first 在 `fact`/`evidence` detail level 才展开关联 Claim/证据，并对展开结果继续执行稳定 ID 去重和预算
- [x] 6.4 保持无相关 Card statement 时的显式 Claim fallback，复用同一 Query Plan 并记录 requested/actual route 与原因
- [x] 6.5 添加四种路由、Card statement 命中、按需 Claim/证据展开、Claim fallback、Pattern-only Card 和预算边界回归测试

## 7. 安全诊断与可观测性

- [x] 7.1 扩展 `MemoryQueryResult` 和最终 `MemoryItem` metadata，记录 query 字段摘要、term 数/截断、各 lane 候选数、degraded reason、贡献 rank、规范化分和 fused relevance
- [x] 7.2 分别统计 hard filter、相对阈值、MMR、类型/数量/字符预算过滤数量，保持现有 omitted item/char 语义
- [x] 7.3 将新的检索摘要接入 trajectory 诊断，确保诊断写入失败不改变候选排序或主回合结果
- [x] 7.4 添加安全测试，证明诊断不包含 query/记忆正文副本、原始 embedding、API key 或越权候选内容

## 8. 文档与验证

- [x] 8.1 更新 memory 系统文档和示例配置，说明 MemOS 风格 lane 数据流、默认参数、`keyword_weight` 移除、schema 7 重建与 degraded 行为
- [x] 8.2 使用 `D:\software\miniconda\envs\memoli\python.exe` 运行新增 Query Builder、迁移、sparse lane、融合、路由和诊断测试
- [x] 8.3 使用同一 Conda 环境运行既有 memory、context、CLI 相关回归测试并处理行为契约内的回归
- [x] 8.4 使用同一 Conda 环境运行 `python -m ruff check memoli_agent benchmarks tests` 和 `python -m pyright`
- [x] 8.5 运行 `openspec validate adopt-memos-style-hybrid-memory-retrieval --strict` 与 `openspec validate --all --strict`，确保 delta spec 和仓库全部通过
