## Context

ToolRegistry 当前把 JSON Schema 仅作为 Provider 提示，不在执行边界校验；各工具手工校验不一致，已经造成 `memory_recall` 声明但忽略事实元数据、`memory_manage` 消费却无法声明这些元数据，以及容器 `code_run` 暴露 PowerShell 后必然失败的问题。

渐进披露的现有实现把 `_disclosed_tool_names` 保存为 Registry 进程级全局集合；ContextCompiler 则为 `(session, epoch)` 冻结首次收到的全部工具 schema。两者组合后，Registry 可以认为工具已披露，但同一 epoch 的 Provider 仍使用旧快照；不同 Session 还会共享披露状态。

## Goals / Non-Goals

**Goals:**

- 保证模型可见输入 schema 与执行代码逐字段一致，并在副作用前统一验证。
- 让 `code_run` schema 只描述当前 runner 真正支持的语言。
- 让 Tool Search 的发现、模型可见性、执行授权和重启恢复统一绑定 `(session_key, conversation_epoch)`。
- 维持基础 system/Skill/base-tool 前缀不变，把披露 schema 作为追加层处理。

**Non-Goals:**

- 不拆分 action 型工具，不引入统一输出 schema。
- 不增加语义/BM25 工具检索、MCP 分层路由或工具卸载。
- 不实现并行工具、后台进程事件或通用 Sidecar。

## Decisions

### 1. 使用 Draft 2020-12 统一验证输入

Registry 在注册时检查工具 schema 自身合法；执行时先验证模型原始参数，再运行 Policy Hook，并对 Hook rewrite 后参数再次验证。失败返回稳定 `ToolArgumentsInvalid`，不调用后续 Policy/Tool 或产生工具副作用。

选择 `jsonschema` 而非自制子集验证器，因为 MCP 输入 schema 可能使用组合、引用和嵌套约束；只实现内置 schema 子集会形成新的静默保真缺口。

### 2. 记忆参数按职责归位

`memory_recall` 移除不会进入 `MemoryQuery` 的 `fact_type/subject/entity/predicate/value/sensitivity`。`memory_manage` 声明其 remember/correct 路径实际消费的同名字段，并保留运行时默认值与敏感度下限策略。

本变更不为不同 action 引入 `oneOf`，因为工具拆分和 action 条件 schema 属 P1；P0 只保证已声明字段不被忽略、已消费字段可合法传入。

### 3. `code_run` schema 由实例能力生成

将 parameters 改为实例属性：container 仅给出 `python`；trusted-host 给出 `python`，并仅在启动时探测到 PowerShell 时加入 `powershell`；disabled runner 不注册 `code_run`。执行层继续保留同样的 fail-closed 检查，防止绕过 schema 的直接调用。

### 4. 披露状态持久化为 Context State 派生账本

新增 `(session_key, conversation_epoch, tool_name)` 唯一的 disclosure 记录，保存规范化完整 schema、schema hash、首次 tool call id 和创建时间。SQLite 使用 additive migration；InMemory Repository 提供同一合同。

`tool_search` 从当前 ToolExecutionContext 获得 session、epoch 和本次请求实际可见工具名，过滤已可见项，将匹配 schema 原子记录后返回完整 schema 与 hash。重复搜索幂等，不移动首次位置。

选择 Context State 而非 Registry 全局状态或只解析消息：账本天然按 epoch 隔离，可在历史 turn 被压缩后继续恢复，也不会让某个 Session 的搜索污染其他 Session。

### 5. 基础快照与披露层分离

ContextSnapshot 继续只冻结首次编译的 base tools，稳定前缀 hash 不因披露改变。每次 compile 从 Repository 读取当前 `(session, epoch)` 的 disclosures，按首次序号/工具名确定性追加到 effective tools，并计算 effective tool schema hash。Tool Search 的首次结果仍作为普通 tool result 固定在轨迹原位置。

Reasoner 把本次 `iteration_tools` 的名称集合放入 ToolExecutionContext。Registry 在渐进模式下只允许 base tool 或该集合中的 deferred tool 执行，避免模型猜测未披露名称绕过搜索。

### 6. 安全撤销覆盖基础与披露层

若基础快照或当前披露层包含已安全撤销工具，ContextCompiler fail closed；普通 unregister 只让执行返回不存在，不把旧 schema 隐式替换为同名新实现。

## Risks / Trade-offs

- [动态 tools 数组仍可能降低部分 Provider 的原生 Prompt Cache 命中] → 保持 base snapshot 和历史位置不变，并单独报告 effective schema hash；原生 `tool_search_output` 适配留给后续 Provider 专项。
- [严格校验暴露此前被工具忽略的非法调用] → 返回稳定字段路径和约束原因，补充所有内置工具回归测试。
- [SQLite migration 失败会阻止 Context State 启动] → 使用 additive v5 migration，并保留现有事务/版本检查与回滚。
- [PowerShell 可用性受宿主 PATH 影响] → schema 在 Registry 构建时探测一次并在 epoch 内冻结，保持确定性。

## Migration Plan

1. 升级 Context State schema，新建空 disclosure 表；旧 Session 不推断或迁移进程内披露状态。
2. 新进程启动后，旧 epoch 的 base snapshot 保持有效；需要 deferred tool 时重新调用 `tool_search` 建立记录。
3. 若回滚，v5 新表可被旧代码忽略；公开记忆、轨迹和工作状态格式不变。

## Open Questions

无；语义检索、输出 schema 与 action 工具拆分留在后续优先级中处理。
