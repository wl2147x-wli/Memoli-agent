## 1. 基线与配置合同

- [x] 1.1 核对已完成工具 change 与当前 canonical specs，消除 `update_working_checkpoint`、`memory_recall` 和默认工具列表的重叠合同
- [x] 1.2 为现有 Markdown 记忆、关键词召回、工作 checkpoint、passive turn 和 SQLite trajectory 增加不改变行为的回归基线
- [x] 1.3 扩展配置模型，加入 `memory.database`、自动检索、核心卡片、检索预算、consolidation 和 legacy import 配置并验证非法值
- [x] 1.4 增加独立 `working_memory` 配置、状态数据库路径、字符预算和 stale policy，并保证关闭个人记忆不影响工作记忆
- [x] 1.5 更新示例配置但不提交真实 workspace、数据库、密钥或用户记忆

## 2. 工作记忆数据与持久化

- [x] 2.1 定义确定性运行硬状态、语义 checkpoint、revision、patch 请求和渲染结果的数据合同
- [x] 2.2 实现 schema-versioned SQLite `WorkingStateRepository`，支持按 task/session 创建、读取、原子 patch、完成和显式恢复
- [x] 2.3 实现 expected revision 冲突检测，确保过期更新不能覆盖新 checkpoint
- [x] 2.4 实现新任务隔离、旧任务 stale 标记和显式恢复，不自动继承无关任务进度
- [x] 2.5 将 `update_working_checkpoint` 改为有界替换或结构化 patch，并返回新 revision 与实际状态

## 3. 确定性状态投影与统一注入

- [x] 3.1 实现从当前 turn、预算、工具结果和已提交轨迹增量计算硬状态的 projector
- [x] 3.2 保证完成步骤、产物和成功状态只来自可验证事件，未知字段渲染为 unavailable 而不是模型猜测
- [x] 3.3 实现区分 Harness 硬状态与 Agent 软 checkpoint 的 `<agent_status>` 有界 renderer
- [x] 3.4 在统一 prompt/context assembler 中接入最新工作状态，使首次、工具后续、重试和 fallback 模型调用使用同一路径
- [x] 3.5 将最新状态放在动态上下文末尾并只保留一个当前版本，同时保持静态 system 前缀稳定
- [x] 3.6 在 SQLite trajectory 中记录 checkpoint 更新、提交 revision 和每次模型实际可见的状态版本，不增加评价或训练标签

## 4. SQLite 个人记忆存储

- [x] 4.1 定义 claim、evidence、card、card version、claim-card relation、revision、consolidation run 和检索结果数据合同
- [x] 4.2 实现 schema-versioned `memory.db` 初始化、版本检查、事务和未知 schema 拒绝行为
- [x] 4.3 实现 append-only claims 与多对多 evidence repository，支持 message/event/trace 和 legacy file 来源
- [x] 4.4 实现版本化 cards、当前版本指针及 supports、corrects、contradicts、supersedes 和 derived-from 关系
- [x] 4.5 实现 candidate、active、frozen、superseded、rejected、deleted 状态和修订审计
- [x] 4.6 实现 user/session/project scope、时间有效性和敏感等级的存储与查询过滤
- [x] 4.7 在 bootstrap 中通过可替换协议装配 memory store、retriever、consolidator 和 working repository

## 5. Markdown 兼容迁移

- [x] 5.1 实现 `MEMORY.md` 只读解析和 migration preview，报告可解析、跳过和异常条目
- [x] 5.2 在导入前生成三个 legacy Markdown 文件的备份、内容哈希和 migration manifest
- [x] 5.3 将 `MEMORY.md` 条目在单事务中幂等导入为带 `legacy-import` 外部证据的 claims
- [x] 5.4 保证重复 migration 不产生重复 claim，失败事务不留下部分导入或推进 manifest
- [x] 5.5 明确跳过 `HISTORY.md` 与 `RECENT_CONTEXT.md` 的事实提升，并在迁移报告中说明原因
- [x] 5.6 停止在线追加 `HISTORY.md`，保留从权威 trajectory 生成确定性 Markdown 导出的只读能力

## 6. 双层记忆索引与检索

- [x] 6.1 实现核心 card 选择器，按 user/scope、active/frozen 状态、数量和字符预算生成结构化概览
- [x] 6.2 实现 cards/claims 的 FTS5 索引、原文规范化和受限 CJK n-gram 搜索字段
- [x] 6.3 实现从已提交 trajectory 构建带 trace 范围、时间、scope 和上下文前缀的可重建情景片段索引
- [x] 6.4 保证情景命中可解析回未改写的原始消息，索引删除重建不修改 trajectory 或重复片段
- [x] 6.5 实现 scope、状态、敏感等级、有效时间的检索前过滤，以及类型、明确程度和事件时间重排
- [x] 6.6 实现核心 card、claim 和情景片段的独立配额、去重、字符预算和稳定排序
- [x] 6.7 为每个命中返回稳定 ID、当前性、证据引用和召回理由，并记录候选数、过滤原因、注入 ID 与字符数
- [x] 6.8 实现 FTS5 不可用时的有界关键词/LIKE 降级并显式标记 degraded，且不引入 embedding 依赖

## 7. Memory Context 与工具治理

- [x] 7.1 实现使用当前用户消息、checkpoint objective 和 current step 的轻量自动预检索
- [x] 7.2 使用 `<memory_context trust="data">` 渲染个人记忆，防止历史网页、工具输出和 Assistant 文本冒充指令
- [x] 7.3 实现动态上下文预算优先级，保留当前交互、硬状态、用户约束和 frozen 核心卡片后再裁剪情景细节
- [x] 7.4 升级 `memory_recall`，支持类型、时间、scope 和数量过滤并返回结构化命中、证据和解释
- [x] 7.5 实现受治理的 `remember`、`correct`、`freeze`、`forget`、`list` 和 `export` 管理入口
- [x] 7.6 校验正式写入必须关联显式用户消息、人工主体或批准批次；无依据模型推断只能拒绝或创建 candidate
- [x] 7.7 实现删除立即停止召回、最小 tombstone 和 trajectory 独立保留说明，以及受 scope/脱敏约束的导出
- [x] 7.8 实现 memory disabled 和检索失败的结构化结果，使普通 Agent Loop 可观察降级而不注入伪造记忆

## 8. 离线 consolidation

- [x] 8.1 实现按未消费 trace 范围或 `start_long_term_update` 请求选择输入的 consolidation 调度入口
- [x] 8.2 实现逐段候选提取接口，并限制用户偏好/关系事实只从允许的用户证据产生
- [x] 8.3 实现固定 schema、source、scope、敏感字段和证据引用校验，隔离网页/工具文本中的指令
- [x] 8.4 实现 consolidation 稳定批次键、成功幂等、失败不推进 checkpoint 和安全重试
- [x] 8.5 实现 exact hash 去重、相关旧 claim/card 查找和冲突关系候选，不原地删除历史
- [x] 8.6 默认只写 candidate，并为显式用户事实、人工批准和 frozen 冲突分别实现发布门槛
- [x] 8.7 实现 Personal Memory、未来 Skill candidate、评测/后训练候选的分类边界，但本 change 只发布 Personal Memory

## 9. 自动化测试与评测

- [x] 9.1 测试硬状态由真实工具事件更新、软 checkpoint 不覆盖硬状态、未知字段不伪造
- [x] 9.2 测试每次模型调用都注入最新唯一状态，包括多轮工具、retry、fallback、重启恢复和新任务切换
- [x] 9.3 测试 memory schema、事务、未知版本、claims/card versions、关系、状态、scope、时间和敏感过滤
- [x] 9.4 测试 Markdown preview、备份、幂等导入、失败回滚和停止 HISTORY 双写
- [x] 9.5 测试中文 FTS5、降级 lane、核心概览预算、情景片段原始证据解析和检索解释
- [x] 9.6 测试显式记住、纠正、冻结、删除、导出、无依据写入拒绝和 memory disabled 行为
- [x] 9.7 测试 consolidation 幂等、candidate-only、冲突关联、失败不推进和证据/指令隔离
- [x] 9.8 使用书中三层框架建立基础回忆、多会话冲突/时序和主动关联基准，并报告 Recall@k、Precision@k、当前版本命中率、证据覆盖率、状态栏准确率、Token 和延迟
- [x] 9.9 分别评测记忆是否正确生成、是否正确召回、是否被 Agent 正确使用，避免只用端到端总分掩盖瓶颈

## 10. 文档、质量门禁与交付

- [x] 10.1 更新架构文档，说明五类状态、在线/离线双循环、双层记忆、信任边界和模块数据流
- [x] 10.2 更新配置、迁移、备份、恢复、禁用、诊断、用户治理和 Markdown 导出操作文档
- [x] 10.3 在代码中为关键 schema、事务、状态投影和信任边界添加简洁中文注释
- [x] 10.4 运行 `python -m pytest -q` 并修复本 change 引入的回归
- [x] 10.5 运行 `python -m ruff check memoli_agent benchmarks tests` 和 `python -m pyright`
- [x] 10.6 运行 `openspec validate --all --strict`，核对所有 task 与 scenarios 有验证证据后再标记完成
