## Why

真实运行轨迹显示，模型在 `memory_manage remember` 上连续 4 次因 `basis-content-mismatch` 被拒：把用户原话“我是 xky”改写成“用户是 xky”、“我喜欢红色”改写成“用户喜欢红色（偏好）”，而非逐字照抄。`stabilize-triggered-memory-learning` 已确立“当前用户逐字 `basis_quote` → 确定性去包装得权威正文 → 模型 `content` 必须与之精确一致”的反幻觉写入合同，但**工具的模型可见描述与拒绝信息没有向模型说明这是“在线证据层”、改写归“离线整理层”**，导致模型不知道应当逐字照抄而反复浪费调用。同时，记忆写入与离线整理闭环缺乏**分层评估**（候选修改有效率 / 产物激活率 / 遵循成功率 / 留出任务增益），使这类遵循失败被误读为“规则太严”而非“harness-benefit 失败”，也无法度量离线整理是否真正承担了改写与消歧职责。

依据《ai-agent-book》：第 8 章确立“在线执行循环只记录证据、不直接改写正式 Agent；离线进化循环聚合、诊断、生成候选修改并经验证门槛发布”（line 86、241、376），以及“不让同一个模型既当裁判又直接改写规则”（line 49）、“证据不足的偶发故障不应立即触发学习，而应继续积累样本”（line 251）和表 8-3 持续进化的分层评估指标；第 3 章 Mem0 v3 的仅追加写入与检索期解决冲突（line 222）、版本化冲突检测“保留历史版本同时标记最新版本”（line 249）、日志脱敏“不让敏感数据暴露在 LLM 上下文和系统日志中”（line 255）。

## What Changes

- 强化 `memory_manage` 工具的模型可见描述：显式说明 `remember`/`correct` 是**在线证据层**，`content` 必须与当前用户逐字 `basis_quote`（可确定性去除“请记住/记住/remember”指令包装）一致，禁止改写人称、加注（如“自称”）、润色或合并多句；归纳、抽象、消歧与冲突合并属于**离线整理层**，不由本工具完成。
- 强化 `missing-explicit-basis` 与 `basis-content-mismatch` 拒绝信息：指出具体违规类别（缺少当前用户逐字依据 / content 与依据不一致）、给出可自纠正的指引（逐字引用用户原话、不得改写），并保留稳定错误码供诊断聚合。
- 明确单次出现的显式用户陈述可作为**证据**被同步接受，但是否升级为稳定语义记忆由离线整理层决定；同步层不因“仅出现一次”而拒绝合法显式依据。
- 在评测能力中新增**记忆学习分层评估**：候选修改有效率、产物激活率、遵循成功率（将 `basis-content-mismatch`/`missing-explicit-basis` 拒绝计为遵循失败而非规则错误）、留出任务增益，并在报告中分别呈现，避免仅以端到端分数反推更新器好坏。
- 非目标：不新建或修改离线整理 Worker、Candidate Extractor、Governance SubAgent、触发阈值或 Embedding 配置（均属 `complete-offline-memory-learning` 与 `stabilize-triggered-memory-learning`）；不放宽逐字证据合同；不改变 `correct` 的版本化 supersede 语义；不引入在线自进化。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `tool-system`：强化受治理个人记忆工具的模型可见合同描述与拒绝信息，明确在线证据层与离线整理层的职责边界，使模型能自纠正逐字照抄。
- `benchmarking`：新增记忆学习分层评估指标与报告要求，区分更新器能力与受益能力。

## Impact

- **代码**：影响 `agent/tools/builtin.py`（`memory_manage` 工具描述、`remember`/`correct` 拒绝信息文案与稳定错误码）、工具描述聚合点与相关单元测试；评测侧影响 `benchmarks/` 指标聚合与报告生成。
- **公共合同**：`memory_manage` 工具描述与拒绝信息文本变化，错误码 `missing-explicit-basis`/`basis-content-mismatch` 稳定化并出现在工具结果 metadata；不改变工具参数 schema、不改变写入与拒绝的判定逻辑（`_same_fact` 精确相等与 `basis not in context.user_content` 检查保持不变）。
- **兼容性**：仅文本与诊断码变化；现有通过逐字写入的成功行为不变；无数据库迁移、无配置迁移。
- **安全**：拒绝信息仅指出违规类别与自纠正指引，不得回显用户原话之外的越权正文、不得包含 embedding 向量或 API key；遵循既有记忆诊断脱敏合同。
- **评估**：新增分层指标为可选报告项，与既有 LoCoMo/LongMemEval 官方评分合同正交，不影响官方分数计算。
