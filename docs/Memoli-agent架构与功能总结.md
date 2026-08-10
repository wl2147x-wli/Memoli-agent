# Memoli-agent 架构与功能总结

> 生成日期：2026-08-09
> 项目版本：0.1.0
> 项目描述：A memory-focused extensible agent runtime（记忆驱动的可扩展智能体运行时）

---

## 一、项目概述

Memoli-agent 是一个 Python 3.11+ 的智能体运行时，核心特色是**证据化长期记忆**、**可审计轨迹**和**插件化扩展**。系统采用消息总线模式，通过 Channel（CLI/IPC）接收用户输入，经 6 阶段 PassiveTurnPipeline 处理后返回结果。所有操作均记录在 SQLite 轨迹存储中，确保完整可审计性。

### 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| 异步运行时 | asyncio（标准库） |
| 配置 | TOML via tomllib（3.11 标准库） |
| 持久化 | SQLite（标准库 sqlite3）— 用于记忆、轨迹、工作状态、插件、子Agent |
| LLM 集成 | OpenAI-compatible API via urllib（标准库，线程池运行）；EchoProvider 回退 |
| 记忆 | 证据化 SQLite claims + 版本化 cards + FTS5 全文检索 + CJK n-gram + RRF 混合召回 |
| 嵌入 | Deterministic（哈希）/ OpenAI-compatible / 禁用 |
| MCP | mcp>=1.27,<2 Python SDK，stdio 传输 |
| 插件沙箱 | Docker（非 root 用户 65532，资源限制：256MB/0.5CPU/32PIDs） |
| 可观测性 | SQLite append-only 轨迹存储，OpenTelemetry 兼容 trace/span ID |
| 测试 | pytest（24 个测试文件） |
| 代码质量 | ruff + pyright |
| 规范管理 | OpenSpec（规范驱动开发工作流） |

**外部依赖极简**：运行时仅依赖 `mcp` 包，其余全部使用 Python 3.11+ 标准库。

---

## 二、目录结构

```
Memoli-agent/
├── main.py                          # 入口：load_config → build_app_runtime → start/run/shutdown
├── pyproject.toml                   # 项目元数据、依赖、工具配置
├── config.toml                      # 当前本地配置（DeepSeek v4 Flash）
├── config.example.toml              # 完整参考配置
├── .env.example                     # 环境变量参考
│
├── memoli_agent/                    # 核心源码
│   ├── bootstrap/                   # 配置加载与运行时装配
│   │   ├── config.py                # 17 个 dataclass 配置 + load_config()
│   │   ├── app.py                   # AppRuntime 组装根（build_app_runtime）
│   │   ├── tools.py                 # 内置工具注册
│   │   ├── memory.py                # MemoryRuntime 构建器
│   │   ├── subagent.py              # SubAgentManager 构建器
│   │   ├── channels.py              # 通道连线
│   │   ├── mcp.py                   # MCP 客户端构建器
│   │   ├── proactive.py             # 主动循环构建器
│   │   └── trajectory.py            # 轨迹存储构建器
│   │
│   ├── agent/                       # Agent 运行时核心
│   │   ├── loop.py                  # AgentLoop — 异步消息泵
│   │   ├── runner.py                # AgentRunner — 路由到 pipeline
│   │   ├── provider.py              # LLM provider 协议 + 实现
│   │   ├── session.py               # 会话管理（历史窗口）
│   │   ├── context.py               # ContextBuilder（prompt 组装）
│   │   ├── trajectory.py            # SQLiteTrajectoryStore（~810 行）
│   │   ├── types.py                 # ChatMessage, TurnState 等
│   │   │
│   │   ├── core/                    # Turn 处理核心
│   │   │   ├── reasoner.py          # 核心推理循环（~914 行）
│   │   │   ├── passive_turn.py      # 6 阶段 PassiveTurnPipeline
│   │   │   ├── prompt_blocks.py     # System prompt 构建器
│   │   │   ├── response_parser.py   # LLM 响应解析
│   │   │   └── results.py           # TurnResult, LoopOutcome
│   │   │
│   │   ├── lifecycle/               # 生命周期阶段系统
│   │   │   ├── phase.py             # PhaseModule 协议
│   │   │   ├── phases.py            # 6 个默认阶段实现
│   │   │   └── types.py             # PassiveTurnContext
│   │   │
│   │   ├── tools/                   # 工具系统
│   │   │   ├── base.py              # Tool 协议, ToolResult
│   │   │   ├── registry.py          # ToolRegistry + HookBus 集成
│   │   │   ├── generic.py           # FileRead, FileWrite, FilePatch, CodeRun
│   │   │   ├── control.py           # WorkingState, AskUser, LongTermUpdate, Time, MemoryRecall
│   │   │   ├── browser.py           # WebScan, WebExecuteJS
│   │   │   ├── builtin.py           # 内置工具聚合
│   │   │   ├── execution.py         # 工具执行辅助（WorkspacePathResolver, bound_text）
│   │   │   └── tool_search.py       # 工具搜索能力
│   │   │
│   │   ├── memory/                  # 记忆子系统
│   │   │   ├── models.py            # 所有记忆数据模型
│   │   │   ├── runtime.py           # MemoryRuntime（query, mutate, recall）
│   │   │   ├── sqlite_store.py      # SQLite 证据化存储（~1710 行）
│   │   │   ├── store.py             # MarkdownMemoryStore（legacy）
│   │   │   ├── hybrid.py            # HybridMemoryRetriever + RRF
│   │   │   ├── semantic.py          # Embedders（Deterministic, OpenAI, Disabled）
│   │   │   ├── episodic.py          # TrajectorySegmentIndexer
│   │   │   ├── cards.py             # CardBuilder
│   │   │   ├── consolidator.py      # 记忆整理
│   │   │   ├── migration.py         # Legacy markdown 迁移器
│   │   │   └── retriever.py         # 基础检索器
│   │   │
│   │   ├── working/                 # 工作记忆
│   │   │   ├── models.py            # Working state 模型
│   │   │   └── repository.py        # SQLite 工作状态存储
│   │   │
│   │   ├── plugins/                 # 插件基础设施
│   │   │   ├── manager.py           # PluginManager
│   │   │   ├── manifest.py          # Manifest 解析
│   │   │   ├── hooks.py             # HookBus + 事件类型
│   │   │   ├── events.py            # 插件事件定义
│   │   │   ├── capabilities.py      # 能力代理
│   │   │   ├── registrar.py         # 注册事务
│   │   │   ├── backends.py          # 进程内 + Docker 后端
│   │   │   ├── runner.py            # 插件运行器（沙箱）
│   │   │   ├── rpc.py               # 插件 RPC 协议
│   │   │   ├── context.py           # 插件上下文
│   │   │   ├── decorators.py        # 插件装饰器
│   │   │   └── base.py              # 插件基类
│   │   │
│   │   ├── subagent/                # 子Agent 系统
│   │   │   ├── manager.py           # SubAgentManager（SQLite 任务 DAG）
│   │   │   ├── runtime.py           # SubAgentRuntime + 工厂
│   │   │   ├── repository.py        # TaskGraphRepository（SQLite）
│   │   │   ├── profiles.py          # ProfileToolRegistryFactory + profiles
│   │   │   ├── models.py            # 子Agent 数据模型
│   │   │   ├── context.py           # 子Agent 上下文
│   │   │   └── events.py            # 完成事件
│   │   │
│   │   ├── proactive/               # 主动循环
│   │   │   ├── loop.py              # ProactiveLoop（周期性 tick）
│   │   │   ├── sensor.py            # Sensor（状态观察）
│   │   │   ├── decision.py          # Decision（是否行动）
│   │   │   └── state.py             # 主动状态
│   │   │
│   │   └── mcp/                     # MCP 客户端集成
│   │       ├── client.py            # MCP 客户端（stdio 传输）
│   │       ├── registry.py          # MCP 工具注册
│   │       └── tool.py              # MCP 工具适配器
│   │
│   ├── bus/                         # 消息与事件基础设施
│   │   ├── queue.py                 # MessageBus（入站/出站队列）
│   │   ├── events.py                # InboundMessage, OutboundMessage
│   │   └── event_bus.py             # 内部事件总线
│   │
│   ├── channels/                    # 外部通道
│   │   ├── cli.py                   # CLI 通道（stdin/stdout）
│   │   ├── contract.py              # Channel 协议
│   │   └── ipc.py                   # IPC 通道
│   │
│   ├── plugins/                     # 内置插件
│   │   ├── memory_default/          # 观察者插件（TURN_AFTER）
│   │   └── shell_safety/            # 策略插件（TOOL_BEFORE）
│   │
│   └── skills/                      # Agent 技能定义（占位）
│
├── benchmarks/                      # 基准测试工具
│   ├── run.py                       # CLI 入口
│   ├── config.py                    # 基准测试配置
│   ├── memory_evaluation.py         # 记忆评估运行器
│   ├── agents/                      # Agent 适配器（memoli, http, cli, python）
│   ├── datasets/                    # 数据集适配器（LoCoMo, LongMemEval）
│   ├── metrics/                     # 指标计算
│   ├── reports/                     # 报告生成
│   └── config.*.toml               # 各数据集配置
│
├── tests/                           # 24 个测试文件
│   ├── fixtures/plugins/            # 测试插件夹具
│   └── test_*.py                    # 各模块测试
│
├── docs/                            # 文档
│   ├── architecture/                # 架构设计文档
│   ├── systems/                     # 各子系统文档
│   ├── benchmarks/                  # 基准测试文档
│   └── development/                 # 开发规范与路线图
│
├── openspec/                        # 规范驱动开发
│   ├── specs/                       # 9 个规范定义
│   └── changes/                     # 变更提案与归档
│
├── docker/                          # Docker 支持
│   └── plugin-runner/               # 沙箱插件运行镜像
│
└── workspace/                       # 运行时数据（gitignored）
    ├── memory.db                    # SQLite 记忆数据库
    ├── trajectories.db              # 轨迹事件日志
    ├── working-state.db             # 工作状态
    ├── subagents/task-graph.db      # 子Agent 任务图
    └── memory/                      # Legacy markdown 记忆文件
```

---

## 三、核心架构

### 3.1 数据流总览

```
用户输入 (CLI/IPC)
      │
      ▼
  ┌─────────┐    InboundMessage     ┌────────────┐
  │ Channel  │ ──────────────────▶  │ MessageBus │
  │ (CLI/IPC)│                      │  (asyncio) │
  └─────────┘                      └─────┬──────┘
                                         │
                                         ▼
                                  ┌────────────┐
                                  │ AgentLoop   │  (异步消息泵)
                                  └─────┬──────┘
                                         │
                                         ▼
                                  ┌────────────┐
                                  │AgentRunner │  (路由到 pipeline)
                                  └─────┬──────┘
                                         │
                                         ▼
                           ┌─────────────────────────┐
                           │  PassiveTurnPipeline     │  (6 阶段)
                           │  1. BeforeTurn           │
                           │  2. BeforeReasoning      │
                           │  3. PromptRender         │
                           │  4. Reasoner             │
                           │  5. AfterReasoning       │
                           │  6. AfterTurn            │
                           └────────────┬────────────┘
                                        │
                          ┌─────────────┼─────────────┐
                          ▼             ▼              ▼
                    ┌──────────┐ ┌──────────┐  ┌────────────┐
                    │ LLM      │ │ Tools    │  │ Memory     │
                    │ Provider │ │ Registry │  │ Runtime    │
                    │(OpenAI/  │ │ (9+ 工具)│  │ (SQLite    │
                    │ Echo)    │ │          │  │  claims/   │
                    └──────────┘ └──────────┘  │  cards)    │
                                               └────────────┘
```

### 3.2 组件装配顺序（`bootstrap/app.py` — `build_app_runtime()`）

1. **MessageBus** — 两个 asyncio.Queue（入站/出站）
2. **TrajectoryStore** — SQLite append-only 事件日志
3. **MemoryRuntime** — embedding + hybrid retriever + card builder + trajectory indexer
4. **LLM Provider** — OpenAI-compatible（stdlib urllib，线程池运行）或 EchoProvider 回退
5. **HookBus** — 插件事件调度
6. **WorkingState** — SQLite 工作记忆 + revision 追踪
7. **ToolRegistry** — 9 个内置工具 + 条件工具
8. **SubAgentManager** — SQLite 任务 DAG，信号量并发控制
9. **PluginManager** — manifest-first 加载，生命周期 hooks
10. **Reasoner** — 核心推理循环
11. **SessionManager** — 按会话消息历史
12. **ContextBuilder** — 组装 system prompt → memory block → working block → history → user message
13. **PassiveTurnPipeline** — 6 阶段 turn 处理
14. **AgentRunner** — 路由入站消息到 pipeline
15. **AgentLoop** — 异步消息泵
16. **ProactiveLoop** — 周期性主动检查
17. **MCPManager** — 外部 MCP 服务器连接

---

## 四、核心子系统详解

### 4.1 推理循环（Reasoner）

**文件**: `memoli_agent/agent/core/reasoner.py`（~914 行）

**核心机制**：有界串行模型/工具循环
- **三种终止条件**：
  - `max_iterations`（默认 12）— 迭代次数上限
  - `max_elapsed_seconds`（默认 300）— 时间预算
  - `no_progress_limit`（默认 3）— 连续相同工具调用检测
- **完成重试**：空响应或 `finish_reason="length"` 时自动重试
- **回退 Provider**：主 LLM 失败时回退到 EchoProvider
- **进度指纹**：通过哈希工具调用模式检测 Agent 是否陷入循环
- **轨迹优先**：工具意图必须在执行前记录；轨迹写入失败则终止操作

**终止原因枚举**：
- `COMPLETED` — 正常完成
- `NEEDS_USER` — 需要用户决策（ask_user 工具触发）
- `FAILED` — 模型错误或无进度
- `BUDGET_EXHAUSTED` — 迭代/时间预算耗尽

### 4.2 6 阶段 PassiveTurnPipeline

**文件**: `memoli_agent/agent/core/passive_turn.py`

每条用户消息经历 6 个阶段：

| 阶段 | 职责 | Hook 集成 |
|------|------|-----------|
| 1. BeforeTurn | 会话初始化、TURN_BEFORE hook | ✅ |
| 2. BeforeReasoning | 记忆预召回（pre_recall） | ✅ |
| 3. PromptRender | ContextBuilder 渲染 prompt | ✅ |
| 4. Reasoner | 核心模型/工具循环 | ✅ |
| 5. AfterReasoning | 整理、轨迹 Episode 投影 | ✅ |
| 6. AfterTurn | 最终 hooks、维护 tick | ✅ |

### 4.3 长期记忆系统

**三层实体**：

| 实体 | 描述 | 特性 |
|------|------|------|
| **Claim** | 原子事实 | append-only、内容哈希去重、scope/sensitivity/explicitness、有效时间范围、证据引用 |
| **Card** | 版本化摘要 | 从 claims 自动投影、代表用户画像/项目信息、核心卡片始终注入 prompt |
| **Episode** | 轨迹片段 | 从已完成 trace 派生、包含上下文前缀用于消歧 |

**混合 RRF 检索**（`hybrid.py`）：
- **关键词通道**：FTS5 全文检索（不可用时降级为 LIKE）
- **语义通道**：Embedding 余弦相似度（默认关闭）
- **元数据通道**：核心卡片 + 按重要性排序的 claims
- **RRF 公式**：`score = Σ weight / (k + rank)`，可配置 `rrf_k=60`
- **类型配额**：card_limit=2, claim_limit=5, episode_limit=2
- **溢出顺序**：claim → card → episode

**记忆生命周期状态**：`candidate → active → approved → frozen → superseded → rejected → deleted`

**治理规则**：所有变更必须关联显式用户证据。助手推断不能直接写入正式记忆。

**离线整理**（`consolidator.py`）：处理未 claim 的轨迹，提取候选并绑定证据，幂等性通过批次键保证。

**卡片自动投影**（`cards.py`）：确定性卡片构建器，从符合条件的 claims 创建卡片，验证每条卡片陈述都有 claim 支撑。

**语义索引**（`semantic.py`）：可选远程嵌入，带任务队列、退避和内容寻址向量存储。

### 4.4 轨迹可观测性

**文件**: `memoli_agent/agent/trajectory.py`（~811 行）

OpenTelemetry 兼容的 trace/span/event 系统：
- **Trace**：顶层对话轮次
- **Span**：5 种类型 — AGENT, LLM, TOOL, MEMORY, GUARDRAIL
- **Event**：`model_requested`, `model_responded`, `tool_intent_recorded`, `tool_finished`, `trace_started`, `trace_finished` 等
- **内容捕获模式**：metadata-only / redacted / full-local
- **Payload 存储**：内联（<64KB）/ blob（zlib 压缩）/ 外置文件（>4MB）
- **敏感键脱敏**：api_key, authorization, cookie, password, secret, token
- **隐藏推理键**：reasoning, thinking, chain_of_thought

### 4.5 工作记忆 / Checkpoint

**文件**: `memoli_agent/agent/working/`

两层状态管理：
- **软状态**（Agent 维护）：`WorkingCheckpoint` — objective, current_step, next_action, key_info, related_sop, constraints, decisions, artifacts
- **硬状态**（运行时投影）：`RuntimeStatus` — iteration, elapsed, last_tool, artifacts
- 渲染为 `<agent_status>` XML 块注入模型上下文
- **乐观并发**：基于 revision 的冲突检测

### 4.6 子Agent 任务 DAG

**文件**: `memoli_agent/agent/subagent/`

SQLite 持久化任务编排：
- **任务生命周期**：`PENDING → RUNNABLE → RUNNING → COMPLETED/FAILED/CANCELLED/INTERRUPTED`
- **依赖调度**：DAG + 循环检测，依赖完成自动转换到 RUNNABLE
- **Profile**：`general`, `research`, `coding`，不同工具访问权限
- **后台执行**：`spawn_background()` 立即返回 task_id，完成时发布 InboundMessage
- **深度限制**：可配置最大深度

### 4.7 插件系统

**文件**: `memoli_agent/agent/plugins/`

**10 个 Hook 点**：
`RUNTIME_START`, `TURN_BEFORE`, `CONTEXT_CONTRIBUTE`, `MODEL_BEFORE`, `MODEL_AFTER`, `TOOL_BEFORE`, `TOOL_AFTER`, `RESPONSE_TRANSFORM`, `TURN_AFTER`, `RUNTIME_STOP`

**三种 Hook 类型**：
- **Transformer**：修改事件/载荷（如 prompt 增强）
- **Policy**：允许/拒绝/改写/要求确认（错误时 fail-closed）
- **Observer**：仅观察副作用（错误不影响主流程）

**内置插件**：
- `memory_default`：观察者插件，观察 TURN_AFTER
- `shell_safety`：策略插件，TOOL_BEFORE 阶段阻止文件工具访问隐藏路径、绝对路径、`..`、`~`

### 4.8 主动循环

**文件**: `memoli_agent/agent/proactive/`

定时器驱动的 sensor → decision → action 循环：
- **Sensor**：读取最小状态（时间、tick 数、记忆启用状态）
- **Decision**：基于冷却时间的保守逻辑
- 注入 `InboundMessage` 到 bus，触发完整 agent pipeline

### 4.9 MCP 集成

**文件**: `memoli_agent/agent/mcp/`

- **Client**：基于 stdio 的 MCP 客户端
- **工具注册**：外部工具以 `mcp__{server}__{tool}` 命名注册
- **多服务器**：`MCPClientManager` 同时连接多个 MCP 服务器

---

## 五、工具清单

### 默认 9 个工具（始终注册）

| 工具 | 描述 |
|------|------|
| `code_run` | 在子进程中执行 Python/PowerShell，带超时、网络检测、输出截断 |
| `file_read` | 读取 workspace 文件，支持行分页（max 2000 行, 15000 字符） |
| `file_patch` | 精确唯一匹配文本替换 |
| `file_write` | 创建/覆盖/追加/前插 workspace 文件 |
| `update_working_checkpoint` | Patch 式 checkpoint 更新，带 revision 冲突检测 |
| `ask_user` | 暂停执行向用户提问（设置 needs_user 标志） |
| `start_long_term_update` | 创建待处理的长期整理请求 |
| `time` | 返回本地和 UTC 时间 |
| `memory_recall` | 混合检索，支持 query, types, scope, status, sensitivity, 时间过滤 |

### 条件注册工具

| 工具 | 条件 | 描述 |
|------|------|------|
| `memory_manage` | `memory_manage_enabled=true` | 完整治理：remember/correct/freeze/forget/list/export |
| `spawn_subagent` | `subagent_tool_enabled=true` | 委派结构化任务 |
| `manage_subagent` | `subagent_tool_enabled=true` | list/get/cancel/resume/regenerate 子Agent 任务 |
| `web_scan` | `browser_enabled=true` + adapter | 获取简化页面内容和标签页列表 |
| `web_execute_js` | `browser_enabled=true` + adapter | 在当前页面执行 JavaScript |
| `mcp__{server}__{tool}` | MCP enabled | 从 MCP 服务器发现的工具 |

---

## 六、配置体系

### 6.1 配置文件层次

| 文件 | 用途 |
|------|------|
| `config.toml` | 当前本地配置（当前使用 DeepSeek v4 Flash） |
| `config.example.toml` | 完整参考配置（含所有选项） |
| `config.benchmark.toml` | 基准测试专用配置 |
| `.env.example` | 环境变量参考 |

### 6.2 配置段

| 段 | 关键字段 |
|------|------|
| `[runtime]` | workspace |
| `[llm]` | provider, model, api_key, base_url |
| `[agent]` | name, max_iterations, max_elapsed_seconds, no_progress_limit, history_window |
| `[trajectory]` | enabled, database, capture_content, payload 限制 |
| `[memory]` | enabled, engine, auto_recall, card/recall 限制, consolidation, legacy_import |
| `[memory.embedding]` | disabled by default, openai-compatible provider |
| `[memory.hybrid]` | rrf_k, keyword_weight, semantic_weight, metadata_weight |
| `[working_memory]` | enabled, database, max_chars, stale_policy |
| `[tools]` | tool_search, code timeout/output, file limits, browser/subagent/memory_manage 开关 |
| `[plugins]` | enabled list, sandbox config, hook_deadline_seconds, trusted/force_sandbox |
| `[subagent]` | enabled, default_profile, max_concurrent, profiles |
| `[proactive]` | enabled, interval_seconds, cooldown_seconds |
| `[mcp]` | enabled, servers list |

### 6.3 环境变量

| 变量 | 用途 |
|------|------|
| `MEMOLI_CONFIG` | 配置文件路径 |
| `MEMOLI_WORKSPACE` | 工作目录 |
| `MEMOLI_LLM_API_KEY` | LLM API 密钥 |
| `MEMOLI_LLM_BASE_URL` | LLM API 基础 URL |
| `MEMOLI_EMBEDDING_API_KEY` | 语义嵌入 API 密钥 |

---

## 七、数据模型

### 7.1 记忆 Schema（SQLite, version 2）

- `claims` — append-only 原子事实，content_hash 去重
- `claim_relations` — supports/corrects/contradicts/supersedes/derived-from 关系
- `cards` + `card_versions` — 版本化卡片摘要
- `card_claim_relations` — 卡片与 claim 的关联
- `trajectory_segments` — 轨迹片段
- `claim_search` — FTS5 虚拟表
- `memory_index_jobs` — 语义索引队列
- `semantic_index` — 内容寻址向量存储
- `projection_jobs` — 卡片自动投影队列
- `consolidation_runs` — 离线整理批次追踪

### 7.2 轨迹 Schema（SQLite, version 1）

- `trajectory_meta` — Schema 版本
- `payloads` — 内容寻址存储（inline/zlib/external）
- `traces` — 顶层对话记录
- `spans` — AGENT/LLM/TOOL/MEMORY/GUARDRAIL spans
- `events` — 有序事件序列

### 7.3 子Agent Schema（SQLite, version 2）

- `agent_tasks` — 完整任务记录
- `task_edges` — DAG 依赖边
- `agent_messages` — Agent 间通信
- `agent_artifacts` — 生成的产物（SHA256）
- `task_attempts` — 执行尝试历史
- `task_state_log` — 状态转换审计

### 7.4 工作记忆 Schema（SQLite, version 1）

- `working_checkpoints` — 当前软状态
- `working_revisions` — 乐观并发 revision 日志

---

## 八、关键设计原则

1. **轨迹优先**：工具意图必须在执行前记录。轨迹写入失败则终止一切操作。
2. **证据化记忆**：无隐式事实。所有记忆必须关联显式用户证据或已批准的离线主体。
3. **Append-only Claims**：更正是新 claim + 关系，而非修改旧 claim。完整审计链。
4. **Fail-closed 策略**：插件策略错误拒绝操作。Observer 错误仅记录不阻塞。
5. **Workspace 限制**：所有文件操作限制在 workspace 目录。越界符号链接/junction 被拒绝。
6. **候选式整理**：离线记忆提取只产生候选，不自动提升为正式记忆。
7. **Manifest 驱动插件**：插件能力声明、验证、约束，事务性注册。
8. **OpenSpec 工作流**：规范是行为真相源。变更通过 propose → apply → archive 生命周期。

---

## 九、基准测试系统

支持 LoCoMo 和 LongMemEval 数据集：
- **Agent 适配器**：Memoli, HTTP, CLI, Python import
- **数据集适配器**：LoCoMo, LongMemEval（S/M/Oracle）
- **指标计算**：LoCoMo 专用指标
- **报告生成**：Markdown 报告

---

## 十、测试覆盖

24 个测试文件，覆盖以下模块：

| 测试文件 | 覆盖模块 |
|----------|----------|
| `test_reasoner_loop` | 多工具轮次、needs_user 终止、provider fallback、完成重试、迭代预算、无进度检测 |
| `test_generic_tools` | FileRead/FileWrite/FilePatch/CodeRun |
| `test_trajectory_store` | Trace/span/event 记录、payload 存储、内容脱敏、JSONL 导出 |
| `test_evidence_memory` | Claim 追加+证据、去重、Card 投影、生命周期 |
| `test_memory_hybrid_indexing` | 三通道 RRF、FTS5 fallback、类型配额、溢出 |
| `test_subagent_graph` | 任务 DAG、依赖调度、循环检测、状态转换、cancel/resume |
| `test_plugin_*` | HookBus、PluginManager、Sandbox、RPC、Manifest、Capabilities |
| `test_dynamic_working_status` | Working checkpoint CRUD、revision 冲突、运行时状态投影 |
| `test_runtime_config` | 配置加载、验证、默认值 |
| `test_benchmark_*` | 基准测试适配器、数据集、指标、运行器 |
