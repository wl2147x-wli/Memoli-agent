# Memoli-agent

Memoli-agent 是一个面向长期会话、证据化记忆和持续任务的本地 Agent 运行时。
项目已经具备分层上下文编译、OpenAI/Anthropic Provider、严格工具合同、SQLite
长期记忆、离线记忆治理、版本化 Skill、插件、持久 SubAgent、Proactive Loop、
MCP 接入和可回放运行轨迹。

当前可观察行为以 `openspec/specs/` 为事实源；README 用于快速启动和能力导航，
详细边界与内部设计以 [系统文档](docs/README.md) 为准。

## 项目结构

```text
Memoli-agent/
  main.py                  # 兼容启动入口
  memoli_agent/            # Agent 运行时源码
    agent/
      context_management/ # 分层上下文、压缩、快照和 Tool Disclosure
      core/                # Reasoner 与有界 Agent Loop
      memory/              # 记忆存储、检索、离线学习和治理
      tools/               # 内置工具及统一 ToolRegistry
    bootstrap/             # 配置加载和运行时装配
    bus/                   # 消息与事件总线
    channels/              # 外部消息通道
    plugins/               # 内置插件
  benchmarks/              # 评测运行器、适配器和任务配置
  tests/                   # 自动化测试
  docs/                    # 架构、开发、系统及评测文档
  openspec/                # 当前行为规格与拟议变更（事实源）
  docker/code-runner/      # code_run 容器镜像
  config.example.toml      # 常规运行配置样例
  config.benchmark.toml    # 评测运行时配置
  pyproject.toml           # 项目元数据、依赖和工具配置
```

完整文档导航见 [docs/README.md](docs/README.md)。

## OpenSpec 开发

项目使用 OpenSpec 管理当前能力和后续设计。`openspec/specs/` 是当前可观察
行为的事实源；新功能、行为修复、兼容性变化和非平凡重构应先创建 change，
评审规格与设计后再实现，验证通过后归档。

```text
/opsx:propose <change-name>
/opsx:apply <change-name>
/opsx:archive <change-name>
```

查看和校验规格：

```powershell
openspec list --specs
openspec validate --all --strict
```

完整约定见 [OpenSpec 开发工作流](docs/development/openspec-workflow.md)。

## 安装

要求 Python 3.11 或更高版本。

Windows PowerShell 推荐使用独立 Conda 环境：

```powershell
conda create -n memoli python=3.11 -y
conda activate memoli
python -m pip install -e ".[dev]"
```

不使用 Conda 时也可以直接安装：

```powershell
python -m pip install -e .
```

安装测试、代码检查和类型检查工具：

```powershell
python -m pip install -e ".[dev]"
```

项目依赖统一由 `pyproject.toml` 管理。

## 配置与运行

复制配置样例并启动：

```powershell
Copy-Item config.example.toml config.toml
memoli
```

示例配置默认使用不联网的 `EchoProvider`，用于验证 CLI 和本地运行时。接入正式模型
时，在 `config.toml` 中选择 `openai`、`anthropic` 或 `openai-compatible`，并通过
环境变量提供密钥；不要把真实密钥写入仓库。

`memoli` 无参数时启动前台 CLI 对话；`memoli chat` 是等价的显式写法。
可以用公共参数选择配置、工作目录和本地会话：

```powershell
memoli --config config.toml --workspace workspace --session local
memoli chat --config config.toml --session research
```

交互式 TTY 默认启用逐键编辑、进程内历史、Rich Markdown、模型流式输出、底部
状态栏和 `/` 命令面板。输入 `/` 后可用方向键选择、Tab 补全、Enter 提交、Esc
关闭面板；Alt+Enter 或 Esc+Enter 插入换行。Ctrl+C 在任务运行时等价于 `/stop`，
空闲时清空输入；空缓冲区 Ctrl+D 正常退出。输入仍串行进入 Agent Loop，运行中
可以继续排队，队列达到配置上限后会拒绝新的普通消息。

本地斜杠命令不会调用模型，也不会写入普通 Session 消息或被动 turn 轨迹：

```text
/help        查看命令帮助
/status      查看非敏感 Runtime 配置摘要
/checkpoint 查看当前会话工作 checkpoint（/working 为别名）
/trace       查看当前会话最近一个 trace id
/clear       创建新 conversation epoch，并重置当前会话派生上下文
/stop        只停止当前 turn，不退出 Runtime
/workspace   查看当前工作目录（首版只读）
/model       查看 Provider、模型与 streaming 状态（首版只读）
/tools       查看可用工具（首版只读）
/memory      查看记忆状态；也用于候选审核和失败恢复
/skills      查看 Skill catalog 可用状态（不会加载 Skill）
/context     查看 epoch、分层预算、压缩、frontier、outbox 和熔断诊断
/exit        退出（/quit 为别名）
//text       将 /text 作为普通消息发送给模型
```

`/clear` 不删除长期记忆、原始轨迹、受管 payload 或 working checkpoint。记忆候选审核
要求显式确认，并使用 revision 防止批准过期版本：

```text
/memory candidates
/memory show <candidate-id>
/memory approve <candidate-id> <revision> confirm
/memory reject <candidate-id> <revision> confirm
/memory recovery
/memory retry-job <job-id> confirm
/memory retry-request <request-id> confirm
/memory suppress-request <request-id> confirm
```

stdin/stdout 被管道或重定向、增强终端初始化失败，或设置
`channels.cli.interactive = false` 时自动使用无 ANSI/动画的 plain CLI。设置
`NO_COLOR=1` 可关闭颜色。正式 Provider 默认 `llm.stream = true`；需要一次性输出时
显式设置 `llm.stream = false`。Echo Provider 即使默认配置为 true 也会按能力自动
使用非流式调用。

plain CLI 不是另一套旧终端实现：interactive 与 plain 共用同一个命令注册表、
`CLIController`、排队/取消边界和 renderer 状态机。plain adapter 只降级逐键编辑、
候选面板、颜色与动画，因此管道和 CI 行为不会与交互模式产生两套业务语义。

无需启动 Provider、插件、MCP 或 Agent Loop，即可离线只读查询已保存的工作状态：

```powershell
memoli checkpoint --config config.toml --session research
memoli checkpoint --config config.toml --session research --json
```

离线查询不会创建数据库，也不会恢复或更新 checkpoint。没有记录或功能关闭时
返回退出码 `3`，存储读取失败返回 `1`。旧入口仍兼容，并委托给同一套 CLI 生命周期：

```powershell
python main.py --config config.toml --session local
```

`config.toml`、`.env`、`workspace/` 和 `logs/` 是本地运行内容，不应提交。
没有 `config.toml` 时，Agent 显式使用 `EchoProvider`；一旦选择正式 Provider，
缺少 API key 会快速失败。OpenAI、Anthropic 和 OpenAI-compatible 服务均通过
`config.toml` 配置，详见 [LLM Providers](docs/systems/llm-providers.md)。

## 记忆启用边界

示例配置默认开启长期记忆存储与自动召回，但关闭离线提取和语义 Embedding：

- `[memory].enabled = true`：启用 SQLite 记忆库和在线召回。
- `[memory].consolidation_enabled = false`：不启动离线 Consolidation Worker。
- `[memory.embedding].enabled = false`：混合检索仍可使用 FTS、Pattern 和 metadata lane。
- `[memory.offline.extractor].provider = "disabled"`：不会从普通对话自动提取候选记忆。

要启用完整离线学习，需要同时开启 consolidation、配置有效 Extractor，并根据需要
开启自动扫描；治理阶段使用内部 `memory-governor` SubAgent，只绑定治理专用工具，
不会把治理工具暴露给主 Agent。候选记忆不会绕过 Policy Gate 自动成为正式记忆，
需要满足自动批准策略或由用户通过 `/memory` 明确审核。详细配置见
[记忆系统](docs/systems/memory.md)。

## 核心能力

- 上下文系统：以 `(session_key, conversation_epoch)` 冻结稳定快照，按 token 预算
  编译 system、Skill、记忆、working state、历史 turn、archive frontier 和工具 schema；
  支持 soft/hard/emergency 多层压缩、恢复诊断和 fail-closed 能力撤销。
- 工具系统：异步 `Tool` 协议与 `ToolRegistry`，在执行前按 JSON Schema Draft
  2020-12 统一校验参数，安全 Hook 改写后再次校验。`code_run` 只声明当前 runner
  实际支持的语言；设置 `code_runner = "disabled"` 时不注册该工具。
- 渐进工具披露：可选 `tool_search` 将完整 schema 持久化到当前 Session/Epoch 的
  Disclosure Ledger，下一轮 Provider 请求才获得并授权执行；其他会话不会继承，
  未披露工具不能靠猜测名称调用。
- Agent Runtime：有边界的串行模型/工具循环，以及可查询、可导出的 SQLite 完整运行轨迹。
- LLM Providers：OpenAI Chat Completions、OpenAI-compatible 与 Anthropic
  Messages 原生异步 Adapter、流式事件、能力路由、有界重试和真实模型 fallback。
- 记忆系统：独立 working state、Claim/Evidence/Card/Episode 分层存储，FTS、Pattern、
  semantic、metadata 多 lane 召回与加权 RRF/MMR 融合，Card 优先检索和按需
  Claim/Evidence 展开；离线候选经租约、重试、治理 SubAgent 和用户审核闭环进入正式记忆。
- 插件系统：生命周期 Hook、工具执行前 Hook 和内置安全插件。
- SubAgent：SQLite 持久化 Agent Tree/Task DAG、受限工具循环、依赖调度、取消恢复及完成事件回流。
- Skill Runtime：SQLite 不可变版本治理、Session 快照 Catalog、只读渐进加载和可审计使用事件。
- Proactive：可配置的主动检查循环。
- MCP：通过 stdio 接入外部 MCP Server，并注册为统一工具。

各能力的配置和限制见 [系统文档](docs/systems/)。

## 评测

评测配置位于 `benchmarks/`。数据集路径默认按项目同级目录解析，例如
`../locomo/` 和 `../LongMemEval/`；可按本机数据集位置调整。

```powershell
python -m benchmarks.run --config benchmarks/config.locomo.toml
```

详见 [评测架构](docs/benchmarks/architecture.md) 和
[评测配置](docs/benchmarks/configuration.md)。

## 开发验证

```powershell
python -m pytest -q
python -m ruff check memoli_agent benchmarks tests
python -m pyright
openspec validate --all --strict
```

行为变化必须先通过 OpenSpec change 描述、实现和验证；完成后同步主规格并归档。
