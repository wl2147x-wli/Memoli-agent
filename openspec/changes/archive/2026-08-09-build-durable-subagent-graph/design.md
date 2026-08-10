## Context

Memoli 当前把子任务类型、运行时和生命周期拆分在 `agent/subagent/` 中，并通过 `spawn_subagent` 支持同步或后台执行。`SubAgentManager` 已提供 task id、独立目录、信号量和 MessageBus 完成回流，但 `bootstrap/app.py` 为 SubAgent 创建的 Reasoner 没有 ToolRegistry 且 `max_tool_rounds=0`，因此 profile 只存在于提示词中，执行等价于一次 LLM 生成。任务请求和结果只写入 `task.json`、`result.md`，运行中的 asyncio task 没有持久登记，重启后也不能查询或恢复。

本变更跨越 SubAgent runtime、工具装配、SQLite 持久化、MessageBus、trajectory、working state、Hook/Sandbox 和配置。设计需保持主 Agent Loop 简洁，复用现有 Reasoner，不引入第二套工具循环，并为将来有限嵌套、并发、轨迹处理和后训练保留稳定数据边界。

## Goals / Non-Goals

**Goals:**

- 让 SubAgent 成为具有独立上下文、真实工具权限和有界 Reasoner 循环的执行单元。
- 用 SQLite 持久化 Agent 父子关系、Task 依赖、状态、控制消息和产物索引。
- 以结构化 Context Package 传递最小充分上下文，以结构化 Result 回流结论、证据和产物。
- 支持同步、后台、查询、取消、依赖解锁和任务级中断恢复，并保留主 Agent 唯一用户出口。
- 将每个子任务的 agent/task/parent/trace 谱系写入完整 trajectory，为后续离线轨迹处理保留证据。
- 默认采用串行、单层的保守配置，同时让数据模型可扩展到有限层级和并发。

**Non-Goals:**

- 不实现任意 SubAgent 之间的 Peer-to-Peer 自由通信或 Agent Teams UI。
- 不实现跨机器执行、A2A 协议、分布式锁或远程队列。
- 不实现 token 级断点续跑；恢复边界是完整任务。
- 不允许 SubAgent 直接写入长期 Memory Card，也不实现反馈评分或自动进化闭环。
- 不自动迁移历史 `workspace/subagents/*/task.json` 到新数据库。
- 不在第一阶段支持多个 Coding Agent 同时修改主工作区；写入只允许进入任务目录。

## Decisions

### 1. 分离 Agent Tree、Task DAG 与 Message Log

系统分别建模三种关系：Agent Tree 使用 `parent_agent_id` 表达创建归属；Task DAG 使用独立边表表达 `depends_on`；Message Log 记录控制消息。一个 Agent 只有一个父节点，但一个任务可依赖多个任务，因此不能用单一 parent 字段表达全部关系。

备选方案是使用一个通用 `edges(type, source, target)` 表表示所有关系。该方案灵活但会弱化外键、唯一性和无环校验，查询和状态推导也更复杂，因此第一版采用显式数据模型。

### 2. SQLite 是任务状态唯一事实源，文件是可读导出和大产物载体

新增任务图数据库，至少持久化 tasks、dependency edges、messages 和 artifacts。状态转换在事务中完成；`task.json` 与 `result.md` 在关键状态后导出，供人工调试，但不参与调度判断。报告、代码和数据继续保存在 `workspace/subagents/<task_id>/`，数据库只保存路径、类型、大小和摘要/哈希。

备选方案是延续 GenericAgent 风格的目录和控制文件。文件协议极简且易观察，但难以原子更新依赖、状态和取消信息，也不利于跨重启恢复和图查询。

### 3. SubAgent 复用现有 Reasoner，而非复制 Agent Loop

bootstrap 提供 SubAgent Runtime Factory。每次执行根据 profile 构造独立 Reasoner，注入共享 Provider、SQLite trajectory、HookBus，以及 profile 过滤后的 ToolRegistry；使用独立 `session_key=subagent:<agent_id>`、trace id 和 working-state namespace。Reasoner 已提供迭代、耗时、无进展和工具轨迹边界，SubAgent 不再维护另一套循环。

备选方案是像 Akashic 一样实现专用 SubAgent loop。专用循环容易裁剪，但会重复工具消息配对、Hook、轨迹、终止和错误处理，长期会与主运行时产生语义漂移。

### 4. Profile 通过能力装配强制执行

Profile 同时声明允许工具、网络、读写根目录、最大迭代、最大耗时和是否允许继续委派。Runtime Factory 从主工具集合建立新的受限 registry，不把未授权工具暴露给模型；文件和命令工具仍需通过 Hook/Sandbox 进行运行时校验。

初始能力建议为：

- `research`：记忆召回、工作区只读、网页检索/读取；禁止 Shell、写入和继续委派。
- `coding`：工作区只读，任务目录可写，Shell 默认禁网；禁止修改主工作区和继续委派。
- `general`：调研与任务目录执行的受限合集，只能显式选择，不作为未来推荐默认值。

提示词继续描述边界，但不承担安全职责。第一阶段无需为 Coding Agent 创建 Git worktree；任务目录隔离稳定后再扩展。

### 5. 委派使用结构化 Context Package

`DelegationRequest` 包含 objective、acceptance criteria、constraints、confirmed facts、memory refs、artifact refs、dependency ids、profile、run mode 和预算覆盖。Context Compiler 只组合当前任务所需信息，不复制主对话完整轨迹。依赖结果以摘要和产物引用传入，大正文由子 Agent 按需读取。

第一版 Context Compiler 使用确定性拼装：调用方参数、父任务稳定约束、依赖结果和显式记忆引用。语义自动选择 Memory Card/Episode 可复用现有召回服务，但不得在编译阶段产生新的长期记忆。

备选方案是 fork 主上下文。fork 交接成本低，但会携带无关历史、扩大上下文并削弱安全隔离，不适合长期个人助手的默认模式。

### 6. 结果采用结构化协议，完整细节留在 trajectory

SubAgent Result 包含 status、conclusion、evidence、artifacts、completed criteria、open questions、remaining work、usage 和 error。同步调用直接返回该结果的模型可读摘要；后台调用先返回 task id，完成后通过 MessageBus 投回原 session。主 Agent 只接收结构化摘要和引用，完整工具输出保留在子 trace。

若模型未按结构返回，Runtime 使用确定性兼容层把文本放入 conclusion，并明确标记 `unstructured_fallback=true`，不能把格式问题误报为任务成功证据。

### 7. Scheduler 第一阶段串行、依赖驱动

状态集合为 `pending`、`blocked`、`runnable`、`running`、`waiting_input`、`completed`、`failed`、`cancelled`、`interrupted`。创建任务后，存在未完成依赖则为 blocked，否则为 runnable；Scheduler 领取 runnable 任务并原子转换为 running。依赖任务完成时重新计算其直接后继，所有依赖成功才可解锁。

默认 `max_concurrent=1`、`max_depth=1`。配置可提高并发，但所有任务仍经过同一 Scheduler。第一阶段依赖失败不自动重试，下游保持 blocked 并记录阻塞原因，由主 Agent 决定取消、替换依赖或重试。

### 8. 生命周期控制与恢复采用任务级语义

Manager 登记所有活跃 asyncio task，并提供 list/get/cancel。取消先持久写入请求，再取消运行对象，最终状态和完成事件只发布一次。启动时扫描遗留 running/waiting_input：没有活跃执行所有权的任务改为 interrupted；只读且无外部副作用的任务可由显式 resume 重新排队，其他任务需要主 Agent 或用户确认。

不尝试恢复模型生成中间位置。任务重跑必须创建新的 attempt/trace，同时保持同一 task id 或通过 `retry_of` 关联，避免覆盖原轨迹。

### 9. 轨迹与记忆保持单向安全边界

每个子任务使用独立 trace，根 span 记录 agent id、parent agent id、task id、parent task id、profile、depth 和 attempt。SubAgent 可以通过受限工具读取与 Context Package 相关的记忆，但不能调用长期记忆写入或修改主会话 working checkpoint；其 working state 使用独立 namespace。任务完成结果由主 Agent 或后续 Memory Processor 决定是否进入长期记忆。

本变更只保证未来可处理的轨迹谱系，不生成评分、偏好标签或训练样本。

### 10. 公共工具接口兼容扩展

保留 `spawn_subagent(instruction, profile, background, parent_session_key)` 的现有参数，并允许新增 objective/acceptance criteria/context refs/dependencies/budget 等结构化字段。旧调用映射为只有 objective 的 DelegationRequest。新增独立管理工具或统一管理动作，暴露 list/get/cancel/resume；具体 Python 类名不构成规范，但返回必须包含 task id 和稳定状态。

## Risks / Trade-offs

- [任务图与 trajectory 分属两个 SQLite 存储，跨库不能原子提交] → 任务状态先保证正确，轨迹关联写入失败时将任务标记为可诊断失败；共享同一连接仅在不破坏现有 trajectory 边界时考虑。
- [Profile 过滤不完整导致越权] → 使用 allowlist 构造全新 registry，并以文件路径、网络和命令 Hook/Sandbox 作为第二层校验；增加越权回归测试。
- [结构化上下文遗漏关键信息] → 保留 confirmed facts、constraints、artifact refs 和 open questions，并允许主 Agent 追加消息或重新委派，不自动复制完整轨迹。
- [SQLite 调度出现重复领取] → runnable→running 使用带期望旧状态的事务更新；只有更新成功的 Scheduler 获得执行权。
- [取消与完成竞争导致重复通知] → 使用终态条件更新和 completion-event 标记，只有首次进入终态的路径发布事件。
- [任务目录仍可能被 Coding Agent 写入危险内容] → 任务目录不是系统沙箱；继续依赖现有 Sandbox/Hook，并默认禁网、禁止主工作区写入。
- [多 Agent 增加 token 和延迟] → 委派策略优先保留简单任务在主 Agent，默认串行和有限预算，结果只回流摘要。
- [新 schema 增加实现范围] → 按“真实 Runtime → 持久状态 → 依赖调度 → 恢复与管理”的顺序交付，每一步都有可独立运行的兼容路径。

## Migration Plan

1. 先为现有同步/后台委派、任务文件和完成回流增加回归基线，确保升级不改变调用方基本行为。
2. 引入任务图 schema 与 repository，创建新任务时同时写 SQLite 和现有导出文件；旧目录保持只读兼容。
3. 引入 Profile ToolRegistry Factory 和独立 Reasoner，将默认并发设为一，逐个开放 research、coding、general。
4. 接入结构化 Context/Result、trajectory 谱系和独立 working-state namespace。
5. 接入状态查询、取消、依赖调度和启动恢复，再将文档中的“已完成”描述更新为真实能力边界。
6. 全量测试、lint 和类型检查通过后才允许提高并发或深度。

回滚时可关闭新的 SubAgent 工具或切回 legacy one-shot runtime；新数据库和任务目录保留，不做破坏性删除。若数据库 migration 失败，SubAgent 功能应禁用并返回可诊断错误，主 Agent 对话继续工作。

## Open Questions

- 任务图是否与 trajectory 共用同一 SQLite 文件，需在实现时根据现有连接生命周期和迁移风险决定；规范只要求 SQLite 持久化和稳定关联。
- `general` 是否保留为公开 profile，还是在后续变更中拆为 `code-reader`、`coder`、`test-runner` 等更小能力单元。
- Coding Profile 的独立 Git worktree 和合并审批属于后续能力，待任务目录隔离与取消恢复稳定后单独设计。

