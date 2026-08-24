## Context

Memoli 当前由 `ContextBuilder` 在 turn 开始时组合基础 system prompt、Skill catalog、Memory、Working Checkpoint、Session 历史和当前用户消息；`Reasoner` 在工具循环的每次 Provider 调用前移除旧状态并追加最新 Working State，同时把 assistant tool call 和 tool result 累积到本轮消息列表。Session 仅在内存中按消息条数滑动，Memory、Skill、Working State 和各工具分别限制字符数，Provider 能报告 usage 与上下文超限，却没有统一输入预算和可恢复压缩路径。

该状态有四个跨模块问题：第一，各块局部有界不代表总请求适配模型窗口；第二，动态 Memory/插件段位于较早位置、工具 schema 依赖运行时注册顺序，降低跨请求 Prompt Cache 命中；第三，长工具结果只做显示截断时会丢失可重新读取的模型证据，完整保留又会导致上下文腐化；第四，按消息条数滑动既可能破坏完整 turn，也会丢失早期决策并反复改变缓存前缀。

设计必须保持现有标准 API role/tool-call 关联、append-only trajectory、Memory/Working State/Skill 独立存储和 Provider 可替换性。压缩结果是当前任务的派生视图，不能成为原始证据，也不能绕过个人记忆治理。

## Goals / Non-Goals

**Goals:**

- 所有正式 Provider 请求从同一个可测试、可审计的上下文编译边界产生。
- 以模型输入窗口为单位执行全局 token 预算，并为输出、协议开销和估算误差预留空间。
- 最大化基础 system、Session Skill snapshot 和工具 schema 的字节级稳定性，把动态信息限制在尾部。
- 通过原文外置、确定性去噪、任务感知归档和紧急压缩支持长工具循环，并保留证据引用。
- 使正常压缩、紧急恢复、失败熔断和缓存 usage 都能通过同一 trace 观察。
- 旧配置和现有九/十工具调用合同继续工作，不要求迁移或重写已有数据库内容。

**Non-Goals:**

- 不重新定义静态 system prompt 的业务正文；该内容由独立提示词变更负责。
- 不改变长期记忆检索、Claim/Card 生命周期、Skill 发布或训练数据流程。
- 不依赖任一供应商专有的上下文编辑 API；支持时可作为后续适配优化。
- 不保证不同 Provider 或不同模型之间共享 Prompt Cache；只保证发送内容的确定性和可观测性。
- 不将隐藏推理作为通用压缩输入；Thinking block 的保留继续遵循 Provider 协议。

## Decisions

### 1. 在 Provider 前引入唯一 Context Compiler

每次模型调用前，Runtime 将基础 blocks、工具 schema、当前工作消息、召回记忆和最新状态交给统一编译器。编译器输出规范化 messages/tools、预算明细、块清单、哈希和压缩诊断；实际请求与轨迹记录均使用同一输出，避免“审计内容”和“Provider 内容”分叉。

选择 Provider 前编译而非仅扩展 turn 初始 `ContextBuilder`，因为工具结果和 Working State 会在同一 turn 内变化，预算必须在每次模型决策前重新评估。`ContextBuilder` 可保留为 block 生产者，但不再是最终预算裁决者。

### 2. 使用四区上下文布局

最终布局为：

1. **稳定静态前缀**：版本化基础 system prompt、Session 冻结的 Skill catalog、规范化工具 schema。
2. **不可变任务归档**：已经压缩并冻结的结构化 archive，按代次追加，不重写旧 archive。
3. **近期完整轨迹**：完整 turn 边界内的 user/assistant/tool 消息以及本轮工具循环。
4. **动态尾部**：当前相关 Memory、插件低权限 section 和最新 Working State。

静态安全规则永远在插件和外部数据之前。Memory、工具内容、插件段和 archive 即使以协议兼容的 system/user 消息承载，也必须有来源与 trust 标签，不能获得终端用户授权语义。动态尾部可以按预算重新生成；它不会改写静态前缀。

选择最新状态“末尾替换”，而不是永久累积所有状态版本。当前实现和 canonical working-memory spec 都要求模型只看到一个最新状态。替换只使尾部缓存失效，语义确定性优先于保存少量尾部缓存；轨迹仍保留每次历史 revision。

### 3. Session 冻结缓存关键材料

Session 首次编译时冻结：system prompt 版本/哈希、Skill catalog 文本/哈希、工具 schema snapshot/哈希和布局版本。工具 schema 按稳定键规范化排序，JSON 对象使用确定性序列化。普通插件激活、MCP 发现或 Skill active 指针变化只影响新 Session；安全撤销仍可使当前 Session 的受影响能力 fail closed，但不得静默换成另一个版本。

基础工具保持完整 schema。可选插件/MCP 工具数量较大时复用现有 `tool_search` 能力做渐进披露；是否开启仍由配置决定，本 change 不改变默认工具名称。

### 4. Token 预算属于模型 Profile

模型 Profile 新增：`context_window_tokens`、`context_safety_margin_tokens` 和可选 tokenizer/估算策略；context compaction 配置新增 soft/hard trigger ratio、recent tail、archive/preview 预算、最大压缩尝试等。可用输入预算计算为：

`context_window - max_output_tokens - safety_margin`

优先使用 Provider/模型适配的 tokenizer；不可用时使用明确标记为 estimate 的保守估算。编译器必须同时计入 messages、工具 schema 和协议固定开销。未知 context window 时使用保守内置值，而不是假定无限窗口。

预算保留优先级为：静态安全规则与当前用户输入、工具调用结构完整性、最新 Runtime 状态与用户硬约束、显式冻结核心记忆、不可变归档、近期证据、其他召回和低价值工具细节。不能通过切断 tool call/result 对或半条结构化消息满足预算。

### 5. 工具大结果采用无损原文与冻结预览分离

工具执行后先形成脱敏原始结果并写入现有受管 trajectory payload/artifact，再生成模型可见预览。预览包含来源、内容哈希、原始/可见大小、截断/压缩标志和可授权重读的稳定引用；同一结果一旦生成预览便持久化冻结，恢复或重编译不得重新措辞。

这复用现有 payload 基础设施，而不是创建任意工作区临时文件。模型重读仍必须经过现有工具、scope 和权限边界，引用本身不授予额外访问权。

### 6. 分层、批量且任务感知地压缩

编译器按以下顺序降载：

1. 复用已冻结预览并确定性删除可证明重复/空白/被替代的噪声。
2. soft threshold 触发时，对一批尚未压缩的旧工具结果生成任务感知 archive；输入包含当前目标、验收条件、Working Checkpoint 和来源引用。
3. archive 使用固定 schema 保存决策与理由、用户约束、事实与证据引用、文件/产物、验证状态、失败路径、TODO 和 remaining work；原始 payload 不删除。
4. hard threshold 或 Provider 输入超限时，保留近期完整 tail 后压缩更旧的完整 turn；必要时执行一次最终全量归档。

压缩在两次 Provider 调用之间批量发生，不每轮摘要。每个源消息/结果记录 `compacted_by`，已归档内容不重复进入后续摘要。旧 archive 不原地重写，新 archive 只追加，从而把缓存失效限制到新的归档边界。

摘要器使用显式配置的压缩模型 profile，默认可复用 agent profile；失败不得修改当前视图。连续失败达到阈值后打开当前 Session 的熔断器，停止自动压缩并返回可观察失败，避免递归烧费。

### 7. Session 历史按完整 turn 和归档管理

`history_window` 保留为旧配置兼容和硬消息上限，但主要选择单位改为完整 turn/token。系统不得留下孤立 tool result、缺少 result 的 tool call，或从 assistant 半轮开始的窗口。被移出近期 tail 的高价值内容先形成 archive，而不是直接丢弃；低价值内容可以在有明确诊断时删除。

Session archive 需要 schema-versioned 本地持久化，以支持进程恢复时使用相同冻结摘要和哈希。它与 `working-state.db`、`memory.db`、`trajectories.db` 分离；推荐在新 context-state SQLite 中保存 Session snapshot、archive generation、source refs、preview refs 和熔断状态。若关闭持久化，功能可退化为进程内 archive，但重启后不得声称恢复旧对话上下文。

### 8. 输入超限进行一次语义恢复，不做相同请求重试

`ContextLengthProviderError` 是不可通过同输入传输重试修复的语义错误。Reasoner 捕获该分类后，在同一 trace 中强制 hard compaction、重新编译并最多重试一次。重试前要记录原预算、触发原因和新上下文哈希。若已执行紧急压缩、压缩熔断或最小必需上下文本身仍超限，则以稳定 `context-budget-exhausted` 失败，不切换到窗口更小或能力不明确的 fallback。

### 9. 编译与缓存可观测性

每次编译记录 layout version、block 类型/来源/trust、估算或实际 token、裁剪量、稳定前缀与工具 schema 哈希、archive generation、preview/原文引用和压缩原因。Provider 响应继续记录 `input_tokens`、`cached_input_tokens`、`cache_creation_input_tokens`；可计算时增加 cache hit ratio，但未知值不得填零冒充未命中。

轨迹只记录可观察消息和摘要，不保存 Provider 未返回的隐藏思考。压缩模型调用使用子 span，并关联所消费的 payload 与生成的 archive。

## Risks / Trade-offs

- [Token 估算与实际 tokenizer 不一致] → 使用 Provider 专用 tokenizer 优先、保守余量、估算标志和一次超限恢复；测试中覆盖中文、JSON 和工具 schema。
- [LLM 摘要丢失关键约束或决策理由] → 固定结构、明确不可丢字段、保留 source refs、近期完整 tail，并用回放/基准测试验证；原文始终在受管 payload。
- [压缩调用增加成本和延迟] → 仅在 soft threshold 批量触发，先做确定性外置/去噪，并记录压缩收益；连续失败熔断。
- [末尾状态替换仍破坏部分缓存] → 将状态严格放在尾部，限制大小；用 cache usage 评估后再考虑增量追加，不牺牲“唯一最新状态”合同。
- [Session 冻结工具快照与运行时撤销冲突] → 安全撤销优先并 fail closed；记录 snapshot 失效原因，不自动替换为其他能力。
- [新增 context-state 持久化与现有数据库边界复杂] → 独立 schema、增量创建、外键只引用稳定字符串 ID；关闭/回滚时旧数据库保持可读且不影响 Agent 基础运行。
- [动态 Memory 后移可能改变模型行为] → 保留 trust 和来源边界，通过集成测试与 memory benchmark 对比召回使用率；当前用户与状态的尾部位置优先。
- [不同 Provider 对尾部 system/user Harness message 支持不同] → 编译器产生逻辑 block，由 Provider dialect 映射为合法消息，不手写 Chat Template。

## Migration Plan

1. 先加入配置和只读 token 诊断，默认不压缩，通过 shadow compile 对比当前请求内容。
2. 引入确定性工具 schema、稳定前缀哈希和工具结果冻结预览；不改变短结果行为。
3. 创建独立 context-state schema，首次使用时增量初始化；不迁移旧 trajectory 或 Session 内存历史。
4. 启用四区布局和完整 turn 选择，保留 `history_window` 兼容上限。
5. 依次启用 soft compaction、archive 持久化和一次紧急恢复，并通过配置提供总开关。
6. 回滚时关闭 context compaction，恢复现有 ContextBuilder/Reasoner 路径；新 context-state 和 payload 保留但不消费，既有 Memory、Working State、Skill 和 trajectory 无需回滚。

## Open Questions

- 第一版是否引入模型原生 tokenizer 依赖，还是先以 Provider 可插拔接口和保守估算实现？任务中先实现接口与 deterministic estimator，并为可选 tokenizer 留扩展点。
- context-state 独立数据库的默认路径与保留策略是否跟随 trajectory？建议默认 `workspace/context-state.db`，保留策略暂与 Session/trajectory 生命周期解耦并在文档中明确。
- 压缩模型是否允许单独 route/profile？建议支持可选 `context_compaction` route，未配置时复用 agent route，但禁止 fallback 到 Echo 生成正式 archive。

