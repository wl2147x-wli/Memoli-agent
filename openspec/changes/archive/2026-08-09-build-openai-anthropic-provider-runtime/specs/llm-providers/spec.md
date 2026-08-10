## ADDED Requirements

### Requirement: Unified stateless model contract

系统 SHALL 通过统一、异步且无会话状态的模型合同表达有序消息内容块、工具定义、生成选项、模型响应、工具调用、结束原因和规范化 usage；Provider SHALL NOT 管理 Session、记忆、上下文裁剪或工具执行。

#### Scenario: Runtime performs a model call

- **WHEN** Runtime 使用规范化请求调用任一已配置 Provider
- **THEN** Provider SHALL 返回同一种规范化响应合同
- **AND** Runtime SHALL 能在不知道厂商 SDK 类型的情况下读取文本、工具调用、结束原因和 usage

#### Scenario: Provider is shared by runtimes

- **WHEN** 主 Agent 与 SubAgent 共享同一 Provider 实例
- **THEN** Provider SHALL NOT 在实例中保存某个 Session 的消息历史或动态 system prompt

### Requirement: Native OpenAI provider

系统 SHALL 提供 OpenAI Provider，通过 OpenAI Chat Completions 协议发送 system/user/assistant/tool 消息、工具 schema 和生成选项，并 SHALL 支持通过显式 base URL 与 dialect 连接符合该协议的 OpenAI-compatible 服务。

#### Scenario: OpenAI returns a direct answer

- **WHEN** OpenAI 端点返回包含文本和结束原因的成功响应
- **THEN** 系统 SHALL 生成包含实际 Provider、模型、文本、结束原因、请求标识和规范化 usage 的模型响应

#### Scenario: OpenAI requests tools

- **WHEN** OpenAI 端点返回一个或多个 function tool calls
- **THEN** 系统 SHALL 保留每个调用的 ID、顺序、名称和已解析 JSON 参数
- **AND** 后续请求 SHALL 使用关联 ID 回传工具结果

#### Scenario: OpenAI-compatible dialect is configured

- **WHEN** Profile 显式选择受支持的 OpenAI-compatible dialect 和自定义 base URL
- **THEN** 系统 SHALL 仅应用该 dialect 声明的请求与响应转换
- **AND** SHALL NOT 根据 URL 或模型名猜测其他厂商行为

### Requirement: Native Anthropic provider

系统 SHALL 提供 Anthropic Provider，通过原生 Messages 协议发送 system 内容、Messages content blocks、工具定义和生成选项，并将原生响应规范化为与 OpenAI Provider 相同的模型合同。

#### Scenario: Anthropic returns text and thinking blocks

- **WHEN** Anthropic 返回有序的 thinking、text 或 redacted-thinking blocks
- **THEN** 系统 SHALL 保持 API 返回的可见块顺序并提取最终用户可见文本
- **AND** SHALL 保留协议要求用于本次工具续接的 opaque 信息而不把它作为用户文本

#### Scenario: Anthropic requests tools

- **WHEN** Anthropic 返回一个或多个 `tool_use` blocks
- **THEN** 系统 SHALL 将它们规范化为有序工具调用
- **AND** 后续请求 SHALL 以关联的 `tool_result` blocks 回传执行结果

#### Scenario: Anthropic system messages are provided

- **WHEN** 规范化请求包含一个或多个 system 内容块
- **THEN** Anthropic Provider SHALL 将它们映射到 Messages API 的 system 边界
- **AND** SHALL NOT 把 system 内容错误地作为普通用户消息发送

### Requirement: Provider profiles and configured credentials

系统 SHALL 将 Provider endpoint、模型 Profile 和 Runtime route 分离；API 凭证 SHALL 通过 `config.toml` 中对应 Provider endpoint 的 `api_key` 字段设置，且未知 Provider、缺失必需凭证或无效 Profile SHALL 在发出模型请求前失败。

#### Scenario: API key is configured directly

- **WHEN** Provider endpoint 的 `api_key` 包含非空凭证
- **THEN** 系统 SHALL 使用该凭证构造对应 Provider
- **AND** SHALL NOT 将凭证值复制到日志、Hook、轨迹或导出结果

#### Scenario: API key uses an environment placeholder

- **WHEN** `config.toml` 的 `api_key` 使用受支持的 `${ENV_VAR}` 占位符且对应环境变量存在
- **THEN** 系统 SHALL 在配置加载时解析该值并构造对应 Provider
- **AND** 该方式 SHALL 保持为 `api_key` 字段的可选取值形式而非另一套必需配置入口

#### Scenario: Required credential is missing

- **WHEN** OpenAI 或 Anthropic Profile 被选中但其必需凭证无法解析
- **THEN** Runtime 启动 SHALL 报告可操作的配置错误
- **AND** SHALL NOT 静默创建 Echo Provider 或发出远程请求

#### Scenario: Legacy LLM configuration is loaded

- **WHEN** 用户仍使用旧版单段 `[llm]` 配置
- **THEN** 系统 SHALL 在迁移期将其映射为默认 endpoint、Profile 和 route
- **AND** 旧配置中的 `api_key` SHALL 继续具有与新 endpoint `api_key` 相同的凭证语义

### Requirement: Capability-aware invocation

每个模型 Profile SHALL 声明受支持能力，系统 SHALL 在网络调用前验证请求所需能力与 Adapter/Profile 的共同能力，并 SHALL 仅选择满足请求能力的 fallback。

#### Scenario: Tool-capable model is selected

- **WHEN** 请求包含工具 schema 且所选 Profile 声明 `tools` 能力
- **THEN** 系统 SHALL 将工具声明发送给 Provider

#### Scenario: Requested capability is unavailable

- **WHEN** 请求需要 tools、reasoning、streaming、vision 或 structured output，但所选 Profile 不支持该能力
- **THEN** 系统 SHALL 返回 `unsupported-capability` 分类错误或选择显式配置的兼容 fallback
- **AND** SHALL NOT 向不兼容 Provider 发送降级后的不等价请求

### Requirement: Equivalent streaming and non-streaming results

OpenAI 与 Anthropic Provider SHALL 支持非流式完成和可取消的流式完成；流式事件 SHALL 区分思考、文本、工具调用增量、usage 和完成，并 SHALL 组装出与同语义非流式调用相同的最终模型响应。

#### Scenario: Text is streamed

- **WHEN** Provider 逐步返回文本或思考增量
- **THEN** 系统 SHALL 按接收顺序发布类型化增量事件
- **AND** 完成时 SHALL 返回已组装的规范化响应

#### Scenario: Tool arguments are streamed

- **WHEN** Provider 将多个工具调用的名称或 JSON 参数分片返回
- **THEN** 系统 SHALL 按调用 ID 或稳定索引分别组装各调用
- **AND** 只有完整合法的调用 SHALL 交给 Agent Loop 执行

#### Scenario: Streaming call is cancelled

- **WHEN** 调用协程被取消或 Runtime 正在关闭
- **THEN** Provider SHALL 关闭流并停止后续重试和 fallback

### Requirement: Typed errors and bounded retries

系统 SHALL 将认证、权限、限流、超时、网络、上下文长度、内容安全、无效请求、响应协议和能力失败规范化为可观察错误，并 SHALL 只对明确可重试的失败执行有界退避。

#### Scenario: Transient provider failure occurs

- **WHEN** 请求遇到网络错误、超时、HTTP 408/429 或 5xx
- **THEN** Provider SHALL 在配置上限内使用退避重试并遵守可用的 `Retry-After`
- **AND** 每次尝试 SHALL 可由轨迹观察

#### Scenario: Permanent provider failure occurs

- **WHEN** 请求因无效凭证、权限、无效参数、上下文超长、内容安全或响应协议错误失败
- **THEN** Provider SHALL 返回对应分类错误
- **AND** SHALL NOT 对同一无效请求执行盲目重试

#### Scenario: Tool arguments are malformed

- **WHEN** 模型返回的工具参数不是完整合法的 JSON object
- **THEN** 系统 SHALL 返回响应协议错误或生成不可执行的结构化修正反馈
- **AND** SHALL NOT 将任意 raw 字符串作为已验证参数执行

### Requirement: Explicit real-provider fallback

系统 SHALL 只按照 route 中显式配置的顺序执行真实模型 fallback，并在切换前验证能力兼容；Echo SHALL 仅在被明确选为主 Profile 或测试 Provider 时使用。

#### Scenario: Primary provider exhausts retryable attempts

- **WHEN** 主 Provider 的可重试失败达到上限且存在兼容的真实 fallback
- **THEN** 系统 SHALL 使用同一已提交运行状态调用下一个 Profile
- **AND** 响应与轨迹 SHALL 标识原 Provider、实际 Provider、切换原因和尝试次数

#### Scenario: No compatible fallback exists

- **WHEN** 主 Provider 失败且没有显式配置的能力兼容 fallback
- **THEN** 系统 SHALL 向 Runtime 返回分类失败
- **AND** SHALL NOT 使用 Echo 伪造成功回复

#### Scenario: Echo is selected explicitly

- **WHEN** 默认无配置模式、开发者或测试显式选择 Echo Profile
- **THEN** 系统 SHALL 使用 Echo 并明确标识该响应来自测试 Provider

### Requirement: Provider observability and confidentiality

每次逻辑模型调用 SHALL 通过现有 Hook 与 trajectory 边界记录实际 Provider、模型、协议、Profile、能力、延迟、尝试、fallback、结束原因、请求 ID、规范化 usage 和分类错误，同时 SHALL 对秘密和 Provider 私有状态执行最小化与脱敏。

#### Scenario: Provider call succeeds

- **WHEN** OpenAI 或 Anthropic 调用完成
- **THEN** 轨迹 SHALL 包含足以关联请求、模型响应、工具调用和 Token 使用的规范化元数据
- **AND** SHALL 能区分 prompt、cache、reasoning 和 output usage 中 Provider 实际提供的字段

#### Scenario: Provider call fails

- **WHEN** Provider 调用或某次尝试失败
- **THEN** 轨迹 SHALL 记录分类错误、可脱敏状态码、耗时和是否继续重试或 fallback

#### Scenario: Captured data contains sensitive provider state

- **WHEN** 请求、SDK 异常或配置包含 API key、Authorization、Cookie、URL secret 或 Provider opaque continuation 字段
- **THEN** 普通日志、公共 Hook、SQLite 和 JSONL 导出 SHALL NOT 包含这些值
- **AND** 系统 SHALL NOT 请求或保存 Provider 未返回的隐藏推理

### Requirement: Provider conformance verification

OpenAI 与 Anthropic Adapter SHALL 通过共享的离线协议一致性测试，并 SHALL 使用各自的模拟 HTTP/stream 响应验证真实 wire mapping；默认测试 SHALL NOT 依赖公网或真实凭证。

#### Scenario: Conformance suite runs offline

- **WHEN** 开发者运行默认测试套件
- **THEN** OpenAI 与 Anthropic SHALL 分别覆盖直接回复、工具调用与结果续接、流式组装、usage、取消、错误、重试和秘密扫描
- **AND** 测试 SHALL 使用模拟服务或脚本响应

#### Scenario: Real-provider smoke test is requested

- **WHEN** 开发者显式选择需要凭证的集成测试 marker
- **THEN** 系统 MAY 调用对应真实端点
- **AND** 该测试 SHALL 与默认离线测试隔离且不得输出凭证
