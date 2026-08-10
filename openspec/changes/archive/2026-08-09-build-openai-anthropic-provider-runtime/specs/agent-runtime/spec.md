## MODIFIED Requirements

### Requirement: Provider selection and fallback

系统 SHALL 支持显式 Echo Provider、OpenAI Chat Completions/OpenAI-compatible Provider 和 Anthropic Messages Provider；所有正式模型调用 SHALL 使用统一模型合同，并且 fallback SHALL 仅切换到显式配置、能力兼容的真实模型 Profile。

#### Scenario: OpenAI credentials are available

- **GIVEN** agent route 选择 OpenAI 或 OpenAI-compatible Profile 且所需凭证可用
- **WHEN** Agent 请求模型回复
- **THEN** 系统 SHALL 通过 OpenAI Chat Completions 协议发送规范化消息及可用工具 schema
- **AND** SHALL 将响应转换为统一模型合同

#### Scenario: Anthropic credentials are available

- **GIVEN** agent route 选择 Anthropic Profile 且所需凭证可用
- **WHEN** Agent 请求模型回复
- **THEN** 系统 SHALL 通过 Anthropic Messages 原生协议发送规范化内容块及可用工具 schema
- **AND** SHALL 将响应转换为与 OpenAI 相同的统一模型合同

#### Scenario: Real provider is temporarily unavailable

- **GIVEN** 已配置主 Provider 和至少一个能力兼容的真实 fallback Profile
- **WHEN** 主 Provider 的可重试请求在有界重试后仍失败
- **THEN** 系统 SHALL 按配置顺序尝试兼容 fallback
- **AND** 回复元数据与运行轨迹 SHALL 标识请求 Provider、实际 Provider、切换原因和尝试次数

#### Scenario: Real provider fails without fallback

- **WHEN** 正式 Provider 失败且没有显式配置的兼容 fallback
- **THEN** turn SHALL 以可观察的 Provider 错误失败
- **AND** 系统 SHALL NOT 使用 Echo 生成看似成功的回复

#### Scenario: Formal provider credentials are absent

- **WHEN** 配置显式选择 OpenAI、OpenAI-compatible 或 Anthropic，但缺少必需凭证
- **THEN** 系统 SHALL 在发出模型请求前报告配置错误
- **AND** SHALL NOT 静默使用 Echo Provider

#### Scenario: Echo provider is selected explicitly

- **WHEN** 配置文件缺失而使用内置本地默认值，或用户/测试显式选择 Echo Profile
- **THEN** 系统 SHALL 使用 Echo Provider 维持本地链路
- **AND** 响应元数据 SHALL 明确标识 Echo 而不伪装成正式模型
