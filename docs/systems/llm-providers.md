# LLM Providers

每个模型 Profile 同时声明 `context_window_tokens`、`context_safety_margin_tokens` 和 `token_estimator`。Runtime 在 Provider 前基于完整 messages、tools、输出预留及协议开销统一预算；KV cache 由 Provider 管理，Runtime 只稳定前缀并记录实际返回的 cache usage。详见 [Context Management](context-management.md)。

Memoli 通过一个无厂商 SDK 类型的异步合同接入 OpenAI Chat Completions、
OpenAI-compatible 服务和 Anthropic Messages。Provider 只完成协议转换、流式组装、
错误分类和有界重试；Session history、system prompt、工具执行与轨迹提交仍由 Runtime
负责，因此主 Agent 和 SubAgent 可以安全复用同一个无状态 Provider/Router。

## 内部合同

`ModelRequest` 使用有序 `ModelMessage` 与内容块表示模型输入：

- `TextBlock`：可见文本。
- `ThinkingBlock`：API 明确返回的 thinking；Anthropic signature 只用于原协议续接。
- `ToolUseBlock`：带稳定 ID、名称和 JSON object 参数的工具调用。
- `ToolResultBlock`：通过 `tool_use_id` 关联原工具调用。

`ModelResponse` 返回最终规范化消息、工具调用、结束原因、实际模型、请求 ID 和
`TokenUsage`。SDK 响应和异常对象不会越过 Adapter 边界。流式调用额外发布
`thinking_delta`、`text_delta`、`tool_call_delta`、`usage` 和 `completed` 事件，
但最终仍只产生一个完整响应，Reasoner 继续按模型声明顺序串行执行工具。

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

首版显式 dialect 为 `default`、`deepseek`、`dashscope` 和 `ollama`，不会根据
base URL 或模型名称猜厂商。

## 错误、重试与 fallback

认证、权限、上下文超长、内容安全、无效请求、响应协议和能力错误均为不可重试；
网络、超时、HTTP 408/429 与 5xx 使用尊重 `Retry-After` 的有界指数退避。单个
Provider 的重试耗尽后，Router 才会按 route 顺序切换真实模型。Echo 不能作为
隐式 fallback。

跨 Provider fallback 会保留文本、工具调用和工具结果，并移除无法在目标协议中
安全重放的私有 thinking/signature。认证等永久错误不会被 fallback 掩盖。

## 轨迹与安全

模型 span 和 Hook 投影包含 route/profile、实际 Provider/model、protocol/dialect、
能力、请求 ID、尝试次数、fallback 原因、结束原因和规范化 usage。Provider 本身
不直接写 SQLite，所有证据继续由 Reasoner 在现有事务边界提交。

API key、Authorization、Cookie、带秘密的 URL、SDK client 和 opaque continuation
不会进入公共 Hook、SQLite 或 JSONL。轨迹中的消息块会移除 signature/opaque；
可见内容仍遵守 `trajectory.capture_content` 与 payload 大小上限。

## 迁移与回滚

旧 `[llm] provider/model/api_key/base_url` 无需立即修改，它会被映射为隐式
`default` endpoint/profile/route。需要多模型 fallback 或分别声明能力时，再迁移到
分层配置。回滚时恢复旧单段配置即可，不涉及数据库 migration；不得通过增加 Echo
fallback 掩盖正式 Provider 故障。

本次未实现 OpenAI Responses API、Anthropic 托管工具、真正的 prompt cache 写入、
视觉输入和成本路由。这些能力虽然出现在能力词表或后续方向中，但必须由独立
OpenSpec change 实现，不能仅靠配置声明视为可用。
