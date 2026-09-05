## 1. 基线与依赖

- [ ] 1.1 保存遥测接入前的代表性模型 request JSON、Agent 事件和现有测试结果作为兼容基线，并验证基线工件可由测试读取且不包含凭据
- [ ] 1.2 新增 `requirements-observability.txt` 并锁定经过验证的 Langfuse Python SDK 主版本，验证核心依赖安装与不安装可选依赖两种环境均可启动项目
- [ ] 1.3 在默认配置中加入 `observability` 和 `evaluation` 非敏感配置段，验证旧版缺失配置、合法新配置和非法枚举/范围的配置测试通过
- [ ] 1.4 实现 Langfuse 凭据只从环境变量读取，并验证 config 中出现 public/secret key 时会被忽略且只输出脱敏迁移告警

## 2. 内部可观测契约与空实现

- [ ] 2.1 创建 `agent/observability/` 模块结构和 `Tracer/TraceHandle/ObservationHandle` Protocol，验证类型检查和最小 fake 实现测试通过
- [ ] 2.2 实现幂等、线程安全的 `NoopTracer` 与空 handle，验证重复 update/end、嵌套 context manager 和异常退出均无副作用
- [ ] 2.3 实现 `TraceContext` 与 `EvaluationContext` 的 capture/attach/reset，验证嵌套运行恢复、并发线程隔离和显式跨线程传播测试通过
- [ ] 2.4 实现 `ObservationKind`、状态、错误类别和 `telemetry_schema_version` 常量，验证所有序列化事件都包含受支持的 schema 版本
- [ ] 2.5 实现 tracer factory 的延迟初始化、SDK 缺失降级和单例生命周期，验证导入失败、配置错误与重复初始化均返回可用空实现

## 3. 隐私、指纹与数据大小控制

- [ ] 3.1 实现 JSON 确定性规范化以及顺序敏感/无关哈希，验证 dict 键顺序、工具顺序和等价 schema 的测试向量符合预期
- [ ] 3.2 实现基于独立密钥的 HMAC 标识指纹，验证相同输入稳定、不同环境隔离且原始低熵 ID 不出现在结果中
- [ ] 3.3 实现 secret 字段识别、allowlist、固定掩码、路径脱敏、内容截断和自定义 mask，使用 secret canary 验证 SDK 载荷与本地 receipt 均无泄漏
- [ ] 3.4 实现 mask 失败即丢弃载荷的安全降级，验证异常 mask 不会回退发送未脱敏内容
- [ ] 3.5 实现 Observation metadata、排名明细和正文大小上限，验证超限数据被有标记地截断且不会复制完整大型工具结果

## 4. Langfuse 适配器

- [ ] 4.1 实现 Langfuse tracer 初始化、环境/版本/tag 映射和 SDK 配置，使用 mock SDK 验证构造参数和凭据来源
- [ ] 4.2 实现根 Trace、Span、Generation、Embedding、Retriever 和 Tool Observation 映射，验证父子 ID、名称、类型、时间和终态字段正确
- [ ] 4.3 实现 Observation 的正常、错误、取消、超时和 unknown 结束路径，验证任何路径都恰好 end 一次
- [ ] 4.4 实现 Score 上报和版本化命名校验，验证 numeric/boolean/categorical 以及 unknown 不被错误记零
- [ ] 4.5 实现批量 flush、shutdown、有界超时和未发送计数，验证短生命周期进程结束时 mock 队列被刷新
- [ ] 4.6 实现连续故障熔断、半开恢复和 fail-open 日志，验证 Langfuse 全程异常时 Agent 模拟任务仍成功且不会日志风暴
- [ ] 4.7 使用本地或测试 Langfuse 执行 contract test，验证远端持久化的 Observation 类型、usage details、completion start time 和 Score 与本地预期一致

## 5. Run 生命周期与 Trace 关联

- [ ] 5.1 在 `AgentBridge._begin_run` 创建根 Trace 并复用本地 run ID，验证普通会话的 conversation run 与 Langfuse Trace 一对一
- [ ] 5.2 将 Langfuse trace ID、schema version、experiment 和 variant 写入 run extras，验证 `ConversationStore.get_run` 可返回关联信息
- [ ] 5.3 在 `AgentBridge._end_run` 汇总并结束 Trace，验证成功、失败和取消状态且本地 ambient run ID 始终恢复
- [ ] 5.4 为绕过 bridge 的直接 `Agent.run_stream` 实现 fallback Trace，验证已有 Trace 时不重复建根、无 Trace 时仍得到完整运行
- [ ] 5.5 实现确定性 run 级采样，验证一个未采样 Trace 的所有子 Observation 一致不发送且无孤立节点

## 6. 模型流、TTFT 与 Usage

- [ ] 6.1 实现 `RawUsage/NormalizedUsage/UsageCollector`，覆盖 OpenAI、Responses、Anthropic 风格和项目已知 provider 字段，验证 fixture 表中的所有映射
- [ ] 6.2 实现 inclusive input 扣除 cache read/cache creation 的非负计算，验证 unknown、明确0、字段冲突、负值和 total 不一致的处理
- [ ] 6.3 修改 OpenAI-compatible 请求以支持 `include_stream_usage=auto|true|false`，验证请求只在启用时增加 `stream_options.include_usage`
- [ ] 6.4 实现 endpoint/model 级 stream usage 能力协商，验证只有明确 unsupported-parameter 且未开始生成时降级一次，网络/流错误不重复请求
- [ ] 6.5 修改各相关原生 provider 响应转换以保留缓存和详细 usage 字段，使用 provider fixture 验证转换不再丢失明细
- [ ] 6.6 在 HTTP SSE 客户端加入无正文的传输时序回调，验证 request-sent、headers、first-SSE、end 和异常时间顺序正确
- [ ] 6.7 在 `_call_llm_stream` 为每次尝试创建 Generation 并首先消费 usage-only chunk，验证末尾无 choices 的 usage 仍被记录
- [ ] 6.8 实现 first-model-event 与首个非空 reasoning/content TTFT，验证空 delta、role-only、reasoning-first、tool-only 和普通文本流
- [ ] 6.9 让正常、空响应重试、fallback、上下文溢出、取消和流中断分别结束 Generation，验证每次尝试独立可见且不会合并 token
- [ ] 6.10 实现 `RunMetricsAccumulator` 按 observation ID 去重和按用途分项，验证 main/summary/judge/subagent usage 汇总不重复计费
- [ ] 6.11 在 Langfuse 自定义模型 fixture 中验证 `input`、`input_cached_tokens`、`input_cache_creation`、`output` 和 `total` 的 token/成本计算与原始账单一致

## 7. Prompt 构建与 KV Cache 指纹

- [ ] 7.1 扩展 Prompt Builder 可选返回 `PromptBuildReport/PromptSection`，验证默认字符串 API 和最终 Prompt 字节与基线完全一致
- [ ] 7.2 为 tools、skills、memory、knowledge、workspace、permissions、identity、context files 和 runtime 区段生成边界与指纹，验证动态时间变化可定位到 runtime
- [ ] 7.3 在 `Agent.get_full_system_prompt` 加入 `prompt-build` Span，验证读取/刷新失败回退时仍记录来源和最终 system hash
- [ ] 7.4 在实际 LLM 请求前生成 system/tools/messages/request 指纹和尺寸，验证记录的是转换前明确层级且可与 provider 最终发送快照关联
- [ ] 7.5 为工具 schema 记录 ordered 与 canonical hash、schema source 和名称序列，验证动态 schema、静态 params 和乱序对照
- [ ] 7.6 实现有界的相邻请求前缀状态与 component/message 首差异定位，验证不同 session/provider/model 互不污染
- [ ] 7.7 在匹配 tokenizer/chat template 可用时实现精确 LCP token，在不可用时标记客户端估算，验证报告不会把估算写成 Provider 真值

## 8. 上下文压缩与截断观测

- [ ] 8.1 实现统一 `ContextTransformRecorder` 和 before/after 快照，验证消息数、轮数、字符、估算 token、工具对完整性和首差异字段
- [ ] 8.2 为 `run_stream` 的上下文准备与 `_trim_messages` 轮次限制埋点，验证半区删除的 discarded/kept 范围和摘要 job ID
- [ ] 8.3 为 token 超限下的少轮纯文本压缩与多轮半区删除埋点，验证策略分支、前后 token 和工具链变化
- [ ] 8.4 为 `_smart_compact_to_budget` 的每次 guard 迭代、Provider 预算解析、最终重试和 context reset 埋点，验证溢出恢复轨迹可重建
- [ ] 8.5 为当前轮和历史轮工具结果截断埋点，验证原始大小、模型可见大小、限制类型和所属 tool call 正确
- [ ] 8.6 为摘要 callback 注入建立 message/job 关联，验证异步摘要修改目标消息时记录准确且没有跨 run 注入
- [ ] 8.7 计算压缩事件前后缓存边界和后续缓存恢复轮数，使用 scripted usage 流验证 cache loss/recovery 指标

## 9. 记忆、摘要和 Embedding 观测

- [ ] 9.1 为 `MemoryManager.search` 添加 Retriever Span，验证 query 指纹、scope、阈值、同步状态、候选计数、top-k 和耗时
- [ ] 9.2 记录向量/关键词原始候选、融合权重、时间衰减、最终分数和 rank，验证有界明细能解释已知 fixture 排序
- [ ] 9.3 为 embedding query cache 记录 hit/miss 且不上传 query 原文，验证缓存命中时不创建远程 embedding 调用
- [ ] 9.4 为 `add_memory` 和 `sync` 添加 write/sync Span，验证文件扫描、changed/deleted、chunk、upsert/delete 和 dirty 重试状态
- [ ] 9.5 为 `flush_memory` 创建 job ID 并显式传播 TraceContext，验证 dispatch 与后台实际成功/失败不会混淆
- [ ] 9.6 在 `_flush_worker/_call_llm_for_summary` 创建 memory flush Span 和 summary Generation，验证异步完成后仍关联原 run 并更新分项成本
- [ ] 9.7 记录摘要去重、空 sentinel、规则回退、文件写入和 callback 结果，验证重复 flush 不重复计费且回退原因清楚
- [ ] 9.8 实现 `ObservedEmbeddingProvider` 装饰器并在 factory/initializer 接入，验证所有 provider 无需分别复制埋点代码
- [ ] 9.9 记录 embedding provider/model/dimension、逻辑条目、实际批次、大小、延迟、返回数量/维度和错误，验证 batch 分片与维度错误 fixture
- [ ] 9.10 为 keyword-only 回退和索引失败添加状态，验证文件已持久化但不可检索时 Trace 不会误报完整成功
- [ ] 9.11 在 memory_get/search 注入模型时记录 retrieved->injected 状态，验证 retrieved、injected、used/contributed 不被自动合并

## 10. 工具与 MCP 观测

- [ ] 10.1 在 `_execute_tool` 所有早返回之前创建 Tool Span，验证 missing args、not found、permission denied、loop protection、正常和异常均有终态
- [ ] 10.2 记录工具参数脱敏值/指纹、schema hash、权限模式、执行时间、状态和错误分类，使用 canary 参数验证无凭据泄漏
- [ ] 10.3 记录工具结果原始与模型可见大小、截断、artifact 和 display 分离，验证自行渲染卡片工具不会产生重复 Span
- [ ] 10.4 为 `_run_parallel_calls` 显式传播上下文并生成 parallel group，验证并行 Tool Span 是同一父节点下的兄弟且时间区间重叠
- [ ] 10.5 将同工具同参数调用关联为 retry/loop group，验证重复率、连续失败和恢复尝试统计
- [ ] 10.6 为 MCP 同步、连接状态和动态加载记录有界事件，验证单个 server 失败不会阻止其他工具观测
- [ ] 10.7 在 `_select_tools_for_injection` 记录 MCP retrieval query 指纹、候选排名、top-k、新增/累计集合和 fallback，验证最终注入集与 Generation tools hash 对应
- [ ] 10.8 实现工具轨迹 evaluator 的 required/allowed/forbidden、参数断言、顺序和多余调用评分，验证黄金与反例轨迹

## 11. Skill 观测与评测

- [ ] 11.1 为 SkillLoader 记录 discovered、source、文件指纹、诊断和同名覆盖，验证自定义 Skill 覆盖内置 Skill 时只有最终版本进入可用集合
- [ ] 11.2 为 `refresh_skills` 生成刷新版本并记录新增/删除/变化，验证运行间 Skill 变化可以通过版本和 hash 识别
- [ ] 11.3 为 `filter_skills/filter_unavailable_skills` 记录 selection、enabled、requirements、missing requirements 和知识开关，验证 unavailable 与 disabled 不混淆
- [ ] 11.4 为 `build_skills_prompt/build_skill_snapshot` 记录 injected 名称、顺序、来源、Prompt 大小与 hash，验证记录与最终 system Prompt 区段一致
- [ ] 11.5 建立 Skill 路径 registry，并在 read 工具访问规范化 `SKILL.md` 路径时标记 selected/definition-read，验证普通 markdown 读取不误报 Skill
- [ ] 11.6 实现 eligible->injected->selected->definition-read->applied->contributed 状态模型，验证缺证据状态保持 unknown 而不是成功
- [ ] 11.7 实现 Skill evaluator 的触发/非触发、must/must-not steps、工件和 adherence 规则，验证读取但违反流程会判 adherence failure
- [ ] 11.8 实现 Skill 启用/禁用消融运行，验证报告包含触发准确率、遵循度、任务质量、token、延迟和轨迹差异

## 12. Scheduler、子代理、委托与后台任务

- [ ] 12.1 为 scheduler 自动和手动运行建立 task Trace 属性，验证 task ID/source、计划/实际时间、claim/release 和终态
- [ ] 12.2 在 `agent/subagent/runner` 复用 child run ID 创建子 Trace，验证 parent_run_id、模板、深度、brief hash、工具/Skill 继承和 summary
- [ ] 12.3 显式传播并行子代理上下文，验证多个子 Trace 不串线且父任务聚合不重复计费
- [ ] 12.4 为 `agent_delegate` 建立 source request Span 与 target Trace link，验证跨线程委托仍可从父任务导航到目标运行
- [ ] 12.5 将 daily flush、deep dream 和 evolution 建模为 background task Trace/causal link，验证不会让已返回用户请求的父 Span 长期悬空
- [ ] 12.6 为可选渠道发送建立 `channel.delivery` Span，验证渠道延迟与模型 TTFT 分离且发送失败不改写模型成功状态

## 13. 评测数据模型与确定性运行器

- [ ] 13.1 实现数据集、任务、期望结果、轨迹约束、工件断言和 limits 的 schema 校验，验证合法 fixture 与缺字段/冲突 fixture
- [ ] 13.2 实现版本化 dataset loader 与不可变内容 hash，验证同名数据修改会产生不同版本且正式运行保存版本
- [ ] 13.3 实现临时工作区快照创建和运行后工件收集，验证 baseline/candidate 初始文件完全相同且互不污染
- [ ] 13.4 实现冻结时钟、随机种子和稳定任务顺序，验证相同 manifest 可复现同一运行计划
- [ ] 13.5 实现本地/MCP/网络工具 replay adapter，验证匹配调用返回固定响应、额外调用被标记轨迹偏差且不会访问真实外部系统
- [ ] 13.6 实现 variant 配置覆盖而不修改用户 `config.json`，验证 baseline、stable-system、stable-tools 和 compression 变体隔离
- [ ] 13.7 实现 runner 的重复、随机区组、超时、取消、失败继续和有界并发，验证单任务失败不丢失其他任务 receipt
- [ ] 13.8 为每个运行保存脱敏本地 JSONL receipt 和 manifest，验证包含代码/脏树/依赖/OS/硬件/模型/配置/命令且可独立读取
- [ ] 13.9 集成 Langfuse Dataset/Experiment 关联，验证 dataset item、experiment run、Trace 和本地 receipt 可以通过 ID 双向匹配

## 14. 组件评测器

- [ ] 14.1 实现 KV cache 微基准的预热、hit/miss 配对、固定宽度早期变异、前缀长度和并发矩阵，验证每对参数除目标变量外一致
- [ ] 14.2 实现本地缓存隔离与云 Provider 污染记录，验证变体切换会记录 restart/namespace/randomized-block 策略
- [ ] 14.3 实现上下文压缩数据生成器，覆盖长多轮、少轮超大消息、固定大型工具结果和溢出模拟，验证所有压缩分支能稳定触发
- [ ] 14.4 实现压缩事实、决策、约束、实体和工具链保留 evaluator，验证已知丢失/幻觉/完整摘要 fixture
- [ ] 14.5 实现记忆黄金查询与 Recall@K、Precision@K、MRR、nDCG、空结果和错误 scope evaluator，验证手算排名 fixture
- [ ] 14.6 实现记忆生成的事实覆盖、错误、重复、冲突和时效 evaluator，验证新事实优先和重复 flush 场景
- [ ] 14.7 实现端到端文本、轨迹、工件和规则 evaluator，验证“文本声称成功但工件缺失”不会通过
- [ ] 14.8 实现可选 LLM judge 子 Generation、结构化解析和 unknown 降级，验证 judge 失败不覆盖确定性分数

## 15. 聚合、统计与发布门禁

- [ ] 15.1 实现按 Observation ID 去重的本地与 Langfuse 数据合并，验证摄取重复和迟到后台事件不会重复累计
- [ ] 15.2 实现缓存 token 比例、调用命中率、可观测覆盖率、TTFT、总 token/成本和每成功任务成本，验证聚合采用总和之比
- [ ] 15.3 实现工具、Skill、记忆、压缩和子代理指标聚合，使用固定 receipts 验证所有公式和 unknown 传播
- [ ] 15.4 实现 baseline/candidate 配对差值、中位数、p95、效果量和 bootstrap 置信区间，验证固定随机种子下输出稳定
- [ ] 15.5 实现 Langfuse Observations/Metrics API 的有界轮询与分页，验证摄取延迟、部分缺失和 API 错误会产生 provisional/inconclusive
- [ ] 15.6 实现总体及类别级非劣、成本、延迟、错误率和缓存覆盖门禁，验证 pass/fail/inconclusive 三态和机器可读退出码
- [ ] 15.7 生成 Markdown、JSON 和 CSV 报告，验证报告包含样本量、缺失量、置信区间、配置、证据链接和限制声明

## 16. 数据集、Dashboard 与文档

- [ ] 16.1 创建不调用外部服务的 smoke 数据集，覆盖直接回答、工具成功/失败、权限、取消、压缩、记忆、Skill 和子代理，验证全量可离线运行
- [ ] 16.2 创建完整评测数据集与类别覆盖清单，验证 direct/file/code/search/browser/MCP/memory/skill/long-context/overflow/parallel/subagent/fallback 均有样本
- [ ] 16.3 创建 baseline、stable-system、stable-tools、stable-all、half-trim、watermark-compact、rolling-summary 和 recent-tools-preserved 变体配置并验证解析
- [ ] 16.4 配置 Langfuse 自定义模型 usage key 与价格模板，验证未知价格不生成虚假成本且已知价格与手算一致
- [ ] 16.5 建立任务质量、KV cache/TTFT、压缩、记忆、工具、Skill 和子代理 Dashboard 模板，验证可按 experiment/variant/category/provider/model 过滤
- [ ] 16.6 编写安装、环境变量、自托管/Cloud 连接、隐私、运行 benchmark、查看 Trace、导出报告和故障排查文档，并按文档在干净环境完成一次 smoke
- [ ] 16.7 编写指标数据字典和 schema 版本迁移说明，验证每个 Langfuse usage/metadata/score 字段都有单位、null/0 语义和来源

## 17. 集成验证与渐进发布

- [ ] 17.1 运行全部现有测试并比较遥测关闭时的模型 request 快照、Agent 事件和结果，验证无行为回归
- [ ] 17.2 运行新增单元与集成测试，验证 Trace 层级、usage、TTFT、隐私、并发、后台任务和 fail-open 覆盖
- [ ] 17.3 连接测试 Langfuse 运行完整 smoke experiment，验证远端 Trace/Observation/Score 与本地 receipts 条数和关键数值一致
- [ ] 17.4 使用支持缓存真值的本地生成模型运行 KV cache component benchmark，验证重复长前缀出现非零 cache read 且早期变异降低复用
- [ ] 17.5 使用真实 embedding 服务运行记忆 component benchmark，验证向量维度、批次、混合检索指标和 keyword-only 故障回退
- [ ] 17.6 运行 baseline 与至少一个上下文优化 candidate 的完整配对实验，验证可产出质量、缓存、token、成本和延迟综合报告
- [ ] 17.7 测量关闭、生产低采样和评测全采样三种模式的 CPU、内存、延迟与载荷大小，验证达到设计的性能预算或记录门禁失败
- [ ] 17.8 在开发环境以 hashes-only 低采样启用并检查 dropped events、熔断、隐私 canary 和摄取延迟，验证后再形成生产启用清单
- [ ] 17.9 验证运行时关闭 `observability.enabled` 可立即回到 Noop 路径且无需回滚业务代码，并记录最终回滚演练结果
