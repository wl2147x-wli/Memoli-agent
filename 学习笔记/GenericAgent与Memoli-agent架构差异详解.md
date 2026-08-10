# GenericAgent、Akashic-agent 与 Memoli-agent 架构对比

> 对比项目：
>
> - `D:\wli\project1\GenericAgent`
> - `D:\wli\project1\akashic-agent`
> - `D:\wli\project1\Memoli-agent`
>
> 更新时间：2026-07-24  
> 本文依据当前本地代码、配置和架构文档整理。

## 1. 核心结论

三个项目代表三种不同的 Agent 架构路线：

| 项目 | 核心定位 | 主要特点 |
|---|---|---|
| GenericAgent | 个人自治与本机自动化 Agent | 长任务循环、高权限原子工具、文件 SOP/技能树、多前端 |
| Akashic-agent | 主动式、长期在线的工程化 Agent Runtime | 多轮 Reasoner、双层记忆、插件生命周期、Proactive/Drift、Dashboard |
| Memoli-agent | 小型、清晰、可评测的记忆型 Runtime | 薄 AgentLoop、六阶段 Pipeline、类型化接口、低权限、Benchmark |

它们不是简单的完整版与简化版关系：

- GenericAgent 强调“让模型用少量高权限工具解决真实任务，并把经验固化成技能”。
- Akashic-agent 强调“用模块化 Runtime 将被动对话、主动推送、记忆、插件和后台任务组成长期在线系统”。
- Memoli-agent 强调“保留 Agent Runtime 的关键抽象，以较小代码规模支持学习、替换和记忆评测”。

## 2. 规模与成熟度

| 维度 | GenericAgent | Akashic-agent | Memoli-agent |
|---|---:|---:|---:|
| Python 文件数（粗略） | 约 73 | 约 402 | 约 65 |
| Python 行数（粗略） | 约 36,624 | 约 85,328 | 约 2,829 |
| 集中测试体系 | 较少 | 约 118 个测试文件 | 4 个 benchmark 测试文件 |
| 当前形态 | 应用与框架混合体 | 平台级 Runtime | 早期 Runtime |
| 默认运行模式 | 本机交互和自动化 | 长期服务、多渠道 | CLI |

规模不代表质量，只反映当前功能承载量和工程复杂度。

## 3. 总体架构

### 3.1 GenericAgent

```text
前端 / SDK / Reflect / 子进程
          ↓
GenericAgent.put_task()
          ↓
同步 task_queue
          ↓
GenericAgent.run()
          ↓
agent_runner_loop()
          ↓
LLM Client / Session
          ↕
GenericAgentHandler
          ↓
代码、文件、浏览器、记忆
```

GenericAgent 将核心自治能力集中在 `agent_runner_loop()`、`GenericAgent` 和 `GenericAgentHandler`。模型通过多轮工具调用直接操作真实环境。

### 3.2 Akashic-agent

```text
Telegram / QQ / 飞书 / CLI / IPC
                ↓
           Channel Host
                ↓
        MessageBus inbound
                ↓
            AgentLoop
                ↓
        Agent Core Runner
                ↓
 Passive / Proactive / Drift Turn
                ↓
 Lifecycle Phase + Reasoner
                ↓
 Tool / Plugin / Memory / Provider
                ↓
         Outbound Dispatch
```

Akashic-agent 将消息运输、Turn 类型、推理循环、副作用、记忆和主动系统分成独立模块，适合长期运行和多渠道接入。

### 3.3 Memoli-agent

```text
CLI / Proactive / SubAgent Completion
                ↓
           MessageBus
                ↓
            AgentLoop
                ↓
           AgentRunner
                ↓
      PassiveTurnPipeline
                ↓
       六阶段生命周期
                ↓
 Reasoner / Tool / Memory / Provider
```

Memoli-agent 与 Akashic-agent 的基础结构相近，但只保留了最小实现。

## 4. 入口与依赖装配

| 项目 | 入口 | 装配方式 | 特点 |
|---|---|---|---|
| GenericAgent | `agentmain.py`、`ga_cli`、多个前端入口 | 核心对象内部初始化、动态导入、全局模块 | 启动灵活，但隐式依赖较多 |
| Akashic-agent | `main.py` 子命令 | 大型 `bootstrap/` 和 Wiring | 支持 setup/init/serve/cli/dashboard，生命周期完整 |
| Memoli-agent | `main.py` | `bootstrap/app.py` Composition Root | 最简单清晰，但缺少管理命令 |

Memoli-agent 应保持薄入口，可增加 Akashic 风格的 `setup`、`init`、`inspect`，但不应把初始化逻辑堆进 `main.py`。

## 5. 配置体系

| 项目 | 配置形式 | 模型配置 | 优点 | 局限 |
|---|---|---|---|---|
| GenericAgent | `mykey.py` | 多 Session、Mixin、供应商参数 | 表达力强，支持复杂 Python 配置 | 缺少统一 Schema，配置文件具有执行权限 |
| Akashic-agent | `config.toml` + 配置模型 | main/fast/vl/embedding 分工 | 验证完整，支持向导和插件 Schema | 配置项很多，学习成本高 |
| Memoli-agent | `config.toml` + dataclass | 单主 Provider + Echo fallback | 简单、类型明确 | 缺少多模型、环境变量覆盖和严格验证 |

三者都必须确保真实密钥不进入 Git。GenericAgent 使用本地 `mykey.py`，另外两个项目使用被忽略的 `config.toml`。

## 6. 消息总线、并发与任务控制

### GenericAgent

- 使用线程和同步 `queue.Queue`。
- 一个 Agent 实例串行消费任务。
- 每个任务使用独立 `display_queue` 输出流式 `next/done`。
- 并行通常通过多个实例或进程实现。

### Akashic-agent

- 使用 asyncio MessageBus。
- 为当前 session 保存 active task 和 active turn state。
- 支持按 session 中断、取消和续跑。
- 还有内部事件、生命周期事件和 ProcessingState。

### Memoli-agent

- 使用最小 asyncio inbound/outbound 队列。
- AgentLoop 串行消费消息。
- 尚无 per-session active task、任务取消、流式事件和续跑状态。

| 能力 | GenericAgent | Akashic-agent | Memoli-agent |
|---|---|---|---|
| 并发基础 | Thread/Queue/Process | asyncio/MessageBus | asyncio/MessageBus |
| 流式输出 | display_queue | Channel/Event | 最终 Outbound 为主 |
| 单任务中断 | stop signal/控制文件 | session task cancel | 未完善 |
| 中断后续跑 | 日志/文件提示 | 结构化 interrupt state | 无 |
| 多 session 状态 | 多实例更合适 | Runtime 内管理 | 基础 session history |

## 7. AgentLoop 与 Reasoner

这是三个项目最关键的差异。

### GenericAgent：任务级自治循环

`agent_runner_loop()` 负责：

```text
LLM
→ 多个工具
→ StepOutcome
→ 下一轮 Prompt
→ 重试、自检或结束
```

- 实际最大轮数为 180。
- 工具通过 `data / next_prompt / should_exit` 控制循环。
- `no_tool` 检查模型是否真正完成。
- 周期提醒 checkpoint、验证和策略切换。

### Akashic-agent：消息循环与多轮 Reasoner 分离

AgentLoop 只处理消息和任务控制；`DefaultReasoner` 负责多轮工具循环。

- 配置示例 `max_iterations=40`。
- 每轮包含 BeforeStep/AfterStep。
- 保存 `tool_chain`、`tools_used`、thinking 和 termination reason。
- Tool Loop Guard 可阻止重复或异常工具循环。
- 支持工具延迟暴露、中断和部分执行状态。

### Memoli-agent：消息循环与一次工具回调

AgentLoop 是薄消息泵，设计正确；但 Reasoner 当前 `max_tool_rounds=1`：

```text
LLM
→ 一批工具
→ LLM 最终回答
→ 结束
```

它无法完成需要“读取—修改—验证—失败重试”的长任务。

| 维度 | GenericAgent | Akashic-agent | Memoli-agent |
|---|---|---|---|
| AgentLoop 粒度 | 任务执行循环 | 消息泵/控制面 | 消息泵 |
| Tool Loop 位置 | `agent_runner_loop` | `DefaultReasoner` | `Reasoner` |
| 最大迭代 | 实际 180 | 示例 40 | 1 轮工具回调 |
| 完成协议 | StepOutcome + Handler | ReasonerResult + reason | 二次模型回复 |
| 工具轨迹 | 输出和 Session 历史 | 结构化 tool_chain | 临时 tool messages |
| 无进展保护 | Prompt/Handler | Loop Guard/预算 | 无 |

Memoli-agent 应保留薄 AgentLoop，并将 Akashic 的多轮执行、预算和结束原因移植到 Reasoner，而不是采用 GenericAgent 将循环职责集中在主 Loop 的方式。

## 8. Turn Pipeline 与生命周期

| 阶段 | GenericAgent | Akashic-agent | Memoli-agent |
|---|---|---|---|
| Agent 前后 | Hook | Event/Phase | Plugin 初始化/结束 |
| Turn 前后 | Hook | BeforeTurn/AfterTurn | BeforeTurn/AfterTurn |
| 推理前后 | LLM Hook | BeforeReasoning/AfterReasoning | BeforeReasoning/AfterReasoning |
| Prompt 渲染 | 直接拼接 | PromptRender Phase | PromptRender Phase |
| 每个工具步骤 | Tool Hook | BeforeStep/AfterStep | 无独立 Step Phase |
| 数据传递 | 动态 locals 字典 | 类型化 Slot | PassiveTurnContext |

GenericAgent 最轻量；Akashic 最完整；Memoli 已形成六阶段骨架，但需要在多轮 Reasoner 内补充 Step 生命周期。

## 9. Provider 与模型协议

### GenericAgent

`llmcore.py` 支持：

- OpenAI Chat Completions；
- OpenAI Responses；
- Anthropic；
- 原生与文本工具协议；
- SSE 流式响应；
- Thinking 和 Prompt Cache；
- 多模态；
- 多节点 Mixin fallback；
- 历史裁剪和协议转换。

### Akashic-agent

- 使用 OpenAI/Anthropic SDK。
- main 模型负责主推理。
- fast 模型负责记忆 Gate、Rewrite、HyDE 等轻任务。
- vl 模型负责视觉。
- embedding 模型负责向量检索。
- Provider 与 Prompt Budget、Reasoner 和 Memory Worker 分离。

### Memoli-agent

- EchoProvider；
- OpenAICompatibleProvider；
- 简单 fallback；
- 无流式、Anthropic、Responses、多模型分工、使用量统计。

| 项目 | 强项 | 主要问题 |
|---|---|---|
| GenericAgent | 供应商和协议兼容最灵活 | `llmcore.py` 复杂度高 |
| Akashic-agent | 模型职责分工和工程集成完整 | 依赖和配置复杂 |
| Memoli-agent | 接口小而清楚 | 实际能力不足 |

## 10. Prompt、Context 与 Session

| 项目 | Prompt 构建 | 历史保存 | 上下文控制 |
|---|---|---|---|
| GenericAgent | 模板 + L1 记忆 + extra prompt + anchor | LLM Session 完整历史 + 简化轨迹 | History trim、checkpoint、SOP 指针 |
| Akashic-agent | Prompt Assembler + Section + Context Frame | 结构化 Session Store | Budget、静态/动态块、Tool Search、Memory 注入 |
| Memoli-agent | ContextBuilder | 内存 SessionManager | history window + memory recall |

GenericAgent 的任务级 Working Memory 最实用；Akashic 的 Prompt Budget 最系统；Memoli 缺少 Task Checkpoint、持久 Session 和分段预算。

## 11. 工具架构

### GenericAgent：少量高权限原子工具

核心工具包括：

- `code_run`
- `file_read`
- `file_write`
- `file_patch`
- `web_scan`
- `web_execute_js`
- `ask_user`
- `update_working_checkpoint`
- `start_long_term_update`

工具少，但足以控制终端、文件和真实浏览器。能力扩展主要依靠 Agent 自己编写脚本。

### Akashic-agent：平台化工具运行时

包含：

- Shell、Filesystem；
- Web Search/Fetch、Vision；
- Memory Recall/Memorize/Forget；
- Message Push/Lookup；
- Schedule、Spawn；
- MCP、Peer Agent；
- Tool Search、Meta Toolbox。

工具执行经过 Registry、Bundle、Toolset Provider、Pre Hook、Safety、Loop Guard 和 Trace。

### Memoli-agent：最小安全工具集

包含：

- time、calculator；
- memory_write、memory_recall；
- workspace-only filesystem_read；
- spawn_subagent；
- MCP 动态工具。

| 维度 | GenericAgent | Akashic-agent | Memoli-agent |
|---|---|---|---|
| Schema | 集中 JSON | 对象/装饰器/Meta Catalog | Tool 对象自带 Schema |
| 执行分派 | `do_<name>` | Executor/Registry | ToolRegistry |
| 工具发现 | 固定九工具 | deferred tool_search | 基础 tool_search |
| 权限 | 很高 | 高但有治理 | 默认较低 |
| 审计 | 输出日志 | 结构化 Trace/Observe | 基础结果 |

## 12. 记忆架构

### 12.1 GenericAgent：分层文件技能树

```text
L0  memory_management_sop.md   记忆治理规则
L1  global_mem_insight.txt     极简关键词与文件索引
L2  global_mem.txt             稳定环境和用户事实
L3  *.md / *.py                SOP 与可执行技能
L4  L4_raw_sessions/           会话压缩归档
```

召回流程：

```text
System Prompt 注入 L1
→ 模型判断相关文件
→ file_read
→ Working Checkpoint
```

写入流程：

```text
start_long_term_update
→ 读取 L0
→ 检查已有记忆
→ file_patch/file_write
→ 同步 L1
```

它没有内置向量库，记忆质量主要依赖模型遵守 SOP。

### 12.2 Akashic-agent：Markdown + 向量双层记忆

Markdown 层：

| 文件 | 作用 |
|---|---|
| `MEMORY.md` | 稳定长期记忆，全文进入 System Prompt |
| `SELF.md` | 用户画像与 Agent 自我信息 |
| `HISTORY.md` | 时间线事件 |
| `PENDING.md` | 等待 Optimizer 处理的候选事实 |
| `RECENT_CONTEXT.md` | 近期摘要、线程和最近回合 |

自动流转：

```text
对话
→ Consolidation
→ HISTORY + PENDING + RECENT_CONTEXT
→ ConsolidationCommitted
→ memory2 embedding
→ Optimizer 低频更新 MEMORY
```

`memory2/` 提供：

- Query Rewrite；
- Query Builder；
- HyDE；
- Embedding；
- 关键词/向量混合检索；
- 时间过滤；
- 去重；
- Procedure Tag；
- Profile Extractor；
- Sufficiency Check；
- Injection Planner。

PENDING 缓冲层避免频繁修改完整注入的 MEMORY，从而保护 Prompt Cache。`source_ref` 和两阶段提交保证幂等与崩溃恢复。

### 12.3 Memoli-agent：最小 Memory Runtime

组件包括：

- MemoryItem/Query/Mutation；
- MarkdownMemoryStore；
- KeywordMemoryRetriever；
- MemoryRuntime；
- MemoryConsolidator；
- memory_write/memory_recall。

它的接口适合替换和 benchmark，但当前没有向量层、用户画像、候选缓冲、冲突治理和 Optimizer。

### 12.4 记忆能力对比

| 能力 | GenericAgent | Akashic-agent | Memoli-agent |
|---|---|---|---|
| 人可读文件 | 强 | 强 | 强 |
| 自动沉淀 | 模型主动结算 | 自动 Consolidation | 简单 Consolidator |
| 向量检索 | 无内置 | memory2.db | 无 |
| 索引 | L1 文本指针 | 全文 + 混合检索 | 关键词 |
| 工作记忆 | Handler checkpoint | Turn/Context 状态 | 缺少 Task checkpoint |
| 用户画像 | 文件事实 | SELF + Extractor | 无独立层 |
| 程序性记忆 | SOP/Python 技能 | Procedure + SKILL.md | 骨架 |
| 幂等与事务 | SOP 约束 | source_ref + 两阶段提交 | 基础 |
| 评测 | 无统一层 | LongMemEval/PersonaMem | LoCoMo/LongMemEval |

## 13. 插件、事件与可观测性

### GenericAgent

- 字符串 Hook 注册表；
- Agent/Turn/LLM/Tool 前后事件；
- 插件自动导入；
- 模型日志和前端流作为主要观测手段。

### Akashic-agent

- PhaseModule 与类型化 Slot；
- EventBus Gate/Tap；
- `@on_tool_pre`；
- `@tool`；
- Plugin Manifest 和配置 Schema；
- Plugin Dashboard Panel；
- Observe SQLite；
- Strategy Trace、Latency、全局错误。

### Memoli-agent

- Plugin Protocol；
- PluginContext；
- PluginManager；
- HookRegistry；
- 生命周期 Hook 和 tool_pre；
- 缺少统一 Event/Observe/Persistence。

| 项目 | 插件成熟度 | 可观测性 |
|---|---|---|
| GenericAgent | 轻量、动态 | 日志与 UI 输出 |
| Akashic-agent | 平台级 | Event + SQLite + Dashboard |
| Memoli-agent | 基础类型化 | metadata 与日志 |

## 14. SubAgent 与 Peer Agent

| 维度 | GenericAgent | Akashic-agent | Memoli-agent |
|---|---|---|---|
| 运行载体 | 独立进程 | Background Runtime | 同进程 asyncio Task |
| 任务协议 | 文件目录和控制文件 | Spawn Tool/Completion Event | MessageBus completion |
| Profile | Prompt/SOP 为主 | 明确 Profile | 明确 Profile |
| 工具能力 | 可运行完整 GA | 可按 Runtime 配置 | 子 Reasoner 当前无工具轮次 |
| 编排 | Conductor Agent Pool | SubAgent + Peer Agent | 基础 Manager |
| 中断/状态 | 控制文件 | 结构化状态 | 基础 |

GenericAgent 隔离性强；Akashic 控制面最完整；Memoli 实现轻量但能力有限。

## 15. 主动性、Scheduler 与后台自治

### GenericAgent

Reflect 脚本定期调用 `check()`，返回 Prompt 后进入普通任务队列。已有 Scheduler、Goal Mode、Autonomous、Checklist 等模式。

### Akashic-agent

Proactive v2 流程：

```text
Presence/Energy
→ 自适应轮询
→ alert/content/context 数据源
→ Contract Normalize
→ Gate/Judge/Quota
→ reply 或 skip
→ message_push
```

无内容可推时进入 Drift，执行 `SKILL.md` 后台任务。Scheduler 使用 APScheduler 和正式 JobStore。

### Memoli-agent

ProactiveSensor/Decision/State/Loop 已分层，但实际主要是 interval、cooldown 和简单消息投递；没有独立 Scheduler 和 Drift。

| 能力 | GenericAgent | Akashic-agent | Memoli-agent |
|---|---|---|---|
| 主动触发 | Reflect | Proactive v2 | ProactiveLoop |
| 数据源协议 | 各脚本自行定义 | alert/content/context | 简单 Signal |
| 自适应频率 | 脚本实现 | Energy/Presence | 固定 interval |
| 空闲任务 | Autonomous/Goal | Drift | 无 |
| 定时任务 | JSON 轮询 | APScheduler | 无独立服务 |
| 去重/额度 | 脚本负责 | 内置 | 基础 cooldown |

## 16. MCP、Skill 与外部能力

| 模块 | GenericAgent | Akashic-agent | Memoli-agent |
|---|---|---|---|
| MCP | 无核心实现，依靠代码/HTTP | Client、Registry、管理工具、主动数据源 | stdio Client 和 Tool Adapter |
| Skill | 自由 SOP/Python 文件 | 标准 SKILL.md，可供 Drift 使用 | README 骨架 |
| Browser | 真实浏览器 scan + JS | Web Search/Fetch，Vision | 无 |
| Shell | code_run | shell tool | 无 |
| Peer Agent | 外部桥/Conductor | Registry/Process Manager | 尚未实现 |

Memoli-agent 最适合通过 MCP 外置 Shell、Browser 和高权限能力，避免扩大核心 Runtime 权限。

## 17. Channel、前端与工作区

### Channel 与前端

| 项目 | 主要入口 |
|---|---|
| GenericAgent | Streamlit、Webview、TUI、Tauri、Qt、桌宠、Telegram、QQ、飞书、微信、企微、钉钉、Discord |
| Akashic-agent | Telegram、QQ、飞书、CLI/TUI、IPC、React Dashboard |
| Memoli-agent | CLI、基础 IPC |

GenericAgent 更像桌面产品；Akashic 更像常驻服务；Memoli 仍是开发运行时。

### Workspace

| 项目 | 运行数据位置 | 特点 |
|---|---|---|
| GenericAgent | 项目内 `temp/`、`memory/` | 直观，但代码和用户资产相邻 |
| Akashic-agent | `~/.akashic/workspace/` | 与代码分离，适合升级和多服务 |
| Memoli-agent | 项目内 `workspace/` | 简单，但部署隔离不足 |

Memoli 后续可以保留可配置路径，同时将默认值迁移到用户数据目录。

## 18. 安全模型

| 项目 | 默认权限 | 安全措施 | 主要风险 |
|---|---|---|---|
| GenericAgent | 很高 | Prompt/SOP、用户环境隔离 | 任意代码、文件和浏览器登录态 |
| Akashic-agent | 高 | Shell Safety、Pre-execution、Loop Guard、测试与观测 | 本地 Shell、插件、MCP 仍有进程权限 |
| Memoli-agent | 较低 | workspace 限制、AST 计算、tool_pre | 插件/MCP 仍需审批和审计 |

Memoli 应继续采用默认低权限，并在 Tool 层增加：

- risk level；
- requires approval；
- timeout；
- allowed paths；
- output budget；
- audit event。

## 19. 测试与评测

### GenericAgent

- 缺少集中自动化测试目录。
- 更依赖真实任务、自举和人工运行验证。

### Akashic-agent

测试覆盖：

- Agent Core 和 Tool Loop；
- Lifecycle；
- Memory 和 memory2；
- Plugin；
- SubAgent；
- Proactive；
- Scheduler；
- Channel；
- Safety；
- Dashboard；
- Observe。

评测包括 LongMemEval 和 PersonaMem。

### Memoli-agent

测试集中在 benchmark：

- Agent Adapter；
- Dataset；
- Metric；
- Benchmark Run。

支持：

- LoCoMo；
- LongMemEval；
- Memoli/HTTP/CLI/Python Agent Adapter。

Memoli 的评测分层较清楚，但 Runtime 核心测试明显不足。

## 20. 工程取舍

| 维度 | GenericAgent | Akashic-agent | Memoli-agent |
|---|---|---|---|
| 代码风格 | 实用主义、动态、核心文件较大 | 类型化、平台化、模块很多 | 简洁、分层、小模块 |
| 学习成本 | 中 | 高 | 低 |
| 真实任务能力 | 高 | 高 | 低 |
| 默认安全性 | 低 | 中 | 高 |
| 可替换性 | 中 | 高 | 高 |
| 维护复杂度 | 中高 | 很高 | 低 |
| 产品成熟度 | 高 | 高 | 早期 |
| 适合研究记忆 | 中 | 高 | 高 |

## 21. Memoli-agent 的改进优先级

### 第一阶段：补齐可靠的核心执行

1. 为 AgentLoop、Pipeline、Reasoner、Memory、Plugin、SubAgent 增加单元测试。
2. 将 Reasoner 改为有预算的多轮工具循环。
3. 增加 termination reason、tool_chain 和重复调用检测。
4. 增加 per-session task cancel、interrupt 和 resume。

主要参考 Akashic-agent。

### 第二阶段：补齐上下文与记忆治理

1. 新增 Task/Run 和 Working Checkpoint。
2. 为长期记忆增加稳定 ID、source_ref 和候选缓冲。
3. 实现 consolidation 幂等和冲突检查。
4. 增加可选 embedding/hybrid retrieval。
5. 定义 Procedure Memory 和 SKILL.md。

Working Checkpoint 和技能沉淀参考 GenericAgent；存储、幂等和检索接口参考 Akashic-agent。

### 第三阶段：补齐服务能力

1. 增加流式 AgentEvent。
2. 增加 HTTP/WebSocket Channel。
3. 增加 Observe Store 和最小 Dashboard。
4. 完善 Provider streaming、retry、usage 和多模型分工。
5. 增强 MCP 健康检查、重连、审批和主动数据源。

### 第四阶段：增强主动性和协作

1. Proactive 增加来源 Contract、去重、quiet hours 和额度。
2. 独立实现 Scheduler。
3. 增加 Drift/后台 Skill。
4. 增强 SubAgent 状态、取消、工具白名单和结果汇总。
5. 在此基础上再考虑 Peer Agent。

## 22. 适用场景

### 选择 GenericAgent

- 需要立即操作本机、浏览器和文件；
- 任务需要长时间自主探索；
- 希望通过 SOP 和脚本积累个人能力；
- 能够提供可信或隔离的高权限环境。

### 选择 Akashic-agent

- 需要长期在线和主动联系用户；
- 需要多渠道、Dashboard 和完整插件体系；
- 需要 Markdown 与向量记忆协同；
- 能承担复杂部署、配置和维护成本。

### 选择 Memoli-agent

- 希望学习和控制 Agent Runtime 的每一层；
- 研究长期记忆和统一 benchmark；
- 需要低权限、清晰接口和可替换组件；
- 愿意逐步实现尚未成熟的能力。

## 23. 最终判断

```text
GenericAgent
  = 长任务自治
  + 高权限原子工具
  + 文件 SOP/脚本技能树
  + 多前端个人自动化

Akashic-agent
  = 类型化多轮 Runtime
  + Markdown/向量双层记忆
  + Proactive/Drift
  + 插件、观测和多渠道平台

Memoli-agent
  = 薄 AgentLoop
  + 六阶段 Pipeline
  + 最小 Memory/Tool/Plugin 接口
  + 统一记忆评测基础
```

Memoli-agent 的合理演进方向是：

> 以 Akashic-agent 的多轮 Reasoner、记忆治理、任务控制和事件体系作为工程参考，以 GenericAgent 的 Working Checkpoint、文件技能树和长期任务经验作为能力参考，同时保留自身结构小、默认低权限和便于 benchmark 的特点。
