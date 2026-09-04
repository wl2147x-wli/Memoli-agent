# LLM Providers

每个模型 Profile 同时声明 `context_window_tokens`、`context_safety_margin_tokens` 和 `token_estimator`。Runtime 在 Provider 前基于完整 messages、tools、输出预留及协议开销统一预算；KV cache 由 Provider 管理，Runtime 只稳定前缀并记录实际返回的 cache usage。详见 [Context Management](context-management.md)。

Memoli 通过一个无厂商 SDK 类型的异步合同接入 OpenAI Responses、OpenAI Chat Completions、
OpenAI-compatible 服务和 Anthropic Messages。Provider 只完成协议转换、流式组装、
错误分类和有界重试；Session history、system prompt、工具执行与轨迹提交仍由 Runtime
负责，因此主 Agent 和 SubAgent 可以安全复用同一个无状态 Provider/Router。

## 内部合同

`ModelRequest` 使用有序 `ModelMessage` 与内容块表示模型输入：

- `TextBlock`：可见文本。
- `ReasoningSummaryBlock`：Provider 明确标记且配置允许展示的有界推理摘要。
- `ToolUseBlock`：带稳定 ID、名称和 JSON object 参数的工具调用。
- `ToolResultBlock`：通过 `tool_use_id` 关联原工具调用。

Provider 私有推理状态不再属于通用消息块。`OpaqueContinuation` 只在当前
`ProviderExchange` 内存活，带协议、Provider、Profile 和模型标签；Runtime 只能将它
原样返回固定目标，不能读取、持久化、压缩或跨 Provider 转换。旧 `ThinkingBlock`
仅保留迁移读取能力。

`ModelResponse` 返回最终规范化消息、工具调用、结束原因、实际模型、请求 ID 和
`TokenUsage`。SDK 响应和异常对象不会越过 Adapter 边界。流式调用额外发布
`reasoning_summary_delta`、`text_delta`、`tool_call_delta`、`usage` 和 `completed` 事件，
但最终仍只产生一个完整响应，Reasoner 继续按模型声明顺序串行执行工具。

## 推理策略与协议选择

Profile 使用 `reasoning_mode = "off" | "adaptive"`、可选的 `reasoning_effort`，以及
`reasoning_visibility = "hidden" | "summary" | "updates"`。能力声明和启用策略相互
独立；不支持的组合在网络请求前失败。旧配置默认 `off`，不会静默增加推理成本。

`protocol = "openai-responses"` 才会使用 Responses API。首版固定 `store=false`，请求
`reasoning.encrypted_content`，并在工具结果续接时原序重放推理项和函数调用项；不会按
模型名或 URL 自动切换协议，也不使用 `previous_response_id` 保存跨轮状态。

Anthropic 工具续接会在不透明信封中保留当前 assistant 轮次的 thinking、
redacted-thinking、signature 与 tool-use 块，并在下一次同交换请求中原序原样回传。
`hidden` 不发布推理文字；`summary`/`updates` 只投影 Provider 明确提供的摘要或更新，
任何模式都不会把签名或原始思维链发送到表现层。

## 配置

没有 `config.toml` 时显式使用本地 Echo，便于首次启动。只要选择正式 Provider，
空 API key、未展开的环境占位符、未知 Provider/Profile 或无效 route 都会在启动时
失败，不会静默回退到 Echo。

### 单 Provider 兼容配置

```toml
[llm]
provider = "openai-compatible"
model = "deepseek-chat"
api_key = "${MEMOLI_LLM_API_KEY}"
base_url = "https://api.deepseek.com/v1"
dialect = "deepseek"
max_retries = 1
stream = true
```

`api_key` 是正式配置入口，可以直接填写，也可以写成完整占位符
`"${MEMOLI_LLM_API_KEY}"`。`config.toml` 已被 Git 忽略；不要把真实凭证写入
`config.example.toml`、日志、测试 fixture 或提交记录。

### Endpoint、Profile 与 Route

```toml
[llm.providers.primary]
protocol = "anthropic"
api_key = "${ANTHROPIC_API_KEY}"
base_url = "https://api.anthropic.com"
max_retries = 1

[llm.providers.backup]
protocol = "openai"
api_key = "${OPENAI_API_KEY}"
base_url = "https://api.openai.com/v1"
max_retries = 1

[llm.models.main]
provider = "primary"
model = "<anthropic-model-id>"
capabilities = ["text", "tools", "reasoning", "streaming", "prompt-cache"]
max_output_tokens = 8192
reasoning_mode = "adaptive"
reasoning_effort = "high"
reasoning_visibility = "hidden"

[llm.models.fallback]
provider = "backup"
model = "<openai-model-id>"
capabilities = ["text", "tools", "streaming", "structured-output"]
max_output_tokens = 8192

[llm.routes]
agent = "main"
fallback = ["fallback"]
```

Endpoint 保存协议、凭证和传输参数；Profile 保存模型 ID、能力和生成上限；Route
保存主模型与有序 fallback。Runtime 在联网前计算请求所需能力，并取 Profile 声明
与 Adapter 能力的交集。能力不满足时只尝试显式且兼容的 Profile。

显式 dialect 为 `default`、`deepseek`、`dashscope`、`ollama` 和
`qwen-vllm`，不会根据 base URL 或模型名称猜厂商。Qwen3 由 vLLM 承载时应选择
`qwen-vllm`：`reasoning_mode = "off"` 会在每次请求中发送
`chat_template_kwargs.enable_thinking = false`，`adaptive` 则显式发送 `true`，
不依赖 Qwen3 的默认 thinking 行为。

`qwen-vllm` 会丢弃专用 `reasoning_content`，并从普通 `content` 中剥离
`<think>...</think>`。由于标签可能横跨流式 chunk，该方言先缓冲整段 content，
完成分类后才发布最终文本。它不会用“首先”“我需要”等自然语言特征猜测推理；
若服务端既没有结构化字段也没有标签，客户端无法可靠区分两者，应在请求侧硬关闭
thinking，或在 vLLM 启动时启用 Qwen reasoning parser。

## 错误、重试与 fallback

认证、权限、上下文超长、内容安全、无效请求、响应协议和能力错误均为不可重试；
网络、超时、HTTP 408/429 与 5xx 使用尊重 `Retry-After` 的有界指数退避。单个
Provider 的重试耗尽后，Router 才会按 route 顺序切换真实模型。Echo 不能作为
隐式 fallback。

跨 Provider fallback 只允许发生在尚未产生私有续接、部分流输出或工具副作用时，
并且只携带文本、工具调用和工具结果等可移植语义。一旦交换依赖签名、加密推理项或
已经执行工具，续接失败会终止该交换，不会切换 Provider 或自动重复工具。

## 轨迹与安全

模型 span 和 Hook 投影包含 route/profile、实际 Provider/model、protocol/dialect、
能力、请求 ID、尝试次数、fallback 原因、结束原因和规范化 usage。Provider 本身
不直接写 SQLite，所有证据继续由 Reasoner 在现有事务边界提交。

API key、Authorization、Cookie、带秘密的 URL、SDK client 和 opaque continuation
不会进入公共 Hook、SQLite 或 JSONL。轨迹中的消息块会移除 signature、加密内容和响应续接标识；
可见内容仍遵守 `trajectory.capture_content` 与 payload 大小上限。

## 迁移与回滚

旧 `[llm] provider/model/api_key/base_url` 无需立即修改，它会被映射为隐式
`default` endpoint/profile/route。需要多模型 fallback 或分别声明能力时，再迁移到
分层配置。回滚时恢复旧单段配置即可，不涉及数据库 migration；不得通过增加 Echo
fallback 掩盖正式 Provider 故障。

本次仍未实现 Anthropic 托管工具、真正的 prompt cache 写入、视觉输入、成本路由、
`previous_response_id` 服务端续接和未完成交换的崩溃恢复。这些能力必须由独立
OpenSpec change 实现，不能仅靠配置声明视为可用。
