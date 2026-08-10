## MODIFIED Requirements

### Requirement: Unified dynamic context assembly

Runtime SHALL 在每次 Provider 调用前通过统一装配边界生成模型可见上下文：静态基础规则之后纳入当前 Session 稳定且有界的 Skill catalog，再依次纳入当前交互、受限会话历史、个人记忆上下文和最新工作状态；同一 Session 的静态 system 前缀和 Skill catalog SHALL 不因每轮动态状态或 active 指针变化而重写。

#### Scenario: Initial model decision is prepared

- **WHEN** Runtime 为新的用户 turn 准备首次模型调用
- **THEN** 模型可见上下文 SHALL 包含当前用户输入、可用 Skill catalog、核心记忆、自动召回结果和当前工作状态
- **AND** Skill catalog、动态数据 SHALL 使用可区分于终端用户指令和静态安全规则的边界

#### Scenario: A later tool-loop decision is prepared

- **WHEN** Skill 或通用工具结果已经提交且 Runtime 准备同一 turn 的后续模型调用
- **THEN** 模型可见上下文 SHALL 包含该工具结果和其后生成的最新工作状态
- **AND** SHALL NOT 继续注入已过期的工作状态版本或运行中重写 Session Skill catalog

#### Scenario: No Skill is available

- **WHEN** Skill Runtime 关闭、降级或当前 Session 没有可见 Skill
- **THEN** Runtime SHALL 在不伪造空 Skill 指令的情况下装配现有交互、历史、记忆和工作状态
- **AND** 普通 Agent Loop SHALL 保持可用

## ADDED Requirements

### Requirement: Skill context trust and budget separation

Runtime SHALL 将 catalog 视为 Harness 提供的路由元数据，将成功加载的 Skill 正文视为低于静态安全规则和当前用户授权的版本化程序性说明，并 SHALL 对 catalog、Skill 正文和 reference 分别应用明确预算与来源边界。

#### Scenario: Skill text requests policy override

- **WHEN** Skill 正文或 reference 包含覆盖安全规则、扩大权限或冒充当前用户授权的文本
- **THEN** Runtime SHALL 保持静态规则、工具策略和用户授权优先
- **AND** SHALL NOT 因 Skill active 或 approved 状态执行越权动作

#### Scenario: Loaded Skill exceeds content budget

- **WHEN** 绑定 Skill 正文或请求的 reference 超过配置预算
- **THEN** Runtime SHALL 拒绝加载或返回明确的有界失败结果
- **AND** SHALL NOT 静默截断关键程序性说明后将其标记为成功加载

