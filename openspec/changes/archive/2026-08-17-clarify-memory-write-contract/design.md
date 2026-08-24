## 背景：两阶段原则与现有合同

《ai-agent-book》第 8 章把“在线追加证据、离线集中整理”确立为持续进化的双循环：在线执行循环只完成任务并记录证据，不直接改写正式 Agent；离线进化循环聚合轨迹、诊断根因、生成候选修改，再通过验证门槛发布新版本（line 86、241、376）。第 3 章 User-as-Code 是同一思想的记忆版——只增不删的事实日志加周期性重建结构化用户模型（line 124）；Mem0 v3 进一步把冲突处理从写入期移到检索期，仅追加写入、按时间与多信号排序（line 222），并要求版本化冲突检测“保留历史版本同时标记最新版本”（line 249）。第 8 章还要求“不让同一个模型既当裁判又直接改写规则”（line 49）、“证据不足的偶发故障不应立即触发学习”（line 251），以及表 8-3 的分层评估指标。

`stabilize-triggered-memory-learning` 已把上述原则落地为同步写入合同：`basis_quote` 必须是当前用户消息的逐字子串（否则 `missing-explicit-basis`），系统从 `basis_quote` 确定性去除“请记住/记住/remember”指令包装得到权威正文，模型 `content` 必须与该正文经 NFKC 加空白归一后精确相等（否则 `basis-content-mismatch`）；`correct` 以同一显式证据合同创建修正事实并原子保存 corrects/supersedes 关系，旧事实与修订历史保持可审计。`complete-offline-memory-learning` 则把离线整理层（Worker、版本化 Extractor、Governance SubAgent、Candidate、派生投影、Card-first 分层召回）补成完整闭环。

本变更不重复上述两个变更的任何职责，只填补两者留下的两个缺口。

## 缺口一：模型不知道自己处于“在线证据层”

真实运行轨迹里，模型连续 4 次把用户原话改写后写入并全部被 `basis-content-mismatch` 拒绝。根因不是判定逻辑错误，而是**工具的模型可见描述与拒绝信息没有传达两阶段契约**：模型不知道 `remember`/`correct` 是只记证据的在线层、改写归离线层，因此本能地做第三人称转述与加注。

### 数据流与改动点

1. **工具描述（模型可见）**：`memory_manage` 的 `description` 与 `remember`/`correct` 参数描述 SHALL 增加一段两阶段契约说明——“本工具是在线证据层：`content` 必须与当前用户逐字 `basis_quote` 一致（可去‘请记住’包装），禁止改写人称、加注或润色；归纳、抽象、消歧与冲突合并属于离线整理层。”描述文本不复制用户正文，不泄露安全合同细节。
2. **拒绝信息（模型可见）**：`missing-explicit-basis` 与 `basis-content-mismatch` 的 `ToolResult.message` SHALL 指出违规类别并给出可自纠正的指引（“逐字引用当前用户消息中的原话，不得改写人称或加注”），`metadata.error` 保留稳定错误码供诊断聚合。
3. **判定逻辑不变**：`basis not in context.user_content` 与 `_same_fact` 精确相等检查保持原样；本变更不放宽合同，只让模型能预见并自纠正。

### 单次证据接受

同步层 SHALL 接受任何带合法逐字依据的显式用户陈述作为证据，即使该事实此前仅出现一次；是否升级为稳定语义记忆由离线整理层决定（`complete-offline-memory-learning` 的 Candidate→Governance→Card 投影，以及 `stabilize-triggered-memory-learning` 的显式去重）。这与第 8 章“证据不足不立即触发学习”不冲突——记的是证据而非结论，结论需经离线验证门槛。

## 缺口二：缺少分层评估，遵循失败被误读为规则错误

当前评测只产出端到端分数与官方检索 recall。第 8 章表 8-3 要求把更新器能力（harness-updating）与受益能力（harness-benefit）拆开评估：候选修改有效率、产物激活率、遵循成功率、留出任务增益。缺少分层指标会让人把“4 次 basis-content-mismatch”误判为“规则太严、应放松”，而它实为遵循成功率层面的 harness-benefit 失败——正确响应是改工具描述（缺口一），而非放宽合同。

### 指标定义（读取既有审计数据，不新增侵入式埋点）

- **候选修改有效率**：离线整理产出的 Candidate 经 Governance 批准并成功投影为 Card/语义索引的比例，证据来自 `memory.db` 的 governance decision 与 projection 状态。
- **产物激活率**：被召回的记忆是否在正确时机命中，证据来自 `memory_recall` 的召回轨迹与命中 ID。
- **遵循成功率**：`memory_manage remember/correct` 调用中通过逐字证据合同的比例；`missing-explicit-basis`/`basis-content-mismatch` 拒绝计为遵循失败，证据来自工具结果 `metadata.error`。
- **留出任务增益**：未参与整理的留出样本上，召回相关记忆后的回答质量相对基线的增益。

分层指标 SHALL 在报告中分别呈现，并与 LoCoMo/LongMemEval 官方分数并列，避免仅以端到端分数反推更新器好坏。

## 备选方案与取舍

- **放松合同（允许模型改写）**：被否决。违反第 8 章“不让同一个模型既当裁判又改写”（line 49）与“不篡改原始证据”（line 92），且破坏 `stabilize-triggered-memory-learning` 的反幻觉锚点。
- **仅改工具描述、不加分层评估**：不足以验证效果。无法区分“工具描述改好了”与“离线整理层承担了改写职责”，也无法在未来回归中及时发现遵循率退化。
- **把分层评估放进 `memory` 能力而非 `benchmarking`**：被否决。指标与报告聚合天然属于 `benchmarking`；`memory` 只负责可观测诊断，不负责跨 run 报告。

## 回滚

本变更只改工具描述、拒绝信息文案与稳定错误码，以及评测报告的可选指标项。回滚即还原文案与码、移除报告项；无 schema、配置或判定逻辑变更，回滚不涉及数据迁移。判定逻辑（`_same_fact` 与 `basis not in context.user_content`）始终不变，因此回滚不会留下半开的写入漏洞。
