# Memoli-agent 记忆系统说明

本文档说明第七阶段引入的第一版长期记忆系统。

## 记忆目录

默认记忆目录来自 `config.toml`：

```toml
[memory]
enabled = true
engine = "markdown"
path = "workspace/memory"
```

首次启动时会自动创建：

```text
workspace/memory/
  MEMORY.md
  HISTORY.md
  RECENT_CONTEXT.md
```

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `MEMORY.md` | 保存长期事实记忆。主要由 `memory_write` 工具写入。 |
| `HISTORY.md` | 保存每轮用户输入和助手回复的对话流水。 |
| `RECENT_CONTEXT.md` | 预留给后续最近上下文摘要，目前只参与关键词检索。 |

## 运行链路

```text
用户输入
  -> BeforeReasoningPhase 查询相关长期记忆
  -> MemoryRuntime.render_prompt_block()
  -> ContextBuilder 注入 memory prompt block
  -> Reasoner 调用模型
  -> AfterReasoningPhase 记录对话流水到 HISTORY.md
```

## 工具行为

### memory_write

写入一条长期事实记忆到 `MEMORY.md`。

### memory_recall

按关键词检索 `MEMORY.md` 和 `RECENT_CONTEXT.md` 中的记忆条目。

## 当前限制

- 当前使用 Markdown 文件，不使用 SQLite、向量库或 embedding。
- 当前不自动把普通对话总结成长期事实，避免误记。
- 长期事实主要通过 `memory_write` 工具显式写入。
- 检索方式是简单关键词匹配，后续可以替换为 embedding/rerank。
