## Purpose

统一评测本地工具、MCP 工具检索与执行，以及 Skill 的加载、可用性、Prompt 暴露、选择、读取、遵循和任务贡献，并保留权限、并发、失败与截断等真实运行语义。

## ADDED Requirements

### Requirement: 工具候选与 schema 注入观测
系统 SHALL 记录每轮可用工具、被过滤工具、MCP 检索候选、最终注入工具、工具顺序和 schema 指纹，并 SHALL 区分静态本地工具与动态 MCP 工具。

#### Scenario: MCP 按需检索
- **WHEN** MCP 工具检索根据当前消息选择 top-k 并在运行内累加
- **THEN** 系统 MUST 记录查询指纹、候选排名、相似度、top-k、新增工具、累计注入集和回退原因

#### Scenario: schema 动态变化
- **WHEN** 工具的动态 JSON schema 与静态参数不同
- **THEN** 遥测 MUST 记录使用了哪个 schema 来源及其指纹

### Requirement: 工具选择与参数质量
评测系统 SHALL 支持为任务声明允许、必需、禁止的工具和参数断言，并 SHALL 计算工具选择准确率、必需工具召回率、参数正确率、顺序正确率和多余调用率。

#### Scenario: 必需工具未调用
- **WHEN** 黄金轨迹要求读取文件但 Agent 未调用 read
- **THEN** 任务结果 MUST 记录 required-tool miss，即使最终文本表面正确

#### Scenario: 正确工具错误参数
- **WHEN** Agent 选择正确工具但路径、查询或关键参数不满足断言
- **THEN** 系统 MUST 单独记录参数失败，不得计为完整工具成功

### Requirement: 工具执行全生命周期
系统 SHALL 对每个工具调用记录 call ID、工具名、参数指纹、开始/结束、执行时间、状态、异常类别、返回大小、截断、取消、并行组和重试/重复关系。

#### Scenario: 并行工具执行
- **WHEN** 同一轮多个工具并行执行
- **THEN** 每个 Tool Span MUST 是独立兄弟节点，并 MUST 记录同一 parallel group，不得串行伪造耗时

#### Scenario: 权限拒绝
- **WHEN** 工具调用被权限策略拒绝
- **THEN** 系统 MUST 将其分类为 permission denial，而不是工具实现失败，并记录生效权限模式

#### Scenario: 工具结果截断
- **WHEN** 工具原始结果被截断后再注入模型
- **THEN** Tool Span MUST 分别记录原始结果大小、模型可见大小和截断策略

### Requirement: 工具可靠性与循环检测指标
系统 SHALL 统计成功率、错误率、关键错误率、权限拒绝率、取消率、重复调用率、同参连续失败、恢复尝试和每成功任务工具调用数。

#### Scenario: 同参重复失败
- **WHEN** 同一工具和参数重复达到循环阈值
- **THEN** Trace MUST 标注 loop protection 触发，并将此前调用关联为一个失败簇

### Requirement: Skill 生命周期与可用性观测
系统 SHALL 记录 Skill 的发现来源、加载诊断、启用状态、Agent selection、依赖满足状态、Prompt 可见状态、文件指纹和刷新版本。

#### Scenario: Skill 已启用但依赖缺失
- **WHEN** Skill 配置启用但运行要求未满足
- **THEN** 遥测 MUST 标记 unavailable 及缺失要求类别，并记录其是否以安装提示形式进入 Prompt

#### Scenario: 自定义 Skill 覆盖内置 Skill
- **WHEN** 同名自定义 Skill 覆盖内置版本
- **THEN** Trace MUST 记录最终来源和版本指纹，不得把两个版本合并计数

### Requirement: Skill 选择、读取与遵循分层
系统 SHALL 分别记录 Skill eligible、injected、selected、definition-read、applied 和 contributed 状态；未读取定义不得直接视为 Skill 已执行。

#### Scenario: 模型读取 SKILL.md
- **WHEN** 工具轨迹读取某个已注入 Skill 的定义文件
- **THEN** 系统 MUST 关联该读取调用与 Skill，并标记 definition-read

#### Scenario: Skill 被读取但未遵循
- **WHEN** Agent 读取 Skill 后的行为违反其可测试强制步骤
- **THEN** 评测 MUST 将其标记为 adherence failure，而不是 Skill 成功

### Requirement: Skill 评测数据集
评测系统 SHALL 支持为 Skill 定义触发样例、非触发样例、必须步骤、禁止步骤、期望工件和评分器，并 SHALL 进行启用/禁用消融实验。

#### Scenario: Skill 任务消融
- **WHEN** 同一任务分别在 Skill 启用与禁用条件下运行
- **THEN** 报告 MUST 比较触发准确率、遵循度、任务成功、轨迹长度、token、延迟和产物质量

### Requirement: 工具与 Skill 内容隐私
系统 SHALL 默认仅发送参数/结果/Skill 内容的指纹、大小、类别和允许字段；路径、凭据、文件正文和工具结果正文 MUST 经过策略化脱敏。

#### Scenario: 工具参数含凭据
- **WHEN** 参数字段名或值被识别为 secret/token/key/password
- **THEN** Langfuse 载荷 MUST 用固定掩码替换，且哈希不得允许低熵原值被直接反查

