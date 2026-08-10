## 1. 回归基线与依赖准备

- [x] 1.1 为现有 `LLMProvider.chat`、OpenAI-compatible 直接回复、工具调用解析、Echo 显式模式和 Reasoner fallback 建立不改变当前成功路径的回归基线
- [x] 1.2 记录现有 `[llm]` 配置加载、默认无配置启动、主 Agent 与 SubAgent 共享 Provider、Hook 和 trajectory 字段基线
- [x] 1.3 在项目依赖中加入有上限版本范围的 OpenAI 与 Anthropic 官方异步 SDK，并保持生产依赖最小化
- [x] 1.4 在 `conda memoli` 环境中使用清华 PyPI 源安装新增依赖并验证两个 SDK 可导入，不把环境文件或凭证写入仓库
- [x] 1.5 增加 Provider 测试 marker 和离线/真实网络测试隔离约定，保证默认测试不访问公网

## 2. 统一模型数据合同

- [x] 2.1 定义 `TextBlock`、`ThinkingBlock`、`ToolUseBlock`、`ToolResultBlock` 等有序内容块，并验证非法角色与非法块组合
- [x] 2.2 定义无厂商 SDK 类型的 `ModelMessage`、`ModelRequest`、`ModelResponse`、`TokenUsage` 和结束原因合同
- [x] 2.3 定义 `ModelCapabilities` 与请求所需能力的确定性计算，覆盖 text、tools、reasoning、streaming、structured-output、vision 和 prompt-cache
- [x] 2.4 定义 `thinking_delta`、`text_delta`、`tool_call_delta`、`usage`、`completed` 等类型化流式事件
- [x] 2.5 定义统一异步 `LLMProvider.complete` Protocol 和可选事件回调，确保 Provider 不持有 Session history 或动态 system prompt
- [x] 2.6 实现现有 `ChatMessage` 与规范化消息/内容块的双向兼容转换，保留 tool call ID、顺序和工具结果关联
- [x] 2.7 保留迁移期 `chat(messages, tools)` 兼容包装，并用测试证明其返回内容、tool calls、usage 和错误语义可映射到新合同

## 3. 错误、重试与传输公共层

- [x] 3.1 定义认证、权限、限流、超时、网络、上下文长度、内容安全、无效请求、响应协议和能力错误类型
- [x] 3.2 为统一错误增加 Provider、模型、可脱敏状态码、retryable、attempt 和请求关联字段，不保存 SDK 异常对象或秘密
- [x] 3.3 实现共享重试策略，仅允许网络错误、超时、HTTP 408/429 和 5xx 进入有界指数退避
- [x] 3.4 支持安全解析 `Retry-After`、最大等待上限和 jitter，并使协程取消立即停止等待和后续尝试
- [x] 3.5 建立显式 dialect 注册边界，禁止通过 base URL 或模型名字符串猜测厂商转换
- [x] 3.6 为 Provider 客户端关闭、Runtime 取消和异常退出实现幂等异步资源释放

## 4. Provider、模型 Profile 与配置加载

- [x] 4.1 定义 Provider endpoint 配置，包含 protocol、base URL、dialect、`api_key`、超时和重试上限
- [x] 4.2 定义模型 Profile 配置，包含 Provider 引用、模型 ID、能力、输出限制和受控生成参数
- [x] 4.3 定义 Runtime route 配置，包含 agent 主 Profile 和有序 fallback Profile 列表
- [x] 4.4 从 `config.toml` 的 Provider endpoint `api_key` 读取凭证，并可选解析 `${ENV_VAR}` 占位符，验证空值、缺失占位变量、未知 Provider、重复名称和悬空 Profile/route
- [x] 4.5 将旧版 `[llm] provider/model/api_key/base_url` 映射为隐式 `default` endpoint/profile/route，保持旧 `api_key` 与新 endpoint 字段的相同语义
- [x] 4.6 将缺少配置文件时的内置默认 Provider 显式设为 Echo，同时使正式 OpenAI/Anthropic 配置缺少凭证时快速失败
- [x] 4.7 更新 bootstrap Provider factory，使 endpoint、Profile、route 和 Provider 实例在单一组合根装配
- [x] 4.8 验证主 Agent 与 SubAgent 复用无状态 Provider/Router，但保持各自独立消息历史、trace 和工作状态

## 5. OpenAI Provider

- [x] 5.1 实现 `OpenAIProvider` 异步客户端构造、默认官方 endpoint、自定义 OpenAI-compatible base URL 和幂等关闭
- [x] 5.2 实现规范化 system/user/assistant/tool 消息到 Chat Completions messages 的映射
- [x] 5.3 实现工具 schema、tool choice、输出上限及受控生成参数的请求映射
- [x] 5.4 解析非流式文本、多个 function tool calls、finish reason、实际模型、请求 ID 和 usage
- [x] 5.5 对工具参数执行严格 JSON object 校验，使畸形参数不可执行并产生响应协议错误或结构化修正反馈
- [x] 5.6 实现 OpenAI 文本、工具调用与 usage 的流式增量解析和多调用独立组装
- [x] 5.7 将 OpenAI SDK 的认证、限流、超时、连接、上下文长度、内容安全和无效响应映射为统一错误
- [x] 5.8 通过显式 dialect 接入现有 OpenAI-compatible 行为，并为默认、DeepSeek、DashScope/Ollama 差异预留独立薄适配点

## 6. Anthropic Provider

- [x] 6.1 实现 `AnthropicProvider` 原生 Messages 异步客户端构造、默认 endpoint、自定义 base URL 和幂等关闭
- [x] 6.2 将一个或多个规范化 system 内容块正确映射到 Anthropic system 边界
- [x] 6.3 将 user/assistant 文本、thinking、tool use 和 tool result 按原顺序映射为 Anthropic Messages content blocks
- [x] 6.4 将 OpenAI 风格公共工具 schema 确定性转换为 Anthropic `name/description/input_schema`，不改变 ToolRegistry 公共 schema
- [x] 6.5 解析非流式 text、thinking、redacted thinking、多个 tool use、stop reason、实际模型、请求 ID 和 usage/cache usage
- [x] 6.6 保留 API 明确返回且下一轮协议要求的 thinking signature/opaque continuation 信息，并确保它不成为最终用户文本
- [x] 6.7 实现 Anthropic text、thinking、input JSON、tool use 和 usage 的流式增量解析及完整组装
- [x] 6.8 将 Anthropic SDK 的认证、限流、超时、连接、上下文长度、内容安全和无效响应映射为统一错误
- [x] 6.9 验证 thinking + tool_use + tool_result + 下一轮回复的完整原生协议往返，避免签名、block 顺序或角色错误

## 7. 能力路由与真实模型 fallback

- [x] 7.1 实现请求能力提取以及 Adapter/Profile 共同能力校验，在发出网络请求前拒绝不兼容调用
- [x] 7.2 实现按 route 顺序选择主 Profile 和显式 fallback，不允许 Echo 出现在隐式 fallback 路径
- [x] 7.3 在主 Provider 重试耗尽后切换到下一个能力兼容的真实 Profile，并保留当前已提交运行状态
- [x] 7.4 实现跨 Provider 可移植历史转换，保留文本、工具调用和工具结果，移除目标协议不能安全重放的私有 thinking/signature
- [x] 7.5 没有兼容 fallback 时返回分类失败，确保 Reasoner 以 `failed` 结束而不是生成 Echo 成功回复
- [x] 7.6 在 fallback 结果中保留请求 Profile、实际 Profile、原/实际 Provider 与模型、原因和尝试次数

## 8. Reasoner、Streaming 与生命周期集成

- [x] 8.1 将 Reasoner 模型调用切换到 `ModelRequest` 和 `complete()`，保持当前最大迭代、最长时间、无进展和完成判定边界
- [x] 8.2 工具轮次直接追加 Provider 返回的规范化 Assistant message，确保内容块顺序和 Provider 续接信息不被重新拼接丢失
- [x] 8.3 将规范化 `ToolUseBlock` 转换为现有 ToolRegistry 调用，并将串行执行结果转换为关联 `ToolResultBlock`
- [x] 8.4 保持单次响应多个工具按模型声明顺序串行执行，不因 Provider streaming 引入工具并发
- [x] 8.5 将流式事件接入现有生命周期/Channel 可选回调，不支持 streaming 的 Channel 仍只接收最终出站消息
- [x] 8.6 在工具调用出现、partial stream 失败和用户取消时定义一致的用户可见行为，禁止跨 Provider 无提示续写已展示文本
- [x] 8.7 将 Runtime 关闭和 SubAgent 取消传递到 Provider stream/SDK client，验证不会遗留后台请求
- [x] 8.8 移除 Reasoner 对隐式 Echo fallback 的依赖，并保持显式 Echo 的本地测试路径

## 9. Hook、轨迹与安全

- [x] 9.1 扩展模型调用 Hook/trajectory 投影，记录 route/profile、实际 Provider/model、protocol/dialect、能力和请求 ID
- [x] 9.2 记录每次 attempt 的开始、结束、耗时、分类错误、重试等待、fallback 决策和最终 finish reason
- [x] 9.3 将 OpenAI 与 Anthropic usage 规范化为 input、output、reasoning、cache 和 total token 字段，缺失值保持未知而不伪造零值
- [x] 9.4 让模型可见消息、工具 schema、可见 thinking 和工具调用继续遵守现有 capture/redaction/外置上限
- [x] 9.5 从日志、公共 Hook、SQLite、JSONL 和错误文本中移除 API key、Authorization、Cookie、URL secret、SDK client 和 opaque continuation 值
- [x] 9.6 增加秘密扫描回归，证明 OpenAI/Anthropic 请求成功、异常、重试、fallback 和流式失败均不会泄漏凭证
- [x] 9.7 验证 Provider 层不直接写数据库，所有必需证据仍由 Reasoner 在现有事务边界提交

## 10. 协议一致性与集成测试

- [x] 10.1 建立共享 ScriptedProvider conformance suite，覆盖直接回复、单/多工具、空响应、结束原因、usage、错误和取消
- [x] 10.2 建立本地模拟 OpenAI HTTP/SSE fixture，断言实际请求 wire shape、工具结果关联、增量组装和错误映射
- [x] 10.3 建立本地模拟 Anthropic HTTP/SSE fixture，断言 system/content blocks、thinking signature、tool result、增量组装和错误映射
- [x] 10.4 为 OpenAI 与 Anthropic 分别测试网络错误、超时、408、429、5xx 的重试次数、退避和 `Retry-After`
- [x] 10.5 为认证、权限、无效参数、上下文超长、内容安全、畸形响应和畸形工具参数验证不重试语义
- [x] 10.6 测试能力不匹配、真实 fallback 成功、无 fallback 失败、fallback 不兼容和显式 Echo 模式
- [x] 10.7 测试旧 `[llm]` 配置迁移、配置文件直接 API key、可选环境占位符、新 Profile/route 校验、默认无配置启动和正式配置缺密钥失败
- [x] 10.8 增加主 Agent 两轮工具、SubAgent 工具任务、Provider fallback、流式取消和 Runtime 关闭集成测试
- [x] 10.9 增加真实 OpenAI 与 Anthropic 可选 smoke markers，默认关闭且所有输出经过秘密扫描

## 11. 文档、迁移与质量验证

- [x] 11.1 更新 `config.example.toml`，提供通过 `api_key` 设置 OpenAI 主模型、Anthropic 主模型、OpenAI-compatible、本地 Echo 和真实 fallback 的占位示例，并补充可选 `${ENV_VAR}` 写法
- [x] 11.2 更新 Provider/Agent Runtime 系统文档，说明合同边界、能力、错误重试、streaming、fallback 和轨迹字段
- [x] 11.3 编写旧 `[llm]` 到 endpoint/profile/route 的迁移说明，明确 `config.toml` API key 的保护、可选环境占位符和回滚方法
- [x] 11.4 记录 OpenAI Responses、Anthropic 托管工具/prompt cache、视觉能力和成本路由为后续 change，不在本次实现中暗示已支持
- [x] 11.5 运行 `python -m pytest -q` 并修复全部回归
- [x] 11.6 运行 `python -m ruff check memoli_agent benchmarks tests` 并修复新增静态问题
- [x] 11.7 运行 `python -m pyright` 并确保 Provider 合同、SDK 边界和配置类型检查通过
- [x] 11.8 运行 OpenSpec 严格验证并核对 proposal、design、delta specs、中文 tasks 与最终行为一致
