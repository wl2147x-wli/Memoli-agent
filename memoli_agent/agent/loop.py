"""主 AgentLoop。

未来职责：

- 从 MessageBus 消费入站消息。
- 创建 turn 状态。
- 调用 runner 或 passive turn pipeline。
- 发布出站消息。
- 管理 busy 状态和中断状态。
"""
