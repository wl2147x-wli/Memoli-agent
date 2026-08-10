## ADDED Requirements

### Requirement: Isolated turn failure

系统 SHALL 将不可恢复的单轮异常转换为结构化出站错误，并继续处理后续入站消息。

#### Scenario: One turn crashes
- **WHEN** 某条入站消息在准备轨迹、推理或发布前处理中出现不可恢复异常
- **THEN** 系统 SHALL 返回不含原始异常和秘密的错误分类
- **AND** AgentLoop SHALL 继续消费下一条消息

#### Scenario: Loop is cancelled
- **WHEN** Runtime 取消 AgentLoop
- **THEN** 系统 SHALL 传播取消并有序停止，而不是转换为普通错误回复

### Requirement: Stable tool-call correlation

一次模型响应中的每个工具调用 SHALL 在进入消息历史前获得非空稳定 ID，且执行请求、轨迹和 Tool Result SHALL 使用同一 ID。

#### Scenario: Provider omits tool call ID
- **WHEN** Provider 或测试响应返回缺少 ID 的工具调用
- **THEN** Runtime SHALL 生成一次确定性轮内 ID
- **AND** 后续所有关联记录 SHALL 复用该 ID

### Requirement: Bounded no-progress termination

系统 SHALL 对空响应、截断响应和连续全部失败的工具轮次执行有界恢复，并在无进展预算耗尽时终止。

#### Scenario: Failed tools alternate errors
- **WHEN** 连续工具轮次均无成功结果，即使错误文本或参数交替变化
- **THEN** 系统 SHALL 计入无进展预算并在阈值处停止
