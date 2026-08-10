## Context

Memoli 当前是一个约束清晰的早期 Runtime：`AgentLoop` 负责消息泵，`PassiveTurnPipeline` 负责六阶段生命周期，`Reasoner` 支持一次工具回调，长期记忆使用 Markdown，SubAgent 为进程内委派，Proactive 为固定间隔消息，MCP 只支持 stdio，评测层已能适配 LoCoMo、LongMemEval 和外部 Agent。该结构适合继续演进，但尚缺少真实长任务所需的多步执行、持久状态、逐步轨迹、证据化个人记忆和统一安全治理。

目标产品是一个长期个人助手：在线 Runtime 稳定完成任务并记录证据；离线学习平面从经过验证的轨迹中提炼记忆、Skill 和优化候选；所有行为变化通过评测、人工审批、canary 和回滚发布。主要使用者包括个人用户、Runtime/评测开发者以及后训练实验开发者。

关键约束：

- 默认安装和在线 Runtime 保持轻量、可在无 GPU 环境运行。
- 个人数据本地优先，未经授权不得进入训练数据或外部优化服务。
- OpenSpec 记录行为合同；本 change 只给出目标架构，实施必须拆分为小 change。
- 当前 Markdown 记忆、工具 schema、插件入口、Benchmark adapter 和配置应尽量向后兼容。
- 进化与训练只能产生候选，不能绕过发布治理直接修改稳定系统。

## Goals / Non-Goals

**Goals:**

- 建立在线执行平面与离线学习平面的明确边界。
- 让每个任务、模型步骤、工具调用、记忆和学习候选具有可追溯证据。
- 支持跨进程持久任务、多步 Reasoner、中断恢复和真实副作用审批。
- 建立个人事实、工作状态、原始轨迹和程序性 Skill 之间的分层存储。
- 从多条已验证轨迹提炼可版本化 Skill，而不是把单次成功直接固化。
- 统一 Memory、Runtime、Proactive、Evolution 和模型后训练的评测与回归门禁。
- 支持 DSPy/GEPA 类文本优化和 SFT/RFT 类参数优化，但保持可选依赖与隔离运行。
- 形成适合作品集展示的可复现实验、前后指标、审计报告和安全说明。

**Non-Goals:**

- 不一次性实现全部目标能力，也不在母变更中直接修改 Runtime 代码。
- 不以任意本机代码执行、全自动付款/发信、工具数量或聊天平台数量作为核心成果。
- 不在在线会话中热替换 Prompt、Skill 或模型。
- 不把 LLM Judge 作为安全、真实副作用或任务成功的唯一裁判。
- 不在早期实现完全自动的代码自进化、复杂分布式多 Agent 或大规模在线 RL。

## Decisions

### 1. 在线执行平面与离线学习平面分离

在线平面包含 Gateway、Agent Runtime、Reasoner、Tool Runtime、Memory、Skill Loader、SubAgent 和 Proactive；离线平面包含 Trajectory Miner、Evaluation Harness、Evolution Lab、Post-training Pipeline 和 Release Registry。在线平面只读取 `active` 版本，学习平面只写候选区。

选择分离而不是“运行中自改”，因为长期个人助手首先需要稳定、可解释和可回滚。替代方案是让 Agent 在任务结束后直接更新 Prompt/Skill；该方案反馈快，但无法可靠归因，也容易把偶然成功或恶意输入固化。

### 2. 以 append-only trajectory 作为统一证据源

模型请求、模型响应、工具调用、工具结果、状态变化、审批、用户反馈和评测结果均关联 `trace_id/task_id/step_id`。原始轨迹只追加；修正通过新事件表达，不覆盖历史。工作记忆、个人记忆、Skill 和训练样本均保存来源引用。

选择事件证据而不是只保存聊天文本，因为工具状态和最终环境结果才是判断任务是否完成的重要依据。为控制体积，轨迹支持 payload 摘要、外部 blob、保留周期和敏感字段脱敏。

### 3. SQLite-first、可替换存储端口

第一阶段使用 SQLite 持久化 session、task、trajectory、memory metadata、skill registry、candidate 和 evaluation run；大文本或二进制内容按引用存放在 workspace。存储通过协议接口注入，后续可增加 PostgreSQL 或对象存储实现。

选择 SQLite 而不是继续用纯 Markdown，是因为需要事务、唯一约束、版本关系、时间过滤和可查询审计。Markdown 仍作为用户可读导出和兼容输入，不作为所有运行状态的唯一数据库。迁移工具负责导入当前 `MEMORY.md/HISTORY.md/RECENT_CONTEXT.md`。

### 4. 多步 Reasoner 与 Durable Task 解耦

Reasoner 负责单次任务唤醒内的 observe/act/tool/verify 循环、预算和终止原因；Durable Task 负责跨唤醒状态、checkpoint、等待用户/事件、重试策略和恢复。每个 step 触发生命周期事件，但 `AgentLoop` 保持消息泵职责。

选择解耦以避免把持久化、并发和工具循环都塞进主 Loop。任务必须有显式状态机，例如 `queued/running/waiting_approval/waiting_event/completed/failed/cancelled`。

### 5. 风险感知的 Tool Runtime

工具元数据新增风险等级、副作用、幂等性、超时、权限、dry-run、审批和验证能力。高风险或不可幂等动作使用 `prepare → preview → approve → commit → verify`；失败后不得盲目重试。MCP 和插件工具进入相同策略层。

替代方案是在 system prompt 中要求模型谨慎；该方案不能形成强制边界，因此仅作为辅助说明。

### 6. 四类状态分离

- Trajectory：原始运行证据，append-only。
- Working state：当前任务 objective、checkpoint、待办和预算。
- Personal memory：用户事实、偏好、关系、事件和限制，可更新与删除。
- Procedural skill：完成任务的方法、参数、前后条件和测试，可版本化。

个人记忆记录 `type/confidence/valid_from/valid_to/sensitivity/status/source_refs`，支持 candidate、verified、superseded 和 rejected。Skill 记录 manifest、权限、来源轨迹、验证集、成功率和版本状态。

### 7. 混合检索与可解释注入

个人记忆使用关键词、向量、时间、类型、scope 和热度 lane，采用可替换融合与 rerank；注入结果受字符/Token 预算约束，并向 trace 记录命中项、分数和最终注入内容。Embedding、reranker 和向量后端属于可选依赖，关键词 lane 始终可退化运行。

### 8. Proactive 采用机会评分而非固定推送

外部信号、长期目标、最近对话、用户状态、紧迫性、新颖性和打扰成本生成机会决策；策略输出 `silent/prepare/ask/notify`。系统强制 quiet hours、每日预算、重复抑制和高优先级例外。用户接受、忽略或关闭通知形成反馈，但不会未经评测直接更新稳定策略。

### 9. Skill 由多轨迹证据结晶

学习系统先按任务族聚类成功、部分成功和失败轨迹，再提取适用条件、共同策略、错误、例外和来源。至少有多条独立非失败证据，才可创建 Skill candidate。候选必须在隔离环境重放，验证前置检查、执行后检查和最终状态；通过后进入 canary，人工批准后成为 active。

### 10. Evaluation 是发布门禁，不是附属报告

评测环境统一 reset/ingest/execute/verify/close 合同，结果优先使用确定性状态、测试和规则验证；LLM Judge 只评价难以程序化的表达质量并保留 rubric、证据和置信度。所有候选报告 baseline、train/validation/holdout、回归、延迟、Token、费用和失败样例。

### 11. Evolution Lab 适配 Hermes 思路但重新接入真实 Runtime

文本类候选可使用 DSPy/GEPA 或其他 optimizer，但 fitness 必须运行真实 Memoli episode，而不是仅让模型阅读 Skill 后生成文字。优化目标按风险分层：Skill → 工具描述/检索策略 → Prompt section → 代码。早期仅实现前三类；代码修改必须产生独立 OpenSpec change、隔离分支和完整软件门禁。

### 12. 后训练以 SFT/RFT 起步，RLVR 延后

训练数据来自人工 golden、经验证教师轨迹和用户明确授权的脱敏真实轨迹。按用户、任务族和时间做泄漏安全切分；训练、验证和 holdout 不共享近重复轨迹。SFT 固化工具调用、记忆决策和结构化协议；RFT 从多候选中保留验证成功轨迹；RLVR 仅用于有可靠环境状态奖励的沙盒任务。

训练依赖放在独立 `training` extra/环境，模型通过版本化 registry 发布，Runtime 仍通过 Provider 接口调用。

### 13. OpenSpec 作为进化治理接口

通过门禁的高影响候选生成或关联 OpenSpec change，包含失败证据、修改假设、影响预测、delta requirements、任务和评测报告。自动系统可以准备材料，但 review/apply/archive 仍由授权者决定。

### 14. 分阶段交付而非一次 apply 母变更

本 change 的 tasks 以“细化和拆分”为主。推荐依赖顺序：工程门禁 → trajectory → 多步 runtime → durable task → personal memory → skill learning → proactive → evaluation 扩展 → governance → evolution → post-training。每个阶段独立提案、实现和归档。

## Risks / Trade-offs

- **[范围过大导致长期不交付]** → 母变更只固定边界，按依赖拆分小 change；每个 change 必须有可运行演示和量化验收。
- **[轨迹和记忆包含个人敏感数据]** → 本地优先、字段分级、默认拒绝训练、可导出/删除、脱敏审计和最小保留周期。
- **[LLM 生成错误记忆或 Skill]** → candidate 状态、来源回溯、多轨迹支持、确定性验证、用户纠正和可撤销版本。
- **[自进化过拟合评测集]** → train/validation/holdout 隔离、任务族/用户/时间切分、隐藏回归集、候选数量和优化成本报告。
- **[Prompt/Skill 膨胀增加成本]** → 长度预算、语义保留、按需加载、上下文预算和候选长度惩罚。
- **[高权限工具产生不可逆副作用]** → 风险元数据、权限 allowlist、dry-run、两阶段审批、幂等 key 和最终状态验证。
- **[SQLite 在高并发下受限]** → 第一阶段限制单实例写入并使用事务/WAL；保持存储端口以便迁移 PostgreSQL。
- **[可选 ML 依赖破坏 Runtime 安装]** → evolution/training 独立 extra 或独立包，在线核心不导入重型依赖。
- **[迁移破坏现有 Markdown 记忆]** → 只读扫描、备份、幂等导入、迁移报告、双读验证和显式回滚，不原地删除旧文件。
- **[多 Agent 增加成本但没有信息增量]** → 只有需要独立工具、环境反馈或上下文隔离时才委派，并通过消融证明收益。

## Migration Plan

1. 为当前 v0.1 行为保存 Benchmark、配置和 Markdown 记忆基线。
2. 新增 schema-versioned SQLite 与 repository ports，不改变默认用户行为。
3. 双写或影子记录 trajectory，确认性能和脱敏策略后再作为学习证据源。
4. 引入多步 Reasoner 与 Durable Task feature flag，保留旧单轮路径用于回滚。
5. 以只读方式导入现有 Markdown 记忆，比较召回结果后逐步切换新 Personal Memory。
6. 依次启用 Skill candidate、Proactive opportunity、Evaluation gate、Evolution Lab 和 Post-training；每项均先 shadow/canary。
7. 每阶段归档对应 OpenSpec change，并更新当前规格、迁移说明和实验报告。

回滚原则：数据库迁移必须保持向后可读备份；active Skill/Prompt/模型使用不可变版本指针；canary 可原子切回上一稳定版本；训练和进化组件停用后不影响基础对话 Runtime。

## Open Questions

- 第一版 Personal Memory 是否采用 SQLite 向量扩展，还是仅保存 embedding 并由 Python 计算小规模相似度？
- 哪些个人数据类别允许用户选择进入本地后训练，默认保留周期分别是多少？
- Skill candidate 的最小独立轨迹支持数和 canary 提升阈值如何按任务风险分级？
- Proactive 的每日通知预算和高优先级例外由全局配置还是用户画像策略决定？
- 首个后训练实验聚焦“工具协议”“记忆写入决策”还是“失败恢复策略”？
- Evolution 候选与 OpenSpec change 是一一对应，还是低风险候选批量进入同一 change？
