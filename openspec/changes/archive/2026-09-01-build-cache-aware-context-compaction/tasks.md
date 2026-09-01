## 1. 配置与数据合同

- [x] 1.1 为模型 Profile 增加 `context_window_tokens`、`context_safety_margin_tokens` 和 token 计数策略配置，补充正值、窗口余量及旧配置默认值校验测试。
- [x] 1.2 增加 context management 配置组，覆盖启用开关、soft/hard threshold、近期 tail、preview/archive 预算、持久化路径、紧急重试和压缩熔断上限，并同步 `config.example.toml`。
- [x] 1.3 定义 context block、预算明细、编译结果、冻结 snapshot、工具预览、archive generation 和压缩诊断的类型化数据合同。
- [x] 1.4 定义可插拔 TokenEstimator 端口和 deterministic 保守估算实现，覆盖中文、英文、JSON、工具 schema 与协议固定开销测试。

## 2. Context State 持久化

- [x] 2.1 创建 schema-versioned context-state SQLite repository，增量保存 Session snapshot、稳定哈希、archive、source refs、冻结 preview 和压缩熔断状态。
- [x] 2.2 实现 context-state schema 初始化、版本拒绝、事务回滚、幂等写入和并发安全测试，确保不修改 trajectory、memory、working-state 或 Skill 数据库。
- [x] 2.3 实现禁用持久化时的进程内 repository，并测试重启后不伪称恢复旧 Session 历史。
- [x] 2.4 为 context-state repository 增加安全关闭、只读诊断和可恢复失败边界，并在 bootstrap 生命周期中装配。

## 3. 稳定前缀与确定性工具快照

- [x] 3.1 实现基础 system prompt/Layout 版本、Session Skill catalog 和工具 schema 的首次冻结、规范化序列化与稳定哈希。
- [x] 3.2 将 Tool Registry schema 输出改为稳定键排序，覆盖不同注册顺序、插件工具和 MCP 工具产生相同规范化 snapshot 的测试。
- [x] 3.3 实现 Session 中普通 Skill/插件/MCP 变化不重写冻结前缀，以及安全撤销 fail closed 且不静默换版本的测试。
- [x] 3.4 调整插件 context section 顺序和 trust/source 包装，保证基础静态安全规则始终位于插件内容之前并为插件总量设置预算。
- [x] 3.5 验证 Tool Search 启用时按需 schema 首次追加并冻结、禁用时完整确定性 snapshot 保持现有默认工具合同。

## 4. 统一上下文编译器

- [x] 4.1 实现 Provider 前唯一 ContextCompiler，组合稳定前缀、不可变 archive、近期完整轨迹和 Memory/插件/最新 Working State 动态尾部。
- [x] 4.2 实现全局输入预算计算，计入 messages、tools、最大输出预留、安全余量和协议开销，并在最小必需内容超限时返回 `context-budget-exhausted`。
- [x] 4.3 实现确定性块优先级和裁剪诊断，保证当前用户输入、安全规则、工具关联、最新真实状态、用户约束和冻结核心记忆不被低优先级内容挤出。
- [x] 4.4 将 Session 近期历史选择改为完整 turn/tool-call group 和 token tail，保留 `history_window` 作为兼容硬上限，并覆盖孤立 assistant/tool 消息防护测试。
- [x] 4.5 将 Memory 与唯一最新 Working State 放入动态尾部的明确 trust 边界，并回归验证 Memory disabled/degraded 和 Working State unavailable 行为。
- [x] 4.6 让轨迹预提交的 messages/tools 与 ContextCompiler 实际 Provider 输出共享同一不可变编译结果，防止审计/发送分叉。

## 5. 大型工具结果预览

- [x] 5.1 在工具结果进入模型上下文前，将超过预算的脱敏原文写入受管 trajectory payload/artifact，并生成包含 hash、大小、转换标志和稳定引用的预览。
- [x] 5.2 持久化并复用冻结预览，测试重复编译、Session 恢复和 fallback 不会重新措辞或改变引用。
- [x] 5.3 确保引用重读继续经过现有 workspace/scope/工具权限，不因 preview ref 绕过访问控制。
- [x] 5.4 为短结果、长文本、二进制/不可序列化结果、敏感字段脱敏和 payload 写入失败补充工具/轨迹集成测试。

## 6. 分层压缩与归档

- [x] 6.1 实现确定性噪声识别与去重，仅删除可证明为空、重复或被替代的低价值内容，并记录来源与原因。
- [x] 6.2 实现 soft threshold 批量选择尚未压缩的旧工具结果和完整 turn，防止重复选择已有 `compacted_by` 的来源。
- [x] 6.3 实现任务感知压缩请求与固定 archive schema，完整保留目标/约束、决策理由、事实引用、文件/产物、验证状态、失败路径、TODO 和 remaining work。
- [x] 6.4 将压缩调用作为可配置真实模型 route 的独立子 span 执行，禁止 Echo 生成正式 archive，并验证无效结构或 Provider 失败不会改变当前视图。
- [x] 6.5 原子提交不可变 archive generation 和 source refs，后续编译只追加新 archive、不重写旧 archive，并测试字节级恢复一致性。
- [x] 6.6 实现 hard/full compaction：始终保留配置的近期完整 tail，只有分层降载仍不足时才归档更旧历史。
- [x] 6.7 实现连续压缩失败熔断及显式恢复/重置边界，确保不会出现递归或无限压缩调用。
- [x] 6.8 验证 context archive 不会自动写入 Personal Memory、Skill、system prompt 或训练数据，且原始 payload 删除/权限变化后不能通过 archive 引用绕过治理。

## 7. Reasoner 与 Provider 恢复链路

- [x] 7.1 在 Reasoner 每次模型决策前调用 ContextCompiler，并移除现有分散的最终上下文装配逻辑但保留生命周期 block 生产职责。
- [x] 7.2 捕获 `ContextLengthProviderError` 后在同一 trace 内执行至多一次紧急 hard compaction、重新编译和 Provider 重试，记录前后上下文哈希。
- [x] 7.3 确保紧急重试不重复工具副作用、不使用相同超限输入循环重试，也不 fallback 到窗口能力未知或更小的模型。
- [x] 7.4 覆盖压缩成功恢复、最小上下文仍超限、熔断已开启、压缩 Provider 失败和 fallback 兼容性的 Reasoner 集成测试。
- [x] 7.5 按 Provider dialect 保留标准 Chat Template 角色、tool call id 和 Thinking block 合同，验证 OpenAI-compatible 与 Anthropic 请求均合法。

## 8. 可观测性与运行诊断

- [x] 8.1 为每次编译记录 layout version、block 来源/trust、token 策略与用量、预算、裁剪、哈希、archive generation、preview 引用和压缩原因。
- [x] 8.2 规范化保存 Provider `input_tokens`、`cached_input_tokens`、`cache_creation_input_tokens`，仅在字段存在时计算 cache hit ratio。
- [x] 8.3 在 RuntimeInspector/CLI 状态中增加只读 context budget、最近压缩和缓存 usage 摘要，不暴露原始敏感内容。
- [x] 8.4 增加稳定前缀回归测试：相同 Session 连续请求保持 system/tool/catalog hash，动态 Memory/状态变化仅改变尾部编译 hash。

## 9. 端到端验证与基准

- [x] 9.1 增加长工具循环端到端测试，验证上下文不超预算、关键决策/约束/验证/TODO 保留且不会重复工具调用。
- [x] 9.2 增加 context rot/压缩回放 fixture，比较无压缩、确定性预览和任务感知 archive 的完成结果及输入 token。
- [x] 9.3 增加中英文混合、大 JSON schema、多轮 Tool Search、Memory/Plugin 动态变化和进程恢复的边界测试。
- [x] 9.4 运行 `python -m pytest -q`、`python -m ruff check memoli_agent benchmarks tests` 和 `python -m pyright`，修复所有与本 change 相关的问题。

## 10. 规格、文档与归档准备

- [x] 10.1 更新上下文、运行链路、工具和记忆文档，说明四区布局、KV/Prompt Cache 边界、压缩层级、配置、故障恢复和数据保留关系。
- [x] 10.2 更新 `openspec/specs/agent-runtime`、`context-management` 和 `tool-system` 的实现一致性检查，并运行 `openspec validate --all --strict`。
- [x] 10.3 完成 change 验收清单，确认所有任务、测试证据、迁移/回滚说明和文档同步后再执行归档流程。
