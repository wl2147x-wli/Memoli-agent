## Why

Memoli 当前只有最小 OpenAI-compatible 调用，并会在配置缺失或远程调用失败时静默退回 Echo，既无法使用 Anthropic 原生工具与思考协议，也可能把“复述输入”误报为真实模型成功。现在需要建立一套同时支持 OpenAI 与 Anthropic、错误可观察且可由现有 Agent Loop、SubAgent 和轨迹系统共同复用的 Provider 运行时。

## What Changes

- 新增统一、无会话状态的模型请求、响应、工具调用、usage、流式事件、能力与错误合同。
- 同时实现 `OpenAIProvider` 和 `AnthropicProvider`：前者支持 OpenAI Chat Completions 及 OpenAI-compatible 服务，后者使用 Anthropic Messages 原生协议；两者向 Runtime 返回相同的规范化结果。
- 支持非流式与流式文本、思考内容、工具调用增量、结束原因、请求标识和 Token/cache usage，并保持 Agent Loop 串行执行工具。
- 增加显式 Provider/模型 Profile、配置文件 API key、能力声明、超时、有界重试和真实模型 fallback；缺少凭证、未知 Provider 或能力不匹配时快速失败。
- 将 Provider 差异限制在协议适配层，不让 Provider 管理对话历史、上下文装配、工具执行、记忆或轨迹持久化。
- 复用现有 Hook 与 SQLite trajectory，记录实际 Provider、模型、协议、延迟、重试、fallback、usage 和分类错误，同时禁止凭证及未返回的隐藏推理落盘。
- 提供脚本化 Provider、模拟 HTTP/SSE 服务和协议一致性测试，覆盖 OpenAI、Anthropic、工具调用、流式组装、错误、重试与 fallback。
- **BREAKING**：正式 Provider 不再因配置错误或运行失败自动降级到 Echo；Echo 仅能被显式选择或用于测试。旧版单段 `[llm]` 配置在迁移期继续映射为一个默认模型 Profile，并发出弃用提示。

## Capabilities

### New Capabilities

- `llm-providers`: 定义统一模型合同、OpenAI 与 Anthropic 适配器、配置/Profile、能力、流式输出、错误重试、fallback、安全与一致性测试。

### Modified Capabilities

- `agent-runtime`: 将隐式 Echo fallback 改为显式、能力兼容的真实 Provider fallback，并要求所有模型调用使用统一 Provider 合同和可审计元数据。

## Impact

- 主要影响 `memoli_agent/agent/provider.py`、Reasoner 的 Provider 调用边界、`memoli_agent/bootstrap/` 配置与装配、SubAgent 共享 Provider 的装配方式、轨迹/Hook 元数据和相关测试。
- 需要引入或确认支持异步 OpenAI 与 Anthropic 协议、SSE 和可取消超时的 HTTP 客户端依赖；不改变工具 schema、Channel 协议、SQLite 业务表结构和串行 Agent Loop。
- API key 继续通过未纳入版本控制的 `config.toml` 中 `api_key` 字段设置，并可选允许该字段使用 `${ENV_VAR}` 占位符；无论采用哪种取值方式，解析后的凭证均不得进入版本控制、日志、Hook 或轨迹。
- 首版不实现按成本自动选模、在线学习路由、并发工具执行、跨 Provider 自动改写提示词，也不把 Provider 层扩展成通用 LLM 网关。
