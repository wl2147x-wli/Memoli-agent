## Why

Memoli 当前已经具备有界多步 Agent Runtime、SQLite 完整轨迹、GenericAgent 风格工具、SQLite 证据化个人记忆、Working State、SubAgent、Proactive、MCP 和评测骨架，但这些能力尚未形成“真实任务 → 可审计轨迹 → 可信学习信号 → 候选改进 → 隔离评测 → 人工发布”的持续学习闭环。为了让项目成为具有求职辨识度且工程可落地的长期个人助手，需要建立覆盖持久任务、安全执行、长期学习、受控进化和 Agent 后训练的总体行为蓝图，再按独立子变更逐项细化与实现。

## Delivery Status

本 change 仅作为架构母蓝图，不能直接代表其中能力已经实现。当前承接关系如下：

- 已归档：`simplify-agent-loop-with-trajectories`，交付有界串行 Agent Loop 与 SQLite 完整轨迹。
- 已归档：`adopt-genericagent-toolset`，交付默认九工具、完整工具轨迹与工作 checkpoint 控制入口。
- 已归档：`build-evidence-backed-memory-system`，交付 SQLite 证据记忆、Working State、FTS5 检索与迁移治理。
- 已归档：`build-openai-anthropic-provider-runtime`，交付 OpenAI、OpenAI-compatible、Anthropic 与显式真实模型 fallback。
- 已归档：`build-versioned-skill-runtime`，交付会话固定版本的 Skill Catalog、只读按需加载与 Registry。
- 已归档：`build-durable-subagent-graph`，交付串行持久任务图、隔离上下文、预算、取消与恢复。
- 已归档：`enhance-memory-retrieval-and-indexing`，交付关键词、元数据、可选语义 lane 与确定性 RRF。
- 已归档：`harden-agent-loop-and-trajectory`、`harden-memory-integrity-and-retrieval`、`harden-mcp-lifecycle-and-registry` 和 `complete-runtime-integration-and-proactive-safety`，交付本轮 Bug 清理与回归门禁。
- 实施中：`build-plugin-hooks-and-sandbox`，仅剩固定 digest Docker runner 镜像的真实构建验证。
- 实施中：`sandbox-built-in-code-execution`，代码、配置、文档与无回退测试已完成，仅剩 Docker daemon 可用后的固定 digest 镜像构建与真实容器验收。
- 仅拟议：Durable Tasks、Skill Learning、Evolution Lab、Post-training、统一 Safety Governance 及其增强版评测门禁。

## What Changes

- 将单次被动对话 Runtime 演进为支持多步工具执行、明确终止原因、预算、中断与恢复的任务运行时。
- 建立 append-only 轨迹和可观测性能力，为调试、评测、经验提炼与训练数据构建提供统一证据源。
- 将当前文本记忆演进为具有来源、置信度、时间有效性、冲突处理、敏感等级和用户治理的长期个人记忆。
- 引入可版本化、可测试、可回放的 Skill Registry，并从多条验证轨迹中生成 Skill 候选。
- 将 Proactive 从固定消息循环演进为考虑价值、紧迫性、新颖性、打扰成本、静默时间和通知预算的主动机会判断。
- 建立 Evaluation Harness，统一评测记忆、工具任务、主动行为、Skill、进化候选与后训练模型，并要求基线、holdout、回归、成本和可复现报告。
- 引入独立离线 Evolution Lab，用于从失败轨迹生成 Skill、Prompt、工具描述、检索策略等候选；候选不得直接覆盖稳定版本。
- 引入 Agent 后训练数据与模型流水线，优先支持脱敏轨迹上的 SFT/RFT，后续在可验证沙盒中选择性支持 RLVR。
- 建立跨能力的安全治理，包括数据授权、敏感信息、训练数据使用、高风险工具审批、候选发布、canary、回滚与审计。
- 保留插件、MCP 和 SubAgent 的可替换边界，并补充 manifest、权限、隔离、结构化结果和外部连接治理。
- 本 change 是总体架构母变更，不授权一次性实现全部内容；后续 SHALL 拆分为较小 OpenSpec change，逐项确认设计和验收标准。

### Non-goals

- 不以工具数量、多聊天平台或去中心化多 Agent 作为首要目标。
- 不允许在线进程自动修改稳定 Prompt、Skill、代码或模型并直接部署。
- 不把未经验证的单条成功轨迹直接固化为 Skill，也不把真实私人数据默认用于模型训练。
- 不要求第一阶段实现代码自进化、全量 RL 或自研向量数据库。

## Capabilities

### New Capabilities

- `durable-tasks`: 持久任务状态、checkpoint、审批等待、中断恢复、幂等重试和跨进程生命周期。
- `trajectory-observability`: append-only Agent 轨迹、步骤级工具/模型事件、反馈关联、脱敏、查询、回放与保留策略。
- `skill-learning`: Skill manifest、版本、候选生成、多轨迹证据、重放验证、canary、发布和弃用。
- `evolution`: 学习信号、失败聚类、修改假设、候选注册、隔离优化、回归门禁、人工批准和回滚。
- `post-training`: 授权轨迹的数据构建、脱敏、验证、数据切分、SFT/RFT、可选 RLVR、模型注册和对照评测。
- `safety-governance`: 跨域隐私、权限、审批、发布治理、审计和删除/回滚合同。

### Modified Capabilities

- `agent-runtime`: 从单轮工具回调扩展为有预算、步骤、终止原因和恢复边界的多步 Agent 执行。
- `tool-system`: 增加风险声明、超时取消、幂等性、预演审批、结果验证和完整调用 trace。
- `memory`: 增加证据来源、类型、置信度、时间、冲突、敏感度、用户修正/删除和混合检索。
- `plugins`: 增加插件 manifest、版本兼容、配置 schema、权限和确定性 hook 顺序。
- `subagents`: 增加独立上下文、工具 allowlist、预算、取消、状态查询、结构化结果和外部证据要求。
- `proactive`: 增加机会评分、静默时间、通知预算、重复抑制、解释和用户反馈学习。
- `mcp-tools`: 增加连接级权限、超时、健康状态、能力元数据和远程 transport 的可扩展边界。
- `benchmarking`: 扩展为覆盖 Runtime、Memory、Proactive、Skill、Evolution 和模型版本的统一评测与回归体系。

## Impact

- **代码边界**：将影响 `agent/core`、`agent/lifecycle`、`agent/memory`、`agent/tools`、`agent/subagent`、`agent/proactive`、`agent/mcp`、`bootstrap`、`benchmarks`，并新增轨迹、任务、Skill、进化、训练与治理模块。
- **持久化**：SQLite trajectory、evidence-backed memory 和 Working State 已成为当前基线；后续需要在其上补充 Durable Task、Skill、Evolution 与训练数据的独立 schema/version 合同，并保持 legacy Markdown 迁移可恢复。
- **外部接口**：Tool schema、Plugin manifest、MCP 配置、SubAgent 结果、评测记录和模型注册表将新增版本化合同，优先保持向后兼容。
- **依赖与部署**：在线 Runtime 保持轻量；向量检索、DSPy/GEPA、训练框架和 GPU 依赖放入可选 extras 或独立环境，不污染默认安装。
- **安全与隐私**：轨迹和长期记忆可能包含个人数据；默认不得进入训练集，导出、训练、发布和高风险外部动作均需显式策略与审计。
- **开发流程**：本母变更完成细化后，应拆成按依赖排序的子 change；每个子 change 均需自动化测试、OpenSpec 严格校验、评测证据和相关文档同步。
