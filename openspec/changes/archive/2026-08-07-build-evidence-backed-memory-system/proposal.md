## Why

Memoli 当前以 Markdown bullet 保存长期事实、以简单字符串匹配召回，并把普通对话重复写入 `HISTORY.md`；这既无法可靠表达来源、冲突、时效和用户治理，也与已有 SQLite 完整轨迹形成两个不一致的历史事实源。为了支持“长期个人助手”并为后续离线进化和后训练保留可信输入，需要将工作状态、个人记忆、程序经验和原始轨迹明确分层，并采用可审计、可恢复的 SQLite-first 记忆系统。

## What Changes

- 新增结构化工作记忆：由 Harness 确定性维护运行硬状态，由 `update_working_checkpoint` 维护有界语义 checkpoint，并在每次模型决策前以最新状态栏直接注入而非相似度检索。
- 将个人长期记忆改为 SQLite-first 的双层结构：少量核心用户画像卡片提供有界概览，append-only claims 与轨迹片段检索提供可追溯细节。
- 为每条 claim/card 保存用户 scope、类型、状态、置信度、时间有效性、敏感等级和一个或多个轨迹证据引用；修正通过新 claim、版本和 supersede 关系表达，不破坏历史。
- 第一版使用 SQLite FTS5/BM25、类型/时间/scope 过滤和固定注入预算；保留可替换检索端口，embedding lane 不属于本 change。
- 增加自动轻量预检索与显式 `memory_recall` 二次检索；检索结果返回当前有效事实、原始证据引用和可观察的召回解释。
- 在线 Agent 仅完成任务、更新工作状态、保存完整轨迹和处理用户显式记忆命令；普通对话的隐式信息只能由离线 consolidation 产生 candidate，不能直接发布为正式记忆。
- 增加候选、激活、冻结、替代、拒绝和删除生命周期，以及查看、纠正、冻结、删除和导出等用户治理行为。
- **BREAKING**：停止把每轮用户/助手消息追加到 `HISTORY.md`；完整 SQLite trajectory 成为唯一权威运行历史，Markdown 历史仅允许作为派生导出。
- **BREAKING**：长期记忆的权威存储从 `MEMORY.md`/`RECENT_CONTEXT.md` 迁移为 schema-versioned `memory.db`；提供一次性、幂等的 Markdown 导入与备份，不静默删除原文件。
- 非目标：本 change 不实现向量检索、知识图谱、自动 Skill 生成、主动通知、轨迹评价、训练数据生成或模型权重更新。

## Capabilities

### New Capabilities

- `working-memory`: 定义任务级工作 checkpoint、确定性运行状态投影、每轮末尾注入、持久恢复、过期清理和轨迹审计行为。

### Modified Capabilities

- `memory`: 将 Markdown 事实列表升级为证据支持的 SQLite claims/cards、FTS5 双层检索、离线候选整理、冲突时效处理、用户治理与兼容迁移。
- `agent-runtime`: 统一每次模型调用前的动态上下文装配顺序，使最新工作状态、核心画像和检索记忆在工具循环中持续可见，并保持静态系统前缀和运行轨迹边界。
- `tool-system`: 增加受治理的个人记忆管理工具合同，使显式记住、纠正、冻结、删除、查看和导出可与只读召回区分，并拒绝缺少用户依据的正式写入。

## Impact

- 主要影响 `memoli_agent/agent/memory/`、工作状态控制、prompt/context 组装、passive turn lifecycle、SQLite repository、内置记忆工具和 `memoli_agent/bootstrap/` 装配。
- 新增本地 schema-versioned `memory.db`、FTS5 索引和工作 checkpoint 持久化；继续复用现有 `trajectory.db` 作为 append-only 证据源，不复制原始 payload。
- 配置需要表达 memory database、注入预算、core card 上限、自动检索和 consolidation 开关；旧 Markdown path 仅用于迁移输入与可读导出。
- 迁移必须幂等、可回滚并保留原文件备份；遇到未知 schema 或证据引用损坏时拒绝写入而不是重建数据库。
- 敏感信息在写入和检索层按用户 scope 与敏感等级过滤；网页、工具输出和 LLM 摘要均不得作为可执行指令或未经验证的正式用户事实。
- 需要新增三层用户记忆、状态栏准确性、冲突/时序、检索解释、迁移和禁用状态测试，并同步架构与运维文档。
