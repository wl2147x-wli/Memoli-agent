## MODIFIED Requirements

### Requirement: Cache-aware context layout

Runtime SHALL 在每次 Provider 调用前按稳定静态前缀、不可变任务归档、近期完整轨迹和动态尾部的顺序编译模型可见上下文；静态安全规则 SHALL 位于插件、记忆、工具内容和压缩摘要之前，动态内容 SHALL NOT 改写稳定前缀，初始 Prompt 组合 SHALL NOT 预先复制工作状态动态块。

#### Scenario: First decision in a session is compiled

- **WHEN** Runtime 为新 Session 的首次模型决策编译上下文
- **THEN** 基础 system prompt、Session Skill catalog 和工具 schema SHALL 形成确定性稳定前缀
- **AND** 当前用户消息、相关记忆和唯一最新工作状态 SHALL 出现在具有明确来源与信任边界的后续区域

#### Scenario: Later tool decision is compiled

- **WHEN** 同一 turn 已追加 assistant tool call 和关联工具结果并准备下一次模型决策
- **THEN** Runtime SHALL 保持已有稳定前缀和完整 tool call/result 关联不变
- **AND** SHALL 在轨迹之后仅提供一个从当前 store 重建的最新 `<agent_status>`，不得保留先前或遗留工作状态副本

#### Scenario: Plugin contributes context

- **WHEN** 插件为当前 turn 贡献上下文 section
- **THEN** section SHALL 位于基础静态安全规则之后并带来源和低于 system/user 授权的信任标记
- **AND** 插件 SHALL NOT 把内容插入稳定安全前缀之前，且任何状态样式文本 SHALL NOT 替代 Runtime 重建的最新工作状态
