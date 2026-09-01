## MODIFIED Requirements

### Requirement: Deferred long-term update request

`start_long_term_update` SHALL 只创建持久、可追踪的待处理长期整理请求并唤醒已启用的离线 Worker，不在当前工具调用中执行或等待记忆提取，也不得直接更新 Prompt、Skill、程序或模型参数。

#### Scenario: Long-term update is requested

- **WHEN** 模型调用 `start_long_term_update`
- **THEN** 系统 SHALL 持久化并返回包含稳定请求标识、关联 trace、scope 和 `pending` 状态的结果
- **AND** 重复的同一工具调用 SHALL 返回同一请求身份而不创建重复请求

#### Scenario: Runtime restarts after request creation

- **WHEN** 请求已提交但 Runtime 在 Worker 消费前重启
- **THEN** 请求 SHALL 继续可查询并在离线能力启用时恢复处理
- **AND** SHALL NOT 退化为仅存在进程内存的状态

#### Scenario: Offline consolidation is disabled

- **WHEN** 模型在 consolidation 关闭时调用 `start_long_term_update`
- **THEN** 工具 SHALL 返回明确 disabled 或 accepted-but-not-runnable 状态及原因
- **AND** SHALL NOT 声称请求会被自动处理或修改任何记忆

#### Scenario: Request is accepted

- **WHEN** 持久请求创建成功
- **THEN** 当前工具调用 SHALL 在不等待 Extractor、Candidate、Card 或 Embedding 的情况下返回
- **AND** SHALL NOT 自动修改 Prompt、Skill、工具实现、训练数据或模型参数

### Requirement: Governed personal-memory tools

启用个人记忆时，系统 SHALL 区分只读召回、显式正式写入与 Candidate 治理操作，并支持显式记住、纠正、冻结、删除、查看、导出以及按 scope 列出、查看、批准和拒绝离线 Candidate。

#### Scenario: Agent explicitly recalls memory

- **WHEN** 模型调用 `memory_recall` 并提供查询、可选类型/时间过滤、`retrieval_mode`、`detail_level` 及数量/展开上限
- **THEN** 工具 SHALL 返回有界的结构化命中、稳定 Card/statement/Claim/Evidence ID、当前性、引用、实际路由和召回/降级解释
- **AND** 该调用 SHALL NOT 修改记忆状态

#### Scenario: Agent requests summary-level recall

- **WHEN** `memory_recall` 使用 `detail_level=summary` 或省略细节层级且 auto 路由命中稳定 Card statement
- **THEN** 工具 SHALL 优先返回有界 Card statement 摘要而不默认展开全部 Claim/Evidence
- **AND** SHALL 返回可供后续 fact/evidence 展开的 statement 和 Claim refs

#### Scenario: Agent requests fact or evidence expansion

- **WHEN** `memory_recall` 使用 `detail_level=fact|evidence` 并引用已命中的 Card/statement 或提供精确、高风险查询
- **THEN** 工具 SHALL 通过受管关系有界展开当前 Claim，并仅在 evidence 层返回 scope-safe Evidence 摘要/引用
- **AND** 工具 SHALL 重新执行 scope、敏感度、生命周期和字符预算，不得返回越权原文

#### Scenario: Caller selects a retrieval route

- **WHEN** 调用者选择 auto、card-first、claim-first、episode-first 或 hybrid
- **THEN** 工具 SHALL 使用请求路由或返回明确的安全降级/不支持结果，并在响应中报告实际执行路由
- **AND** card-first SHALL 保留规范定义的 Claim 回退，episode-first SHALL NOT 把事件直接提升为正式 Claim

#### Scenario: User explicitly asks the agent to remember a fact

- **WHEN** 受治理管理工具收到关联当前显式用户消息的 `remember` 操作
- **THEN** 系统 SHALL 创建可追踪的显式用户 claim 并返回稳定 ID 和状态
- **AND** SHALL NOT 把 Assistant 自己的历史陈述用作用户依据

#### Scenario: Agent attempts an unsupported implicit write

- **WHEN** 模型请求把推断、网页文本、工具输出或 Assistant 回复直接发布为正式个人记忆且没有允许的批准主体
- **THEN** 管理工具 SHALL 拒绝正式写入或仅创建明确标记的 candidate，并由独立治理任务而不是当前 Assistant 决定后续状态
- **AND** SHALL 返回拒绝或候选原因

#### Scenario: User lists offline candidates

- **WHEN** 有权用户请求查看其 scope 内待审 Candidate
- **THEN** 工具 SHALL 返回有界 Candidate ID、结构化内容、状态、来源摘要、Evidence reference、冲突诊断和提取版本
- **AND** SHALL 过滤其他 scope 或超过调用者敏感权限的正文

#### Scenario: User approves or rejects a candidate

- **WHEN** 管理工具收到有权用户或人工主体对目标 Candidate 的 `approve` 或 `reject` 操作
- **THEN** 系统 SHALL 执行合法状态转移并返回实际影响 ID、前后状态和修订
- **AND** Extractor、自动 Worker 或普通 Assistant 身份 SHALL NOT 自行批准其提取结果；Governance SubAgent 只能通过专用受限决定合同请求 Policy Gate 执行转换

#### Scenario: User corrects or freezes a memory

- **WHEN** 管理工具收到关联显式用户消息的 `correct` 或 `freeze` 操作及目标 ID
- **THEN** 系统 SHALL 创建修正版本或更新冻结状态并返回实际受影响 ID
- **AND** 原始 claim、来源和修订历史 SHALL 保持可审计

#### Scenario: Memory subsystem is disabled

- **WHEN** 任一个人记忆工具在 memory 关闭时被调用
- **THEN** 工具 SHALL 返回结构化 disabled 结果
- **AND** SHALL NOT 创建 memory database 写入

## ADDED Requirements

### Requirement: Least-privilege governance SubAgent tools

系统 SHALL 为 `memory-governor` Profile 提供专用、最小权限的 Candidate 读取、Evidence 读取、同 scope 相关记忆读取和结构化决定工具；这些工具 SHALL NOT 允许任意 Claim 状态写入、跨 scope 查询、文件/网络/代码能力或再次委派。

#### Scenario: Governance SubAgent reviews a candidate

- **WHEN** Runtime 以 `memory-governor` Profile 启动治理任务
- **THEN** SubAgent SHALL 只能读取任务绑定的 Candidate、已验证 Evidence 和允许 scope 内的相关 Claim
- **AND** 提交决定 SHALL 包含 candidate ID、expected revision、固定 decision 枚举、reason codes、置信度和 governor/prompt/policy 版本

#### Scenario: Governance SubAgent attempts an arbitrary status update

- **WHEN** SubAgent 请求未绑定 Candidate、任意目标状态、跨 scope 目标或通用 `memory_manage` 写操作
- **THEN** 工具层 SHALL 拒绝调用并记录不含敏感正文的 denied 审计
- **AND** Claim、governance job 和派生投影 SHALL 保持不变

#### Scenario: Policy Gate applies a governance decision

- **WHEN** 专用决定工具收到格式有效的 approve、reject、needs-user-review 或 defer 决定
- **THEN** Policy Gate SHALL 按证据、风险、冲突、frozen、策略版本和 expected revision 校验允许的实际转换
- **AND** 工具 SHALL 返回决定 ID、前后状态、实际影响 ID及 approved/rejected/escalated/stale/denied 结果

### Requirement: CLI candidate review experience

交互式 CLI SHALL 在不阻塞普通输入和回复渲染的前提下显示当前用户 scope 内 `needs-user-review` 的有界数量，并 SHALL 提供候选列表、详情、批准和拒绝入口；CLI SHALL 复用治理服务/工具合同而不得直接读写 SQLite。

#### Scenario: CLI shows pending user reviews

- **WHEN** 当前 scope 存在一个或多个 `needs-user-review` governance job
- **THEN** CLI 状态区或记忆状态视图 SHALL 显示待用户审核数量
- **AND** `/memory candidates` 或等价命令 SHALL 返回有界列表，包括 Candidate ID、事实摘要、风险/冲突原因和审核状态

#### Scenario: User inspects and approves a candidate in CLI

- **WHEN** 用户通过 CLI 打开 Candidate 详情并确认 approve
- **THEN** CLI SHALL 展示 scope-safe Evidence 摘要和自动治理理由，并通过同一治理服务提交带 actor/revision 的用户决定
- **AND** 成功结果 SHALL 显示实际前后状态，stale/forbidden 结果 SHALL 不伪装成批准成功

#### Scenario: CLI remains usable while governance runs

- **WHEN** Governance SubAgent 正在审核或治理队列暂时不可用
- **THEN** CLI SHALL 继续接受用户输入并显示 running/retry/unavailable 的安全状态
- **AND** SHALL NOT 阻塞在线 turn、重复输入框或破坏历史会话渲染

### Requirement: Offline-memory request diagnostics

系统 SHALL 提供只读、scope-safe 的长期整理请求状态查询，至少区分 pending、running、retry、completed、failed/dead-letter 和 cancelled，并报告有界尝试、时间、版本与错误分类而不暴露敏感正文、凭证或向量。

#### Scenario: User checks a request

- **WHEN** 调用者查询其有权访问的长期整理 request ID
- **THEN** 工具 SHALL 返回当前状态、关联 trace、候选数量、尝试次数、版本和安全错误分类
- **AND** 查询 SHALL NOT 触发新的提取或状态修改

#### Scenario: Caller checks another scope

- **WHEN** 调用者查询不属于其 scope 或无权限访问的 request ID
- **THEN** 系统 SHALL 返回 not-found/forbidden 的安全结果
- **AND** SHALL NOT 泄露请求是否存在、来源正文或 Candidate 内容
