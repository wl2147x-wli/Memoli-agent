## 1. Runtime 合同与配置

- [x] 1.1 新增带类型的循环结果、终止原因、步骤摘要和 turn 结果合同，并测试有效与无效的状态组合。
- [x] 1.2 新增 `agent.max_iterations`、`agent.max_elapsed_seconds` 和 `agent.no_progress_limit` 默认值及 TOML 解析测试。
- [x] 1.3 新增 `trajectory.enabled`、SQLite 数据库路径、内容采集模式、内联/payload 大小限制、payload 目录和额外敏感字段配置，并提供安全的本地默认值及解析测试。

## 2. SQLite 轨迹模型与存储

- [x] 2.1 为 trace 开始、模型请求/响应、工具意图/结果、循环决策和 trace 结束定义版本化的 trace、span、event 和 payload 记录，并测试稳定的 32 位十六进制 trace ID、16 位十六进制 span ID 及确定性序列化。
- [x] 2.2 定义初始 SQLite schema、外键、唯一 `(trace_id, sequence)` 约束，以及按 session、时间、结果、Provider、模型和 span kind 查询的索引。
- [x] 2.3 实现显式 schema 创建和顺序 migration 处理，并测试未知未来版本或 migration 失败时不会删除或重建已有数据。
- [x] 2.4 实现递归敏感字段脱敏、内容采集模式、有界降级序列化、压缩、内容哈希以及截断/外部引用标记。
- [x] 2.5 实现受管 payload 存储，支持内联文本、压缩 BLOB 和有界外部文件，并验证哈希、大小及 workspace 路径约束。
- [x] 2.6 实现用于隔离 Runtime 测试的内存轨迹存储，并断言事务可见的追加顺序和事件序号。
- [x] 2.7 实现单 writer SQLite 轨迹存储，启用外键、WAL、完整同步提交、busy timeout 和事件/投影原子更新。
- [x] 2.8 实现本地只读查询，能够按顺序重建 trace，并按 session、时间、终止原因、Provider、模型和 span kind 筛选。
- [x] 2.9 实现禁用状态下的 Null store，并验证其不创建数据库或 payload 记录，同时保持循环行为不变。
- [x] 2.10 从已提交的 SQLite 记录实现确定性、schema-versioned JSONL exporter，并验证重复导出不会修改源 trace。
- [x] 2.11 使必需 SQLite 事务失败对调用方可观察，并验证 `trace-write-failed` 后不会启动新的 Provider 或 Tool 操作；可选导出失败应可重试且不改变 turn 结果。

## 3. 极简串行 Agent Loop

- [x] 3.1 重构 Reasoner，使其返回结构化 turn 结果，同时保留直接无工具回复和现有 Provider fallback 元数据。
- [x] 3.2 实现单一串行 model/tool 循环，并按声明顺序执行一次模型响应中的多个工具调用。
- [x] 3.3 将关联工具结果追加到下一轮模型可见上下文，同时不把中间工具流量写入长期 Session 历史。
- [x] 3.4 为正常回复、空响应和 Provider 标识的截断响应实现轻量 CompletionGate。
- [x] 3.5 在后续模型或工具操作前执行最大迭代数和最长运行时间检查，并在不虚假声明完成的情况下返回 `budget-exhausted`。
- [x] 3.6 实现确定性的无进展指纹，并在重复相同失败动作达到配置阈值时停止循环。
- [x] 3.7 在模型、工具和循环决策周围持久化必需的 trace/span/event 记录，包括在副作用发生前提交工具意图，并为每个正常 Runtime 终止尝试写入最终 trace 记录。

## 4. 生命周期与 bootstrap 集成

- [x] 4.1 调整被动 turn 的 reasoning 和 after-turn 阶段以消费结构化 turn 结果，同时保持现有出站 Channel 消息兼容。
- [x] 4.2 在 bootstrap 中装配配置选择的 SQLite 或 Null 轨迹存储，不在 `main.py` 中加入持久化逻辑。
- [x] 4.3 确保 Runtime 关闭时先提交待处理的必需记录、关闭 SQLite 连接并释放 payload 资源，再停止依赖组件。
- [x] 4.4 将默认 SQLite 数据库、WAL/SHM sidecar 文件和 payload 目录加入版本控制忽略规则，并验证不会跟踪生成的轨迹数据。

## 5. 端到端验证

- [x] 5.1 增加脚本化 fake Provider 测试：任务需要连续两轮工具执行后才能生成最终回复，并断言完整且有序的 SQLite trace/span/event 层级。
- [x] 5.2 增加单次响应多工具、工具失败、`needs-user`、Provider fallback 和正常无工具完成测试。
- [x] 5.3 增加迭代预算耗尽、运行时间耗尽、空响应/截断重试及无进展终止的边界测试。
- [x] 5.4 增加崩溃前缀和事务回滚测试，证明已提交证据仍可查询、不完整 trace 不会被报告为成功且部分事务不可见。
- [x] 5.5 增加隐私测试，证明配置的秘密、Provider 凭证和隐藏 reasoning 不会出现在 SQLite、受管 payload 或 JSONL 导出中。
- [x] 5.6 增加 JSONL 导出测试，覆盖事件顺序、重复导出的确定性、payload 标记和导出失败隔离。
- [x] 5.7 运行完整测试套件、Ruff 和 Pyright，并解决本 change 引入的全部回归。

## 6. 文档与 OpenSpec 完成

- [x] 6.1 在 Runtime/开发文档中说明串行 Agent Loop、终止语义、轨迹事件顺序和配置。
- [x] 6.2 说明 SQLite schema 生命周期、本地隐私、payload 存储、磁盘占用、禁用模式、备份/导出流程及不完整 trace 的解释方式。
- [x] 6.3 运行 `openspec validate --all --strict`，并在标记 change 实现完成前解决全部校验错误。
