"""主 agent 路由器。

未来职责：

- 区分普通用户消息和内部事件。
- 将普通消息交给 PassiveTurnPipeline。
- 将 subagent completion 交给专门处理逻辑。
"""
