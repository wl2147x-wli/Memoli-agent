## Why

当前 SubAgent 已具备同步/后台委派、任务目录和完成回流骨架，但运行时只执行一次无工具 LLM 请求，profile 尚未形成真实能力边界，任务状态也无法持久查询、取消、恢复或表达依赖。为了让 Memoli 能可靠承接长期个人助手中的独立调研、编码和后台任务，需要在复用现有 Reasoner、SQLite trajectory、MessageBus、Hook 与 Sandbox 的基础上，将其升级为可审计、可恢复且受限的 SubAgent 执行与任务图系统。

## What Changes

- 让每个 SubAgent 使用独立上下文、独立 session/trace 和经过 profile 过滤的 ToolRegistry，运行现有有界 Reasoner 工具循环，而不是单次无工具生成。
- 将 profile 从提示词声明升级为强制能力边界，约束工具、网络、文件写入范围、迭代次数、耗时和委派深度。
- 引入结构化委派请求、最小充分 Context Package 和结构化 SubAgent Result；主 Agent 继续作为唯一用户出口。
- 新增 SQLite 持久化 Agent Task Graph，分别记录 Agent 父子树、任务依赖 DAG、控制消息和产物索引。
- 新增任务状态机、依赖解锁、串行优先调度、状态查询、取消和任务级中断恢复；第一阶段默认最大深度与并发均为一。
- 将完整子任务执行写入现有 SQLite trajectory，并使用 agent、parent、task 与 trace 标识建立谱系，保留后续轨迹处理和 Agent 后训练所需信息。
- 保留 `task.json` 与 `result.md` 作为人类可读导出，但以 SQLite 为任务状态唯一事实源。
- 不在本变更中实现 SubAgent 直接写长期记忆、自动反馈评分、自由 Peer-to-Peer 协作、跨机器 Agent 或大规模 Agent Swarm。

## Capabilities

### New Capabilities

- `agent-task-graph`: 定义持久化 Agent/Task 图、状态机、依赖调度、控制操作、完成回流与任务级恢复行为。

### Modified Capabilities

- `subagents`: 将现有单次生成式子任务升级为独立有界工具循环，并增加强制 profile 权限、Context Package、结构化结果、轨迹谱系和记忆写入边界。

## Impact

- 主要影响 `memoli_agent/agent/subagent/`、`memoli_agent/bootstrap/subagent.py`、工具注册、配置、SQLite 持久化和 MessageBus 完成事件。
- 复用现有 Provider、Reasoner、ToolRegistry、SQLite trajectory、WorkingState、HookBus 与 Sandbox，不引入新的 Agent Loop 实现。
- `spawn_subagent` 的简单调用方式保持兼容；新增结构化参数和管理工具时应提供默认值，现有同步/后台行为继续可用。
- 需要为旧的仅文件任务记录提供非破坏性兼容：历史目录可继续读取，但新任务状态以 SQLite 为准，不要求自动导入旧记录。
- 安全边界收紧：profile 未授权工具不可见，写入必须限制到任务目录或后续独立 worktree；提示词不作为权限控制手段。
