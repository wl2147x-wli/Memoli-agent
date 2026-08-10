## 1. 母变更评审与范围冻结

- [ ] 1.1 逐项评审 proposal 中 6 个新增能力与 8 个修改能力，确认名称、边界、依赖和非目标
- [ ] 1.2 回答 design.md 的 Open Questions，并把结论记录为明确设计决策
- [ ] 1.3 为总体路线建立当前 Runtime、Memory、Proactive 和 Benchmark 的可重复基线结果
- [x] 1.4 确认母变更仅作为架构蓝图，记录子 change 的创建、合并和归档策略

## 2. 在线执行基础细化

- [ ] 2.1 细化 `trajectory-observability` 的事件 schema、敏感字段、查询/回放接口和保留策略
- [ ] 2.2 细化 `agent-runtime` 的 step 状态机、预算、终止原因、无进展检测和 lifecycle 合同
- [ ] 2.3 细化 `durable-tasks` 的状态机、checkpoint、等待条件、恢复和幂等策略
- [ ] 2.4 细化 `tool-system` 的风险分级、权限、dry-run、审批、commit、取消和最终状态验证合同
- [ ] 2.5 为在线执行基础分别创建按依赖排序的小型 OpenSpec implementation changes

## 3. 长期个人学习能力细化

- [ ] 3.1 细化 `memory` 的记录 schema、来源证据、冲突处理、时间有效性、敏感等级和用户治理
- [ ] 3.2 通过对比实验决定第一版关键词、embedding、融合、rerank 和降级检索方案
- [ ] 3.3 细化 `skill-learning` 的 manifest、版本状态、多轨迹门槛、重放环境、canary 和回滚指标
- [ ] 3.4 细化 `proactive` 的机会评分、quiet hours、通知预算、重复抑制、解释和反馈指标
- [ ] 3.5 为 Personal Memory、Skill Learning 和 Proactive 分别创建独立 OpenSpec implementation changes

## 4. 扩展与多 Agent 边界细化

- [ ] 4.1 细化 `subagents` 的 profile、上下文隔离、工具 allowlist、预算、取消和结构化结果 schema
- [x] 4.2 细化 `plugins` 的 manifest、版本兼容、配置 schema、hook 排序和权限模型（由子 change `build-plugin-hooks-and-sandbox` 承接实现与验证）
- [ ] 4.3 细化 `mcp-tools` 的信任级别、连接健康、transport、工具风险继承和错误隔离合同
- [ ] 4.4 为 Reviewer、Research 和 Executor 三类 SubAgent 定义必须引入的外部证据及消融评测

## 5. 评测与安全治理细化

- [ ] 5.1 将 `benchmarking` 细化为统一 episode、确定性 verifier、LLM Judge、holdout、回归和报告合同
- [ ] 5.2 为 Memory、Runtime、Proactive、Skill 和 Evolution 定义数据集、基线、核心指标和发布阈值
- [ ] 5.3 细化 `safety-governance` 的数据用途、授权、脱敏、审批、删除、canary、审计和回滚矩阵
- [ ] 5.4 制定 Markdown 记忆、内存 Session 和现有 Benchmark 产物向新 schema 的幂等迁移与回滚测试

## 6. Evolution Lab 细化

- [ ] 6.1 审计 Hermes Self-Evolution Phase 1 的真实执行、fitness、constraint 和发布缺口并形成适配清单
- [ ] 6.2 细化 `evolution` 的 learning signal、失败聚类、候选 manifest、optimizer adapter 和 release gate
- [ ] 6.3 为 Skill、工具描述、检索策略和 Prompt section 分别定义真实 Memoli episode fitness
- [ ] 6.4 设计候选到 OpenSpec change 的证据、影响预测、delta specs 和评测报告映射
- [ ] 6.5 创建第一项低风险 Skill evolution 的独立 OpenSpec implementation change

## 7. Agent 后训练细化

- [ ] 7.1 选择首个后训练目标，并记录选择工具协议、记忆决策或失败恢复策略的对比依据
- [ ] 7.2 细化 `post-training` 的授权、脱敏、质量过滤、去重和按用户/任务族/时间切分的数据合同
- [ ] 7.3 定义基座模型、LoRA SFT、RFT 的可复现训练配置和相同条件评测矩阵
- [ ] 7.4 定义 RLVR 可接受的确定性环境、奖励、反奖励黑客检查和停止条件
- [ ] 7.5 创建 trajectory dataset builder 和首个 SFT/RFT 实验的独立 OpenSpec implementation changes

## 8. 求职作品集交付设计

- [ ] 8.1 设计“个人研究与工作助手”端到端演示脚本，覆盖记忆、工具、SubAgent、主动帮助、Skill 候选和模型对比
- [ ] 8.2 定义 Dashboard/报告最小展示面：trace、证据记忆、候选 diff、前后指标、成本、安全门禁和回滚
- [ ] 8.3 为每个实施阶段要求一个可运行示例、自动化测试、实验报告和架构决策记录
- [ ] 8.4 更新 README 路线图和 docs 导航，但保持未实现能力明确标记为 proposed

## 9. 变更质量门禁

- [ ] 9.1 检查所有子 change 的行为 delta 与本母变更一致，并消除重复或冲突的 Requirement
- [ ] 9.2 运行相关单元/集成/benchmark 测试以及 Ruff、Pyright，并保存无法运行检查的明确原因
- [ ] 9.3 运行 `openspec validate --all --strict` 并修复所有错误和警告
- [ ] 9.4 在全部能力已被实现或由已归档子 change 接管后，决定同步、拆分或归档本母变更
