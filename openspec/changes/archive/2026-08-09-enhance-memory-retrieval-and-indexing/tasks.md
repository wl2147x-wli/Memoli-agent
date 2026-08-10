## 1. 回归基线与数据契约

- [x] 1.1 为现有 FTS5/LIKE 关键词召回、类型配额、作用域过滤和空结果行为补齐不改变行为的回归测试
- [x] 1.2 为现有 passive turn 的工作 checkpoint 注入、召回诊断和 memory block 预算补齐回归测试
- [x] 1.3 为现有 Card 版本写入、Episode 显式索引及旧版 `memory.db` 打开流程补齐回归测试
- [x] 1.4 扩展 `MemoryQuery` 与结果诊断模型，分别表达主查询、工作目标、当前步骤、会话、scope、类型、时间边界和预算
- [x] 1.5 修改 `MemoryRuntime.pre_recall()` 使用结构化查询，并验证无 checkpoint 时仅使用当前用户输入和硬约束

## 2. SQLite 索引模式与迁移

- [x] 2.1 为 `semantic_index`、`memory_index_jobs` 和投影状态设计带类型注解的数据模型与稳定键
- [x] 2.2 增加向前兼容的 SQLite schema migration、唯一索引和 schema version 更新，不修改已有事实记录
- [x] 2.3 实现源内容规范化与 content hash 计算，覆盖 Card 当前版本、有效 Claim 和 Episode 检索文本
- [x] 2.4 在 eligible source 提交、更新和失效路径中幂等登记、刷新或清理索引任务
- [x] 2.5 增加从现有 Card、Claim、Episode 回填索引任务的可重复执行入口及迁移测试

## 3. 可选语义索引

- [x] 3.1 定义异步 `Embedder` 协议、禁用实现、错误类型和不依赖网络的确定性测试实现
- [x] 3.2 实现 OpenAI-compatible embedding adapter，支持独立超时、模型/版本/维度配置和环境变量密钥读取
- [x] 3.3 实现 float32 BLOB 编解码、维度校验、有限值校验和余弦相似度计算
- [x] 3.4 实现串行批处理 `MemoryIndexWorker`，覆盖 pending 领取、原子发布、退避重试、过期 job 丢弃和安全错误摘要
- [x] 3.5 实现按 model/version/dimensions/content hash 读取 ready vector 的精确语义检索通道，并先执行元数据预过滤和候选上限
- [x] 3.6 实现全量/按类型语义索引重建，确保重建不改变 Claim、CardVersion、Episode ID 和证据
- [x] 3.7 测试禁用、超时、无效维度、stale vector、重启续跑、重复 job 和重建期间的关键词降级

## 4. 确定性混合召回

- [x] 4.1 将现有 FTS5/BM25 与有界 LIKE 封装为统一关键词候选通道并保持兼容排序测试
- [x] 4.2 实现 core/importance/recency 元数据候选通道，复用现有 scope、status、sensitivity 和 validity 规则
- [x] 4.3 实现统一候选模型和稳定 ID 去重，保留每个候选的来源通道、证据与命中原因
- [x] 4.4 实现可配置的 RRF 融合、lane weight、固定并列规则，并禁止直接混加未经标定的原始分数
- [x] 4.5 实现 Card/Claim/Episode 类型预算、固定配额回流顺序和最终字符预算裁剪
- [x] 4.6 扩展召回结果与 trajectory metadata，记录使用/降级通道、候选数、过滤数、注入 ID 和结构化字段，不记录向量与密钥
- [x] 4.7 将混合检索器接入 `MemoryRuntime` 和 bootstrap；无 embedding 配置时自动使用关键词兼容模式
- [x] 4.8 增加多通道重复候选、同分排序、单通道失败、全部无匹配、配额回流和重复查询确定性的测试

## 5. 受治理的 Card Builder

- [x] 5.1 定义稳定的 `scope + subject + card_kind` 投影键、Card 草稿和逐句 Claim 引用模型
- [x] 5.2 实现只选择 active/approved、有效、同 scope 且有 evidence Claim 的确定性 Card 投影器
- [x] 5.3 实现可替换的 Card 文本生成接口和确定性默认生成器，并校验生成内容不能脱离 Claim 引用
- [x] 5.4 实现 Card 创建、内容 hash 幂等判断和原子新版本提交，完整保留旧版本与 current 指针一致性
- [x] 5.5 实现 frozen Card 跳过、candidate/rejected/expired Claim 排除和时序冲突并列保留
- [x] 5.6 在 Claim 生命周期变化后登记 Card 投影工作；投影失败不得回滚 Claim 或覆盖当前 Card
- [x] 5.7 为新建、修订、无变化、冻结、候选排除、冲突和无证据生成失败增加测试

## 6. Episode 自动投影与索引

- [x] 6.1 扩展 Episode segment 数据以保存稳定 segment ID、原始轨迹引用、context prefix、search text、segmenter version 和 content hash
- [x] 6.2 实现只读取已完整提交 trace 的确定性 segmenter，以 turn 为默认边界并在超长时按消息/工具事件边界拆分
- [x] 6.3 使用 session、当前用户请求、working objective/current-step 和 turn outcome 生成有界上下文前缀，不调用额外 LLM
- [x] 6.4 在 trace durable completion 生命周期点登记 Episode 投影，重复通知以稳定键 upsert
- [x] 6.5 将新 Episode 同步接入关键词索引并登记语义索引 job，确保原始细节仍通过 trajectory 引用解析
- [x] 6.6 实现按 trace 和 segmenter version 的幂等重试、重建与历史 Episode backfill
- [x] 6.7 测试完整/未完整 trace、歧义片段上下文化、超长拆分、重复通知、轨迹读取失败和版本重建

## 7. 配置、组合与运行维护

- [x] 7.1 扩展配置模型与 `config.example.toml`，加入默认关闭的 `[memory.embedding]`、混合融合参数、类型预算和投影开关
- [x] 7.2 在 `memoli_agent/bootstrap/memory.py` 组合 store、lanes、embedder、index worker、Card Builder 和 Episode projector，保持组件可替换
- [x] 7.3 在 runtime 启动和轮次空闲生命周期中以有界批次 tick 索引/投影工作，不并发执行 agent turn
- [x] 7.4 为迁移、索引积压、通道降级、重建和关闭语义能力增加安全的诊断输出或管理入口
- [x] 7.5 更新 `docs/systems/memory.md`、相关架构文档和 README，说明三类数据库边界、配置、降级、重建与安全约束

## 8. 验证与验收

- [x] 8.1 增加固定小数据集，对关键词兼容模式和混合模式执行确定性、召回结果及字符预算回归；该数据集不采集用户反馈、不训练排序器
- [x] 8.2 增加语义索引规模递增的 P50/P95 延迟与数据库体积基准，记录未来切换 sqlite-vec/HNSW 的建议阈值
- [x] 8.3 使用旧版数据库副本完成迁移、开启语义索引、关闭语义索引和派生表重建的端到端测试
- [x] 8.4 运行 `python -m pytest -q`、`python -m ruff check memoli_agent benchmarks tests` 和 `python -m pyright` 并修复本 change 引入的问题
- [x] 8.5 运行 `openspec validate enhance-memory-retrieval-and-indexing --strict`，核对 proposal、design、spec 和中文任务一致
