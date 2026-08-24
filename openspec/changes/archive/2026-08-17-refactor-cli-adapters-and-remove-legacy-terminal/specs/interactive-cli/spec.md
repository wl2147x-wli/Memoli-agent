## MODIFIED Requirements

### Requirement: Interactive terminal with deterministic fallback

系统 SHALL 在交互式 TTY 中提供增强 CLI，并 SHALL 在 stdin/stdout 非 TTY、终端能力不足或增强输入初始化失败时使用行为兼容的纯文本模式；两种模式 SHALL 共享本地命令、消息提交、串行排队、取消和最终结果语义，plain 模式 SHALL 仅降级终端表现能力。

#### Scenario: Interactive terminal is available

- **WHEN** 用户在支持的 TTY 中执行 `memoli` 或 `memoli chat`
- **THEN** 系统 SHALL 启动支持逐键输入、补全和安全异步重绘的交互式终端
- **AND** SHALL 保持现有 Runtime、session key 和串行 Agent Loop 语义

#### Scenario: Input is piped or redirected

- **WHEN** stdin 或 stdout 不是 TTY
- **THEN** 系统 SHALL 自动使用 plain CLI 并按输入顺序输出最终回复
- **AND** SHALL NOT 输出光标控制序列、候选面板或交互动画

#### Scenario: Enhanced terminal initialization fails

- **WHEN** prompt toolkit、终端模式或颜色能力无法安全初始化
- **THEN** 系统 SHALL 输出有界诊断并降级到 plain CLI
- **AND** SHALL NOT 因表现层故障阻止 Agent Runtime 启动

#### Scenario: Same command is submitted in either terminal mode

- **WHEN** 用户在 interactive 或 plain 模式提交同一个本地命令
- **THEN** 系统 SHALL 使用同一命令定义、可用性判断和只读 Runtime 投影
- **AND** SHALL NOT 因终端模式不同而调用 LLM、写入普通 Session 或产生被动 turn 轨迹

#### Scenario: Same prompt is submitted in either terminal mode

- **WHEN** interactive 或 plain 模式接受相同普通提示
- **THEN** 系统 SHALL 通过同一有界提交边界发布一条 InboundMessage
- **AND** 最终 Outbound、trace 关联、排队顺序和错误分类 SHALL 保持等价
