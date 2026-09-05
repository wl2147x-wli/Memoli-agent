## Purpose

建立能够区分真实缓存命中、理论前缀复用和偶然延迟变化的 KV cache 评测规范，以可重复实验量化 Prompt 组装、工具 schema、上下文变化和并发对缓存效率的影响。

## ADDED Requirements

### Requirement: 缓存真值与可观测性分级
系统 SHALL 将 Provider 或推理引擎报告的缓存 token/计数器作为真实命中证据，将 token 最长公共前缀作为理论复用证据，将 TTFT 仅作为辅助证据。

#### Scenario: Provider 返回 cached tokens
- **WHEN** 模型响应包含明确的缓存读取 token
- **THEN** 运行 MUST 标记为 `cache_observable=true` 并使用该字段计算真实缓存比例

#### Scenario: 只有 TTFT 变快
- **WHEN** Provider 不返回缓存字段但重复请求 TTFT 降低
- **THEN** 报告 MUST 表述为延迟改善，不得宣称真实 KV cache 命中率提升

### Requirement: 前缀稳定性分析
系统 SHALL 比较同一会话相邻 Generation 的 system、tools、messages 和整体请求指纹，并在具备匹配 tokenizer/chat template 时计算最长公共前缀 token 数与首个差异位置。

#### Scenario: 本地模型 tokenizer 可用
- **WHEN** 评测使用已知 tokenizer 和实际 chat template
- **THEN** 系统 MUST 输出 LCP token 数、理论缓存比例、首个差异 token 索引和差异所属区段

#### Scenario: 外部 Provider 模板不可见
- **WHEN** 无法获得服务端最终 chat template
- **THEN** 系统 MUST 将客户端 LCP 标记为估算值，并分别提供规范化字节前缀与 Provider cached token 真值

### Requirement: 配对微基准协议
系统 SHALL 提供相同长度、相同输出预算和相同采样参数的命中/未命中配对实验，并 SHALL 交替运行完全相同前缀与靠前固定宽度变异前缀。

#### Scenario: 4K 前缀配对测试
- **WHEN** 运行缓存微基准
- **THEN** 系统 MUST 先执行预热，再以 hit/miss 成对交替方式运行不少于配置的重复次数，并记录每一对的原始数据

#### Scenario: 位置敏感测试
- **WHEN** 测试修改位置对缓存的影响
- **THEN** 数据集 SHALL 覆盖开头、中间、尾部追加以及工具 schema 顺序变化

### Requirement: Agent Prompt 变体实验
系统 SHALL 支持比较当前 Prompt、稳定 system、稳定 tools、稳定全部区段以及动态时间不同放置方式，且每个变体 MUST 使用相同任务、模型、参数和工具回放。

#### Scenario: 动态时间对照
- **WHEN** 比较当前 system 内动态时间与尾部临时消息两种方案
- **THEN** 报告 MUST 同时给出 system 哈希变化、真实缓存比例、理论 LCP、TTFT 和任务质量

### Requirement: 缓存污染控制
系统 SHALL 记录模型实例、服务实例、并发、预热、请求顺序、时间间隔和缓存隔离方法，并 MUST 防止不同变体互相预热导致错误归因。

#### Scenario: 本地引擎变体切换
- **WHEN** 从一个实验变体切换到另一个变体
- **THEN** 运行器 MUST 重启/清空缓存或采用等效隔离方法，并记录隔离方式

#### Scenario: 云 Provider 无法清缓存
- **WHEN** Provider 不提供缓存清理或命名空间能力
- **THEN** 系统 MUST 使用随机化区组与独立前缀标记污染风险，报告中 MUST 披露该限制

### Requirement: KV cache 聚合指标
系统 SHALL 输出真实缓存 token 比例、缓存调用命中率、uncached input、TTFT p50/p95、总延迟、吞吐、理论 LCP 和缓存收益成本。

#### Scenario: 聚合缓存比例
- **WHEN** 汇总多个 Generation
- **THEN** 缓存比例 MUST 使用 `sum(cached)/sum(inclusive_input)` 计算，不得简单平均单次比例

#### Scenario: 混合可观测数据
- **WHEN** 数据集中部分调用没有缓存真值
- **THEN** 真实缓存指标 MUST 只使用 `cache_observable=true` 的调用，并单独报告覆盖率

### Requirement: KV cache 统计结论
系统 SHALL 保存逐调用原始记录，并 SHALL 使用配对差值、中位数、p95 和置信区间比较变体；报告 MUST 同时显示效果量和样本量。

#### Scenario: 生成正式比较报告
- **WHEN** 两个变体完成规定重复次数
- **THEN** 报告 MUST 包含命中率差、缓存 token 比例差、TTFT 配对改善率、置信区间、质量非劣结果与不可观测比例

