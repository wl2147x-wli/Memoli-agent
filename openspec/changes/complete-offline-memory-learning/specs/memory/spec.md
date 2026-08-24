## MODIFIED Requirements

### Requirement: Candidate-only offline consolidation

系统 SHALL 在在线 turn 之外按未消费的已提交轨迹范围或持久化长期整理请求执行幂等、版本化 consolidation；系统 SHALL 只从当前主体有权读取的权威 trajectory 构造输入、回查原始证据，并 SHALL 将隐式提取结果保存为 candidate 而不是直接发布为正式核心记忆。

#### Scenario: A consolidation batch succeeds

- **WHEN** 离线 Worker 领取一个持久请求或选择一组尚未消费的已完成轨迹
- **THEN** 系统 SHALL 从权威 trajectory 构造带 source reference 和内容哈希的输入，执行版本化提取、schema/scope/source/证据校验、相关记忆对比并记录稳定批次键
- **AND** Candidate、关系、run 状态和消费 checkpoint SHALL 在同一事务中提交
- **AND** 隐式偏好、关系或归纳事实 SHALL 先保持 candidate，直至独立 Governance SubAgent 的决定通过确定性 Policy Gate 或允许的用户/人工主体批准

#### Scenario: Consolidation is retried

- **GIVEN** 相同 scope、来源集合和 extractor/schema/policy 版本已有成功 consolidation 批次
- **WHEN** 该批次被重复请求
- **THEN** 系统 SHALL 返回既有结果或幂等跳过
- **AND** SHALL NOT 重复创建相同来源和证据的 claim

#### Scenario: Extractor version changes

- **GIVEN** 相同轨迹范围已有旧 extractor 版本的成功批次
- **WHEN** 操作者用新的 extractor、schema 或 policy 版本显式重跑
- **THEN** 系统 SHALL 创建可区分的新 run 并继续按 scope、来源和证据去重 Candidate
- **AND** SHALL 保留旧 run 的版本、结果和审计状态

#### Scenario: Consolidation fails before commit

- **WHEN** 轨迹读取、提取、证据回查、关系校验或数据库事务失败
- **THEN** 系统 SHALL NOT 推进已消费 checkpoint或留下部分 Candidate/关系
- **AND** 已发布 memory 和原始 trajectory SHALL 保持不变
- **AND** run SHALL 记录不含敏感正文的失败分类和可重试状态

#### Scenario: Incomplete or unauthorized trace is selected

- **WHEN** 请求引用未完成、已删除、越权或不属于请求 scope 的 trajectory
- **THEN** 系统 SHALL 拒绝或跳过该来源并记录可审计原因
- **AND** SHALL NOT 将该来源正文发送给 Extractor 或写入 Candidate

#### Scenario: Consolidation is disabled

- **WHEN** `consolidation_enabled` 为 false
- **THEN** 系统 SHALL NOT 启动离线提取 Worker或自动扫描轨迹
- **AND** 显式 Claim 写入、Episode 投影和普通记忆召回 SHALL 保持可用

### Requirement: Deterministic hybrid memory retrieval

系统 SHALL 在可用时继续通过 keyword、semantic 和 metadata lanes 检索候选、在最终选择前执行治理过滤、按稳定记忆身份去重并使用确定性 Reciprocal Rank Fusion；系统 SHALL 在 `auto` 模式按查询意图选择 Card-first、Claim-first、Episode-first 或有界 hybrid 路由，并 SHALL 支持从当前 Card statement 沿结构化关系按需展开 Claim 和 Evidence。最终上下文 MUST 遵守每类型数量、statement/claim/evidence 展开和总字符预算，并 MUST 暴露稳定 ID、记忆类型、Card/statement/Claim/Evidence 引用、检索原因、路由和降级状态。

#### Scenario: Multiple lanes return relevant memory
- **WHEN** keyword、semantic 和 metadata lanes 为当前路由返回相关候选
- **THEN** 系统 SHALL 按配置的确定性 lane 权重、RRF 常量、类型预算和总预算执行过滤、去重、融合与选择

#### Scenario: The same memory appears in multiple lanes
- **WHEN** 两个或多个 lane 返回相同稳定记忆身份
- **THEN** 最终结果 SHALL 只包含一个项目且诊断原因标识所有贡献 lane

#### Scenario: Candidates have equal fused scores
- **WHEN** 多个合格候选具有相同融合分数
- **THEN** 系统 SHALL 使用文档化的稳定类型、时间和 ID tie-break 顺序

#### Scenario: One retrieval lane is unavailable
- **WHEN** FTS5、Embedding Provider 或 semantic index 不可用
- **THEN** 检索 SHALL 通过剩余 lane 或允许的直接回退继续，标记不可用 lane 为 degraded，并继续执行全部治理与输出预算

#### Scenario: All searchable lanes produce no match
- **WHEN** 检索和硬过滤后没有合格候选
- **THEN** 系统 SHALL 返回带 candidate/filter 计数的空记忆上下文且不得注入空 memory block

#### Scenario: A type quota is not fully used
- **WHEN** 某个记忆类型的合格结果少于配置 quota
- **THEN** 未使用容量 SHALL 只按固定配置的 spillover 顺序重新分配且不得超过总数量或字符预算

#### Scenario: The same snapshot is queried repeatedly
- **WHEN** query、来源快照、Card/statement/index 版本、路由和检索配置均未变化
- **THEN** 重复检索 SHALL 产生相同顺序的稳定 ID、展开关系和降级元数据

#### Scenario: Stable profile query uses Card-first retrieval
- **WHEN** `auto` 路由将查询判定为稳定画像、偏好、配置或项目概览
- **THEN** 第一阶段 SHALL 优先检索当前 Card statement 并只选择有界摘要
- **AND** Card 摘要足够且没有精确、证据、高风险、冲突或降级触发条件时 SHALL NOT 展开全部关联 Claim

#### Scenario: Card statement requires authoritative detail
- **WHEN** 用户请求依据、精确值或时间，查询为高风险，Card stale/degraded/冲突，摘要不足或调用方显式请求 fact/evidence 细节
- **THEN** 系统 SHALL 沿命中 statement 的持久 Claim refs 有界展开当前 Claim，并在需要时继续沿 EvidenceRef 展开授权来源
- **AND** SHALL NOT 通过解析展示 Markdown 或无界全库 Claim 搜索确定 statement 的来源

#### Scenario: Card projection cannot represent the latest fact
- **WHEN** Card 不存在、projection pending/retry/dead-letter、Card frozen 且可能滞后、Card 无匹配或查询明确要求最新权威事实
- **THEN** 系统 SHALL 使用受治理的 Claim 直达回退并报告 Card 降级原因
- **AND** SHALL NOT 因派生 Card 不可用而隐藏有效 active/approved/frozen Claim

#### Scenario: Event query bypasses Card-first routing
- **WHEN** `auto` 路由将查询判定为历史事件、执行过程或某次任务结果
- **THEN** 系统 SHALL 直接使用 Episode-first 检索并保持 Episode 的来源引用
- **AND** SHALL NOT 把 Episode 当作正式用户事实或要求先命中 Card

#### Scenario: Current CardVersion is published
- **WHEN** CardBuilder 发布新的当前 CardVersion
- **THEN** 系统 SHALL 原子保存有序 Card statement、statement content hash 和 statement-to-Claim 映射，并只让当前版本进入默认 keyword/semantic 检索
- **AND** 历史 statement SHALL 保持可审计但不得作为当前结果返回

#### Scenario: Card and expanded Claim overlap
- **WHEN** 最终候选同时包含 Card statement 和其展开的相同 Claim
- **THEN** 系统 SHALL 按稳定 Claim refs 折叠重复事实并只计算一次事实内容预算
- **AND** 结果 SHALL 保留 Card、statement、Claim 和贡献 lane 的可追踪元数据

## ADDED Requirements

### Requirement: Durable offline-memory requests

系统 SHALL 将长期整理请求持久化为可查询、可恢复的版本化状态，并 SHALL 保存稳定 request ID、来源、scope、trace 选择边界、状态、尝试次数、租约、版本指纹和安全错误分类。

#### Scenario: Runtime restarts with a pending request

- **WHEN** Runtime 在持久请求尚未完成时关闭并重新启动
- **THEN** 请求 SHALL 继续保持 pending/retry 或在租约过期后恢复为可领取状态
- **AND** SHALL NOT 因重启丢失请求或重复提交已完成候选

#### Scenario: Worker crashes while processing

- **WHEN** Worker 在领取请求后未提交结果且租约到期
- **THEN** 系统 SHALL 使请求重新可领取并保留尝试次数及上次错误分类
- **AND** 另一个 Worker SHALL NOT 在有效租约内并发消费同一请求

#### Scenario: Retry budget is exhausted

- **WHEN** 请求达到配置的最大尝试次数或发生永久 schema、权限或配置错误
- **THEN** 系统 SHALL 将请求转入 dead-letter 或等价终态
- **AND** SHALL 允许操作者查看安全诊断并显式重试，而不自动无限循环

### Requirement: Versioned candidate extraction contract

系统 SHALL 通过可替换 Extractor 从权威 Source Segment 生成固定 schema 的 Candidate Draft，并 SHALL 为每个 run 记录 extractor、schema、prompt/policy、provider/model、segmenter 和输入内容版本；Candidate SHALL 支持自然语言事实、事实类型、subject/card kind、可选实体/属性、有效时间、重要度、置信度、敏感等级、explicitness 和 evidence locator。

#### Scenario: Extractor returns a valid draft

- **WHEN** Extractor 为允许 scope 内的完整来源返回符合当前 schema 的候选
- **THEN** 系统 SHALL 保留自然语言事实及提供的有效结构字段并进入证据回查和关系解析
- **AND** SHALL 将 Extractor 版本指纹关联到 run 和 Candidate

#### Scenario: Extractor returns malformed or unknown fields

- **WHEN** Extractor 输出无法按当前 schema 解析、包含未知类别或越界字段值
- **THEN** 本批次 SHALL 校验失败且不得部分提交
- **AND** 系统 SHALL 记录有界错误分类而不持久化原始 Provider 响应

### Requirement: Authoritative evidence verification

离线 Candidate 在提交前 SHALL 回查每个证据定位器对应的已提交 trajectory/message、role、逐字引用或 offset、内容哈希、scope 和访问权限；派生摘要、上下文前缀、Card 或 Assistant 陈述 SHALL NOT 单独证明用户事实。

#### Scenario: Explicit user claim has valid evidence

- **WHEN** Candidate 声明 `explicit-user` 且引用当前 scope 内真实 user message 的匹配原文
- **THEN** 系统 SHALL 保存稳定 Evidence reference、原文定位和来源哈希
- **AND** Candidate SHALL 继续进入提交阶段

#### Scenario: Evidence reference is fabricated

- **WHEN** message/trace 不存在、role 不匹配、quote 不在来源中、hash 已变化或 scope 越权
- **THEN** 系统 SHALL 拒绝整个批次或该规范规定的原子单元
- **AND** SHALL NOT 创建可召回 Candidate 或把越权正文发送给后续 Provider

#### Scenario: Tool or assistant text implies a preference

- **WHEN** 候选用户偏好仅由 Tool Result、Assistant 文本、摘要或上下文前缀支持
- **THEN** 系统 SHALL NOT 将其标记为 explicit-user 或批准为正式用户事实
- **AND** 可保留的事件性信息 SHALL 使用与其实际来源一致的类型和治理状态

### Requirement: Candidate conflict and governance lifecycle

系统 SHALL 在提交 Candidate 前对同 scope 的当前及历史记忆执行确定性去重和相关候选检索，并 SHALL 将支持、纠正、冲突、替代或不确定关系保存为可审计结果；系统 SHALL 为 Candidate 创建持久治理任务，并只允许独立 Governance SubAgent 经确定性 Policy Gate 或有权用户/人工主体批准 Candidate 进入正式状态。

#### Scenario: Candidate exactly duplicates current memory

- **WHEN** Candidate 与同 scope、同来源语义和证据身份的当前 Claim 完全重复
- **THEN** 系统 SHALL 幂等复用既有 Claim、按稳定 Evidence 身份补充尚未存在的来源并记录 duplicate 审计
- **AND** SHALL NOT 创建第二条当前 Claim、重复 governance job、重复 Card statement 或重复派生投影

#### Scenario: Candidate semantically supports an existing claim

- **WHEN** Candidate 与同 scope、相同事实槽位的当前 Claim 含义等价但措辞或 Evidence 不同，且关系解析结果为 supports
- **THEN** 治理通过后系统 SHALL 优先把新 Evidence 幂等合并到既有 Claim并保留来源/run 版本审计
- **AND** SHALL NOT 保留第二条语义等价的当前 Claim，除非 Evidence 证明它们是两个独立事实

#### Scenario: Candidate may contradict existing memory

- **WHEN** Candidate 与相关当前 Claim 在实体、属性或有效时间上冲突但无法确定优先级
- **THEN** 系统 SHALL 保存 candidate 和 `needs-user-review` governance 诊断或冲突关系
- **AND** SHALL NOT 自动 supersede、删除或覆盖现有正式记忆
- **AND** SHALL NOT 为该未决 Candidate 登记正式 Card/索引投影

#### Scenario: Approved correction supersedes an existing claim

- **WHEN** 有权治理决定批准一个具有确定目标、明确纠正意图或可排序有效时间的 corrects/supersedes Candidate
- **THEN** 系统 SHALL 在同一事务中把新 Claim 转为 approved、目标 Claim 转为 superseded、保存关系/actor/Evidence/revision 并登记一次 Card/索引投影
- **AND** 任一 expected revision、frozen、关系、证据或写入校验失败 SHALL 回滚全部状态和派生 job 变更

#### Scenario: Governance SubAgent approves a low-risk explicit candidate

- **WHEN** Candidate 有已验证的显式 user Evidence、属于配置的低风险白名单、同 scope 无冲突且 Governance SubAgent 提交 approve 决定
- **THEN** Policy Gate SHALL 重新校验证据、scope、风险、策略版本和 Candidate revision，并在全部通过后原子转为 approved
- **AND** 系统 SHALL 记录 governor/profile/model/prompt/policy 版本、reason codes、actor 和决定幂等键，再登记 Card/索引投影

#### Scenario: Governance SubAgent approves a low-risk implicit candidate

- **WHEN** 低风险隐式偏好至少由配置数量的独立已完成 Trajectory 一致支持、没有反向证据、时间有效且 Governance SubAgent 提交 approve 决定
- **THEN** Policy Gate SHALL 仅在独立 Evidence 数量至少为默认值二且所有硬规则通过时批准
- **AND** 单一模型置信度、单条行为证据或 Extractor 结论本身 SHALL NOT 足以触发批准

#### Scenario: Candidate requires user review

- **WHEN** Candidate 涉及凭据、身份认证、医疗、法律、财务、精确身份/地址、关系推断、高风险决策、敏感策略禁止项、正式记忆冲突或 frozen 记忆
- **THEN** Governance SubAgent/Policy Gate SHALL 将 governance job 标记为 `needs-user-review` 并保持 Claim 为 candidate
- **AND** CLI/治理接口 SHALL 能向有权用户展示安全摘要和审核入口而不默认召回该 Candidate

#### Scenario: Governance SubAgent rejects an objectively invalid candidate

- **WHEN** Candidate 证据客观无效或越权、schema 非法、确定性重复或属于禁止存储类型
- **THEN** Policy Gate MAY 将 Candidate 转为 rejected 并保存可审计 reason code
- **AND** 语义不确定、证据不足或关系无法消歧 SHALL 改为 defer 或 needs-user-review，而不是自动拒绝

#### Scenario: Governance decision is stale or exceeds authority

- **WHEN** 决定的 expected revision 不再匹配、scope 不一致、策略版本无效或决定试图覆盖 frozen/高风险记忆
- **THEN** Policy Gate SHALL 拒绝状态迁移并记录 stale/denied 结果
- **AND** SHALL NOT 登记 Card/索引投影或覆盖用户并发完成的决定

#### Scenario: User approves a candidate

- **WHEN** 有权用户或人工主体查看来源后批准其 scope 内 Candidate
- **THEN** 系统 SHALL 原子记录 actor、修订、证据和新状态，并登记对应 Card/索引投影
- **AND** 后续默认召回 SHALL 只按正式生命周期和时间规则使用该记忆

#### Scenario: User overrides or corrects an autonomous decision

- **WHEN** 有权用户查看自动治理审计后拒绝、重新审核或使用新显式 Evidence 修正该记忆
- **THEN** 系统 SHALL 通过合法生命周期和版本化关系保存用户决定，不抹除原 Governance Decision
- **AND** 后续 Governor SHALL NOT 使用旧 revision 覆盖用户决定

#### Scenario: User rejects a candidate

- **WHEN** 有权用户或人工主体拒绝 Candidate
- **THEN** Candidate SHALL 进入 rejected 状态并停止默认召回和正式 Card 投影
- **AND** 系统 SHALL 保留最小审计和拒绝 actor，而不删除原始 trajectory

### Requirement: Conflict-safe evidence-backed Card projection

系统 SHALL 将 Card 构建为正式 Claim 的可重建、版本化物化视图；Card SHALL 按 scope、subject 和 card kind 分组，只包含带 Evidence、当前有效且未被正式 corrects/supersedes 关系支配的 active/approved Claim，并 SHALL 保留每条 statement 到 Claim 的直接支持关系。

#### Scenario: Approved claim schedules a card projection

- **WHEN** Claim 被批准或其 Evidence/生命周期改变且影响对应 `(scope, subject, card kind)`
- **THEN** 系统 SHALL 幂等登记该稳定 projection key 的 Card job
- **AND** Candidate、rejected、superseded、deleted、过期或无 Evidence Claim SHALL NOT 进入 Card 内容

#### Scenario: Card projection has unchanged canonical input

- **WHEN** 同 projection key 的规范化 title/content 和有序 Claim ID 集与当前 CardVersion 完全相同
- **THEN** Worker SHALL 返回 unchanged 且不得创建重复 CardVersion 或重复索引 job

#### Scenario: Card projection changes

- **WHEN** 当前有效 Claim 集或确定性 Card 内容相对现有版本发生变化
- **THEN** 系统 SHALL 复用稳定 Card ID并原子追加新 CardVersion、更新当前 supports 关系和登记语义索引 job
- **AND** 旧 CardVersion、历史 Claim 和 Evidence SHALL 保持可审计

#### Scenario: Dominated claim is excluded from a card

- **WHEN** 一个当前 approved Claim 通过正式 corrects 或 supersedes 关系支配旧 Claim
- **THEN** CardBuilder SHALL 排除被支配目标并只渲染当前事实
- **AND** SHALL NOT 在同一当前 CardVersion 中同时展示新旧不兼容值

#### Scenario: Unresolved contradiction reaches projection

- **WHEN** CardBuilder 在同一事实槽位和重叠有效时间发现两个无法排序的不兼容 active/approved Claim
- **THEN** Card job SHALL 安全失败或进入 `needs-user-review` 诊断且保持上一 CardVersion
- **AND** SHALL NOT 发布包含矛盾语句的新版本或把 Card 本身用作解决冲突的事实来源

#### Scenario: Card generator emits an unsupported statement

- **WHEN** Card draft 的语句为空、缺少 Claim ID、引用不可用 Claim或内容不能由所引 Claim 直接支持
- **THEN** 系统 SHALL 拒绝整个 Card draft并保持上一 CardVersion
- **AND** 派生失败 SHALL NOT 回滚或改变权威 Claim

#### Scenario: Frozen card receives an automatic rebuild

- **WHEN** projection key 对应的 Card 状态为 frozen
- **THEN** 自动 CardBuilder SHALL 跳过版本更新并记录安全结果
- **AND** 只有有权用户/人工主体可通过显式治理改变 frozen Card

### Requirement: Recoverable derived-memory maintenance

Card、Episode 和 Semantic Index 等派生维护 SHALL 使用有界批次、租约、可恢复状态、有界重试和 dead-letter 语义，并 SHALL 在没有新用户 turn 时继续按配置排空积压；派生失败不得改变权威 Claim、Card 历史或 Trajectory。

#### Scenario: Derived job is abandoned by a crashed worker

- **WHEN** 派生 Job 保持 running 但租约已过期
- **THEN** 后续 Worker SHALL 安全恢复该 Job 为可重试状态
- **AND** 完成操作 SHALL 使用条件更新防止双重发布

#### Scenario: Remote embedding handles a batch

- **WHEN** 多个允许远程处理的当前来源同时待索引且 Provider 支持批量输入
- **THEN** Worker SHALL 在配置批次与 Provider 限制内合并请求并分别原子发布有效结果
- **AND** 单项失败或过期 SHALL NOT 损坏其他权威来源

#### Scenario: Embedding model or version is switched

- **WHEN** 运维重建语义索引并切换 embedding 模型或版本
- **THEN** 系统 SHALL 清理该来源的旧语义索引并仅发布当前配置对应的索引
- **AND** 旧 embedding 版本 SHALL NOT 继续占用存储或参与召回

#### Scenario: Sensitive source forbids remote processing

- **WHEN** Episode、Claim 或 Card 的敏感策略禁止远程 Extractor 或 Embedding
- **THEN** Worker SHALL 在发出网络请求前过滤该来源并记录不含正文的策略结果
- **AND** 该来源 SHALL 继续通过允许的本地或非语义路径保持可用
