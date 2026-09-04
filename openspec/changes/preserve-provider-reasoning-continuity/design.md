## Context

当前调用路径是 `Reasoner -> invoke_provider -> ModelRequest.from_chat_messages`。
`ModelRequest.reasoning` 默认值为 `False`，而 `invoke_provider` 没有推理参数，模型配置也只有宽泛的 `reasoning` 能力标记。因此 Anthropic 适配器中已有的 `thinking={"type": "adaptive"}` 分支通常不可达。OpenAI 适配器使用 `chat.completions.create`，流式时仅从部分兼容方言读取 `reasoning_content`，非流式响应不解析推理内容，也无法支持要求使用 Responses API 的 Codex 类模型。

Anthropic 当前实现已经能按块顺序解析 `thinking`、`signature`、`redacted_thinking` 和 `tool_use`，但这些内容经 `ModelMessage -> ChatMessage.blocks` 进入通用工作历史。轨迹写入会过滤签名和不透明内容，却仍让协议私有状态经过上下文编译、压缩和降级路径。OpenAI Responses 的推理项则没有对应表示。

上下文路径还存在两套不一致的消息视图：令牌估算会读取结构化块，而上下文哈希依赖 `to_dict()`，没有覆盖相同内容。即使当前工具轮次通常能保留内存中的消息块，提交历史后仍会丢失这些块，缓存判定、压缩和实际发送内容因而可能不一致。

两家公开协议体现了相同原则：模型推理状态是有序、不可随意改写的协议对象；工具结果续接时必须保留关联标识和必要的加密状态；用户可见文本、可选推理摘要和私有续接状态必须分开。两种协议的线级结构不同，不能用一个字符串 `thinking` 字段相互转换。本设计只借鉴公开协议能够验证的行为，不推断 Codex 或 Claude Code 的内部实现。

## Goals / Non-Goals

**Goals:**

- 正确启用、配置和计量提供商原生推理能力。
- 在多轮工具调用中保持同一提供商的推理连续性以及项、块的原始顺序。
- 支持 Codex 类模型所需的 OpenAI Responses API，同时保留兼容端点。
- 保持最终答案、进度说明、推理摘要和不透明续接状态之间的明确边界。
- 让降级、压缩、轨迹和界面对推理数据的处理可预测、可验证且不泄漏。

**Non-Goals:**

- 不尝试获取、重建、展示、持久化或训练原始思维链。
- 不通过提示词中的 `<thinking>` 标签模拟提供商原生推理。
- 不让 OpenAI-compatible 端点自动冒充 Responses API。
- 不在本变更中实现未完成交换的跨进程恢复、跨用户轮次续接或长期推理记忆。
- 不照搬 Codex 或 Claude Code 的未公开内部实现；只采用其公开 API 合同可验证的模式。

## Decisions

### 1. 将推理策略与能力声明分开

`reasoning` 能力标记只表示模型配置与适配器是否具备该能力。新增模型配置级策略：

- `reasoning_mode = "off" | "adaptive"`
- `reasoning_effort = "low" | "medium" | "high" | "xhigh" | "max"`（可省略）
- `reasoning_visibility = "hidden" | "summary" | "updates"`

适配器维护各协议和模型系列的支持矩阵，把中立策略转换为合法的线级参数；无法映射的组合在联网前返回稳定的 `UnsupportedReasoningPolicy`。`summary` 表示仅显示提供商明确标记的摘要，`updates` 表示允许显示提供商明确标记的流式推理更新；它们不承诺各提供商具有相同粒度。旧配置等价于 `off`，避免静默增加成本。Anthropic 旧式的 `enabled + budget_tokens` 和 OpenAI 特有的摘要详细程度只作为显式提供商扩展，不塞入中立字段。

首版推理状态的作用域固定为当前提供商交换，不暴露名为 `all-turns` 但实际上无法安全兑现的配置。跨用户轮次续接必须在后续变更中先解决加密持久化、状态过期和删除语义。

### 2. 新增显式 OpenAI Responses 适配器

`protocol = "openai-responses"` 使用 `client.responses.create`。首版默认采用无状态模式：`store=false`，显式请求 `reasoning.encrypted_content`，并在工具续接请求中原样回传上一次响应的有序输出项，再追加带相同 `call_id` 的函数调用结果。

选择手工无状态续接，是因为 Memoli 自己拥有 `ContextCompiler`、轨迹和降级边界，也需要兼容零数据保留场景。`previous_response_id` 仅作为后续可选续接模式；若启用，必须把提供商端状态依赖、过期和不可恢复错误显式化，不能与本地手工重放混用。

Responses 适配器不假定 `output[0]` 是助理文本。它按顺序解析推理、消息、函数调用和其他已支持的项；保留项标识、调用标识、助理 `phase` 和加密内容，并从所有输出文本片段组装最终可见文本。遇到续接所必需但未知的项时采用封闭式失败，不会静默丢弃后继续工具循环。

### 3. 用 `ProviderExchange` 隔离私有续接状态

新增一次逻辑交换的瞬态状态：

```text
ProviderExchange
  exchange_id
  provider/profile/model/protocol
  frozen_reasoning_policy
  opaque_continuation
  portable_assistant_message
  status = active | completed | failed
```

`opaque_continuation` 是适配器自有、带协议标签和版本的不可解释信封。Reasoner 只负责在下一次同协议调用时原样传回；`ContextCompiler`、Hook、轨迹、记忆和通用消息转换都不能读取或序列化它。可移植助理消息只包含文本、工具调用等语义块。

Anthropic 信封保存当前助理轮次中完整有序的思考块、脱敏思考块和工具调用线级块。OpenAI 信封保存完整有序的输出项；首版不保存响应标识作为服务端续接方式。两者绝不转换成对方的推理类型。

### 4. 工具循环期间固定路由和策略

首次模型调用选定实际目标后，整个交换固定该提供商、模型配置、协议、模型和推理策略。工具结果只能续接到该目标。只有在生成任何提供商续接状态或执行任何工具副作用之前，路由器才能选择另一个兼容的降级目标。

如果续接调用失败，运行时保留稳定的失败分类并结束交换；它不会丢弃 Anthropic 签名或 OpenAI 加密项后交给另一提供商猜测。下一个用户轮次可以从已提交的可移植语义历史建立新的交换。

### 5. Anthropic 保持块原样与单轮一致性

适配器根据目标模型的支持情况映射自适应、关闭或旧式手动推理。一个工具交换内不能切换推理模式、推理强度或展示策略。向工具结果续接时，当前助理消息的全部思考块和脱敏思考块必须保持原顺序、原内容和原签名，并与工具调用块一起回传。

默认 `reasoning_visibility="hidden"` 在协议支持时映射为 `display="omitted"`，从而只接收续接所需签名，不流式输出摘要。明确启用摘要或更新时，`thinking_delta` 必须先在适配器内分类为提供商摘要或更新，再投影成安全展示事件。

### 6. 三类展示内容使用不同事件

- `TEXT_DELTA`：最终或中间的用户可见助理文本。
- `PROGRESS_UPDATE`：Agent 主动产生、可直接展示的工作状态，不是模型隐藏思维。
- `REASONING_SUMMARY_DELTA`：提供商明确声明为摘要或更新且模型配置允许展示的
  有界文本。

原始推理、签名、加密内容、工具 JSON 增量和 SDK 对象均不进入展示通道。CLI 默认把隐藏推理投影为无内容阶段；只有显式配置才渲染 `REASONING_SUMMARY_DELTA`，并标注“推理摘要”，避免把摘要误称为完整思维链。

### 7. `ContextCompiler` 把活跃交换后缀视为原子边界

上下文压缩只能作用于已完成的可移植历史。当前交换的助理工具调用与紧随其后的工具结果形成不可拆分后缀，不能重排、摘要或部分删除。不透明续接状态不参与通用正文的令牌估算，但适配器应把提供商报告的实际输入、缓存、推理和输出用量回写预算诊断。

通用消息只生成一次规范化表示，序列化、令牌估算、上下文哈希和缓存键都基于该表示。适配器私有信封使用单独的交换级指纹，只用于检测同一交换内的意外改变，不混入可持久化历史哈希。

### 8. 补齐规范事实源中的提供商规格

以已归档 `build-openai-anthropic-provider-runtime` 的可观察行为和当前测试为基线，补齐 `llm-providers` 规格，再叠加本变更的推理连续性要求。归档时同步更新 `openspec/README.md`，消除事实源缺项。

### 9. 为 Qwen/vLLM 建立显式方言和最终文本隔离

本地 vLLM 不再复用 `dashscope` 方言，而使用显式注册的 `qwen-vllm` 方言。Qwen3
默认可能启用 thinking，因此 `reasoning_mode="off"` 不能通过省略参数表达；适配器
必须发送 `chat_template_kwargs.enable_thinking=false`。启用推理时发送 `true`，并仍由
展示策略决定是否允许摘要进入界面。

`qwen-vllm` 同时处理两种已知响应形式：服务端通过 `reasoning_content` 返回的推理
永远不进入可移植消息；服务端把推理放在普通 `content` 的 `<think>...</think>` 块时，
适配器按协议标记剥离该块，只保留标记之外的最终回答。流式响应采用交换内缓冲后
分类，再发布最终文本，避免标签跨 chunk 时已经把部分思考发送到 CLI。工具调用仍可
在分类完成后按原有结构执行。

不根据“首先”“我需要”等自然语言猜测推理，因为这会误删合法回答。若服务端返回
没有结构化字段、也没有协议标记的混合文本，适配器无法可靠恢复边界；运维配置必须
通过 vLLM 的聊天模板硬关闭 thinking，或启用兼容的 reasoning parser。相比在 CLI
末端正则清洗，选择在适配器边界分类，可以让消息历史、Hook、轨迹和所有展示通道
共享同一份仅含最终回答的规范化结果。

## Risks / Trade-offs

- [无状态 Responses 重放会增加请求体和本地瞬态状态] → 只保留当前交换所需的项，完成后立即丢弃；先依据缓存命中、推理用量、成本与延迟评估，再决定是否增加服务端托管模式。
- [提供商模型参数可能随版本变化] → 模型配置显式声明能力，适配器使用协议矩阵并对不支持的组合快速失败；不依据模型字符串静默猜测。
- [路由亲和性会减少工具循环中的临时降级机会] → 以避免工具产生副作用后丢失推理状态或重复执行为优先；可靠性由同一提供商内重试和新用户轮次恢复承担。
- [推理摘要可能包含敏感内容] → 默认隐藏；显式启用后仍执行长度限制和凭证脱敏，且不写入长期记忆。
- [旧 `ThinkingBlock` 消费方兼容] → 先提供读取迁移层，再移除通用历史中的私有字段；
  已落盘轨迹本来不含可重放 signature，因此无需数据迁移。
- [Qwen 的 `<think>` 标记可能跨多个流式片段] → `qwen-vllm` 在完成分类前不发布文本；
  以牺牲该方言的逐 token 最终文本展示换取不泄漏保证。
- [第三方端点可能移除标记后仍把推理混入正文] → 不做语言启发式猜测；要求服务端
  硬关闭或结构化分离，并提供可选真实端点冒烟测试验证部署合同。

## Migration Plan

1. 先补齐规范事实源中的 `llm-providers` 基线和新合同测试，不改变默认配置。
2. 引入推理策略、`ProviderExchange` 与适配器续接合同，将 Reasoner 工具循环迁移到新合同。
3. 新增 `openai-responses` 适配器；现有 `openai` 和兼容方言保持原行为。
4. 将 Anthropic 私有思考数据从 `ChatMessage.blocks` 迁到交换信封，并保留短期兼容读取。
5. 更新界面安全事件、文档和配置示例；使用固定样例验证完整的线级往返。
6. 如需回滚，配置可切回 `openai` Chat Completions 或关闭推理；升级旧版本前应移除新增字段，持久化 SQLite 数据结构不变。
7. 本地 Qwen/vLLM 配置从 `dashscope` 迁移到 `qwen-vllm`；先以硬关闭模式部署并验证，
   再按需启用结构化 reasoning parser。回滚时恢复旧方言，同时在服务端保持 thinking
   默认关闭，避免重新暴露混合内容。

## References

- OpenAI Responses 创建接口：推理加密内容、`previous_response_id`、有序输出项与推理令牌上限：
  https://developers.openai.com/api/reference/cli/resources/responses/methods/create
- OpenAI 模型指南：推理强度与上下文、手工重放输出项和 Responses 工具调用建议： https://developers.openai.com/api/docs/guides/latest-model
- OpenAI GPT-5-Codex：Codex 优化模型使用 Responses API：
  https://developers.openai.com/api/docs/models/gpt-5-codex
- Anthropic 推理指南：摘要与省略展示、签名、工具续接、交错推理与流式顺序： https://platform.claude.com/docs/en/build-with-claude/thinking

## Open Questions

- 是否在后续变更中为未完成交换增加加密、短存活期的崩溃恢复存储？这需要先定义本地密钥管理和重复工具副作用恢复合同。
- 是否需要服务端托管的 OpenAI `previous_response_id` 模式？应先通过真实长会话基准测试比较无状态重放的缓存命中、成本、延迟和恢复行为。
