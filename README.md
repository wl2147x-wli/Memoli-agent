# Memoli-agent

Memoli-agent 是一个面向长期记忆、自我沉淀和可插拔评测的 Agent 运行时。
项目已具备消息总线、会话上下文、OpenAI/Anthropic Provider、工具调用、
证据化 SQLite 长期记忆、版本化 Skill、插件、SubAgent、Proactive Loop 和 MCP 接入能力。

## 项目结构

```text
Memoli-agent/
  main.py                  # CLI 启动入口
  memoli_agent/            # Agent 运行时源码
    agent/                 # 推理、会话、工具、记忆及扩展能力
    bootstrap/             # 配置加载和运行时装配
    bus/                   # 消息与事件总线
    channels/              # 外部消息通道
    plugins/               # 内置插件
  benchmarks/              # 评测运行器、适配器和任务配置
  tests/                   # 自动化测试
  docs/                    # 架构、开发、系统及评测文档
  openspec/                # 当前行为规格与拟议变更（事实源）
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

```powershell
pip install -e .
```

安装测试、代码检查和类型检查工具：

```powershell
pip install -e ".[dev]"
```

项目依赖统一由 `pyproject.toml` 管理。

## 配置与运行

复制配置样例：

```powershell
Copy-Item config.example.toml config.toml
python main.py
```

`config.toml`、`.env`、`workspace/` 和 `logs/` 是本地运行内容，不应提交。
没有 `config.toml` 时，Agent 显式使用 `EchoProvider`；一旦选择正式 Provider，
缺少 API key 会快速失败。OpenAI、Anthropic 和 OpenAI-compatible 服务均通过
`config.toml` 配置，详见 [LLM Providers](docs/systems/llm-providers.md)。

## 核心能力

- 工具系统：参照 GenericAgent 的九个极简默认工具，覆盖代码执行、文件
  读写、工作 checkpoint、用户询问、长期整理请求、时间和记忆检索。
- Agent Runtime：有边界的串行模型/工具循环，以及可查询、可导出的 SQLite 完整运行轨迹。
- LLM Providers：OpenAI Chat Completions、OpenAI-compatible 与 Anthropic
  Messages 原生异步 Adapter、流式事件、能力路由、有界重试和真实模型 fallback。
- 记忆系统：独立工作状态、证据化 SQLite 个人记忆、关键词/向量/元数据
  RRF 混合召回、Card 自动投影和完整轨迹驱动的 Episode 索引。
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
```
