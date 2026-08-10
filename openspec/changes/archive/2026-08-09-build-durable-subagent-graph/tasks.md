## 1. 现有行为回归基线

- [x] 1.1 为现有 `spawn_subagent` 同步调用补充回归测试，固定 task id、profile、task directory 和结果返回行为
- [x] 1.2 为现有后台委派补充回归测试，固定立即返回 task id 和完成事件回流原会话的行为
- [x] 1.3 为 SubAgent 禁用状态、未知 profile、空指令和并发等待补充失败及边界测试
- [x] 1.4 为 `task.json`、`result.md` 的当前人类可读内容补充兼容基线，避免升级后破坏已有调试入口

## 2. 任务图数据契约与 SQLite 持久化

- [x] 2.1 定义带类型注解的 DelegationRequest、ContextPackage、StructuredSubAgentResult、AgentTask、TaskEdge、AgentMessage、AgentArtifact 和 TaskAttempt 数据契约
- [x] 2.2 定义任务状态枚举及合法转换规则，覆盖 pending、blocked、runnable、running、waiting_input、completed、failed、cancelled 和 interrupted
- [x] 2.3 实现任务图 SQLite schema 和幂等 migration，持久化任务身份、父子关系、状态、预算、时间、目录和结果摘要
- [x] 2.4 实现任务依赖、控制消息、产物索引和执行 attempt 的 SQLite 表、索引与外键约束
- [x] 2.5 实现异步 TaskGraphRepository 生命周期、事务写入和按根会话、task id、agent id 查询接口
- [x] 2.6 实现带期望旧状态的原子状态转换，确保同一 runnable 任务不能被重复领取
- [x] 2.7 实现 Task DAG 加边与环检测，非法依赖不得改变已有图
- [x] 2.8 为 schema migration、CRUD、状态转换、会话隔离、环检测和重复领取编写 SQLite 集成测试

## 3. Profile 能力装配与安全边界

- [x] 3.1 扩展 SubAgentProfile，声明工具 allowlist、网络、读写根目录、迭代、耗时、委派深度和是否允许继续委派
- [x] 3.2 实现 ProfileToolRegistryFactory，从已装配工具中构造全新的受限 registry，未授权工具不得出现在模型 schema 中
- [x] 3.3 实现 `research` profile 的只读文件、记忆召回和网页检索能力，并禁止 Shell、写入和继续委派
- [x] 3.4 实现 `coding` profile 的工作区只读、任务目录可写和默认禁网 Shell 能力，并拒绝写入主工作区其他位置
- [x] 3.5 实现显式选择的 `general` profile 受限能力合集，确保不会绕过 Hook 与 Sandbox
- [x] 3.6 为各 profile 的可见工具、文件越界、网络越权、Shell 越权和长期记忆写入拒绝编写安全回归测试

## 4. 独立 SubAgent Runtime

- [x] 4.1 实现 SubAgentRuntimeFactory，复用共享 Provider、fallback Provider、trajectory、HookBus 和配置创建每任务独立 Reasoner
- [x] 4.2 将 SubAgent 从 `max_tool_rounds=0` 单次生成升级为现有有界 Reasoner 工具循环，并使用 profile 的迭代和耗时预算
- [x] 4.3 为每个 SubAgent 分配独立 session key、trace id、root span、working-state namespace 和任务目录
- [x] 4.4 在子任务根轨迹记录 agent id、parent agent id、task id、parent task id、profile、depth 和 attempt 谱系属性
- [x] 4.5 确保子任务完整记录模型请求、工具意图、实际参数、原始/模型可见结果、终止和错误事件
- [x] 4.6 为正常完成、工具失败、无进展、迭代耗尽、时间耗尽、provider fallback 和轨迹写入失败编写 Runtime 测试

## 5. Context Package 与结果协议

- [x] 5.1 实现确定性 ContextCompiler，组合目标、验收标准、约束、已确认事实、显式记忆引用、产物引用和依赖结果
- [x] 5.2 确保 ContextCompiler 默认不复制完整主对话轨迹，并对大体积依赖产物只传递摘要和引用
- [x] 5.3 接入现有记忆召回服务，使 SubAgent 只能读取 Context Package 允许的相关记忆并记录召回轨迹
- [x] 5.4 实现结构化结果解析和验证，覆盖状态、结论、证据、产物、验收项、开放问题、剩余工作、使用量和错误
- [x] 5.5 实现非结构化最终文本的兼容降级，保留 conclusion 并标记 `unstructured_fallback`，不得伪造验收证据
- [x] 5.6 实现 task artifact 登记和路径/哈希/类型/大小持久化，大文件正文只保存在任务目录
- [x] 5.7 为上下文隔离、依赖摘要、记忆只读、结构化成功、部分完成、格式降级和产物登记编写测试

## 6. AgentGraphManager 与串行 Scheduler

- [x] 6.1 重构 SubAgentManager，通过 TaskGraphRepository 创建稳定 task id、agent id、parent/root 关联和初始 attempt
- [x] 6.2 实现依赖驱动 Scheduler，将无依赖任务置为 runnable，将未满足依赖任务置为 blocked
- [x] 6.3 实现前置任务成功后的直接后继重新计算和自动解锁
- [x] 6.4 实现前置任务失败、取消或中断时的阻塞原因记录，禁止自动把下游任务标记成功
- [x] 6.5 实现默认 `max_concurrent=1` 的执行容量控制，并保证提高配置后仍遵守依赖和原子领取规则
- [x] 6.6 实现默认 `max_depth=1` 的父子深度检查，超界委派返回可诊断错误且不创建任务
- [x] 6.7 集中登记活跃 asyncio task，确保 Runtime 终止后清理执行所有权并持久化唯一终态
- [x] 6.8 为串行顺序、多依赖解锁、依赖失败、容量等待、深度拒绝和终态竞争编写 Manager/Scheduler 测试

## 7. 查询、取消、恢复与完成回流

- [x] 7.1 扩展现有委派工具 schema，在兼容 `instruction/profile/background/parent_session_key` 的同时支持验收标准、上下文引用、依赖和预算参数
- [x] 7.2 实现按当前根会话隔离的 list/get 管理能力，返回状态、profile、父子关系、依赖、目录、时间和结果/错误摘要
- [x] 7.3 实现取消协议：先持久记录取消意图，再停止 Runtime，最终进入 cancelled 且至多发布一次终态通知
- [x] 7.4 实现启动恢复扫描，把没有活跃执行所有权的 running/waiting_input 任务转换为 interrupted 并保留原轨迹和产物
- [x] 7.5 实现显式 resume，为允许重试的 interrupted 任务创建新 attempt/trace 并重新排队
- [x] 7.6 对可能存在不可重复外部副作用的任务拒绝无确认自动恢复，并返回需要确认的状态
- [x] 7.7 更新后台完成事件，携带 task id、agent id、稳定终态和结果引用，并由 MessageBus 路由回原根会话
- [x] 7.8 实现完成事件幂等处理，取消竞争、重放或重复回调不得形成第二次完成通知
- [x] 7.9 为会话可见性、未知任务、取消竞争、启动中断、显式恢复、副作用确认和事件幂等编写集成测试

## 8. 人类可读导出与兼容

- [x] 8.1 将 `task.json` 扩展为 SQLite 任务记录的可读快照，包含身份、上下文摘要、依赖、profile 和预算
- [x] 8.2 将 `result.md` 扩展为结构化终态、结论、证据、产物、剩余工作、trace 和 attempt 的可读导出
- [x] 8.3 实现从 SQLite 重新生成缺失或损坏导出的能力，查询和调度不得依赖导出文件
- [x] 8.4 保持旧 SubAgent 任务目录可读但不自动导入，并为新旧目录并存编写兼容测试

## 9. Bootstrap、配置与运行时集成

- [x] 9.1 在 bootstrap 中集中装配 TaskGraphRepository、ProfileToolRegistryFactory、SubAgentRuntimeFactory、Scheduler 和 AgentGraphManager
- [x] 9.2 扩展 `[subagent]` 配置，加入数据库、最大深度、默认并发一、恢复策略和 profile 预算，并验证非法值
- [x] 9.3 保持主 Agent、Provider、ToolRegistry、HookBus、Sandbox、trajectory 和 working state 的现有可替换边界
- [x] 9.4 确保任务图数据库启动或 migration 失败时禁用 SubAgent 并返回可诊断错误，主对话仍可继续
- [x] 9.5 更新示例配置但不修改或提交用户 `config.toml`、workspace 数据和密钥

## 10. 文档、质量检查与 OpenSpec 同步

- [x] 10.1 更新 SubAgent 系统文档，说明 Agent Tree、Task DAG、消息记录、Context Package、Result 和主 Agent 唯一输出边界
- [x] 10.2 更新架构图、运行流程、配置说明和 roadmap，区分已有 one-shot 骨架与本变更实现后的真实能力
- [x] 10.3 在文档中明确第一阶段不包含 Peer-to-Peer Agent Teams、长期记忆直接写入、反馈评测闭环、跨机器执行和 Coding worktree 合并
- [x] 10.4 运行完整 `python -m pytest -q` 并修复本变更引入的回归
- [x] 10.5 运行 `python -m ruff check memoli_agent benchmarks tests` 并修复静态检查问题
- [x] 10.6 运行 `python -m pyright` 并修复类型检查问题
- [x] 10.7 运行 `openspec validate build-durable-subagent-graph --strict`，确保 proposal、design、增量 specs 和 tasks 一致且可实施
