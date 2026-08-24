## MODIFIED Requirements

### Requirement: Explicit serial loop outcomes
每个 turn SHALL 产生 `completed`、`needs-user`、`failed`、`budget-exhausted` 或 `cancelled` 之一的结构化终止原因，并关联稳定的 trace 标识；取消当前 turn SHALL NOT 隐式取消整个消息泵。

#### Scenario: Required user input is unavailable
- **WHEN** 工具或完成判定表明继续执行需要用户提供信息或授权
- **THEN** 系统 SHALL 以 `needs-user` 结束本次 turn
- **AND** SHALL 向用户返回明确问题而不是继续猜测执行

#### Scenario: Unrecoverable execution failure occurs
- **WHEN** Provider、工具协议或 Runtime 出现不可恢复错误
- **THEN** 系统 SHALL 以 `failed` 结束本次 turn
- **AND** 终止结果 SHALL 包含可观察的错误分类而不暴露秘密

#### Scenario: Provider fallback succeeds
- **GIVEN** 主 Provider 调用失败且现有 fallback 成功
- **WHEN** 串行循环继续或完成
- **THEN** 终止结果和运行轨迹 SHALL 标识 fallback 已被使用

#### Scenario: User cancels current turn
- **WHEN** 前台通道对活动 turn 发出用户取消请求
- **THEN** 系统 SHALL 取消该 turn 的 Provider、工具等待和后续操作并以 `cancelled` 结束
- **AND** AgentLoop SHALL 保持运行并继续消费后续排队消息

#### Scenario: Runtime cancels the message pump
- **WHEN** Runtime 关闭并取消 AgentLoop 消息泵
- **THEN** 系统 SHALL 传播控制流取消并有序停止
- **AND** SHALL NOT 将其转换为某个用户 turn 的 `cancelled` 回复

## ADDED Requirements

### Requirement: Structured safe presentation events
Runtime SHALL 为前台表现层投影结构化、有界、非权威事件，并 SHALL 将事件与 session、trace、turn 和 step 关联，而不暴露 Provider SDK 对象或隐藏内容。

#### Scenario: Turn progresses through model and tool steps
- **WHEN** turn 开始、模型产生文本、工具开始或结束、usage 更新且 turn 最终结束
- **THEN** Runtime SHALL 按发生顺序发出对应的安全事件类型与稳定关联标识
- **AND** 最终 Outbound/终止结果 SHALL 继续作为用户可见完成状态的权威来源

#### Scenario: Provider emits hidden content
- **WHEN** 原始 Provider 事件包含 reasoning、thinking 或工具参数增量
- **THEN** Runtime SHALL 在进入 presentation channel 前过滤或转换为无内容的安全阶段事件
- **AND** SHALL NOT 依赖终端 renderer 再清除秘密

#### Scenario: Presentation observer fails or lags
- **WHEN** 表现事件队列已满、观察者抛错或 renderer 消费缓慢
- **THEN** Runtime SHALL 丢弃或合并可降级表现事件并继续 Agent 行为
- **AND** 最终 Outbound、轨迹证据和工具副作用 SHALL 不受影响

### Requirement: Interactive chat streams by default
正式 Provider 支持 streaming 且用户未显式关闭时，交互式 chat SHALL 请求流式模型响应；非交互调用和显式关闭 SHALL 保持确定性一次性响应能力。

#### Scenario: Streaming-capable provider starts interactive turn
- **WHEN** TTY chat 使用声明 streaming 能力的正式 Provider 且配置未关闭 streaming
- **THEN** 每次模型请求 SHALL 启用 Provider 的流式协议并产生规范化文本/usage/工具事件
- **AND** 最终统一模型响应 SHALL 与已接收增量语义一致

#### Scenario: User explicitly disables streaming
- **WHEN** 配置设置 `llm.stream = false`
- **THEN** Runtime SHALL 使用非流式 Provider 调用并只在完成后返回统一响应
- **AND** Agent Loop、轨迹和终止判定 SHALL 保持等价

#### Scenario: Stream fails after partial output
- **WHEN** Provider 在已经产生用户可见文本或工具增量后中断
- **THEN** Runtime SHALL 将错误标识为 partial-stream 并停止透明 fallback 拼接
- **AND** SHALL 向表现层发出安全失败状态且不把部分文本宣称为完成答案

### Requirement: Isolated active-turn cancellation
AgentLoop SHALL 维护可寻址的当前 turn 取消边界，使通道可以取消活动处理而不并发执行消息、不丢失整个消息泵或错误关联后续回复。

#### Scenario: Cancellation arrives during provider request
- **WHEN** 用户停止请求发生在活动 Provider stream 中
- **THEN** Runtime SHALL 关闭 Provider stream、完成必要轨迹终止记录并释放 turn 资源
- **AND** SHALL NOT 启动 fallback 或继续工具调用

#### Scenario: Cancellation arrives during tool execution
- **WHEN** 用户停止请求发生在可取消的活动工具等待中
- **THEN** Runtime SHALL 请求取消并阻止后续模型步骤
- **AND** 对无法安全撤销的已发生副作用 SHALL 只报告真实状态而不声称回滚

#### Scenario: Queued message follows cancelled turn
- **WHEN** 当前 turn 被取消且队列中已有下一条消息
- **THEN** AgentLoop SHALL 在取消清理完成后处理下一条消息
- **AND** 下一条 Outbound SHALL 使用自己的 trace 和输入关联

