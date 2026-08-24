## 1. 工具描述与拒绝信息

- [x] 1.1 在 `memory_manage` 工具的 `description` 中增加两阶段契约说明：`remember`/`correct` 是在线证据层，`content` 必须与当前用户逐字 `basis_quote`（可去“请记住/记住/remember”包装）一致，禁止改写人称、加注或润色；归纳、抽象、消歧与冲突合并属离线整理层
- [x] 1.2 在 `remember` 与 `correct` 参数描述中保留并明确 `basis_quote`“必须逐字来自当前用户消息”的语义，使模型在读取参数时即能预见逐字要求
- [x] 1.3 强化 `missing-explicit-basis` 的 `ToolResult.message`：指出缺少当前用户消息中的逐字依据、要求逐字引用，`metadata.error` 稳定为 `missing-explicit-basis`
- [x] 1.4 强化 `basis-content-mismatch` 的 `ToolResult.message`：指出 `content` 与依据不一致、要求逐字引用用户原话且不得改写人称或加注，`metadata.error` 稳定为 `basis-content-mismatch`
- [x] 1.5 确认 `_same_fact` 精确相等与 `basis not in context.user_content` 判定逻辑保持不变，仅文案与错误码稳定化

## 2. 单次证据接受

- [x] 2.1 在 `remember` 路径确认：任何带合法逐字依据的显式用户陈述均被接受为证据，`remember` 不得仅因“该事实此前只出现一次”而拒绝
- [x] 2.2 在工具描述中说明“是否升级为稳定语义记忆由离线整理层决定”，同步层不承担升级判定

## 3. 分层评估指标

- [x] 3.1 在评测指标聚合中增加“遵循成功率”：`memory_manage remember/correct` 通过逐字证据合同的比例，将 `missing-explicit-basis`/`basis-content-mismatch` 拒绝计为遵循失败
- [x] 3.2 增加“候选修改有效率”：经 Governance 批准并成功投影为 Card 或语义索引的 Candidate 比例，证据来自 `memory.db` governance decision 与 projection 状态
- [x] 3.3 增加“产物激活率”：被召回记忆在正确场景被命中并使用的比例，证据来自 `memory_recall` 召回轨迹与命中 ID
- [x] 3.4 增加“留出任务增益”：未参与整理的留出样本上召回相关记忆后的回答质量相对基线的增益
- [x] 3.5 在报告中将四项分层指标与 LoCoMo/LongMemEval 官方分数分别呈现，分层指标为可选项且不干扰官方评分

## 4. 自动化测试

- [x] 4.1 添加测试：`memory_manage` 工具描述包含两阶段契约关键词（在线证据层、逐字、禁止改写、离线整理层），且不含用户正文样本或 embedding 字样
- [x] 4.2 添加测试：`missing-explicit-basis` 与 `basis-content-mismatch` 的 `metadata.error` 稳定，且 `message` 包含逐字引用/不得改写的自纠正指引
- [x] 4.3 添加测试：单次出现的显式用户陈述带合法逐字依据时 `remember` 成功，且不因“仅一次”被拒
- [x] 4.4 添加测试：逐字写入成功路径的返回结构在文案改动后保持不变（回归保护）
- [x] 4.5 添加测试：评测聚合将合同拒绝计为遵循失败、分层指标与官方分数分开呈现，且未启用分层指标时不降级官方评分
- [x] 4.6 保持 `ruff check memoli_agent benchmarks tests` 与 `pyright` 在改动文件上无新增错误

## 5. 文档与验证

- [x] 5.1 在 `docs/systems/memory.md` 或对应记忆文档中补充“在线证据层与离线整理层”两阶段契约说明，并引用 `stabilize-triggered-memory-learning` 与 `complete-offline-memory-learning` 的职责边界
- [x] 5.2 更新评测文档，说明四项分层记忆指标的定义、数据来源与“遵循失败 ≠ 规则错误”的解读
- [x] 5.3 运行 `openspec validate clarify-memory-write-contract --strict` 与 `openspec validate --all --strict`，确保本变更 delta 与仓库全部通过
- [x] 5.4 在本变更的 proposal/design 中确认未与 `complete-offline-memory-learning`、`stabilize-triggered-memory-learning` 的职责重叠，非目标边界清晰
