# SubAgent 持久化任务图

Memoli 的 SubAgent 是主 Agent 管理的本地执行单元。主 Agent 仍是唯一面向用户的输出边界；SubAgent 只能把结果交回父控制链路，不能直接回复用户。

## 结构

```text
主 Agent / root session
  -> spawn_subagent（结构化 DelegationRequest）
  -> SubAgentManager
  -> SQLite Task DAG（事实源）
  -> 单并发 Scheduler
  -> 独立 Reasoner + 受限 ToolRegistry
  -> StructuredSubAgentResult
  -> 同步工具结果或 MessageBus 完成事件
```

Agent Tree 表示控制权：一个 Agent 只有一个父 Agent。Task DAG 表示执行依赖：一个任务可以依赖多个前置任务，但不能成环。两者分开存储，避免把“谁负责结果”和“谁必须先完成”混为一谈。

## 生命周期与恢复

任务状态为 `pending / blocked / runnable / running / waiting_input / completed / failed / cancelled / interrupted`。状态转换使用期望旧状态的 SQLite 原子更新，因此同一个 runnable 任务不会被重复领取。

启动时遗留的 `running` 或 `waiting_input` 会被标记为 `interrupted`，不会自动重放。显式恢复会创建新的 attempt 和 trace；可能产生外部副作用的任务还需要 `confirm_side_effects=true`。

## 上下文、轨迹与结果

Context Package 只包含目标、验收标准、约束、已确认事实、显式记忆/制品引用和依赖摘要，不复制完整主对话。每个任务拥有独立 session、working state、task directory、trace 和 root span。轨迹记录 agent、parent agent、task、parent task、profile、depth、attempt 等 lineage。

结果优先使用结构化协议，包含结论、证据、制品、已完成验收项、开放问题、剩余工作、usage 和 error。模型只返回普通文本时会保留原文并标记 `unstructured_fallback`，不会伪造证据。

## 持久化与可读导出

默认数据库为 `workspace/subagents/task-graph.db`。任务、依赖、控制消息、制品索引、attempt 和状态日志都存入 SQLite。

```text
workspace/subagents/<task_id>/
  task.json   # SQLite 任务快照
  result.md   # 结构化结果、trace 与 attempt 的可读导出
  ...         # coding profile 产生的制品
```

调度和查询只信任 SQLite。`task.json` 或 `result.md` 缺失、损坏时，可通过 `manage_subagent(action="regenerate")` 重建；旧任务目录保持可读，但不会自动导入数据库。

## Profile 安全边界

- `research`：工作区只读、显式授权的记忆召回、已启用的网页读取；没有写工具或继续委派工具。
- `coding`：工作区只读，写入和代码执行根目录绑定到任务目录，代码执行默认拒绝常见网络访问。
- `general`：显式选择的受限能力合集，仍不暴露长期记忆写入、主 working checkpoint 或继续委派。
- `memory-governor`：只注册绑定当前 Job 的
  `governance_candidate_read / governance_evidence_read /
  governance_related_claims / governance_decide`。它使用 `NullTrajectoryStore`，Reasoner
  与 ToolRegistry 均不继承共享 HookBus；决定只经 Policy Gate 写 `memory.db`，task ID
  与状态留在 task graph，不写主 `trajectories.db`。

每个任务创建全新的 ToolRegistry，未授权工具不会进入模型 schema。Hook 仍位于工具执行边界。这里的“禁网”是本阶段的进程内策略防线，不等同于操作系统或容器级网络隔离。

启用 Skill Runtime 后，profile 可获得同一个只读 `skill_load` 边界，但每个 SubAgent
attempt 使用独立 `session_instance_id` 和 Catalog 快照。Catalog 按该 profile 实际
装配的工具过滤；例如要求 `file_write` 的 Skill 对 research 不可见、对 coding 可见。
主 Agent 已加载的 Skill 正文和更高权限不会复制到子 Agent，加载也不会改变 depth、
iteration、elapsed、并发或取消限制。

## 工具与配置

`spawn_subagent` 支持同步/后台执行、profile、验收标准、约束、事实、记忆/制品引用、依赖和副作用标记。`manage_subagent` 支持 `list / get / cancel / resume / regenerate`，并按当前 root session 隔离可见性。

配置项位于 `[subagent]`：`database`、`root`、`default_profile`、`max_concurrent`、`max_depth`、`recovery_policy`，以及两个 profile 预算表。默认最大并发和最大深度均为一。

## 第一阶段明确不包含

本阶段不包含 Peer-to-Peer Agent Teams、SubAgent 直接写长期记忆、反馈评测闭环、跨机器执行、系统级容器隔离或 Coding worktree 自动合并。这些能力需要新的 OpenSpec 变更单独设计。
