## Why

当前项目已经具备多轮 Agent loop、上下文修剪与摘要、长期记忆、混合检索、工具与 MCP、Skill 提示注入、子代理和任务运行记录，但缺少贯穿这些组件的统一可观测数据模型与可重复评测基线。现有日志和事件主要服务于运行展示，无法严谨回答 KV cache 是否命中、压缩是否真正节省总 token、记忆是否提升任务质量、工具与 Skill 是否被正确选择，以及一次完整任务的质量、延迟、成本和失败原因。

## What Changes

- 引入可插拔的 Langfuse 可观测层，以一个 Agent run 为根 Trace，以每次 LLM 调用、工具执行、Skill 使用、记忆操作、上下文压缩和子代理运行为结构化子 Observation。
- 新增统一的 usage 规范化与流式计时能力，保留提供商返回的 prompt、cached、cache creation、completion 和 total token，并明确区分“缓存未命中”和“提供商不可观测”。
- 新增请求指纹与前缀稳定性观测，对 system prompt、工具 schema、消息历史、动态区段和相邻请求公共前缀进行脱敏度量，用于解释 KV cache 命中变化。
- 建立上下文压缩评测，覆盖主动修剪、溢出恢复、工具结果截断、异步摘要和摘要注入，核算主 Agent 与压缩模型的完整 token/成本，并评估事实保留和缓存重建代价。
- 建立记忆系统评测，覆盖写入、异步 flush、切块、embedding、索引同步、向量/关键词混合检索、时间衰减、召回、引用和对最终任务质量的增益。
- 建立工具、MCP 工具检索与 Skill 评测，度量候选集、注入集、选择正确性、参数正确性、执行成功率、重复调用、权限拒绝、结果截断、Skill 可用性、Prompt 暴露、遵循度和任务贡献。
- 建立端到端任务与子代理评测，使用固定数据集、确定性工具回放和配对实验，对任务成功、轨迹正确性、质量、延迟、token、成本、稳定性和恢复能力进行版本化比较。
- 提供隐私脱敏、采样、异步批量发送、失败隔离、数据保留和配置能力；Langfuse 关闭或不可用时不得改变 Agent 请求内容与执行结果。
- 提供 Langfuse Dataset/Experiment、Score、Dashboard 和导出分析约定，使离线基准、回归门禁与生产观测使用同一套指标语义。
- 增加单元、集成和端到端测试，验证 Trace 父子关系、usage 精度、流式 TTFT、并发工具/子代理传播、数据脱敏和遥测故障降级。

## Capabilities

### New Capabilities

- `observability/langfuse-tracing`: 定义可插拔追踪接口、Langfuse Trace/Observation 层级、usage 规范化、流式计时、请求指纹、隐私与故障隔离。
- `evaluation/kv-cache`: 定义 KV cache 真值、缓存可观测性、Prompt 前缀稳定性、配对实验、指标聚合和报告要求。
- `evaluation/context-compression`: 定义上下文修剪、压缩、摘要、工具结果截断的成本、质量、缓存扰动和恢复评测。
- `evaluation/memory`: 定义记忆写入、索引、检索、召回、排序、引用、时效性、隔离性和任务增益评测。
- `evaluation/tool-skill`: 定义本地/MCP 工具选择与执行、工具检索、权限结果、Skill 加载/暴露/遵循/贡献的评测与轨迹指标。
- `evaluation/task-execution`: 定义端到端任务数据集、确定性回放、子代理树、质量评分、回归比较、统计分析和发布门禁。

### Modified Capabilities

- 无。当前 `openspec/specs/` 中不存在需要修改的既有能力规格。

## Impact

- 主要影响 `agent/protocol/agent.py`、`agent/protocol/agent_stream.py`、`bridge/agent_bridge.py`、`bridge/agent_initializer.py` 和模型 provider/HTTP 流式链路。
- 记忆侧影响 `agent/memory/manager.py`、`summarizer.py`、embedding provider、storage/vector backend 和 conversation run 生命周期。
- 工具与 Skill 侧影响 `agent/tools/base_tool.py`、MCP 工具检索、`agent/skills/manager.py`、Prompt Builder、工具执行事件和子代理 runner。
- 新增 `agent/observability/`、`agent/evaluation/` 或 `benchmarks/` 下的追踪适配、评测运行器、数据集、分析与导出模块。
- 新增 Langfuse Python SDK 可选依赖和非敏感配置；凭据仅通过环境变量或现有安全凭据机制注入。
- 对外业务 API 不做破坏性修改；新增的遥测必须默认关闭、可采样、可脱敏，并采用 fail-open 行为。
