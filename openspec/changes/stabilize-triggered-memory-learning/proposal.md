## Why

当前离线记忆 Worker 会在每个已完成 CLI 回合后立即扫描轨迹，导致短期问题、重复历史和已经显式写入的事实过早进入 Candidate；同时 `memory-governor` 虽已关闭自身轨迹，仍通过共享 HookBus 写入不存在的 trace，从而使治理工具全部失败。需要把提取触发改为有语义的会话/任务边界，并让治理、候选归并、显式证据和失败恢复真正闭环。

## What Changes

- 将自动轨迹提取从“每个回合结束”改为两个批量触发条件：同一用户会话累计完成 20 个尚未消费的用户—Agent 闲聊回合，或一个至少完成 10 个成功非内部业务工具调用、并满足工具种类/最小耗时条件的长期任务回合成功结束。
- 持久化每个 scope/session 的触发游标、未消费回合数和任务批次边界；只消费完整 `cli:` 轨迹，重启后恢复计数，提交失败不推进游标，同一轨迹不得被两个触发器重复提取。
- 不增加独立 Eligibility Gate；由版本化 Extractor 在触发后的批次中负责从当前用户回合提取原子长期事实、返回空结果、分类一次性问题，并通过 Evidence Verifier 和关系解析器继续治理。
- 将多行显式事实拆成原子 Candidate，并利用成功 `memory_manage remember/correct` 的当前用户证据与既有正式 Claim 去重，禁止为已经正式写入的事实重复创建 Candidate、治理 Job 或 Card statement。
- 为 `memory-governor` 选择一致的 profile-scoped 非持久化资源边界：Reasoner 和 ToolRegistry 均禁用共享 HookBus、轨迹使用 `NullTrajectoryStore`；先实施最小 profile 隔离，仅在多个内部 Profile 或装配分支确有漂移风险时提炼资源包。治理工具仍仅有四个，决定与审计只以 `memory.db` 为权威，不向主轨迹库写治理事件。
- 加强显式记忆写入的证据合同：权威保存当前用户逐字依据，校验规范化事实确由依据支持，记录 verified 状态、事实类型、敏感度和可选结构槽位，避免任意模型改写借合法 quote 写入无关事实。
- 完善治理 dead-letter 的显式重试/升级、consolidation dead-letter 的 quarantine/suppress 生命周期与派生状态诊断；成功投影的内部 `ready` 状态在用户诊断中显示为 completed，失败不得阻塞在线对话。
- Embedding 密钥、Endpoint 和 Provider 配置不在本变更范围内；保留现有语义索引合同和修复后的部署配置。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `memory`: 修改离线提取触发、批次游标、原子 Candidate、显式写入去重、治理恢复和派生诊断要求。
- `agent-runtime`: 增加闲聊回合/至少 10 次业务工具调用的长期任务完成边界，并要求治理 SubAgent 的轨迹、Hook 和工具运行资源完整隔离。
- `tool-system`: 加强显式记忆写入的逐字证据、结构化事实和治理重试合同。
- `plugins`: 约束关闭轨迹的内部 SubAgent 不得通过共享 HookBus 间接写入主轨迹库。

## Impact

- **代码**：影响 `agent/memory/worker.py`、`source.py`、`extraction.py`、`consolidator.py`、`sqlite_store.py`、`agent/core/reasoner.py`、`agent/subagent/runtime.py`、`profiles.py`、`agent/plugins/hooks.py`、`agent/tools/builtin.py`、bootstrap 装配和 CLI 诊断。
- **持久化**：`memory.db` 需要保存会话触发游标/计数和批次身份，并为治理重试与诊断补充条件更新；现有 Claim、Card、Evidence、Trajectory ID 保持稳定。
- **兼容性**：默认闲聊阈值为 20 个完成回合，长期任务阈值为至少 10 个成功非内部业务工具调用；`start_long_term_update` 改为持久化整理意图并唤醒触发调度器，普通 Agent 调用不得绕过触发边界立即提取。旧自动扫描 checkpoint 迁移为新触发游标，禁止回放已消费历史。deterministic Extractor 升级后仅处理显式标记事实，触发后产生零 Candidate 属于正常成功结果。
- **安全**：治理模型仍不能直接改变 Claim；Policy Gate、scope、revision 和 Evidence 校验继续生效。治理内部执行不进入用户交互轨迹，但治理 Job、决定、actor 和错误分类继续审计。
- **非目标**：不新增 Eligibility Gate，不修改 Embedding 密钥/Endpoint 配置，不删除现有轨迹或记忆，不把触发阈值解释为自动批准阈值；不以修复历史 Episode projection `KeyError` 为本变更验收目标，若当前版本仍可独立复现则另建 bugfix change。
