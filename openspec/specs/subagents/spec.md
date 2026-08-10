# SubAgent Specification

## Purpose

定义进程内子任务的 profile 选择、同步与后台委派、并发限制、独立任务记录和完成结果回流行为，并保持主 Agent 作为唯一对话出口。
## Requirements
### Requirement: Profile-based task delegation

系统 SHALL 允许主 Agent 使用 `general`、`research` 或 `coding` profile 委派边界清晰的本地子任务，并 SHALL 通过实际工具装配和执行策略强制每个 profile 的工具、网络、文件写入、迭代和耗时边界。每个 SubAgent SHALL 在独立上下文和 session 中运行现有有界 Reasoner 工具循环，而不是仅执行一次无工具模型生成。

#### Scenario: Synchronous delegation

- **WHEN** `spawn_subagent` 以同步模式收到有效指令
- **THEN** 调用 SHALL 使用所选 profile 的受限工具循环等待子任务完成
- **AND** 返回结果、task id、profile 与任务目录

#### Scenario: Research profile attempts a forbidden action

- **WHEN** `research` SubAgent 尝试调用写文件、Shell 或其他未授权工具
- **THEN** 未授权工具 SHALL 不向模型暴露或由执行边界拒绝
- **AND** 拒绝 SHALL 记录在该子任务的轨迹中

#### Scenario: Coding profile writes an artifact

- **WHEN** `coding` SubAgent 创建或修改文件
- **THEN** 写入 SHALL 只允许发生在该任务的独立任务目录或配置的隔离工作区
- **AND** 对主工作区其他位置的写入 SHALL 被拒绝

#### Scenario: SubAgent is disabled

- **WHEN** SubAgent 系统未启用时收到委派请求
- **THEN** 工具 SHALL 返回失败结果而不影响主对话

### Requirement: Bounded concurrency

系统 SHALL 按配置限制同时执行的 SubAgent 数量，且并发上限至少为一。

#### Scenario: Concurrency limit is reached

- **WHEN** 活跃子任务数量达到配置上限
- **THEN** 后续任务 SHALL 等待执行许可，而不是绕过限制

### Requirement: Durable task records

每个子任务 SHALL 具有唯一 task id、agent id 和独立目录，并 SHALL 将请求、当前状态、父子/轨迹关联和结果持久化到 SQLite。`task.json` 与 `result.md` SHALL 作为人类可读导出保留，但不得作为调度状态的唯一事实源。

#### Scenario: Task is created and completes

- **WHEN** 系统创建并执行子任务
- **THEN** SQLite 记录 SHALL 在执行前包含请求、身份、profile、状态和任务目录
- **AND** 任务目录 SHALL 包含描述请求的 `task.json`
- **AND** 完成后 SQLite 记录 SHALL 包含终态和结果引用
- **AND** 任务目录 SHALL 包含描述状态、输出和元数据的 `result.md`

#### Scenario: Export files disagree with SQLite

- **WHEN** 人类可读导出缺失、损坏或与 SQLite 状态不一致
- **THEN** 查询和调度 SHALL 以 SQLite 状态为准
- **AND** 系统 SHALL 能重新生成导出或报告可诊断错误，而不得回退到不一致文件驱动状态

### Requirement: Background completion re-entry

后台子任务 SHALL 立即返回 task id，并在完成后通过主消息总线回流结果。

#### Scenario: Background task completes

- **WHEN** 后台子任务结束
- **THEN** 系统 SHALL 发布带有完成事件、成功状态、profile 和 task id 的入站消息
- **AND** 结果 SHALL 重新经过主 Agent 对话链路，而不是由 SubAgent 直接向用户输出

### Requirement: Minimal sufficient context package

系统 SHALL 使用结构化 Context Package 向 SubAgent 传递目标、验收标准、约束、已确认事实、记忆引用、产物引用和依赖结果，不得默认复制完整主对话轨迹。

#### Scenario: Independent task is delegated

- **WHEN** 主 Agent 委派一个上下文隔离的子任务
- **THEN** SubAgent SHALL 接收该任务的结构化 Context Package
- **AND** 不相关的主对话消息和其他子任务工具输出 SHALL 不进入其初始上下文

#### Scenario: Dependency produces a large artifact

- **WHEN** 前置任务产生大体积文件供后续任务使用
- **THEN** 后续 Context Package SHALL 传递摘要和产物引用
- **AND** 不得默认内联完整文件正文

### Requirement: Structured subagent result

SubAgent SHALL 返回包含状态、结论、证据、产物、已满足验收项、开放问题、剩余工作、使用量和错误信息的结构化结果；主 Agent SHALL 只接收完成当前决策所需的摘要与引用。

#### Scenario: Task completes normally

- **WHEN** SubAgent 满足任务验收标准并结束
- **THEN** 结果 SHALL 标识 `completed` 并列出结论、证据、产物和已满足验收项

#### Scenario: Model returns unstructured text

- **WHEN** SubAgent 的最终模型输出不能解析为结构化结果
- **THEN** 系统 SHALL 保留文本结论并标记结构化降级
- **AND** 不得仅因格式降级伪造验收证据

#### Scenario: Task ends before completion

- **WHEN** SubAgent 因预算、取消或错误未完成全部目标
- **THEN** 结果 SHALL 如实记录终态、已完成内容、剩余工作和错误
- **AND** 不得把部分进度标记为完整成功

### Requirement: Independent trajectory lineage

每个 SubAgent SHALL 保存独立完整 trajectory，并 SHALL 记录 agent id、parent agent id、task id、parent task id、profile、depth、attempt 和 trace 关联，使主任务与子任务可在不合并上下文的情况下重建执行谱系。

#### Scenario: SubAgent invokes tools

- **WHEN** SubAgent 在执行中调用一个或多个工具
- **THEN** 其模型请求、工具意图、执行参数、原始结果、模型可见结果和终止原因 SHALL 写入独立 trace
- **AND** trace SHALL 可关联回父任务和根会话

### Requirement: Memory and working-state isolation

SubAgent SHALL 只能通过 profile 允许的只读入口访问相关长期记忆，且不得直接写长期 Memory Card 或修改主会话 working checkpoint；子任务运行状态 SHALL 使用独立 namespace。

#### Scenario: SubAgent recalls memory

- **WHEN** Context Package 或任务需要相关个人记忆
- **THEN** SubAgent SHALL 通过受限记忆召回读取相关内容
- **AND** 召回 SHALL 记录在子任务轨迹中

#### Scenario: SubAgent attempts long-term memory write

- **WHEN** SubAgent 尝试直接创建、更新或删除长期记忆
- **THEN** 写入 SHALL 被能力边界拒绝
- **AND** 子任务结果 SHALL 只能把候选事实交回主 Agent 或后续 Memory Processor

