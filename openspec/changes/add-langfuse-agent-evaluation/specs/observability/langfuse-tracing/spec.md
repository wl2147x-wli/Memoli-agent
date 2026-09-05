## Purpose

为项目所有 Agent 运行建立统一、可选、可脱敏且不会影响业务可用性的 Langfuse 追踪契约，使模型、工具、Skill、记忆、压缩、子代理与任务结果能够在同一条可关联轨迹中被准确分析。

## ADDED Requirements

### Requirement: 可插拔且失败开放的遥测
系统 SHALL 通过统一追踪接口提供 Langfuse 实现和空实现，并 MUST 在未启用、依赖缺失、配置无效、网络失败或 Langfuse 服务不可用时继续完成原 Agent 请求。

#### Scenario: 未启用 Langfuse
- **WHEN** 遥测配置为关闭
- **THEN** 系统 MUST 使用空追踪实现，且发送给模型的请求内容、顺序和执行结果 MUST 与接入前一致

#### Scenario: Langfuse 写入失败
- **WHEN** 任一遥测创建、更新、结束或刷新操作抛出异常
- **THEN** 系统 MUST 记录脱敏告警并继续业务执行，不得把遥测异常作为 Agent、工具或任务失败

### Requirement: 标准 Trace 层级与运行关联
系统 SHALL 将每个顶层 Agent run 表示为根 Trace，并 SHALL 将 Prompt 构建、每次模型调用、工具执行、Skill 使用、记忆操作、上下文压缩和子代理运行表示为可关联的子 Observation。

#### Scenario: 多轮工具 Agent 运行
- **WHEN** 一个用户请求触发多次模型调用和多个工具调用
- **THEN** Langfuse 中 MUST 存在一个根 Trace、每次模型调用对应一个 Generation、每次工具执行对应一个 Tool Span，且父子关系与真实执行顺序一致

#### Scenario: 子代理与委托运行
- **WHEN** 父 Agent 派生子代理或委托给另一个 Agent
- **THEN** 子运行 MUST 保留自己的 run ID，并 MUST 通过父 run ID 或 trace context 关联到父运行，不得错误合并并行子代理

### Requirement: 稳定的关联标识与版本字段
系统 SHALL 为每条 Trace 和 Observation 写入稳定的运行、会话、任务、Agent、实验、变体、模型和 schema 版本标识；同一运行在本地 conversation store 与 Langfuse 中 MUST 可双向关联。

#### Scenario: 已存在本地 run 记录
- **WHEN** conversation store 已为运行创建 `run_id`
- **THEN** 遥测 MUST 复用该标识或记录明确的一对一映射，并在本地 run extras 中保存 Langfuse trace ID

#### Scenario: 数据模型升级
- **WHEN** 遥测字段或语义发生变化
- **THEN** 新事件 MUST 携带 `telemetry_schema_version`，分析器 MUST 能拒绝或显式迁移不兼容版本

### Requirement: 模型 Generation 时序
系统 SHALL 记录模型请求开始、首个 SSE 事件、首个非空 reasoning/content delta、完成、错误与取消时间，并 MUST 将 TTFT 定义为请求开始到首个非空模型输出的单调时钟耗时。

#### Scenario: 开头存在空流事件
- **WHEN** 流首先返回 role、ID、usage 或空 delta
- **THEN** 系统 MUST 等到首个非空 reasoning 或 content delta 才设置 completion start time

#### Scenario: 仅工具调用响应
- **WHEN** 模型不输出文本而首先产生有效工具调用 delta
- **THEN** 系统 SHALL 分别记录 first-model-event latency 和 text TTFT 为不可用，避免伪造文本 TTFT

### Requirement: Provider usage 规范化
系统 SHALL 保留原始 usage 的脱敏副本或摘要，并 SHALL 规范化 input、cached input、cache creation、output 和 total token；缺失字段 MUST 保持未知状态，不得默认为零。

#### Scenario: OpenAI 风格缓存字段
- **WHEN** Provider 返回 inclusive prompt tokens 和 `prompt_tokens_details.cached_tokens`
- **THEN** 系统 MUST 将 uncached input 计算为排除缓存部分后的非负值，并把缓存部分作为独立 usage 类型上报

#### Scenario: Provider 未报告缓存字段
- **WHEN** 响应只有 prompt、completion 和 total token
- **THEN** 系统 MUST 标记 `cache_observable=false` 且 cached input 为 null

#### Scenario: 流末 usage 无 choices
- **WHEN** 最后一个 SSE chunk 只有 usage 而没有 choices
- **THEN** 系统 MUST 捕获 usage 且不得因 choices 为空而丢弃该 chunk

### Requirement: 请求指纹与结构度量
系统 SHALL 对实际发送前的 system、tools、messages 和整体请求计算确定性指纹，并 SHALL 记录组成部分大小、顺序敏感哈希和规范化哈希，而不要求上传原始内容。

#### Scenario: 工具顺序变化但内容不变
- **WHEN** 两次调用包含相同工具定义但排列顺序不同
- **THEN** 顺序敏感哈希 MUST 不同，规范化内容哈希 MUST 相同

#### Scenario: 动态系统字段变化
- **WHEN** 当前时间等动态区段导致 system prompt 变化
- **THEN** system 指纹 MUST 反映变化，并 SHALL 记录可定位到区段类别的变化摘要而非原文

### Requirement: 隐私、脱敏与大小限制
系统 SHALL 默认不上传 API 密钥、认证头、环境变量、完整文件内容、完整工具结果和用户敏感正文，并 SHALL 支持内容关闭、字段脱敏、哈希化、截断和自定义 mask。

#### Scenario: 默认评测配置
- **WHEN** 用户未显式允许内容采集
- **THEN** 遥测 input/output MUST 仅包含摘要、长度、类型和指纹，不得包含凭据或完整正文

#### Scenario: 自定义脱敏函数失败
- **WHEN** mask 函数抛出异常
- **THEN** 系统 MUST 丢弃该字段或整条内容载荷，而不是回退上传未脱敏原文

### Requirement: 采样、批量发送与进程结束刷新
系统 SHALL 支持按环境和运行配置采样率，评测运行 MUST 可强制100%采样；发送 SHALL 使用非阻塞批量机制，并 SHALL 在可控退出和短生命周期评测结束时执行有界 flush。

#### Scenario: 未采样运行
- **WHEN** 一个运行未被采样
- **THEN** 该运行的所有子 Observation MUST 一致地不发送，避免产生孤立 Generation

#### Scenario: 进程即将退出
- **WHEN** benchmark 或 CLI 运行正常结束
- **THEN** 系统 MUST 在配置的超时时间内 flush，并报告未成功发送的事件数量

### Requirement: 配置与凭据隔离
系统 SHALL 通过项目配置控制非敏感行为，并 MUST 仅通过环境变量或安全凭据机制获取 Langfuse 公钥、密钥和地址。

#### Scenario: config 文件包含 Langfuse 密钥
- **WHEN** 配置加载器发现被禁止的明文 secret 字段
- **THEN** 系统 MUST 拒绝使用该字段并输出迁移到环境变量的脱敏提示

