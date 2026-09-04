# Memoli-agent 与 CowAgent 详细对比分析

> 分析时间：2026-09-05  
> 对比对象：`D:\project\Memoli-agent` 与 `D:\project\Memoli-agent\CowAgent-master`  
> 分析方式：静态阅读当前工作区中的源码、配置样例、测试、系统文档和 OpenSpec。本文不把 README 中的宣传性描述自动等同于已验证行为；涉及“当前配置”的结论仅适用于本地 checkout。

## 1. 执行摘要

Memoli-agent 和 CowAgent 都在建设“具备工具、长期记忆、Skill、SubAgent 和主动能力的个人 Agent”，但二者当前处于不同的产品层次：

- **Memoli-agent 是偏运行时内核和行为规范的项目**。它重点解决模型调用、推理隔离、上下文预算、工具合同、证据化记忆、离线治理、可回放轨迹、持久任务图和安全边界。其优势是数据模型严谨、行为边界清楚、失败模式可诊断、测试与 OpenSpec 约束较强。
- **CowAgent 是偏完整产品和 Agent Harness 的项目**。它已经把 Agent Core 包装成 Web、桌面端、多即时通讯渠道、模型管理、Skill Hub、知识库、定时任务、浏览器、语音、多模态和一键部署产品。其优势是用户触达面、功能完整度、模型与渠道适配广度、运维体验和日常可用性。

因此，两者并不是简单的“谁更先进”：

| 判断维度 | 更占优势的项目 | 原因 |
| --- | --- | --- |
| 运行时合同、证据链、可审计性 | Memoli | OpenSpec、结构化轨迹、严格 schema、不可变快照和证据化记忆 |
| 记忆治理和冲突处理 | Memoli | Claim/Evidence/Card/Episode、状态机、版本与时态、候选审核 |
| 最终用户产品完整度 | CowAgent | Web/桌面、多渠道、管理页面、安装升级、通知和 Skill Hub |
| 模型和多模态接入广度 | CowAgent | 大量厂商适配器，聊天、视觉、图片、语音、Embedding 可独立配置 |
| 上下文工程严谨性 | Memoli | 分层预算、epoch 快照、archive frontier、工具 schema 冻结及诊断 |
| 知识库体验 | CowAgent | 独立 Markdown Wiki、索引、交叉引用和图谱浏览界面 |
| 默认安全基线 | Memoli | workspace 约束、严格工具校验、容器代码执行、能力撤销；CowAgent 明确说明 shell 权限只是参数级检查 |
| 部署和生态可用性 | CowAgent | 一键安装、Docker、Web 控制台、桌面端、多渠道和市场生态 |

对 Memoli 最合适的路线不是复制 CowAgent 的整套实现，而是：**保留 Memoli 的运行时与治理内核，借鉴 CowAgent 的产品壳、渠道生态、知识库体验、模型能力注册和后台任务可视化。**

## 2. 项目定位与边界

### 2.1 Memoli-agent

Memoli 的 README 将其定义为“面向长期会话、证据化记忆和持续任务的本地 Agent 运行时”。核心代码集中在 [`memoli_agent/`](memoli_agent/)，并以 [`openspec/specs/`](openspec/specs/) 作为当前可观察行为的事实源。

它主要关注：

1. Provider 请求与响应的统一合同。
2. 有界 Agent/Tool 循环。
3. 跨轮上下文编译和预算控制。
4. 工具注册、校验、Hook 和渐进披露。
5. Claim/Evidence/Card/Episode 记忆及离线治理。
6. 持久化 SubAgent Task DAG。
7. 轨迹记录、恢复和诊断。

它目前更像可嵌入其他产品的 Agent Runtime，而不是已经完成的个人助手产品。

### 2.2 CowAgent

CowAgent README 将其定义为完整的 Agent Harness。源码同时包含：

- [`agent/`](CowAgent-master/agent/)：Agent、记忆、知识、Skill、工具、权限和自进化。
- [`models/`](CowAgent-master/models/)：不同厂商和协议的模型适配器。
- [`channel/`](CowAgent-master/channel/)：Web、微信、飞书、钉钉、企微、QQ、Telegram、Slack、Discord 等渠道。
- [`desktop/`](CowAgent-master/desktop/)：桌面端相关实现。
- [`bridge/`](CowAgent-master/bridge/)：渠道和 Agent 之间的桥接层。
- [`cli/`](CowAgent-master/cli/)：进程、配置、Skill、备份等命令行管理。

CowAgent 的边界明显大于 Memoli：它同时承担运行时、应用服务、前端控制台、渠道网关和部署工具的职责。

## 3. 规模快照

以下数据由当前目录静态统计得到，不代表有效代码覆盖率或质量高低：

| 指标 | Memoli-agent | CowAgent-master |
| --- | ---: | ---: |
| Python 源码文件 | 140 | 426 |
| Python 代码行（物理行） | 35,021 | 98,411 |
| 测试文件 | 68 | 111 |
| 测试函数 | 562 | 1,163 |
| 文档文件 | 28 | 273 |
| 当前主 OpenSpec 规格 | 14 | 0 |

需要注意：

- CowAgent 的代码量包含大量渠道、模型厂商、Web、桌面、多媒体和兼容层，不能直接用总代码量判断 Agent Core 更强。
- Memoli 的测试更集中于运行时合同、上下文、记忆治理和 Provider 协议。
- CowAgent 的文档数量包含多语言版本，数量不能直接等价为独立技术内容数量。
- CowAgent 的 `pyproject.toml` 版本为 `1.0.0`，README 变更记录则描述到 `2.1.7`，说明 Python 包元数据与产品发布版本并非同一套版本语义。

## 4. 总体架构对比

### 4.1 Memoli 的核心链路

```text
CLI / IPC
   ↓
Message Bus / Session
   ↓
Lifecycle Phases
   ├─ Cross-turn context
   ├─ Memory pre-recall
   ├─ Context compilation
   └─ Prompt render
   ↓
Bounded Reasoner Loop
   ├─ Provider Router
   ├─ OpenAI / Responses / Anthropic Adapter
   ├─ ToolRegistry + HookBus
   └─ Working checkpoint / SubAgent
   ↓
Trajectory + Context State + Memory + Task Graph
```

特点是运行时状态分库、阶段清晰、合同化程度高。不同状态不会默认混为一体：Session Context、Working State、Trajectory、Personal Memory、Skill 和 SubAgent Task Graph 各自有生命周期。

### 4.2 CowAgent 的核心链路

```text
Web / Desktop / IM Channels
   ↓
Bridge / Channel Context
   ↓
Agent Prompt Builder
   ├─ Tools
   ├─ Skills
   ├─ Memory / Knowledge
   └─ Workspace context files
   ↓
AgentStreamExecutor
   ├─ Multi-provider model adapter
   ├─ Tool loop / selected parallel tools
   ├─ Context trim / compact
   └─ Model fallback
   ↓
Conversation DB + Markdown Memory + Vector Index
```

特点是产品接入层丰富、主链路直接，许多能力通过工作区 Markdown 文件和 Prompt 约定组合完成。

### 4.3 架构取舍

CowAgent 的方式更容易快速增加用户功能；Memoli 的方式更利于证明“模型究竟看到了什么、为什么调用某个工具、某条记忆从哪里来、重启后状态如何恢复”。

对长期个人 Agent 而言，建议以 Memoli 的运行时边界作为内核，以 CowAgent 的渠道和控制台作为外层。若直接把 CowAgent 的文件型状态写法移植进 Memoli，会破坏 Memoli 已经建立的证据和版本治理。

## 5. Agent 循环与任务执行

### 5.1 Memoli

Memoli 的 [`Reasoner`](memoli_agent/agent/core/reasoner.py) 实现有界模型/工具循环，配置样例默认最多 12 次迭代。它把 Provider attempt、工具调用、Hook、fallback、取消、预算和轨迹事件结构化记录。

优势：

- 每次模型调用前重新构造权威请求，而不是复用未经校验的显示文本。
- 工具调用参数进入 `ToolRegistry` 后按 JSON Schema Draft 2020-12 校验。
- Hook 改写参数后再次校验。
- Provider fallback、部分流式输出、协议错误和重试状态进入轨迹。
- Working checkpoint 将任务进度与普通聊天历史分离。

不足：

- 面向最终用户的计划展示、任务列表、通知和后台任务管理界面还不完整。
- 小模型的工具选择质量仍然直接影响任务是否进入正确工具路径。
- 默认内置工具面较窄，用户会将“工具未装配”误解为模型没有能力。

### 5.2 CowAgent

CowAgent 的 [`AgentStreamExecutor`](CowAgent-master/agent/protocol/agent_stream.py) 负责流式模型调用、工具循环、部分并行工具执行、重试、fallback、取消和上下文溢出恢复。默认配置允许 30 个决策步骤。

优势：

- 对流式 UI、IM 渠道和长任务状态更新处理更成熟。
- 对部分声明为可并行的工具调用可以并发执行。
- 模型无文本无工具时会进行有界重试。
- Provider 连续失败后可切换 fallback 模型。
- 对工具重复调用和连续失败有循环抑制逻辑。

风险：

- `agent_stream.py` 同时承载流式解析、工具调度、上下文恢复、推理显示、fallback 和历史维护，文件职责较重，后续维护成本较高。
- 一些关键策略以 Prompt 指令驱动，可靠性受模型服从能力影响。
- Agent 新旧聊天兼容代码、不同 Provider 和渠道行为并存，系统边界比 Memoli 更难穷举验证。

## 6. 模型 Provider 与 thinking/reasoning

### 6.1 Memoli

Memoli 将模型能力显式声明为 `text/tools/reasoning/streaming`，并支持：

- OpenAI Chat Completions。
- OpenAI Responses API。
- Anthropic Messages。
- OpenAI-compatible endpoint。
- `default`、`deepseek`、`dashscope`、`qwen-vllm` 等方言。

[`contracts.py`](memoli_agent/agent/llm/contracts.py) 将 visible text、thinking、tool calls、usage、continuation 和 Provider attempt 分离。[`dialects.py`](memoli_agent/agent/llm/dialects.py) 中的 `qwen-vllm` 方言会处理 `reasoning_content`，并在普通 `content` 中剥离跨 chunk 的 `<think>...</think>` 块。

Memoli 的主要优势是：

- 推理是否开启、强度和可见性是结构化策略，而非单一布尔开关。
- 隐藏 reasoning 不进入用户可见消息的 canonical envelope。
- 工具调用后的 Provider 原生 reasoning continuation 可以保留。
- 不同方言的请求参数和响应提取集中在 Adapter 层。

### 6.2 CowAgent

CowAgent 拥有更广的厂商支持，并在 [`reasoning_capabilities.py`](CowAgent-master/models/reasoning_capabilities.py) 中按 Provider/模型维护 reasoning effort 枚举，包括总是 thinking 的模型。

它同时处理三种常见返回方式：

1. `reasoning_content` 字段。
2. Anthropic 风格 thinking/reasoning content block。
3. 普通 content 内的 `<think>` 标签。

[`agent_stream.py`](CowAgent-master/agent/protocol/agent_stream.py) 会按渠道决定是否显示思考；Web 可展示折叠推理，IM 渠道或关闭 thinking 时剥离。[`openai_compatible_bot.py`](CowAgent-master/models/openai_compatible_bot.py) 还会在 Claude/OpenAI 格式转换时回传 `reasoning_content`，保持部分严格 Provider 的工具调用连续性。

### 6.3 结论

- **协议严谨性：Memoli 更强。** Reasoning 是 Provider contract 的一等字段，并与展示、轨迹和 continuation 分离。
- **厂商覆盖和 UI 体验：CowAgent 更强。** 它维护更多模型能力表，并为 Web/IM 做差异化展示。
- Memoli 应借鉴 CowAgent 的“模型能力注册表 + UI 可选 effort”，但不应退回到一个全局 `enable_thinking` 开关。
- CowAgent 对 `<think>` 使用正则处理；Memoli 的 `qwen-vllm` 采用缓冲后分类，更适合处理标签跨 SSE chunk 的情况。

## 7. 上下文管理

### 7.1 Memoli

Memoli 的 [`context_management/`](memoli_agent/agent/context_management/) 采用分层编译：

- system 和稳定前缀；
- Skill；
- memory；
- working state；
- recent turns；
- archive frontier；
- tool schemas。

主要特性：

- 按模型 profile 的上下文窗口、最大输出和 safety margin 计算输入预算。
- soft、hard、emergency 多级压缩。
- 只压缩完整 turn，避免切断 tool call/tool result 配对。
- archive 不可变且带 source coverage，防止原文和摘要双重注入。
- `(session, conversation_epoch)` 维度冻结上下文与工具 schema 快照。
- 能力被安全撤销时 fail closed。
- 压缩失败、预算不足、被省略块和 frontier 都有诊断。

这是 Memoli 相比 CowAgent 最明显的底层优势之一。

### 7.2 CowAgent

CowAgent 采用更直接的消息列表维护方式：

1. 旧工具结果超过 20,000 字符时截断。
2. 超过 turn 限制时裁剪最早一半完整轮次。
3. 通过 LLM 总结被裁剪内容，写入日级记忆并在下一轮注入摘要。
4. token 仍超限时进行文本化压缩或继续裁剪。
5. API 报上下文溢出时紧急 flush、压缩，最终可清空内存上下文。

见 [`docs/zh/memory/context.mdx`](CowAgent-master/docs/zh/memory/context.mdx)。

优势是策略容易理解，并且压缩结果直接成为日级记忆；不足是 archive 的来源覆盖、版本、去重和失败恢复没有 Memoli 清晰。

### 7.3 建议

Memoli 不应采用 CowAgent 的“简单裁剪一半”替代现有编译器，但可以借鉴：

- `/compact` 这样的明确用户入口。
- Web 中展示上下文消息数、token、角色分布和压缩结果。
- 对 Provider 真实 overflow 错误解析出限制并进行一次精确恢复。
- 压缩完成后的异步通知和可查看摘要。

## 8. 记忆系统

### 8.1 数据模型

#### Memoli

Memoli 将记忆拆为：

- **Claim**：事实正文、scope、状态、置信度、敏感度、有效期。
- **Evidence**：原始消息、quote、hash、trace locator 和验证状态。
- **Card/CardStatement**：从有效 Claim 物化出的稳定用户概览。
- **Episode**：从完整轨迹投影的会话或任务片段。
- **Relation**：supports、corrects、contradicts、supersedes、derived-from。

权威事实保存在 SQLite；FTS 和向量都是可重建派生索引。写入采用追加和版本化思路，删除后停止召回但保留最小 revision/tombstone。

#### CowAgent

CowAgent 使用三层文件记忆：

```text
对话上下文 → memory/YYYY-MM-DD.md → MEMORY.md
```

- `MEMORY.md`：约 30 条以内的核心长期记忆，每次会话自动注入。
- 日级记忆：会话摘要和事件。
- 梦境日记：Deep Dream 的整理记录。
- SQLite `chunks`：Markdown 文件和知识库的分块与向量/FTS 索引。

见 [`docs/zh/memory/index.mdx`](CowAgent-master/docs/zh/memory/index.mdx) 和 [`deep-dream.mdx`](CowAgent-master/docs/zh/memory/deep-dream.mdx)。

### 8.2 写入和整理

Memoli 的在线 `remember/correct` 要求内容与当前用户消息中的 `basis_quote` 对齐。普通推断不能直接成为正式记忆；离线 consolidation 读取权威轨迹、生成 Candidate、验证 Evidence，再由治理 SubAgent 和 Policy Gate 决定发布或请求用户审核。

CowAgent 会在上下文裁剪、每日定时任务、API overflow 时调用 LLM 生成日级摘要；Deep Dream 再读取现有 `MEMORY.md` 和日级记忆，执行去重、冲突更新和清理，并**覆写** `MEMORY.md`。

对比结论：

| 维度 | Memoli | CowAgent |
| --- | --- | --- |
| 写入依据 | 原始用户证据和轨迹引用 | LLM 摘要/蒸馏结果 |
| 正式发布 | Candidate + Governance + Policy Gate | Prompt 约束后写文件 |
| 冲突 | 状态、关系、有效期、supersede | Deep Dream 以新信息更新旧条目 |
| 历史保留 | append-only Claim、Evidence 和 revision | 日级文件保留，但核心文件会覆写 |
| 用户理解成本 | 较高 | 较低，Markdown 可直接查看编辑 |
| 可审计性 | 强 | 中等，依赖日记、文件和日志 |

CowAgent 的体验简单直观，但“同一个模型总结、判断冲突并覆写核心记忆”不适合直接搬到 Memoli。Memoli 可以增加类似 Dream 的展示层，但应让 Dream 输出 Candidate/Proposal，而不是直接改权威 Card/Claim。

### 8.3 检索

#### Memoli 检索

Memoli 当前具备：

- Card-first、Claim-first、Episode-first、Hybrid 路由。
- FTS、Pattern、Semantic、Metadata 四路候选召回。
- scope/status/sensitivity/valid-time 硬过滤。
- 稳定 ID 去重。
- RRF 风格融合。
- 相对阈值、多 lane 保护、类型 smart seed、MMR 和字符预算。
- Claim/Evidence 按详情级别展开。

详见 [`docs/systems/memory.md`](docs/systems/memory.md)。

#### CowAgent 检索

CowAgent 的 [`MemoryManager.search()`](CowAgent-master/agent/memory/manager.py) 会：

- 有 Embedding 时执行向量召回。
- 同时执行关键词召回。
- 关键词路径支持 unicode61 FTS5、trigram FTS5 和 LIKE 回退。
- 默认以 `0.7 × vector_score + 0.3 × keyword_score` 合并。
- 对日期型日记应用 30 天半衰期；`MEMORY.md` 等非日期文件不衰减。
- 应用绝对 `min_score` 后返回。

它还把定位和读取拆成两个工具：

- [`memory_search`](CowAgent-master/agent/tools/memory/memory_search.py)：返回路径、行号、得分和 snippet。
- [`memory_get`](CowAgent-master/agent/tools/memory/memory_get.py)：读取指定文件和行范围。

### 8.4 检索设计结论

Memoli 的治理过滤、类型建模和融合更先进；CowAgent 有三个值得直接借鉴的点：

1. **绝对相关性阈值**：Memoli 当前相对阈值可能让“最不差但仍不相关”的第一名通过。
2. **时间衰减的产品语义**：Episode 可按时间衰减，但核心 Card 不衰减；Memoli 应把它作为排序信号，而不是替代有效期过滤。
3. **Search → Get 两阶段工具体验**：先返回简短定位，再按稳定 ID/证据范围读取详情，减少一次性注入。

Memoli 不应照搬 CowAgent 的固定加权分数，因为 BM25、cosine 和 Pattern 原始分数不可直接跨通道相加；Memoli 当前的 lane 内归一化和 RRF 更安全。

### 8.5 当前 Memoli 的实际配置问题

仓库样例 [`config.example.toml`](config.example.toml) 默认 `auto_recall=true`，但当前本机 [`config.toml`](config.toml) 配置为 `auto_recall=false`。这会使自动 pre-recall 直接返回，并把是否调用 `memory_recall` 完全交给本地小模型。

更重要的是，Memoli 当前 `pre_recall()` 在关闭自动召回后会在核心 Card 选择之前返回，导致“常驻核心概览”和“动态检索”被同一个开关同时关闭。CowAgent 的 `MEMORY.md` 始终注入恰好说明了两层应独立：

- 核心 Card：始终按很小预算提供。
- Claim/Episode：由检索触发器和检索计划按需召回。

## 9. 知识库

CowAgent 把 Memory 和 Knowledge 明确分开：

- Memory 按人与时间组织，保存偏好、决策和经历。
- Knowledge 按主题组织成 Markdown Wiki，维护 index、分类、交叉引用，并在 Web 端展示知识图谱。

Memoli 当前有强记忆模型和 `research-report` Skill，但没有同等产品化的个人知识库域。若把长期研究资料全部塞进 Claim/Episode，会导致：

- 个人事实和公共知识混杂。
- 记忆治理规则被迫承担文档知识管理。
- 检索 scope、衰减和冲突语义不清晰。

建议 Memoli 新增独立 Knowledge 域，但复用基础设施：

```text
Personal Memory：用户事实、偏好、经历、关系
Working State：当前任务状态
Knowledge Base：可复用主题知识和文档
Skill：程序性工作流
Trajectory：原始运行证据
```

Knowledge 可以采用可编辑 Markdown 作为展示与导入格式，但权威索引、source reference、版本和权限仍应结构化管理。

## 10. 工具系统

### 10.1 Memoli

内置能力包括文件读写、精确 patch、代码执行、时间、记忆召回/管理、working checkpoint、ask user、长期更新请求、Web adapter、SubAgent、Skill 加载和 tool search。

优势：

- 注册时验证工具 schema。
- 调用前后都有 Hook。
- 参数被 Hook 改写后再次验证。
- 工具可安全撤销。
- 渐进披露结果持久绑定 session/epoch；未披露工具不能靠猜测名称调用。
- 工具 snapshot 和 capability revision 可诊断。
- 代码执行可使用容器、资源上限和网络开关。

### 10.2 CowAgent

CowAgent 的工具面更宽，包含：

- read/write/edit/ls/search_files；
- bash 和后台命令；
- browser；
- web_search/web_fetch；
- scheduler；
- send；
- vision；
- memory_search/memory_get；
- env_config；
- SubAgent/delegation；
- evolution undo；
- MCP。

[`ToolManager`](CowAgent-master/agent/tools/tool_manager.py) 按 workspace 缓存 MCP 实例，支持后台启动、配置签名和增量刷新，并可在 MCP 工具较多时按需检索工具。

### 10.3 对 Memoli 的启示

Memoli 应优先补齐高频产品工具，而不是一次性扩充几十个接口：

1. `list/search_files`：减少模型把文件读取误解为只能知道精确路径。
2. Scheduler：让 Proactive 从轮询机制变为用户可管理任务。
3. `memory_get` 或按 ID 展开：与 `memory_recall` 的粗召回分离。
4. 可控 shell/background process：若引入，必须走真实 sandbox/容器，不依赖字符串规则。
5. MCP 状态和刷新 UI：显示 pending/ready/failed，避免用户看到旧工具快照。

## 11. Skill 与插件

### 11.1 Skill

Memoli 的 Skill 侧重治理：

- 不可变版本。
- SQLite catalog。
- Session 快照。
- `skill_load` 渐进读取。
- requirements 与工具/MCP 可用性检查。
- 可审计使用事件。

CowAgent 的 Skill 侧重生态和可操作性：

- 工作区文件型 Skill。
- Skill Hub 搜索和一键安装。
- GitHub/URL 等来源安装。
- 对话创建 Skill。
- Web 控制台管理。
- 内置 `skill-creator` 脚本和验证流程。

建议 Memoli 保留不可变 artifact 和版本治理，在其上增加 CowAgent 风格的安装源、市场索引和 UI；不要让远端 Skill 下载后直接覆盖正在使用的版本。

### 11.2 插件

Memoli 的插件系统包含 manifest、capability、Hook、backend、RPC runner 和生命周期事件，更接近受控扩展点。CowAgent 同时保留了传统事件插件目录和 Agent 工具体系，生态兼容性更强，但存在两套扩展范式并存的复杂度。

Memoli 应避免为了兼容 CowAgent 插件而污染核心 Hook 合同。若要复用生态，建议提供单独的兼容 Adapter，并明确其权限低于原生插件。

## 12. MCP

两者都支持 MCP，但重点不同：

- Memoli：将 MCP 工具注册进统一 `ToolRegistry`，复用 schema 校验、Hook、轨迹和披露合同。
- CowAgent：支持 stdio、SSE、OAuth、后台加载、配置热刷新和工具数量过多时的按需检索，运维体验更完整。

Memoli 最值得借鉴的是 CowAgent 的 MCP 生命周期展示：

```text
configured → starting → ready / failed → changed → reloading
```

但最终授权仍应由 Memoli 的 capability revision、session/epoch disclosure ledger 和安全撤销决定，而不是简单把当前 `ToolManager` 中的实例快照复制给新 Agent。

## 13. SubAgent 与多 Agent

Memoli 已实现持久 Agent Tree/Task DAG、依赖调度、取消恢复、profile 工具约束和完成事件回流。其 Governance SubAgent 还能使用独立受限工具集合和空轨迹存储，体现了最小权限思路。

CowAgent 提供：

- subagent 临时任务；
- agent delegation；
- Team/地址机制；
- 面向用户的并行委派体验；
- Self-Evolution 中隔离的复盘 Agent。

对比来看：

- Memoli 的任务状态和恢复语义更扎实。
- CowAgent 的委派入口、用户反馈和生态整合更完整。

Memoli 应重点补齐“用户能看见什么”：任务树、等待依赖、当前执行者、取消范围、完成回流和失败重试，而不是重新实现一套 Team 协议。

## 14. 主动能力与自进化

### 14.1 Memoli

Memoli 有 Proactive Loop、Sensor、Decision 和 cooldown/quiet hours，并有离线记忆 consolidation、Card Builder、索引 Worker。OpenSpec 中还存在 lifelong agent evolution 的设计方向。

其特点是把“记忆整理”“Skill 候选”“训练候选”区分开，不允许普通对话自动越权发布新 Skill 或正式个人事实。

### 14.2 CowAgent

CowAgent 的 Self-Evolution 在会话空闲且达到轮数/上下文压力条件后启动独立复盘任务，可：

- 修复或创建 Skill；
- 推进未完成事项；
- 补记 Memory；
- 补充 Knowledge；
- 记录 evolution 日志；
- 在修改前备份并提供 undo。

Deep Dream 则每日蒸馏日级记忆到核心 `MEMORY.md`。

### 14.3 建议

Memoli 可以借鉴 CowAgent 的触发体验、备份/撤销、变更检测和“没做事不通知”，但实施时必须保留：

1. Evolution 只能生成 Proposal。
2. Proposal 明确列出目标文件/实体、diff、证据、风险和回滚计划。
3. Personal Memory 走 Memory Policy Gate。
4. Skill 走版本化 artifact 发布流程。
5. 外部副作用仍需单独授权。
6. 备份不是证据治理的替代品。

## 15. 渠道、Web 与桌面端

这是 CowAgent 对 Memoli 最大的产品优势。

CowAgent 已包含 Web、终端、微信、飞书、钉钉、企微、公众号、QQ、Telegram、Slack、Discord 等渠道，以及桌面端和 OpenAI-compatible Web API。不同渠道处理 Markdown、流式更新、文件、语音和群聊身份。

Memoli 当前主要是增强 CLI、plain CLI 和 IPC adapter。它的 Message Bus 和 presentation event 已具备扩展基础，但缺少：

- 稳定的外部 channel SDK；
- 用户/群组/租户身份映射；
- 断线、去重、ack 和重放语义；
- 附件与多模态统一 envelope；
- Web 配置、轨迹、记忆和任务管理界面。

建议先建设 Web 控制平面，再接 IM：

1. 只读状态页：模型、工具、MCP、上下文、记忆、任务、trace。
2. 受控管理页：配置变更、记忆审核、任务取消、Skill 安装。
3. Web chat channel。
4. Telegram/飞书等单一外部渠道试点。
5. 再扩展群聊和多租户。

## 16. 权限与安全

### 16.1 Memoli

Memoli 的安全能力主要是：

- 文件工具限定 workspace。
- JSON Schema 参数校验。
- Hook 修改后重校验。
- code runner 可切换到 Docker，并配置网络、内存、CPU、PID 和超时。
- 记忆按 scope、敏感度、状态和有效时间过滤。
- 检索内容标记为 data，不作为指令。
- Tool Disclosure 与 capability snapshot 防止未授权工具调用。
- Governor SubAgent 不具备文件、网络、代码和委派能力。

### 16.2 CowAgent

CowAgent 提供 session 级：

- `read-only`
- `workspace-write`
- `full-access`

但 [`policy.py`](CowAgent-master/agent/permission/policy.py) 明确说明这是参数级检查，不是 OS sandbox。文件工具可以精确检查路径，bash 只能解析常见命令、重定向和危险操作；shell 启动的程序仍可能写入 OS 允许的位置。

另外，当前 [`config-template.json`](CowAgent-master/config-template.json) 写的是 `full-access`，代码又包含新配置默认收紧到 `workspace-write` 的迁移逻辑，文档中也存在默认值差异。产品应统一“样例、代码默认、升级迁移和 UI 展示”四处语义。

### 16.3 结论

Memoli 不应照搬 CowAgent 的 bash 权限字符串解析作为安全边界。可以借鉴其三档权限 UX，但底层映射应是：

| 用户模式 | Memoli 底层策略 |
| --- | --- |
| read-only | 只注册只读工具；写工具不披露 |
| workspace-write | 文件路径约束 + 容器执行 + 禁止外部副作用 |
| full-access | 仍需显式开启；高风险外部动作保留确认 |

## 17. 配置、部署和运维

### Memoli

- Python 3.11+。
- `pyproject.toml` 统一依赖。
- typed TOML 配置和启动期验证。
- CLI、benchmark 配置、Docker code runner。
- 配置错误倾向于 fail fast。

### CowAgent

- 一键安装脚本、Docker、Web 服务、桌面应用。
- Web 控制台动态配置模型、渠道、Skill、记忆。
- `config.py` 保留大量历史和厂商字段，兼容面广但集中配置文件较重。
- 主依赖、可选依赖和不同渠道依赖分散在多个文件及安装流程中。

建议 Memoli 增加控制平面和配置迁移，但继续使用 typed schema。不要复制 CowAgent 的巨型平面 JSON；可以在 UI 中编辑，落盘时仍生成版本化、可校验的 TOML/SQLite 配置记录。

## 18. 可观测性与恢复

Memoli 的原始运行证据保存在 SQLite trajectory，Provider attempts、模型响应、工具调用、结果、Hook、memory retrieval、context compilation 和 SubAgent 事件可关联 trace。Context、Working State、Memory 和 Task Graph 有独立恢复语义。

CowAgent 有日志、会话数据库、记忆文件、Dream/Evolution 日记、Web 状态和服务命令，用户侧可见性更强；但其日志与文件记录不像 Memoli 的 canonical trajectory 那样形成统一证据模型。

最佳组合是：

- 后端继续以 Memoli trace 为权威证据。
- 前端采用 CowAgent 风格的任务、记忆、MCP、模型和日志视图。
- 所有 UI 状态都能回链到 trace ID、stable memory ID、task ID 和 capability revision。

## 19. 测试与工程治理

Memoli 的 [`AGENTS.md`](AGENTS.md) 要求行为变化先走 OpenSpec，并运行 pytest、ruff、pyright 和 `openspec validate --all --strict`。这种流程对上下文、工具、记忆等容易产生隐式回归的系统很重要。

CowAgent 当前测试数量更多，覆盖渠道、工具、模型、记忆、权限和产品兼容场景；但缺少与 OpenSpec 等价的单一行为事实源，README、配置样例、代码默认值之间已能看到少量漂移。

Memoli 应借鉴 CowAgent 的广覆盖集成测试，CowAgent 则适合借鉴 Memoli 的规格化合同。对 Memoli 下一阶段建议新增：

- Web/channel contract tests。
- 多模型 reasoning/tool continuation 兼容矩阵。
- MCP 热刷新和旧快照失效测试。
- 记忆触发、路由、绝对拒绝、多跳和时态评测。
- UI 操作到 trajectory 的端到端关联测试。
- 安装、升级、配置迁移和备份恢复测试。

## 20. Memoli 应优先借鉴的设计

### 20.1 高优先级：可以较快落地

1. **核心记忆常驻与动态记忆解耦**  
   借鉴 CowAgent 始终注入 `MEMORY.md` 的语义，但使用 Memoli 的 bounded current Card statement，不直接注入可覆写文件。

2. **Memory Search → Get 两阶段交互**  
   `memory_recall` 默认只给稳定 ID、摘要、类型、时间和来源；新增按 ID 获取 Claim/Evidence/Episode 原文的只读展开工具。

3. **绝对相关性阈值和时间排序信号**  
   保留 RRF 和 hard filters，增加绝对 no-match 判断；Episode 引入可配置时间衰减，Card 不衰减，Claim 由 valid time/current status 优先。

4. **工具和 MCP 状态面板**  
   直接解决“为什么模型说没有工具”“为什么启动后还是旧工具快照”等用户问题。

5. **模型能力注册表**  
   将 Provider/模型的 thinking-only、effort 值、tool compatibility、streaming、context window 和方言约束集中管理。

6. **显式 `/compact` 和上下文可视化**  
   用户能主动释放上下文，并看到压缩前后 token、archive、被省略块和恢复状态。

### 20.2 中优先级：补齐产品层

1. Web Chat 和只读控制台。
2. 记忆 Candidate 审核、Evidence 查看、冲突和版本时间线。
3. SubAgent Task DAG 展示和取消。
4. MCP/Skill 安装和刷新管理。
5. Scheduler 与可管理的 Proactive jobs。
6. 独立 Knowledge Base。
7. 一个外部 IM 渠道试点。

### 20.3 后续：受治理的自进化

1. 空闲触发器。
2. 独立 evolution profile。
3. 基于 trace 的变更 Proposal。
4. 文件/Skill/Memory 分域审批。
5. 原子备份、diff 和撤销。
6. 无实际变化不通知。
7. 评测通过后才允许提高自动发布范围。

## 21. 不建议直接照搬的 CowAgent 设计

1. **LLM 直接覆写核心记忆**：简单，但可能丢失来源、错误合并冲突或产生不可证明的新事实。
2. **把权限字符串解析当成 sandbox**：适合作为 UX 限制，不足以构成执行安全边界。
3. **全局巨型配置字典**：兼容快，但会使默认值、迁移、UI 和文档漂移。
4. **在单一流式执行器中聚合过多职责**：应拆成 Provider Stream Parser、Turn Controller、Tool Scheduler、Recovery Policy 和 Presentation Adapter。
5. **依赖 Prompt 强制模型主动写记忆/检索**：小模型尤其容易忽略；明确用户请求应由 Runtime 确定性触发。
6. **将 Memory 和 Knowledge 共用一个检索工具但缺少清晰结果类型**：Memoli 应保留域、权限和引用类型。
7. **兼容层长期进入核心路径**：旧聊天机器人、Agent、插件和新工具框架应通过边界 Adapter 隔离。

## 22. 推荐的目标组合架构

```text
┌──────────────── CowAgent 值得借鉴的产品层 ────────────────┐
│ Web / Desktop / IM / Scheduler / Skill Hub / Knowledge UI │
└──────────────────────────┬─────────────────────────────────┘
                           │ Channel + Control API
┌──────────────────────────▼─────────────────────────────────┐
│                  Memoli Runtime Kernel                     │
│ Lifecycle │ Context Compiler │ Reasoner │ Tool Registry    │
│ Provider Router │ Reasoning Contract │ Capability Ledger   │
└──────────────┬───────────────┬───────────────┬─────────────┘
               │               │               │
        Personal Memory   Working State   Task/Agent DAG
        Claim/Evidence    Checkpoint       Persistent Tasks
        Card/Episode
               │
        Independent Knowledge Base
        Document/Entity/Relation/Source
```

核心原则：

- CowAgent 的功能入口可以借鉴，Memoli 的权威状态模型不要弱化。
- UI 可以显示自然语言，后台必须保留稳定 ID、revision、scope、证据和 trace。
- 自动化能力越强，发布与执行权限越要分层。
- 产品层可热更新，运行时当前 turn 的能力必须冻结且可审计；跨 turn 再刷新 capability snapshot。

## 23. 建议路线图

### P0：修复当前可靠性问题

- 解耦核心 Card 和动态 `auto_recall`。
- 对明确“使用 memory/file/tool”的请求实现确定性能力路由。
- 完成软多标签 Memory Search Plan，而不是关键词单标签排他路由。
- 增加绝对 no-match 阈值。
- 修复 Card statement 相关性边界。
- 在 `/tools` 和 `/context` 展示 snapshot revision、注册工具、已披露工具、失效原因和刷新时点。
- 为 Qwen/VLLM、DeepSeek、Anthropic、OpenAI Responses 建立 reasoning/tool 多轮回归矩阵。

### P1：建设最小产品控制面

- 只读 Web 状态和 trace 页面。
- Web Chat。
- Memory Candidate/Evidence/Conflict 管理。
- MCP/Skill 状态与安装。
- Task DAG 页面。
- 配置 schema API 和安全保存。

### P2：扩展可用能力

- Scheduler。
- Knowledge Base。
- search_files 和后台进程工具。
- 多模态消息 envelope。
- 单个 IM 渠道试点。
- Provider/模型能力目录。

### P3：受治理的持续进化

- Evolution Proposal、diff、备份与 undo。
- 离线评测门槛。
- Skill candidate 自动验证。
- 未完成任务恢复策略。
- 主动服务与通知策略。

## 24. 最终判断

如果目标是尽快部署一个可通过 Web 和多个聊天平台使用的个人助手，CowAgent 当前更接近成品。

如果目标是构建一个能长期演进、可以解释记忆来源、严格控制工具权限、支持小模型与多 Provider、并能可靠恢复和审计的 Agent 内核，Memoli 的基础设计更合适。

Memoli 当前最缺少的不是再增加一套 Agent Loop，而是三个层面：

1. **检索与工具触发可靠性**：不能完全依赖小模型自由决定是否调用工具。
2. **产品控制面**：用户需要看见模型、工具、记忆、MCP、上下文、任务和轨迹的真实状态。
3. **渠道和知识生态**：将严谨内核转换为可日常使用的产品。

建议把 CowAgent 视为“产品功能和交互参考”，把 Memoli 自身 OpenSpec、Provider contract、Context Compiler、Tool Registry 和证据化 Memory 继续作为实现事实源。这样既能获得 CowAgent 的可用性，也不会牺牲 Memoli 最有价值的正确性与治理能力。

## 25. 主要核对入口

### Memoli-agent

- [`README.md`](README.md)
- [`AGENTS.md`](AGENTS.md)
- [`pyproject.toml`](pyproject.toml)
- [`docs/systems/memory.md`](docs/systems/memory.md)
- [`docs/systems/context-management.md`](docs/systems/context-management.md)
- [`docs/systems/llm-providers.md`](docs/systems/llm-providers.md)
- [`memoli_agent/agent/core/reasoner.py`](memoli_agent/agent/core/reasoner.py)
- [`memoli_agent/agent/context_management/compiler.py`](memoli_agent/agent/context_management/compiler.py)
- [`memoli_agent/agent/memory/`](memoli_agent/agent/memory/)
- [`memoli_agent/agent/llm/`](memoli_agent/agent/llm/)
- [`memoli_agent/agent/tools/registry.py`](memoli_agent/agent/tools/registry.py)
- [`memoli_agent/agent/trajectory.py`](memoli_agent/agent/trajectory.py)
- [`openspec/specs/`](openspec/specs/)

### CowAgent

- [`CowAgent-master/README.md`](CowAgent-master/README.md)
- [`CowAgent-master/docs/zh/intro/architecture.mdx`](CowAgent-master/docs/zh/intro/architecture.mdx)
- [`CowAgent-master/docs/zh/memory/index.mdx`](CowAgent-master/docs/zh/memory/index.mdx)
- [`CowAgent-master/docs/zh/memory/context.mdx`](CowAgent-master/docs/zh/memory/context.mdx)
- [`CowAgent-master/docs/zh/memory/deep-dream.mdx`](CowAgent-master/docs/zh/memory/deep-dream.mdx)
- [`CowAgent-master/docs/zh/memory/self-evolution.mdx`](CowAgent-master/docs/zh/memory/self-evolution.mdx)
- [`CowAgent-master/agent/protocol/agent_stream.py`](CowAgent-master/agent/protocol/agent_stream.py)
- [`CowAgent-master/agent/prompt/builder.py`](CowAgent-master/agent/prompt/builder.py)
- [`CowAgent-master/agent/memory/manager.py`](CowAgent-master/agent/memory/manager.py)
- [`CowAgent-master/agent/memory/storage.py`](CowAgent-master/agent/memory/storage.py)
- [`CowAgent-master/agent/tools/tool_manager.py`](CowAgent-master/agent/tools/tool_manager.py)
- [`CowAgent-master/agent/permission/policy.py`](CowAgent-master/agent/permission/policy.py)
- [`CowAgent-master/models/reasoning_capabilities.py`](CowAgent-master/models/reasoning_capabilities.py)

