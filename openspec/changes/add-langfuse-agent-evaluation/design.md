## Context

参见 `proposal.md` 的 Why。当前运行链已经存在可复用的关联基础，但各组件尚未共享统一的观测协议：

- `bridge/agent_bridge.py::_begin_run/_end_run` 创建和关闭本地 `runs` 记录，包含 `run_id`、`parent_run_id`、`task_id` 和 `task_source`；这是根 Trace 身份的最佳来源。
- `agent/protocol/agent_stream.py::run_stream` 管理完整 Agent loop，已有 `agent_start/end`、`turn_start/end`、`message_*`、`tool_execution_*` 等 UI 事件，但这些事件缺少模型 usage、稳定父子关系、跨线程传播和评测字段。
- `agent/protocol/agent_stream.py::_call_llm_stream` 在每一轮重建工具 schema、构造 `LLMRequest` 并消费流，是 Generation、请求指纹和 TTFT 的唯一准确接入点。
- `models/openai_compatible_bot.py` 与 `models/openai/openai_http_client.py` 直接发送和解析 OpenAI-compatible HTTP/SSE，不是官方 OpenAI SDK，因此 Langfuse 的 OpenAI drop-in wrapper 不能透明覆盖当前链路。
- 当前部分同步 provider 仅保留 prompt/completion/total，流式 Agent loop 也没有统一捕获末尾 usage；缓存字段可能在 provider 转换或消费阶段丢失。
- `agent/protocol/agent_stream.py::_trim_messages/_smart_compact_to_budget`、工具结果截断和 `agent/memory/summarizer.py` 共同完成上下文变换，其中记忆摘要是后台线程，可能晚于根请求返回。
- `agent/memory/manager.py` 实现 embedding cache、向量/关键词检索、融合和时间衰减；`storage.py`、`vector_backend.py`、embedding provider 和 summarizer 分别承担底层阶段。
- Skill 当前主要通过 `SkillManager.build_skills_prompt` 暴露名称、描述和文件路径，由模型自行读取 `SKILL.md` 后遵循；不存在天然的“执行 Skill”函数，因此必须把 eligible、injected、read、applied、contributed 分层。
- `agent/subagent/runner.py`、委托工具与 scheduler 会跨线程或创建嵌套 run；Python context variable 不会自动跨所有线程传播，不能仅依赖隐式 OpenTelemetry current context。
- `tests/trajectory_eval.py` 已能从 Agent 事件构造测试轨迹，可作为新的确定性评测事件模型的兼容基础。

约束：遥测不得改变模型请求语义，不得成为业务成功的前置条件；默认不得上传用户正文、文件正文、工具结果或凭据；外部 Provider 的服务端 chat template、缓存作用域和驱逐行为可能不可见。

## Goals / Non-Goals

**Goals:**

- 用一个稳定、版本化的内部事件模型覆盖顶层与嵌套 Agent、模型、工具、Skill、记忆、压缩、embedding、任务和后台工作。
- 以手工 Langfuse SDK 适配器实现完整控制，同时保持业务模块只依赖内部接口。
- 精确保存 Provider 报告的 token/cache usage 和流式时间，允许本地真值与云端有限观测并存。
- 建立可重复数据集、确定性工具回放、变体配置、评分器、统计报告和 CI 门禁。
- 明确每一个现有源码接入点、拟新增模块、字段、错误语义和测试方法。

**Non-Goals:**

- 不在本变更中实现或修改具体上下文压缩、记忆排序、工具选择和 Skill 内容策略；本变更只使它们可配置实验、可观测和可比较。
- 不用 Langfuse 推断 Provider 没有报告的真实 KV cache 命中。
- 不把 Langfuse 替换为项目的业务数据库、会话存储、记忆存储或审计日志。
- 不默认上传完整 Prompt、CoT/reasoning、工具参数、文件内容或记忆正文。
- 不承诺跨不同云 Provider、不同硬件或不同推理引擎的延迟结果可以直接横向比较。

## Decisions

### 1. 采用内部可观测接口与 Langfuse 适配器，而不是在业务层直接调用 SDK

新增建议目录：

```text
agent/observability/
  __init__.py
  config.py
  contracts.py
  context.py
  factory.py
  noop.py
  langfuse_tracer.py
  usage.py
  fingerprint.py
  privacy.py
  events.py
  metrics.py
```

职责如下：

| 模块 | 新增代码与职责 |
|---|---|
| `contracts.py` | `Tracer`、`TraceHandle`、`ObservationHandle` Protocol；`ObservationKind`、`TraceStatus`；所有方法必须可安全 no-op |
| `config.py` | `ObservabilityConfig` 数据类、配置解析、合法值校验；绝不读取 config 中的 secret |
| `context.py` | `TraceContext`、`EvaluationContext` 和显式 `capture/attach`；承载 run/trace/parent/experiment/variant/dataset item |
| `factory.py` | 延迟构建进程级 tracer；SDK 缺失或配置错误时返回 `NoopTracer` |
| `noop.py` | 零副作用空实现，保证关闭遥测时业务路径不分叉 |
| `langfuse_tracer.py` | Langfuse SDK 映射、父子 Observation、批量发送、flush/shutdown、异常熔断 |
| `usage.py` | `RawUsage`、`NormalizedUsage`、各 Provider schema 提取与独占 token 计算 |
| `fingerprint.py` | JSON 规范化、顺序敏感/无关哈希、Prompt 区段哈希、LCP 估算 |
| `privacy.py` | secret 字段识别、路径/正文策略、截断、HMAC 指纹、用户自定义 mask |
| `events.py` | 稳定的内部事件名和 payload schema；从现有 Agent UI 事件映射但不复用其展示载荷 |
| `metrics.py` | 单次运行计数器与分项 usage 聚合，避免子 Observation 重复计费 |

核心接口示意：

```python
class Tracer(Protocol):
    def start_trace(self, *, name, trace_id, input=None, metadata=None) -> TraceHandle: ...
    def start_observation(self, *, parent, kind, name, **fields) -> ObservationHandle: ...
    def score(self, *, trace_id, observation_id=None, name, value, **fields) -> None: ...
    def flush(self, timeout_seconds: float) -> FlushResult: ...

class ObservationHandle(Protocol):
    def update(self, **fields) -> None: ...
    def end(self, *, status="success", **fields) -> None: ...
```

所有 handle 都实现幂等 `end()` 和 context manager；析构不承担正确性。替代方案是直接复用 `on_event` 回调上传 Langfuse，但现有事件会截断数据、缺少 usage 和跨线程父节点，而且 UI 展示字段与评测字段演化节奏不同，因此不采用。

### 2. 复用本地 run ID，显式维护 Trace 映射

Trace 根身份优先来自 `AgentBridge._begin_run` 创建的 `run_id`。在本地 `runs.extras` 写入：

```json
{
  "telemetry_schema_version": "1.0",
  "langfuse_trace_id": "...",
  "experiment": "agent-eval-v1",
  "variant": "baseline"
}
```

关联规则：

```text
conversation run_id 1:1 Langfuse Trace
parent_run_id        -> parent trace/run link
一次 LLM call        -> Generation
一次工具执行          -> Tool Span
一次 memory search   -> Retriever Span
一次 embedding API   -> Embedding Observation
一次 LLM 摘要         -> Generation
一次上下文变换         -> Span
一次 Skill 状态跃迁    -> Event/Span
```

接入 `bridge/agent_bridge.py`：

- `_begin_run` 在本地 run 成功后调用 `tracer.start_trace`，将 trace handle 放入显式 `TraceContext`，并把 trace ID 回写 `update_run_extras`。
- `_end_run` 在 `finally` 中结束 Trace、聚合 root usage/scores，再恢复本地 run context；遥测关闭失败不得阻止 `clear_agent_run_id`。
- 直接调用 `Agent.run_stream` 且没有 bridge run 时，由 `AgentStreamExecutor` 创建 fallback trace；若已有 context，则不得重复创建根 Trace。

对跨线程 scheduler、并行工具、memory flush、subagent 使用 `TraceContext.capture()` 后作为显式参数传入工作函数；不假定 contextvars 自动传播。替代方案是为每个 Agent 实例保存当前 handle，但同一 Agent 可处理并发会话，会产生串线，因此不采用。

### 3. Trace/Observation 数据模型

根 Trace 最小字段：

| 字段 | 含义 |
|---|---|
| `trace_id/run_id` | 一次可寻址 Agent 运行 |
| `parent_run_id` | 子代理/委托父运行 |
| `session_id_hash`、`user_id_hash` | HMAC 后的关联键 |
| `agent_id`、`agent_profile_version` | Agent 身份与配置版本 |
| `task_id`、`task_source` | scheduler/board/benchmark 等外部任务 |
| `experiment`、`variant`、`dataset_item_id`、`repeat` | 评测维度 |
| `code_revision`、`dirty_tree_hash` | 代码可复现信息 |
| `model/provider/endpoint_hash` | 模型维度，不含凭据 |
| `status/error_category/cancelled` | 终态 |
| `telemetry_schema_version` | 分析兼容版本 |

Generation 最小字段：

```text
agent_turn, call_index, call_purpose(main|retry|summary|judge)
request_start, first_sse, first_model_event, completion_start, end
ttft_ms, first_model_event_ms, total_latency_ms
system_hash, tools_ordered_hash, tools_canonical_hash, messages_hash, request_hash
system_chars/tokens_est, tools_chars/tokens_est, history_chars/tokens_est
message_count, tool_schema_count, stop_reason, retry_index, fallback_model
usage_details, raw_usage_shape, cache_observable
```

根 Trace 的 usage 由 `RunMetricsAccumulator` 汇总每个唯一 Observation ID，分为 `main_llm`、`compression_llm`、`judge_llm`、`embedding`、`subagent`；父 Agent 汇总子代理时只引用子 trace 总量，不再把其 Generation 加第二次。

### 4. 模型调用埋点与流式 usage

主要接入 `agent/protocol/agent_stream.py::_call_llm_stream`：

1. 完成 MCP 同步与工具选择后，构造实际 `tools_schema`。
2. 在创建 `LLMRequest` 前调用 `build_request_fingerprint(system, tools, messages, model_parameters)`。
3. 创建 Generation，保存 monotonic 与 UTC 起始时间。
4. `self.model.call_stream(request)` 返回后记录 stream-object-ready，不把它当首字节。
5. 每个 chunk 首先交给 `UsageCollector.observe(chunk)`，即使 `choices` 为空。
6. 第一个有效 tool delta 记录 `first_model_event`；第一个非空 reasoning/content delta记录 `completion_start_time`。
7. 正常、空响应重试、Provider 错误、上下文溢出、取消与 fallback 均在 `finally` 结束本次 Generation。
8. 仅最终、完整 usage 进入聚合；增量 usage 使用 merge 规则，禁止求和重复累计字段。

`models/openai_compatible_bot.py::call_with_tools` 增加受能力开关控制的：

```python
request_params["stream_options"] = {"include_usage": True}
```

配置值为 `auto|true|false`。`auto` 仅在 Provider 明确返回 unsupported-parameter 且请求尚未开始生成时降级一次，并缓存 `(provider, endpoint, model)` 能力；网络错误、超时和流中断不得移除参数自动重试，以免重复消费和重复副作用。

`models/openai/openai_http_client.py::_stream_chat` 保持 raw chunk 原样，但增加可选的传输级回调：request-sent、headers-received、first-SSE、stream-ended。回调只接受时间与状态，不复制正文。Zhipu、Claude、Gemini、DashScope 等原生适配器在各自响应转换点保留其 usage 细节，最终统一由 `usage.py` 处理。

### 5. usage 规范化与成本语义

`NormalizedUsage`：

```python
@dataclass(frozen=True)
class NormalizedUsage:
    input_inclusive: int | None
    input_uncached: int | None
    input_cache_read: int | None
    input_cache_creation: int | None
    output: int | None
    total: int | None
    cache_observable: bool
    source_schema: str
```

读取优先级与语义：

| 原始字段 | 规范化字段 |
|---|---|
| `prompt_tokens_details.cached_tokens` | `input_cache_read` |
| `input_tokens_details.cached_tokens` | `input_cache_read` |
| `input_token_details.cache_read` | `input_cache_read` |
| `cache_read_input_tokens` | `input_cache_read` |
| `cache_creation_input_tokens` / `input_token_details.cache_creation` | `input_cache_creation` |
| `prompt_tokens` / `input_tokens` | `input_inclusive`，但必须按 Provider schema 判断 inclusive 语义 |
| `completion_tokens` / `output_tokens` | `output` |

在 OpenAI-compatible inclusive schema 中：

```text
input_uncached = max(input_inclusive - cache_read - cache_creation, 0)
```

Langfuse flat `usage_details` 使用互斥类别：

```json
{
  "input": 86,
  "input_cached_tokens": 17817,
  "input_cache_creation": 0,
  "output": 188,
  "total": 18091
}
```

未知缓存为 null/缺键；明确未命中为0。原始字段只以字段名列表、schema 名和脱敏 JSON 摘要放入 metadata。项目在 Langfuse Models 中为自定义模型配置与这些 usage key 完全一致的单价；若价格未知则只报告 token，不推造成本。

### 6. Prompt 构建与 KV cache 解释数据

`agent/protocol/agent.py::get_full_system_prompt` 增加 `prompt-build` Span，并让 `PromptBuilder` 在不改变最终字符串的前提下可返回可选的 `PromptBuildReport`：

```python
PromptBuildReport(
  final_text,
  sections=[
    PromptSection(name="tools", start_char=..., end_char=..., hash=...),
    PromptSection(name="skills", ...),
    PromptSection(name="memory", ...),
    PromptSection(name="knowledge", ...),
    PromptSection(name="runtime", dynamic=True, ...),
  ],
)
```

默认调用仍返回字符串，避免破坏现有 API；观测路径显式请求 report。这样可以把 system hash 变化定位到 runtime time、Skill 清单、记忆或 workspace 文件，而不用上传内容。

`fingerprint.py` 输出：

- system 完整与分区哈希；
- tools 顺序敏感和按名称规范排序哈希；
- messages 各消息与整体哈希；
- 相邻调用首个变化的 component/message index；
- 匹配 tokenizer/chat template 可用时的精确 LCP token；否则输出 `estimated=true` 的客户端 LCP。

最近一次请求摘要按 `(provider, model, session_id, agent_id)` 保存在有界 LRU，仅存哈希/token ID 或区段边界，不保存正文。跨进程/跨实例的理论 LCP 不尝试本地推断。

### 7. 上下文压缩埋点

在以下现有位置增加统一 `ContextTransformRecorder`：

| 位置 | Observation/事件 |
|---|---|
| `run_stream` 调用 `_trim_messages` 前后 | `context.prepare`，记录整个预处理阶段 |
| `_truncate_historical_tool_results` | `context.tool-result-truncate` |
| 当前轮 `MAX_CURRENT_TURN_RESULT_CHARS` | `context.current-tool-result-truncate` |
| `_trim_messages` 轮次限制 | `context.trim.turn-limit` |
| `_trim_messages` token 少轮纯文本化 | `context.compact.text-only` |
| `_trim_messages` token 多轮半区删除 | `context.trim.token-limit` |
| `_smart_compact_to_budget` | `context.compact.overflow-recovery`，每次 guard 迭代作 event |
| `_build_context_summary_callback` | `context.summary-injected`，关联原摘要 Generation |
| 清空 in-memory context | `context.reset`，高严重度 |

每个变换统一记录：reason/strategy、before/after message/turn/token/char、removed message IDs、工具对完整性、first-difference index、summary job ID、是否同步完成、系统与消息指纹变化。

`MemoryFlushManager.flush_from_messages` 创建后台 job ID，并在派发前捕获 trace context；`_flush_worker` 创建 `memory.flush` Span，其 `_call_llm_for_summary` 是独立 `context-summary` Generation。callback 注入时使用 job ID 与被修改的目标 message ID 关联。根 run 可以先结束，但后台 Observation 必须带原 trace ID；本地 run extras 标记 `background_pending` 并在完成后更新最终成本。

### 8. 记忆与 embedding 埋点

在 `agent/memory/manager.py`：

- `search` 创建 `memory.search` Retriever Span，记录 query HMAC、scope、max_results、min_score、dirty/sync、embedding cache hit、vector/keyword 候选、融合、过滤和 final top-k。
- `_merge_results` 在调试 metadata 中记录每个结果的匿名 chunk ID、vector_score、keyword_score、temporal_decay、combined_score 和 rank；生产采样可只保留 top-k。
- `add_memory` 创建 `memory.write` Span，记录 scope、内容长度、文件/chunk 指纹与状态。
- `sync` 创建 `memory.sync` Span，子事件覆盖扫描、changed/deleted files、chunk、embedding、upsert、delete、失败与 dirty 状态。
- `flush_memory` 只记录 dispatch；实际工作由后台 `memory.flush` 完成，避免把“已派发”误判为“已写入”。

在 `agent/memory/embedding/provider.py` 的公共 `embed/embed_query/embed_batch` 外增加装饰层 `ObservedEmbeddingProvider`，不侵入每个厂商实现。每次逻辑调用创建 Embedding Observation，记录 provider/model/dimensions、query/document、item count、批数、输入字符/估算 token、cache hit、耗时、返回数量/维度和错误。API key、URL query 和正文不上传。

在 `storage.py` 与 `vector_backend.py` 只记录数据库阶段的计数和延迟，不为每个 chunk 创建远程 Span，避免遥测风暴；详细 chunk 排名作为 `memory.search` 的有界 metadata。

评测关联状态分为：

```text
generated -> persisted -> indexed -> retrieved -> injected -> cited/used -> contributed
```

`memory_search`/`memory_get` 工具 Span 负责记录 injected；答案引用由确定性引用解析器或 evaluator 判断，不能由检索器自行宣布 contributed。

### 9. 工具与 MCP 埋点

`agent/protocol/agent_stream.py::_execute_tool` 已覆盖正常、权限拒绝、异常和自行发卡工具，作为 Tool Span 的统一入口：

- 在所有早返回之前创建 handle，确保 missing args、tool not found、permission denial、loop protection 都有终态。
- `tool_call_id` 作为 Observation 关联键，参数先经 `privacy.py` 处理。
- 记录 schema hash、argument hash、argument validation、permission mode、status、error category、execution time、result original/model-visible size、truncation 和 artifact。
- `_run_parallel_calls` 捕获父 context，给同批调用写 `parallel_group_id`；Span 时间使用真实并行区间。
- 重复调用由 `(tool_name, argument_hash)` 关联为 retry/loop group。

`agent/tools/mcp/tool_retrieval.py::select_mcp_tools_with_metadata` 返回值已有 ranked/fallback 信息；在 `AgentStreamExecutor._select_tools_for_injection` 创建 `tool.retrieval` Span，记录候选数、匿名排名与分数、top-k、新增/累计工具、embedding 状态和 fallback reason。工具 schema 最终注入集在 LLM Generation 中再次记录，以验证选择结果确实发送。

### 10. Skill 的可观测状态机

Skill 没有单一执行函数，设计为以下状态机：

```text
discovered
  -> enabled/disabled
  -> eligible/unavailable
  -> injected
  -> selected
  -> definition_read
  -> applied
  -> contributed
```

接入点：

- `SkillLoader.load_all_skills`：发现来源、读取诊断、同名覆盖、文件指纹。
- `SkillManager.refresh_skills`：刷新版本和数量。
- `filter_skills/filter_unavailable_skills`：selection、enabled、requirements、knowledge 开关和 missing requirements。
- `build_skills_prompt/build_skill_snapshot`：injected Skill 名称、顺序、Prompt 大小和整体 hash。
- `_execute_tool`：当 read 工具的规范化路径命中 Skill registry 中的 `file_path` 时标记 `definition_read`；其它方式不得自动推定已读。
- 评测 runner：由任务 manifest 声明 Skill trigger、must/must-not steps、期望工件；轨迹 evaluator 计算 selected/applied/adherence/contributed。

`selected` 默认由首次请求 Skill 定义的明确行为（通常是读取定义）或评测注入的显式 selection marker 触发。生产观测无法可靠判断 applied/contributed 时保持 unknown，不用模型自述替代证据。

### 11. 任务、scheduler、子代理与后台工作

- `bridge/agent_bridge._begin_run/_end_run`：普通会话和外部任务根 Trace。
- scheduler 执行入口：写 `task_source=scheduler`、task ID、计划/实际开始、misfire/claim/release 状态。
- `agent/subagent/runner._open_run/_run_one/_close_run`：子 Trace 复用 child run ID，记录 template、深度、brief hash、继承工具/Skill 配置、summary、usage 和错误。
- `agent_delegate`：委托请求 Span 连接 source trace 与 target trace，防止跨线程上下文丢失。
- evolution/deep dream/daily flush：作为 `task_source=background` 的独立 Trace；若由用户 run 触发则增加 causal link，不错误嵌套成长时间开放的父 Span。
- `bridge/agent_event_handler`：可选 `channel.delivery` Span，度量最终响应从 Agent 完成到渠道发送完成；它不计入模型 TTFT。

### 12. 配置设计

`config.py` 默认配置增加：

```json
{
  "observability": {
    "provider": "none",
    "enabled": false,
    "environment": "development",
    "sample_rate": 0.1,
    "capture_content": false,
    "capture_reasoning": false,
    "capture_tool_arguments": false,
    "capture_tool_results": false,
    "max_field_chars": 2000,
    "include_stream_usage": "auto",
    "flush_timeout_seconds": 5,
    "background_completion_grace_seconds": 30,
    "hash_key_env": "MEMOLI_TELEMETRY_HASH_KEY"
  },
  "evaluation": {
    "enabled": false,
    "experiment": "",
    "variant": "",
    "dataset_version": "",
    "repeat": 0,
    "force_sample": true,
    "save_local_receipts": true
  }
}
```

凭据只读取：`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`、`LANGFUSE_BASE_URL`。配置中出现 secret 字段时忽略并告警。采样对 `run_id` 做确定性哈希，确保整个 Trace 的所有子项一致采样。评测上下文覆盖 `sample_rate=1`，但不自动开启正文采集。

依赖放在 `requirements-observability.txt` 或项目已有可选依赖机制，锁定经过契约测试的 Langfuse Python SDK 主版本；业务默认安装不强制携带 SDK。

### 13. 评测框架代码

新增：

```text
benchmarks/agent_evaluation/
  README.md
  schemas.py
  dataset_loader.py
  workspace_fixture.py
  clock_fixture.py
  replay_tools.py
  runner.py
  variants.py
  evaluators/
    deterministic.py
    trajectory.py
    artifacts.py
    memory.py
    tool_skill.py
    optional_judge.py
  reporting/
    langfuse_export.py
    aggregate.py
    statistics.py
    gates.py
  datasets/
    smoke.jsonl
    full.jsonl
  configs/
    baseline.yaml
    stable-system.yaml
    stable-tools.yaml
    compact-watermark.yaml
```

任务 schema：

```json
{
  "id": "memory-cross-session-001",
  "category": ["memory", "long-context"],
  "input": {"conversation": [], "final_request": "..."},
  "workspace_fixture": "fixtures/ws-001",
  "tool_replay": "fixtures/tools-001.json",
  "expected": {
    "facts": [],
    "required_tools": [],
    "forbidden_tools": [],
    "tool_argument_assertions": [],
    "required_skills": [],
    "artifacts": []
  },
  "limits": {"max_steps": 30, "timeout_seconds": 300},
  "metadata": {"difficulty": "medium"}
}
```

Runner 为每个 dataset item 与 variant 创建隔离工作区和会话，冻结时钟，安装 replay tool adapter，设置 EvaluationContext，运行规定重复次数，并保存本地 JSONL receipt。每条 receipt 包含任务输入 hash、代码/配置/依赖/硬件、Trace ID、原始分项指标、评分器版本与错误，不含 secret。

实验层次：

1. `smoke`：脚本模型与假工具，不调用外部服务，验证轨迹和数据正确性。
2. `component`：真实 embedding/本地模型，隔离测试缓存、记忆、压缩、工具检索。
3. `agent-e2e`：完整 Agent 和固定工具回放，比较策略。
4. `provider-e2e`：真实云 Provider，记录缓存可观测限制。
5. `production-monitor`：低采样趋势和失败样本收集，不与离线基准直接混算。

### 14. 指标和评分设计

统一派生指标：

```text
cache_token_ratio = sum(cache_read) / sum(input_inclusive)
cache_call_hit_rate = calls(cache_read > 0) / observable_calls
cache_observability_coverage = observable_calls / all_calls
token_saving = 1 - candidate_total_tokens / baseline_total_tokens
cost_per_success = all_task_cost / successful_tasks
tool_selection_precision = correct_selected / all_selected
required_tool_recall = required_called / all_required
memory_recall_at_k, precision_at_k, MRR, nDCG
skill_trigger_precision/recall, adherence_rate, contribution_delta
compression_fact_recall, compression_error_rate, cache_recovery_turns
```

缓存比例使用 token 总和之比，不平均单次比例。延迟报告 paired delta、median、p95 和 bootstrap 95% CI；成功率使用配对二元比较与置信区间。正式结论必须带样本量、缺失量和可观测覆盖率。

Langfuse Score 命名采用版本化前缀：

```text
eval.task_success.v1
eval.fact_recall.v1
eval.trajectory_correct.v1
eval.tool_selection.v1
eval.tool_arguments.v1
eval.skill_adherence.v1
eval.memory_recall_at_5.v1
eval.kv_cache_ratio.v1
eval.context_compression_gain.v1
```

确定性评分优先。LLM judge 是独立 Generation，记录 judge model/prompt version/usage，失败为 unknown；不能覆盖确定性失败。

### 15. Langfuse 数据组织与报表

Langfuse Dataset 名称建议 `memoli-agent/full-evaluation-v1`，Experiment Run 名称包含代码版本和变体。tag/dimension：environment、experiment、variant、dataset_version、category、provider、model、agent_id、telemetry_schema_version。

Dashboard 最少包括：

- 任务成功率、事实/轨迹/工件分数和失败分类；
- input uncached/cache read/cache creation/output token 堆叠与成本；
- cache ratio、可观测覆盖率、TTFT p50/p95 和 Prompt 变化来源；
- 压缩前后 token、摘要成本、缓存恢复轮数和事实保留；
- 记忆 Recall@K/MRR/nDCG、检索延迟、fallback 和任务增益；
- 工具选择/参数/执行/权限/重复/截断；
- Skill eligible/injected/read/applied/adherence/contribution 漏斗；
- 子代理数量、深度、成本、成功率和父任务贡献。

UI 用于探索；正式门禁通过 Observations/Metrics API 拉取数据并与本地 receipts 交叉校验。摄取延迟采用有界轮询；超时输出 `inconclusive` 或 provisional，不输出虚假通过。

### 16. 隐私与安全策略

默认策略：

- 用户/session 使用密钥 HMAC，不使用普通 SHA 对低熵标识；
- API key、Authorization、cookie、password、token、secret 字段固定掩码；
- 文件路径仅保留 workspace 相对类别与 HMAC；路径越界只记录类别；
- Prompt、消息、memory、Skill 正文和工具结果默认只记录 chars/token estimate/hash；
- reasoning 永不默认上传；明确开启时仍执行 mask 和大小上限；
- 错误栈清除 URL query、header、绝对用户路径和正文片段；
- 本地 receipt 使用同一策略，不因“本地”而绕过。

`capture_content=true` 是显式高风险开关，并在启动日志和每条 Trace 标记。生产环境可用 allowlist 限定字段，不能仅依赖 denylist。

### 17. 性能、可靠性和熔断

所有遥测 SDK 调用包裹在 adapter 内。Langfuse 连续失败达到阈值后进入短时 open-circuit，期间使用 Noop handle 并计本地 dropped events；恢复采用半开探测。业务线程只进行小对象创建、计时、哈希和 SDK enqueue；大正文规范化、token LCP 和报告统计只在评测模式或后台执行。

限制：完整请求哈希仍需遍历载荷。生产模式对超大工具结果在业务已有字符串/长度上计算，不再次复制；HMAC 流式更新。配置最大 metadata 大小和 top-k 明细数，防止单 Trace 过大。

### 18. 测试策略

新增测试建议：

```text
tests/test_observability_noop.py
tests/test_observability_context.py
tests/test_observability_privacy.py
tests/test_usage_normalizer.py
tests/test_stream_usage_and_ttft.py
tests/test_langfuse_tracer_contract.py
tests/test_agent_trace_hierarchy.py
tests/test_context_transform_events.py
tests/test_memory_observability.py
tests/test_embedding_observability.py
tests/test_tool_trace_parallel.py
tests/test_mcp_retrieval_trace.py
tests/test_skill_evaluation_state.py
tests/test_subagent_trace_propagation.py
tests/test_evaluation_runner.py
tests/test_evaluation_statistics.py
tests/test_evaluation_gates.py
```

使用内存 FakeTracer 做绝大多数测试，不依赖 Langfuse 服务。Langfuse contract 测试 mock SDK，验证字段名、时间、usage、幂等 end 和 flush。SSE fixture 覆盖空 choices usage、增量 usage、流中断、取消、工具-only、reasoning-first。端到端测试使用本地临时工作区和 scripted model；可选 live test 才连接 Langfuse/self-hosted 模型。

必须做快照对照：遥测关闭前后实际模型 request JSON 完全一致；遥测故障前后 Agent 结果一致；并发 run 不交叉；secret canary 不出现在 SDK enqueue payload。

## Risks / Trade-offs

- [Provider 不返回缓存字段] → 标记 `cache_observable=false`，使用本地引擎真值实验；TTFT/LCP 只作辅助证据。
- [某些 Langfuse 自动集成丢失缓存明细] → 不使用 LangChain/OpenAI wrapper 作为唯一来源，直接规范化 raw Provider usage 并用 contract test 校验持久结果。
- [开启 `stream_options.include_usage` 被 Provider 拒绝] → 使用按 endpoint/model 缓存的能力协商和显式配置，只有明确参数错误才安全降级。
- [后台摘要在根 Trace 结束后完成] → 使用显式 trace context 和 job ID；允许 late child/linked trace，并在本地 run extras 标记 pending/finalized。
- [遥测代码侵入热点路径] → 统一 adapter、Noop、采样、有界 metadata 和性能回归测试；不在业务模块直接引用 Langfuse 类型。
- [Skill 是否 applied/contributed 难以自动判断] → 分层状态，生产中允许 unknown；正式评测使用轨迹断言、工件检查和消融，不使用模型自述。
- [上传内容泄密] → 默认 hashes-only、HMAC、allowlist、canary 测试和失败即丢弃策略；密钥只走环境变量。
- [不同变体互相预热缓存] → 本地重启/隔离缓存，云端采用随机区组并披露污染；保存执行顺序和时间间隔。
- [token 估算与 Provider 计费不一致] → Provider usage 为计费主数据，tokenizer 只用于 LCP/容量解释，并标记 exact/estimated。
- [Langfuse 摄取延迟导致 CI 误判] → 保存本地 receipts、有界轮询，数据不足返回 inconclusive。
- [观测事件数量和成本增加] → 生产采样、聚合底层 chunk 操作、限制排名明细；评测环境才开启100%和详细模式。

## Migration Plan

1. 先加入内部 contracts、Noop、配置和 FakeTracer；默认 `provider=none`，运行全量现有测试并比较请求快照。
2. 加入 usage normalizer、SSE usage 捕获和 TTFT，但先只写本地 FakeTracer/receipt；验证所有 Provider 适配器兼容。
3. 接入 Agent run、LLM、工具和子代理层级；在测试环境启用 Langfuse，校验远端 Observation 与本地 receipt 一致。
4. 接入上下文压缩、记忆、embedding、MCP 和 Skill 状态；启用详细组件数据集。
5. 上线 benchmark runner、评分器、Langfuse Dataset/Experiment 与报告/门禁；先运行 smoke 和 component，再运行完整 E2E。
6. 在开发环境以低流量 hashes-only 方式启用，监测性能、丢弃事件、载荷大小和隐私 canary。
7. 验证后逐步扩大采样；生产默认仍关闭正文和 reasoning。

回滚只需关闭 `observability.enabled` 或设为 `provider=none`；Noop 路径保留，业务代码无需回滚。若 SDK 导致启动问题，factory 必须捕获导入异常。新增本地 receipt/字段为附加数据，不迁移或删除既有 conversation 数据。

## Open Questions

- 自托管 Langfuse 的最终地址、保留周期和组织访问控制由部署环境决定，不影响代码接口与任务拆分。
- 各云 Provider 的缓存 token 字段和价格模型需要在接入时通过 live capability probe 建档；未知 Provider 按不可观测处理。
- 正式发布门禁的具体数值阈值需要先跑 baseline 获得分布后写入评测配置，不改变本设计的指标和门禁机制。
