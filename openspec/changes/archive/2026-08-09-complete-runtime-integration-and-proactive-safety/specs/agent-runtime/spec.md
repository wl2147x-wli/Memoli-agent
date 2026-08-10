## ADDED Requirements

### Requirement: Verifiable end-to-end passive turn

系统 SHALL 通过可重复集成测试验证 Inbound、Session、Context、Memory、Skill、Provider、Tool、Trajectory 与 Outbound 的完整串行闭环。

#### Scenario: Deterministic end-to-end turn completes
- **WHEN** 测试 Provider 先请求工具再返回最终答案
- **THEN** 出站消息、Session 历史、工具结果和轨迹 SHALL 可由同一 trace 关联

#### Scenario: First message fails and second succeeds
- **WHEN** 同一 AgentLoop 的首条消息失败而第二条消息有效
- **THEN** 第二条消息 SHALL 仍完成并发布出站结果
