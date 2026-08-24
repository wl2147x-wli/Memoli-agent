## 1. 配置、模型与数据库迁移

- [x] 1.1 在 memory 配置模型和示例配置中加入 offline worker、extractor、Governance SubAgent Profile/策略、独立证据阈值、重试、租约、批量与隐私字段，并保持 `consolidation_enabled = false` 的兼容默认值
- [x] 1.2 为长期整理请求、提取批次、结构化 Candidate、证据定位器、关系建议、governance job/decision 和治理审计定义带类型的 dataclass/枚举合同
- [x] 1.3 增加原子 SQLite schema 迁移，创建持久请求、governance job/decision 表并为 consolidation、projection、semantic-index job 增加租约、重试和 dead-letter 元数据
- [x] 1.4 扩展 Candidate 持久化结构以保存 extractor/schema/prompt/policy/model/segmenter 版本、输入哈希、事实结构和验证状态，同时保留现有稳定 ID
- [x] 1.5 实现请求、治理与派生 job 的创建、查询、条件领取、续租、完成、重试、取消、needs-user-review、dead-letter 和过期租约恢复 repository API
- [x] 1.6 添加数据库迁移、旧库兼容、未知版本 fail-closed、幂等建表和并发领取测试

## 2. 权威轨迹输入与证据校验

- [x] 2.1 为离线学习实现只读 Trajectory Source API，可按稳定游标或显式 trace 集合读取已完成、已脱敏且 scope 授权的消息段
- [x] 2.2 构造不可变 Source Segment 快照，记录 trace/message ID、role、顺序、时间、正文哈希和允许的处理策略，不复制任意调用方正文到请求表
- [x] 2.3 实现 Evidence Verifier，逐项校验 trace 完成状态、消息存在性、role、quote/offset、正文哈希、scope 和访问权限
- [x] 2.4 为 Episode、Claim、Card 和 Source Segment 落实独立的 `prompt_allowed`、`embedding_allowed` 与敏感等级判定，并在远程 provider 调用前再次执行策略校验
- [x] 2.5 添加不完整轨迹、伪造引用、偏移错误、跨 scope、Assistant 单独声称用户偏好、敏感内容和授权成功路径测试

## 3. 版本化 Candidate Extractor

- [x] 3.1 定义可替换的异步批量 `CandidateExtractor` 协议及固定结构化输出解析器，覆盖事实类型、主体、实体关系、有效时间、重要度、置信度、敏感度和证据定位器
- [x] 3.2 实现 deterministic extractor 测试适配器，使离线闭环的自动化测试不依赖网络或非确定模型输出
- [x] 3.3 实现正式 extractor 适配器及 bootstrap 工厂，凭据仅通过所配置的环境变量读取，并对超时、限流、无效响应和永久配置错误分类
- [x] 3.4 计算包含 extractor、schema、prompt/policy、provider/model、segmenter 和输入内容哈希的版本指纹与幂等批次键
- [x] 3.5 添加结构化输出缺字段、非法枚举、越权证据、临时 provider 故障、版本升级重跑和相同版本幂等测试

## 4. 整理批次与候选关系解析

- [x] 4.1 重构 `MemoryConsolidator`，令其根据持久请求加载权威 Source Segment，而不再接受任意正文 segment 作为事实来源
- [x] 4.2 在 extractor 后接入 Evidence Verifier，保证任一必需证据失败时整个批次不提交 Candidate、不推进消费 checkpoint
- [x] 4.3 实现同 scope exact-hash 去重，复用既有 Claim并按稳定 Evidence 身份幂等补充来源，不创建重复 Candidate、治理任务或投影
- [x] 4.4 实现结构化事实槽位检索和 supports 语义等价归并，治理通过后优先合并 Evidence 且不保留第二条当前近义 Claim
- [x] 4.5 实现带确定目标和 expected revision 的 corrects/supersedes 方案，并在批准事务中原子提交新 Claim approved、旧 Claim superseded、关系/审计与单个投影 job
- [x] 4.6 对重叠时态或无法可靠消歧的矛盾保留 Candidate、contradicts 与 `needs-user-review`，禁止猜测目标、批准或登记正式投影
- [x] 4.7 使用单一事务原子提交 consolidation run、Candidate/归并结果、关系、对应 pending governance job、请求状态和自动扫描 checkpoint，并保证失败回滚
- [x] 4.8 添加重复消费、精确重复 Evidence 合并、语义等价、纠正/替代、未决冲突、frozen、事务故障和 checkpoint 不越过失败批次测试

## 5. 离线 Worker 与 Runtime 生命周期

- [x] 5.1 实现有界 `OfflineMemoryWorker` 循环，组合本地 wake event 与轮询，按租约领取持久请求并限制批次大小和并发度
- [x] 5.2 在 bootstrap 中校验 extractor 配置并注入 worker；启用 consolidation 但 extractor 不可用时提供明确启动错误
- [x] 5.3 将 worker 纳入 Application/Runtime 启停顺序，实现停止领取、当前事务有界收尾和下次启动的过期租约恢复
- [x] 5.4 修改 `start_long_term_update`，只持久化请求并唤醒 worker，立即返回稳定 request ID 与状态且不等待提取
- [x] 5.5 将 Episode、Card 和 Semantic Index 的非必要维护移出在线消息泵关键路径，用户回复和下一轮 turn 不等待远程提取或 embedding
- [x] 5.6 保留一次性 `maintenance_tick` 作为测试/运维适配器，并确保空闲时没有新 turn 也能有界排空积压
- [x] 5.7 添加 worker 启停、空闲排空、在线非阻塞、优雅关闭、崩溃后恢复、重复 worker 竞争和 disabled 模式测试
- [x] 5.8 将治理调度器纳入 Runtime 生命周期和独立资源预算，复用 SubAgent Runtime 执行治理但以 `memory.db` governance job 作为权威事实源

## 6. Governance SubAgent、用户治理与 CLI

- [x] 6.1 扩展记忆服务以按 actor/scope 分页列出和查看 Candidate、证据、关系建议、版本与审核状态，响应中不得泄露越权正文
- [x] 6.2 新增不可写文件、不可联网、不可委派且仅允许治理专用工具的 `memory-governor` SubAgent Profile，并为预算覆盖和 bootstrap 注册添加测试
- [x] 6.3 实现绑定任务的 Candidate、已验证 Evidence 和同 scope 相关 Claim 只读工具，拒绝跨 scope、非绑定目标和未验证正文
- [x] 6.4 实现固定 approve/reject/needs-user-review/defer JSON 决定解析器和 deterministic Governor 测试适配器，记录 governor/profile/model/prompt/policy 版本
- [x] 6.5 实现确定性 Policy Gate，覆盖低风险白名单、显式证据、隐式候选至少两条独立 Trajectory 证据、反向证据、时态、敏感度、冲突和 frozen 保护
- [x] 6.6 实现 Candidate 决定的 compare-and-set 与幂等事务，原子记录 actor/revision/reason/evidence/版本、治理 job 状态并登记 Card 与语义索引派生 job
- [x] 6.7 将自动 reject 限制为客观无效、越权、非法 schema、确定性重复和禁止存储类型，将不确定/高风险候选安全升级为 needs-user-review
- [x] 6.8 扩展 `memory_manage` 的 list/show/approve/reject/review/correct 操作 schema，使用户可覆盖自动决定并确保 Extractor、Worker 和普通 Assistant 无治理批准权限
- [x] 6.9 增加长期整理与治理请求的 get/list/status/retry/cancel 诊断入口，返回状态、尝试次数、安全错误分类、待用户审核数量和 backlog 信息
- [x] 6.10 在 CLI 状态区或记忆状态视图显示当前 scope 的 `needs-user-review` 数量，并实现 `/memory candidates` 或等价命令的列表与详情展示
- [x] 6.11 在 CLI 实现带 Evidence/风险/自动决定摘要和确认步骤的 approve/reject 操作，复用治理服务且不直接访问 SQLite、不阻塞输入渲染
- [x] 6.12 添加权限、Prompt Injection、两条独立证据、敏感升级、自动拒绝、stale revision、幂等批准、用户覆盖、frozen 保护、CLI 历史渲染和工具快照测试

## 7. 派生维护的恢复与吞吐

- [x] 7.1 将 Card projection、Episode projection 和 Semantic Index job 统一到可领取、可续租、可恢复、有限重试和 dead-letter 的状态语义
- [x] 7.2 实现 provider 能力范围内的真实批量 embedding 调用，并保证远程请求前执行 `embedding_allowed` 和敏感度过滤
- [x] 7.3 实现临时错误指数退避、永久错误直接 dead-letter、达到最大尝试次数停止，以及运维显式重试
- [x] 7.4 增加不含敏感正文的 backlog、最老任务年龄、租约、重试、dead-letter、吞吐和最近错误诊断
- [x] 7.5 添加进程中断、租约过期、批量部分 provider 失败、索引版本替换清理、隐私过滤和积压排空测试
- [x] 7.6 扩展 CardBuilder 的 eligible Claim 选择，排除 candidate/rejected/superseded/deleted/过期/无 Evidence 以及被正式 corrects/supersedes 关系支配的目标
- [x] 7.7 在 CardBuilder 中按结构化事实槽位检测仍未解决的不兼容当前 Claim，使 projection job fail-closed/needs-user-review 并保留上一 CardVersion
- [x] 7.8 保持 `(scope, subject, card kind)` 稳定 Card ID和确定性 statement/Claim 引用；输入不变返回 unchanged，变化时原子追加版本、替换 supports 关系并登记索引
- [x] 7.9 添加 Card 精确不变、Evidence-only 更新、supersede、未决矛盾、无支持语句、稳定顺序、版本历史和 frozen 跳过测试

## 8. Card-first 分层记忆检索

- [x] 8.1 扩展 MemoryQuery/Result 和配置合同，支持 auto/card-first/claim-first/episode-first/hybrid、summary/fact/evidence 及 statement/claim/evidence 展开预算并保持旧调用兼容
- [x] 8.2 增加 `card_statements` 和 `card_statement_claims` schema/迁移，保存版本、顺序、正文哈希、敏感度和有序 Claim refs，并保证只有当前版本进入默认召回
- [x] 8.3 修改 Card 发布事务以原子写入 CardVersion、结构化 statement/Claim 映射、当前版本切换和 statement 索引 job，失败时保留上一完整版本
- [x] 8.4 实现确定性查询路由器，使稳定画像/偏好/概览走 Card-first，精确/当前/来源/高风险走 Claim-first，事件/过程走 Episode-first，不确定查询使用有界 hybrid
- [x] 8.5 为当前 Card statement 实现 keyword/semantic/metadata 检索与稳定排序，命中返回 card/version/statement/Claim refs 而不解析展示 Markdown
- [x] 8.6 实现 statement→Claim→Evidence 有界展开服务，在每层重新执行 scope、敏感度、生命周期、当前性和字符预算
- [x] 8.7 实现 Card missing/pending/retry/dead-letter/frozen-stale/no-match 时的 Claim 直达回退，并保持 Episode 独立检索和安全降级诊断
- [x] 8.8 在最终融合中按稳定 Claim refs 折叠 Card statement 与展开 Claim 的重复事实，保留贡献 lane/层级诊断且只计算一次事实预算
- [x] 8.9 扩展 `memory_recall` 工具 schema 和输出，支持路由、细节层级、命中 statement 的后续展开以及实际 route/degraded 元数据
- [x] 8.10 添加 Card 摘要即停、精确/高风险展开、Evidence 授权、投影故障回退、frozen-stale、Episode 路由、历史 statement 排除、跨层去重和重复快照确定性测试

## 9. 文档、迁移与运维说明

- [x] 9.1 更新记忆系统文档，说明权威轨迹、请求、worker、Candidate、Governance SubAgent、Policy Gate、用户升级、派生投影和 Card-first 分层召回的完整运行流程
- [x] 9.2 更新 Runtime、SubAgent、工具和 CLI 文档，说明生命周期、最小权限、失败隔离、检索路由/展开、命令/工具合同和诊断方式
- [x] 9.3 更新配置示例与安全说明，记录默认关闭、governor/profile/policy、独立证据阈值、分层检索预算、provider 凭据环境变量、远程处理隐私矩阵和 auto-scan 启用前提
- [x] 9.4 编写数据库备份、迁移、分阶段启用、回滚、dead-letter、Card/statement 重建、检索降级和 backlog 恢复运行手册

## 10. 完整验证

- [x] 10.1 使用项目 conda 环境运行离线记忆、轨迹、分层检索、工具、Runtime 和数据库迁移的定向测试并修复失败
- [x] 10.2 使用项目 conda 环境运行完整 `python -m pytest -q` 回归测试
- [x] 10.3 使用项目 conda 环境运行 `python -m ruff check memoli_agent tests` 和 `python -m pyright`
- [x] 10.4 运行 `openspec validate complete-offline-memory-learning --strict` 并修复全部变更级校验错误
- [x] 10.5 对照 proposal、design 和三组 delta spec 复核实现证据，仅在对应代码、测试和文档均完成后勾选任务
