# Memoli-agent

Memoli-agent 是一个面向长期记忆、自我沉淀和可插拔评测的 Agent 运行时。
项目已具备消息总线、会话上下文、OpenAI-compatible Provider、工具调用、
Markdown 长期记忆、插件、SubAgent、Proactive Loop 和 MCP 接入能力。

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
  config.example.toml      # 常规运行配置样例
  config.benchmark.toml    # 评测运行时配置
  pyproject.toml           # 项目元数据、依赖和工具配置
```

完整文档导航见 [docs/README.md](docs/README.md)。

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
没有配置 API Key 时，Agent 使用 `EchoProvider`；真实模型可通过
`config.toml` 配置 OpenAI-compatible Provider。

## 核心能力

- 工具系统：时间、计算、记忆读写、工作区文件读取和工具搜索。
- 长期记忆：Markdown 存储、检索、上下文注入和对话沉淀。
- 插件系统：生命周期 Hook、工具执行前 Hook 和内置安全插件。
- SubAgent：同步或后台任务委派及完成事件回流。
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
