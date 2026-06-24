# Memoli-agent 项目约定

本文档记录项目第 0 阶段确定下来的基础约定。后续开发应优先遵守这些约定，除非有明确理由修改。

## 1. Python 与包结构

- Python 版本：`>=3.11`
- 主包名：`memoli_agent`
- 命令入口：`main.py`
- 配置样例：`config.example.toml`
- 本地配置：`config.toml`
- 运行时目录：`workspace/`

## 2. 配置约定

项目默认使用 TOML 配置。

必须提交：

```text
config.example.toml
```

不得提交：

```text
config.toml
.env
workspace/
logs/
```

配置优先级建议：

```text
命令行参数 > 环境变量 > config.toml > 默认值
```

## 3. 运行时数据约定

所有运行时产生的数据都应放入 `workspace/`，例如：

```text
workspace/
  sessions/
  memory/
  tasks/
  traces/
```

不要把运行时数据写入源码目录。

## 4. 模块边界约定

`main.py` 只负责入口和命令分发。

`bootstrap/` 负责装配对象，不写复杂业务逻辑。

`bus/` 负责消息和事件边界。

`agent/loop.py` 负责主循环。

`agent/core/` 负责一轮对话 pipeline 和 reasoner。

`agent/tools/` 负责工具协议、注册和执行。

`agent/memory/` 负责记忆读写、检索和沉淀。

`agent/plugins/` 负责插件系统。

`agent/subagent/` 负责子 agent 和后台任务。

`channels/` 负责外部消息通道，不直接写推理逻辑。

## 5. 开发顺序约定

推荐实现顺序：

1. `bus`
2. `config`
3. `provider`
4. `agent loop`
5. `context`
6. `tools`
7. `memory`
8. `lifecycle`
9. `plugins`
10. `subagent`
11. `proactive`
12. `MCP / peer agent`

每完成一个阶段，都要保证项目仍可运行或至少可导入。

## 6. 代码风格约定

- 先写清晰代码，再考虑抽象。
- 优先使用 dataclass 或 Pydantic 风格的数据模型。
- 模块之间通过明确的协议或服务对象通信。
- 不在工具、插件、channel 中直接访问全局状态。
- 注释解释“为什么这样做”，不要重复代码本身。

## 7. 测试约定

后续添加测试时建议使用：

```text
tests/
  test_bus.py
  test_config.py
  test_agent_loop.py
  test_tools.py
  test_memory.py
```

优先测试：

- 消息流
- 配置加载
- 工具注册和执行
- 记忆读写
- 插件加载
- subagent completion 回流

## 8. 第 0 阶段完成标准

第 0 阶段完成后，项目应具备：

- 清晰的目录骨架。
- `README.md`。
- `AGENT_PROJECT_BLUEPRINT.md`。
- `DEVELOPMENT_ROADMAP.md`。
- `PROJECT_CONVENTIONS.md`。
- `config.example.toml`。
- `.env.example`。
- `pyproject.toml`。
- `requirements.txt`。
- `.gitignore` 忽略本地配置和运行时数据。
