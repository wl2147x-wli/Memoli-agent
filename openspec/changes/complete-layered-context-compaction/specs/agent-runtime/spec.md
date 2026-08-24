## MODIFIED Requirements

### Requirement: Session-aware passive turns

系统 SHALL 按 session key 与持久 conversation epoch 维护跨轮上下文边界，从唯一 canonical turn source 读取近期完整 turn 与 archive frontier，并通过统一生命周期生成出站消息；Session SHALL 只维护身份和瞬态控制状态，不得再以独立消息条数窗口提前删除压缩来源。

#### Scenario: User sends a CLI message

- **WHEN** 通道发布一条普通入站消息
- **THEN** 系统 SHALL 依次解析当前 epoch、读取 committed turns、查询动态上下文、规划并编译 prompt、执行推理、提交 canonical turn 并构造出站消息

#### Scenario: Conversation continues after restart

- **GIVEN** 当前 epoch 存在可读取 canonical turns 或 archive frontier
- **WHEN** Runtime 重启后同一 session key 收到新消息
- **THEN** prompt SHALL 包含受 token 预算约束的当前 frontier 与近期完整 turn
- **AND** SHALL 保持 tool correlation、最终用户可见输出和稳定顺序

#### Scenario: User clears visible conversation context

- **WHEN** 用户在没有活动 turn 时执行 `/clear`
- **THEN** Runtime SHALL 持久创建新的 conversation epoch 并重置其派生 context snapshot/frontier/preview 可见状态
- **AND** 旧轨迹、payload、长期记忆和 working-state SHALL 按各自策略保留但不得重新注入新 epoch

#### Scenario: Clear cannot persist its boundary

- **WHEN** epoch store 不可用或新 epoch 无法原子提交
- **THEN** `/clear` SHALL 报告失败并保持原 epoch 有效
- **AND** SHALL NOT 只清除内存状态后声称对话已清理

#### Scenario: Runtime has no durable context source

- **WHEN** Runtime 未启用或无法可靠读取持久 canonical turn 内容
- **THEN** 系统 SHALL 使用新的进程内完整 turn source 并显式标记不可跨重启恢复
- **AND** SHALL NOT 同时拼接旧 Session history、损坏轨迹或 metadata-only 内容

### Requirement: Unified dynamic context assembly

Runtime SHALL 在每次 Provider 调用前通过统一、缓存感知且有全局预算的 Context Plan 生成模型可见上下文；稳定基础规则和当前 epoch 冻结的 Skill/tool 前缀之后依次纳入有界 archive frontier、近期完整交互，再在动态尾部纳入个人记忆、插件扩展和唯一最新工作状态，且所有动态材料 SHALL 使用结构化来源与低权限信任边界。

#### Scenario: Initial model decision is prepared

- **WHEN** Runtime 为新的用户 turn 准备首次模型调用
- **THEN** 模型可见上下文 SHALL 包含当前用户输入、可用的冻结 Skill catalog、预算允许的核心/自动召回记忆和当前工作状态
- **AND** Skill catalog、插件、记忆、archive、工具证据和工作状态 SHALL 具有独立类型、来源、优先级与信任元数据

#### Scenario: A later tool-loop decision is prepared

- **WHEN** Skill 或通用工具结果已经提交且 Runtime 准备同一 turn 的后续模型调用
- **THEN** 模型可见上下文 SHALL 包含完整关联的工具调用/冻结结果和其后的唯一最新工作状态
- **AND** SHALL NOT 注入过期状态、重新渲染已冻结前缀或拆散工具协议消息

#### Scenario: No Skill is available

- **WHEN** Skill Runtime 关闭、降级或当前 epoch 没有可见 Skill
- **THEN** Runtime SHALL 在不伪造空 Skill 指令的情况下编译现有交互、frontier、记忆和工作状态
- **AND** 普通 Agent Loop SHALL 保持可用

#### Scenario: Context compaction is disabled

- **WHEN** 配置关闭语义压缩但仍启用统一编译与硬预算保护
- **THEN** Runtime SHALL 保持标准消息角色并只执行确定性预览、去噪和有诊断的候选选择
- **AND** 仍 SHALL 在超出硬输入预算前返回明确错误而不是发送已知无效请求

#### Scenario: SubAgent runs without durable cross-turn context

- **WHEN** memory-governor 或普通 SubAgent profile 未显式装配 durable Context Source
- **THEN** 其 Reasoner SHALL 使用隔离的本次任务上下文
- **AND** SHALL NOT 读取或修改主 Agent 的 conversation epoch、snapshot 或 archive frontier

### Requirement: Context configuration compatibility

系统 SHALL 为模型窗口、输出预留、安全余量、soft/hard 阈值、近期 tail、source reader turn/byte 上限、压缩 batch、archive frontier 总预算/节点数、preview 预算和失败上限提供可校验配置；缺少新的 `[context]` 字段时 SHALL 使用保守默认值，但已移除的 `[agent].history_window` SHALL 产生可操作迁移错误。

#### Scenario: Configuration omits new context fields

- **WHEN** 配置具有 `[context]` 或完全使用内置默认值但缺少新增 frontier/source/batch 字段
- **THEN** Runtime SHALL 使用保守默认值启动并在诊断中展示有效预算
- **AND** SHALL 保留 Memory、Working State 和 Skill 的组件候选上限作为局部保护

#### Scenario: Legacy history_window is present

- **WHEN** 配置仍包含 `[agent].history_window`
- **THEN** Runtime SHALL 在启动前返回说明该字段已移除的配置错误
- **AND** 错误 SHALL 指向 `[context]` 的 source read、recent tail 与 archive frontier 配置，不得静默忽略或继续按消息条数裁剪

#### Scenario: Context budgets are invalid

- **WHEN** 可用输入预算非正、soft threshold 不低于 hard threshold，或任何 turn/byte/token/item 上限非正或互相矛盾
- **THEN** 系统 SHALL 在发出模型请求或迁移数据库前报告配置错误
- **AND** SHALL NOT 静默禁用预算保护或语义压缩
