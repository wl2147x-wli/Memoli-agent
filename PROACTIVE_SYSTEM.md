# Proactive 系统说明

第 10 阶段实现的是最小本地主动循环，让 Memoli 可以按固定间隔检查状态，
并在需要时主动向主 AgentLoop 投递一条入站消息。

## 运行链路

```text
ProactiveLoop 定时 tick
  -> ProactiveSensor.sense()
  -> ProactiveDecision.decide()
  -> MessageBus.publish_inbound()
  -> AgentLoop
  -> CLI 输出
```

主动消息不会绕过主 agent，也不会直接打印到终端。它会作为普通
`InboundMessage` 进入主处理链路，因此仍然会经过 session、context、
memory、reasoner 和工具系统。

## 配置

默认配置如下：

```toml
[proactive]
enabled = false
interval_seconds = 60
cooldown_seconds = 300
chat_id = "local"
message = "这是一次主动检查。"
```

- `enabled`：是否启用主动循环，默认关闭。
- `interval_seconds`：tick 间隔。
- `cooldown_seconds`：两次主动发送之间的最小间隔。
- `chat_id`：主动消息投递到的会话 ID。
- `message`：主动消息内容。

## 当前限制

- 不接外部信息源。
- 不做复杂任务计划。
- 不做长期任务编排。
- 当前感知器只读取当前时间、tick 次数和记忆系统是否启用。

后续阶段可以在 `ProactiveSensor` 中加入文件变更、RSS、定时任务、
外部 API 或用户项目状态。
