## Context

Memoli 的 `Reasoner` 已经拥有串行 Agent Loop、工具执行、fallback 标记、Hook 和 SQLite trajectory，Provider 因此只需要承担模型协议边界。当前 `OpenAICompatibleProvider` 使用 `urllib` 在线程中执行阻塞请求，输入为 OpenAI 风格 `ChatMessage`，只能解析一次性 Chat Completions；`bootstrap` 在未知 Provider、缺少密钥或调用失败时使用 Echo，使配置错误表现为正常回复。与此同时，原生 Anthropic Messages 使用有序 content blocks、`tool_use`/`tool_result` 和可能需要原样回传的 thinking/signature，不能仅靠替换 URL 正确支持。

本 change 同时交付 OpenAI 与 Anthropic，而不是先抽象后只落地一个 Adapter。实现需要保持现有 Reasoner、ToolRegistry、SubAgent、Hook 和 trajectory 边界可替换，并让旧 `[llm]` 配置有明确迁移路径。

## Goals / Non-Goals

**Goals:**

- 以同一无状态异步合同调用 OpenAI Chat Completions/OpenAI-compatible 服务和 Anthropic Messages。
- 正确往返文本、思考、工具调用、工具结果、结束原因、usage、cache usage 和 Provider 必需的续接信息。
- 同时支持非流式与流式调用，流式只改变用户可见增量，不改变最终规范化响应和串行工具语义。
- 通过显式 Profile、能力检查、分类错误、有界重试和真实模型 fallback 消除静默假成功。
- 让现有轨迹足以比较 Provider、调试失败并派生评测/后训练数据，同时不保存凭证或隐藏推理。
- 使用脚本化 Provider 与本地模拟服务完成无真实密钥的协议一致性回归。

**Non-Goals:**

- 首版不接入 OpenAI Responses API、Anthropic 托管工具、Batch API 或厂商文件 API。
- 不做按价格或主观质量自动路由、在线学习、熔断集群、并发工具执行或多模型投票。
- 不让 Provider 管理 Session、裁剪历史、构造记忆/Skill 上下文、执行工具或直接写 SQLite。
- 不承诺兼容任意声称 OpenAI-compatible 但不遵守工具调用协议的私有网关；差异必须由显式 dialect 配置和测试覆盖。

## Decisions

### 1. 使用规范化 content-block 合同，而不是把 Anthropic 压成纯字符串

新增模型层数据合同：`ModelRequest`、`ModelMessage`、`TextBlock`、`ThinkingBlock`、`ToolUseBlock`、`ToolResultBlock`、`ModelResponse`、`TokenUsage`、`ModelCapabilities` 和流式 `ModelEvent`。Runtime 仍可从现有 `ChatMessage` 构造请求，但工具轮次必须追加 Provider 返回的规范化 Assistant message，而不是重新拼出丢失顺序和续接信息的消息。

OpenAI Adapter 将 blocks 转成 `messages`、`tool_calls` 和 `tool` 消息；Anthropic Adapter 将 leading system 内容移到 `system`，将 Assistant 工具调用转换为 `tool_use`，将关联结果组成 User `tool_result` blocks，并保留 API 明确返回且后续协议要求回传的 thinking/signature。用户最终回复仍由 text blocks 拼接，因此 Channel 公共协议不变。

备选方案是继续只使用字符串 `content + tool_calls`，但它会丢失 Anthropic block 顺序和签名，无法可靠完成带 thinking 的多轮工具调用，因此不采用。

### 2. 两个原生 Adapter 共享窄 Provider Protocol

Provider Protocol 采用单个异步 `complete(request, on_event=None)` 入口，并返回同一种 `ModelResponse`。实现包含：

- `OpenAIProvider`：官方 OpenAI Chat Completions，同时允许通过显式 `base_url`/dialect 连接 DeepSeek、DashScope、Ollama、vLLM 等 OpenAI-compatible 服务；
- `AnthropicProvider`：原生 Anthropic Messages，不通过 OpenAI 中转格式模拟；
- `EchoProvider` 与 `ScriptedProvider`：只用于显式本地演示和确定性测试。

迁移期保留旧 `chat(messages, tools)` 兼容包装，Reasoner 完成切换后再在同一 change 内移除内部调用。Provider 实例不持有 history 或动态 system prompt，同一实例可安全供主 Agent 与多个 SubAgent 共享。

备选方案是复制 GenericAgent 的 Session 层，但其 Session 同时持有 history、system 和传输状态，会与 Memoli 已有 Runtime 职责重叠，因此不采用。

### 3. 使用官方异步 SDK，并把 SDK 类型封闭在 Adapter 内

引入有上限版本范围的 `openai` 与 `anthropic` Python SDK，分别使用其异步客户端、超时、取消和流式解析能力。SDK 对象不得越过 Adapter 边界；测试和 Runtime 只依赖 Memoli 数据合同。这样比自行维护两套 HTTP/SSE 解析器更短、更容易覆盖协议变化，同时避免业务代码绑定 SDK 响应类。

依赖安装和锁定在 `conda memoli` 环境中使用用户指定的清华 PyPI 源完成；CI 仍以项目声明的版本范围为准。若 SDK 引入不可接受的依赖或协议缺陷，可以在保持 Provider Protocol 不变的情况下替换为共享异步 HTTP Transport。

### 4. Provider endpoint、模型 Profile 与 Runtime route 分离

配置分为三层：

```toml
[llm.providers.openai]
protocol = "openai"
api_key = "sk-..."

[llm.providers.anthropic]
protocol = "anthropic"
api_key = "sk-ant-..."

[llm.models.main]
provider = "anthropic"
model = "<model-id>"
capabilities = ["tools", "reasoning", "streaming"]

[llm.models.backup]
provider = "openai"
model = "<model-id>"
capabilities = ["tools", "streaming"]

[llm.routes]
agent = "main"
fallback = ["backup"]
```

Endpoint 保存协议、base URL、dialect、`api_key` 和传输参数；Profile 保存模型 ID、能力、输出限制和受控生成参数；route 保存主 Profile 与有序 fallback。`api_key` 的正式入口始终位于 `config.toml`，既可直接保存凭证，也可选择写成 `${ENV_VAR}` 由现有配置解析规则展开。首版主 Agent 与 SubAgent 默认共享 `agent` route，未来可新增 route 而不改 Provider 合同。

旧 `[llm] provider/model/api_key/base_url` 映射为隐式 `default` endpoint/profile，其 `api_key` 与新 endpoint 配置具有相同语义，不弃用配置文件密钥。配置文件缺失时内置默认值显式选择 Echo，保证“默认可启动”不等价于“正式 Provider 配错后静默 Echo”。

### 5. 能力在发出网络请求前校验

首版能力集合为 `text`、`tools`、`reasoning`、`streaming`、`structured-output`、`vision` 和 `prompt-cache`。Profile 声明能力，Adapter 声明协议能表达的能力，实际可用能力取两者交集。请求包含工具、图片、reasoning 或 streaming 时，Router 必须在调用前校验；不满足时抛出 `UnsupportedCapabilityError`，只允许切换到能力兼容的显式 fallback。

首版不维护随厂商每日变化的全局模型知识库，也不根据模型名猜能力。配置模板提供已验证示例，用户自定义模型需明确声明。

### 6. 重试与 fallback 是两个不同层级

Adapter 内只对网络错误、请求超时、HTTP 408/429 和 5xx 做有上限的指数退避并加入 jitter，遵守可用的 `Retry-After`；认证、权限、无效请求、上下文超长、内容安全和响应协议错误不得盲目重试。错误规范化为认证、限流、超时、网络、上下文长度、内容安全、无效请求、响应协议和能力错误，并携带可脱敏的 Provider、模型、状态码和 retryable 标记。

Router 在同一 Provider 重试耗尽后才按配置顺序尝试真实 fallback。切换前重新做能力校验，并将 Provider 私有 thinking/signature 从可移植历史中剥离，仅保留文本、工具调用和结果。没有兼容 fallback 时，Reasoner 以 `failed` 结束。Echo 永远不作为隐式 fallback。

### 7. Streaming 使用事件回调，但最终结果保持唯一

`on_event` 接收 `thinking_delta`、`text_delta`、`tool_call_delta`、`usage` 与 `completed`。Adapter 在内部累计增量并最终返回与非流式等价的 `ModelResponse`；一旦出现第一个工具调用，不向最终用户提前承诺中间文本。调用协程被取消时必须关闭 SDK stream，不继续重试或切换 Provider。

Reasoner 仍按模型声明顺序串行执行完整工具调用。Channel 是否展示增量由现有生命周期决定，不支持 streaming 的 Channel 可以忽略事件并只发送最终回复。

### 8. 观测使用现有 Hook/trajectory，不在 Provider 内另建日志

每次逻辑模型调用记录 route/profile、请求与实际 Provider/model、protocol/dialect、能力快照、开始/结束时间、延迟、尝试次数、fallback 原因、finish reason、规范化 usage、请求 ID 和分类错误。模型可见消息、工具 schema 与 API 明确返回的可见 thinking 按现有 capture/redaction 策略记录。

API key、Authorization、Cookie、带秘密的 URL、SDK client、完整异常对象、未由 API 返回的隐藏推理和 Provider 私有 opaque continuation 字段不得进入普通日志、Hook 公共上下文、SQLite 或 JSONL 导出。Provider 只返回数据，由 Reasoner 在现有提交边界记录，以保持“先记录意图再执行”的轨迹保证。

### 9. 协议一致性测试作为 Adapter 的准入门槛

建立共享 conformance suite，任何 Provider 都必须通过：直接文本、单/多工具调用、工具结果续接、空内容、结束原因、usage、超时取消、错误分类和秘密扫描。OpenAI 与 Anthropic 分别使用本地模拟 HTTP/SSE fixture 验证真实 wire shape；ScriptedProvider 继续承担 Agent Loop 的确定性测试。真实网络 smoke test 使用 pytest marker 隔离，默认测试不得需要密钥或联网。

## Risks / Trade-offs

- [统一 block 合同扩大了当前 `ChatMessage` 改动面] → 提供双向兼容转换，先改 Provider/Reasoner 内部，再保持 Channel 与 Session 保存格式稳定。
- [Anthropic thinking/signature 在错误转换后导致下一轮 400] → 保留有序 blocks，增加带 thinking + tool_use + tool_result 的 wire-level 回归。
- [两个官方 SDK 增加依赖和升级风险] → 限定版本范围、隔离 SDK 类型、用 conformance suite 锁定行为。
- [OpenAI-compatible 厂商存在非标准字段] → 只通过显式 dialect 扩展，不在核心 Adapter 中按 URL 或模型名猜测。
- [fallback 到不同模型可能改变行为] → 仅使用显式顺序和能力兼容检查，轨迹记录实际模型，评测报告分开统计。
- [流式内容已展示后发生失败] → 标记 partial stream，默认不跨 Provider 无缝续写已展示文本；由 Runtime 返回明确失败或重新开始的提示。
- [`config.toml` 中的 API key 可能被误提交或输出] → 保持该文件被 Git 忽略，示例只使用占位值，所有日志/Hook/轨迹强制脱敏，并允许用户按需在同一 `api_key` 字段使用 `${ENV_VAR}`。

## Migration Plan

1. 增加新合同、分类错误、Profile 配置和旧配置适配器，不改变 Reasoner 行为。
2. 同时实现并通过 OpenAI、Anthropic 非流式 conformance tests，再接入工具续接。
3. 接入 streaming、取消、usage 和 retry 测试；随后由 bootstrap 构造 Router 与 Providers。
4. 将 Reasoner 切换到统一 `complete()`，保留旧 `chat()` 包装和 trajectory 字段兼容。
5. 将默认无配置模式显式改为 Echo；正式配置缺密钥或未知 Provider 时快速失败；开启真实 fallback。
6. 更新示例配置和系统文档，明确 `config.toml` 的 `api_key` 为正式入口及其保护要求，运行全量 pytest、ruff、pyright 和离线秘密扫描。
7. 一个发布周期后可通过独立 change 移除旧 `chat` 包装；本 change 不删除旧 `[llm]` 配置迁移入口。

回滚时可让 bootstrap 重新装配旧 `OpenAICompatibleProvider` 并保留新配置转换层；新合同不写入新的业务持久化表，因此无需数据库回滚。不得通过恢复隐式 Echo fallback 来掩盖故障。

## Open Questions

- OpenAI Responses API、Anthropic prompt-caching beta 和视觉输入在首版只保留能力位与扩展点，具体 wire contract 由后续独立 change 决定。
