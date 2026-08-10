## ADDED Requirements

### Requirement: Isolated subagent execution context

每个 SubAgent SHALL 具有独立上下文、工具 allowlist、预算、取消信号和任务状态，并仅接收完成其任务所需的信息。

#### Scenario: Research subagent lacks write permission

- **WHEN** research profile 尝试调用写入工具
- **THEN** 系统 SHALL 拒绝调用并在结构化结果中报告权限失败

### Requirement: Structured delegation result

SubAgent SHALL 返回状态、结论、证据引用、产生的 artifacts、未解决问题、预算使用和错误，而不是只返回自由文本。

#### Scenario: Reviewer reports success

- **WHEN** Reviewer SubAgent 声称任务通过
- **THEN** 结果 SHALL 包含测试、状态检查、截图或其他外部验证证据

### Requirement: Delegation control

系统 SHALL 支持查询、取消和等待 SubAgent，并限制递归委派深度、并发和总预算。

#### Scenario: Delegation exceeds depth limit

- **WHEN** SubAgent 尝试创建超过允许深度的新 SubAgent
- **THEN** 系统 SHALL 拒绝委派并保留父任务可继续处理的错误结果
