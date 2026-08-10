## ADDED Requirements

### Requirement: Risk-aware tool metadata

每个工具 SHALL 声明风险级别、副作用、幂等性、权限、超时、dry-run、审批和结果验证能力。

#### Scenario: Tool metadata is incomplete

- **WHEN** 具有外部副作用的工具没有风险或审批声明
- **THEN** 系统 SHALL 拒绝以无审批的低风险工具方式注册或执行它

### Requirement: Two-phase side-effect execution

不可逆或不可幂等工具 SHALL 支持预检/预览与批准后的提交，并在提交后验证最终状态。

#### Scenario: User rejects preview

- **WHEN** 用户拒绝待执行动作的预览
- **THEN** 系统 SHALL NOT 执行 commit
- **AND** SHALL 记录拒绝结果

### Requirement: Cancellation and uncertain outcomes

工具执行 SHALL 支持超时与取消语义，并在外部结果不确定时禁止盲目自动重试。

#### Scenario: External request times out after submission

- **WHEN** 工具无法确认副作用是否已发生
- **THEN** 系统 SHALL 返回 uncertain outcome
- **AND** 上层 SHALL 先查询实际状态再决定后续动作

### Requirement: Complete tool trace

每次工具调用 SHALL 记录名称、版本、参数摘要、权限决策、开始/结束时间、结果、错误和验证状态。

#### Scenario: Sensitive arguments are traced

- **WHEN** 工具参数包含配置为敏感的数据
- **THEN** trace SHALL 保存可审计的脱敏表示而非原始秘密
