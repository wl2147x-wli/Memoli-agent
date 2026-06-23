# Memoli-agent

Memoli-agent 计划构建一个面向长期记忆、自我沉淀和可插拔评测的 agent 项目。

当前阶段是项目骨架搭建：已按 `AGENT_PROJECT_BLUEPRINT.md` 中的“推荐目录结构”生成基础文件。每个 Python 文件目前只包含模块开头注释和 TODO，不包含主要业务代码，方便后续按模块逐步实现。

## 项目目标

- 构建一个可运行、可扩展的主 agent runtime。
- 支持长期记忆、会话历史、工具调用和插件扩展。
- 后续支持 subagent、proactive loop、MCP、peer agent 等高级能力。
- 为不同记忆系统的对比、替换和评测预留清晰接口。

## 当前目录

```text
Memoli-agent/
  main.py
  config.example.toml
  requirements.txt
  pyproject.toml
  AGENT_PROJECT_BLUEPRINT.md
  memoli_agent/
    bootstrap/
    bus/
    agent/
    channels/
    plugins/
    skills/
```

## 推荐阅读

1. `AGENT_PROJECT_BLUEPRINT.md`：项目完整架构蓝图。
2. `main.py`：未来命令行入口。
3. `memoli_agent/bootstrap/app.py`：未来 runtime 装配层。
4. `memoli_agent/agent/loop.py`：未来主 agent loop。
5. `memoli_agent/agent/core/passive_turn.py`：未来一轮对话 pipeline。

## 后续实现顺序

建议按以下顺序逐步填充代码：

1. `bus`：消息类型和消息队列。
2. `config`：配置加载。
3. `provider`：LLM provider 抽象。
4. `agent loop`：主消息循环。
5. `context`：prompt/context 构建。
6. `tools`：工具协议、注册表和内置工具。
7. `memory`：长期记忆读写和检索。
8. `lifecycle`：phase 和插件 hook。
9. `plugins`：插件加载和扩展点。
10. `subagent`：任务委派和结果回流。
11. `proactive`：主动循环。
12. `MCP / peer agent`：外部能力接入。

## 当前状态

项目处于“骨架已生成，核心逻辑待实现”阶段。
