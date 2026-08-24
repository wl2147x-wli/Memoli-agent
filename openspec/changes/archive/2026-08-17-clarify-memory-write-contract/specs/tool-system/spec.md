## MODIFIED Requirements

### Requirement: Governed personal-memory tools

启用个人记忆时，系统 SHALL 区分只读召回、显式正式写入、Candidate 治理操作与离线整理请求恢复操作，并支持显式记住、纠正、冻结、删除、查看、导出、有条件重试治理任务，以及对 consolidation dead-letter 执行有审计的 retry/suppress；显式正式写入 SHALL 以当前用户逐字依据为权威事实来源。`memory_manage` 工具的模型可见描述与拒绝信息 SHALL 向模型传达两阶段契约，使模型能预见逐字照抄要求并自纠正，而不得放宽判定逻辑。

#### Scenario: Tool description states the two-phase write contract

- **WHEN** 模型读取 `memory_manage` 工具描述或 `remember`/`correct` 参数描述
- **THEN** 描述 SHALL 说明 `remember`/`correct` 是在线证据层、`content` 必须与当前用户逐字 `basis_quote` 一致（可去“请记住/记住/remember”指令包装），并禁止改写人称、加注或润色
- **AND** 描述 SHALL 指出归纳、抽象、消歧与冲突合并属于离线整理层、不由本工具完成
- **AND** 描述 SHALL NOT 回显任何用户正文样本、embedding 向量或安全合同实现细节

#### Scenario: Rejection names the violation and points to self-correction

- **WHEN** `remember`/`correct` 因缺少当前用户逐字依据被拒绝
- **THEN** 工具结果 SHALL 返回稳定错误码 `missing-explicit-basis`
- **AND** 结果信息 SHALL 指出缺少当前用户消息中的逐字依据并要求逐字引用，而不得回显越权正文或包含 embedding 或 API key

#### Scenario: Content mismatch rejection points to verbatim copy

- **WHEN** `remember`/`correct` 的 `content` 与逐字 `basis_quote` 经 NFKC 加空白归一后不一致被拒绝
- **THEN** 工具结果 SHALL 返回稳定错误码 `basis-content-mismatch`
- **AND** 结果信息 SHALL 指出 `content` 与依据不一致、要求逐字引用当前用户原话且不得改写人称或加注
- **AND** 判定逻辑 SHALL 保持 `_same_fact` 精确相等与 `basis not in context.user_content` 检查不变

#### Scenario: Single explicit statement is accepted as evidence

- **WHEN** 模型对一条此前仅出现一次的显式用户陈述提供合法逐字 `basis_quote` 并以一致 `content` 调用 `remember`
- **THEN** 系统 SHALL 接受该证据写入
- **AND** SHALL NOT 仅因“该事实此前只出现一次”而拒绝
- **AND** 是否升级为稳定语义记忆 SHALL 由离线整理层决定，而非由同步写入工具决定

#### Scenario: Verbatim write still succeeds unchanged

- **WHEN** 模型逐字引用当前用户原话（仅去“请记住”指令包装）并调用 `remember`
- **THEN** 系统 SHALL 按既有合同创建权威事实、verified Evidence 与稳定身份
- **AND** 本变更对工具描述与拒绝信息的改动 SHALL NOT 改变该成功路径的返回结构
