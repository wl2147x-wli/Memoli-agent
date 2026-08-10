## Context

Memoli 已有统一 `Tool` 协议、工具注册表、串行多轮 Agent Loop、插件 `tool_pre` hook、MCP 适配器和 SQLite 完整轨迹。当前默认工具主要是时间、计算器、记忆读写、单文件读取与 SubAgent 委派，缺少完成真实文件与代码任务所需的最小闭环；已有 `ToolSearch` 也未接入推理链路。

GenericAgent 使用九个静态公开工具，以 `code_run`、三种文件工具、两个浏览器工具、工作 checkpoint、询问用户和长期更新信号覆盖大部分任务。其工具 schema 与行为适合作为 Memoli 的第一阶段基线，但 GenericAgent 的反射分发、同步生成器、前端交互、进程内 `eval/exec` 和会话后端不适合直接成为 Memoli Runtime 边界。

本 change 在 `simplify-agent-loop-with-trajectories` 已实现的串行循环和 SQLite 轨迹之上工作。由于该 change 尚未归档，而 canonical `tool-system` 仍保留单次工具往返描述，实施前必须先同步并归档它，之后再以本 delta 更新 canonical 工具行为。

## Goals / Non-Goals

**Goals:**

- 采用 GenericAgent 的工具名称、参数语义、使用边界和错误恢复提示，形成默认九工具集合。
- 保持工具实现小而清晰，适配 Memoli 的异步协议、bootstrap 装配和可替换适配器边界。
- 让文件读取、精确修改、完整写入和通用代码执行形成可完成实际任务的闭环。
- 用工作 checkpoint 支持长任务，用 `ask_user` 支持明确暂停，用长期更新请求连接未来的离线进化流程。
- 在不引入任何评价字段的前提下，忠实保存以后处理器能够重放和派生的数据事实。
- 保持第一阶段串行执行，不实现工具并发、后台任务或事件驱动唤醒。

**Non-Goals:**

- 不在在线 Runtime 中生成 reward、Rubric、成功标签、工具选择评价或失败归因。
- 不实现轨迹清洗、任务切分、SFT/RL 导出或模型后训练。
- 不实现主动工具发现；默认工具数量足够小，继续静态提供 schema。
- 不让 `start_long_term_update` 自动修改记忆、Prompt、Skill、程序或模型参数。
- 不复制 GenericAgent 的 UI、Session、SOP、反射式 `do_<tool>` 分发或全局状态。
- 不在本 change 中确定浏览器后端产品选型；未配置适配器时浏览器工具保持不可见。

## Decisions

### 1. 采用 GenericAgent 行为契约，保留 Memoli 运行时结构

公开工具名称与主要 schema 参照 `GenericAgent/assets/tools_schema.json`，文件、代码和 checkpoint 行为参照 `GenericAgent/ga.py`。每个工具仍实现 Memoli 的显式 `Tool` 协议并通过 `ToolRegistry` 注册，不引入按方法名反射调用。

如直接复制具有实质性的 GenericAgent 代码或 schema 文本，保留 MIT 许可证要求和来源说明；优先按行为重写，避免携带无关的全局状态和前端依赖。

替代方案是把 GenericAgent 作为 Python 依赖直接导入。该方案会把同步生成器、浏览器全局状态和会话对象带入 Memoli，破坏可替换边界，因此不采用。

### 2. 默认九工具与可选工具集

默认模型可见集合固定为：

1. `code_run`
2. `file_read`
3. `file_patch`
4. `file_write`
5. `update_working_checkpoint`
6. `ask_user`
7. `start_long_term_update`
8. `time`
9. `memory_recall`

`web_scan` 与 `web_execute_js` 由同一个 Browser adapter 成对注册；`spawn_subagent` 继续由 SubAgent 配置控制，但不属于默认最小集合。现有 `calculator`、`memory_write` 和 `filesystem_read` 不再默认暴露：计算由 `code_run` 覆盖，读取由 `file_read` 覆盖，未经评价的经验不能由模型直接写入长期记忆。

工具 schema 在每次 Provider 调用时仍由注册表静态提供。只有当 MCP/插件工具规模明显增长时，才通过独立 change 接入工具发现。

### 3. 文件工具共享同一个 workspace 路径边界

三个文件工具使用同一个路径解析器：相对路径以 workspace 为根，规范化后的目标必须位于 workspace 内；拒绝越界路径、目录目标、符号链接或 junction 逃逸以及不支持的文本编码。第一阶段使用 UTF-8 普通文件。

`file_read` 支持 `path`、一基 `start`、`count` 和 `show_linenos`，按行分页并显式标记裁剪。

`file_patch` 只在 `old_content` 非空且恰好出现一次时执行精确替换。空白、缩进、Unicode 引号与换行不得静默规范化；零次或多次匹配都返回可恢复错误并提示重新读取。

`file_write` 要求 `content` 显式出现在工具参数中，支持 `overwrite`、`append` 和 `prepend`。不从 Assistant 普通文本或代码块隐式提取写入内容。第一阶段不支持 GenericAgent 的文件片段引用语法，形似引用的文本按普通内容原样写入；未来若增加显式展开机制，模型原始参数与展开后的实际内容必须分别记录，引用越界或解析失败时不得写文件。

替代方案是只提供 `code_run` 让模型自行操作文件。它工具更少，但无法提供精确 workspace 约束、稳定错误和清晰轨迹，因此保留三个专用文件工具。

### 4. `code_run` 使用隔离子进程而非进程内执行

`code_run` 接收显式 `script`、`type`、`timeout` 和 `cwd`。第一阶段支持 Python 与当前平台可用的 PowerShell，通过 asyncio 子进程执行临时脚本；不支持 GenericAgent 的 `inline_eval`，也不向脚本注入 handler、父 Agent、会话历史或其他 Runtime 内部对象。

`cwd` 默认 workspace 且不得越界。结果区分 stdout、stderr、exit code、超时和启动错误。模型可见输出受配置上限约束，完整的脱敏输出进入已有受管 payload；超时后终止当前子进程，不在本阶段管理后台进程树或恢复任务。

该设计不是强安全沙盒。它提供明确的本地执行边界和审计证据；容器、虚拟机和网络隔离留给后续独立能力。

### 5. 控制类工具通过结构化结果影响 Runtime

`update_working_checkpoint` 更新当前 task/session 的单份短期投影，字段为 `key_info` 与 `related_sop`。每次调用仍作为普通工具事件进入 append-only 轨迹；投影只用于下一次 prompt 注入和任务恢复，不进入长期记忆。

`ask_user` 不在工具内部读取 stdin。工具返回包含问题和候选项的结构化 `needs-user` 信号，Reasoner 将它映射为当前 turn 的 `needs-user` 终止结果。用户回答通过通道开启后续 turn。

`start_long_term_update` 创建一个包含 `request_id`、`trace_id`、时间和 `pending` 状态的长期整理请求。它不运行总结器，也不更新任何学习载体；未来后处理 change 决定如何消费。重复调用通过稳定请求标识避免同一工具调用产生重复请求记录。

### 6. 浏览器是可选适配器而非核心依赖

Browser adapter 对外提供“扫描当前页面/标签页”和“执行 JavaScript”两项能力，工具 schema 参照 GenericAgent。配置关闭、适配器缺失或启动失败时，两项工具都不注册；其他九个默认工具保持可用。

`web_scan` 返回简化的页面内容、页面标识和标签页列表；`web_execute_js` 返回结构化执行结果，并允许将长文本保存到 workspace 文件。两者共享页面会话，但 Browser adapter 的具体实现可以是移植的 GenericAgent 后端、本地 Playwright 或 MCP 桥接。

### 7. 原始事实与派生评价严格分层

在线轨迹只保存可观察事实：

- 实际发送给 Provider 的消息与可见工具 schema 快照或可解析版本引用；
- Provider 返回的 Assistant 内容、tool call id、工具名和原始参数；
- 工具实际执行参数，以及任何显式引用展开或边界转换；
- 工具开始/结束时间、原始输出、stdout、stderr、exit code、超时和异常；
- 返回模型的有界结果及其截断、脱敏或外置引用标记；
- Agent Loop 的继续/终止决定与最终 turn 结果。

轨迹不得保存 Provider 未返回的隐藏推理，也不得加入 `reward`、`quality`、`correct_tool`、Rubric 结果或训练标签。未来处理器从 SQLite 的只读快照生成独立派生产物，并通过 `trace_id`/`event_id` 回指证据，不修改原始事件。

工具意图继续遵循已实现的审计边界：副作用执行前先提交意图，执行后再提交结果。若必需轨迹写入失败，不继续产生新的副作用。

### 8. 兼容与持久化迁移

工具名称变更属于公开 schema 破坏性变化。文档提供迁移表：`filesystem_read` → `file_read`，`calculator` → `code_run`；`memory_write` 改走长期整理请求；`spawn_subagent` 需要显式启用。

现有 SQLite 表优先复用事件/payload JSON 承载新增事实。只有在现有 schema 无法保持查询关系时才增加向前 migration；禁止删除或重建用户轨迹库，旧轨迹仍可查询和导出。

配置增加有默认值的 tools 子项，例如代码执行超时、输出上限、文件分页上限、浏览器和 SubAgent 可选开关。旧配置缺少这些字段时使用安全默认值启动。

## Risks / Trade-offs

- **[本地代码执行能够修改 workspace 或访问主机能力]** → 默认 cwd 限定 workspace、禁用进程内对象注入、设置超时与输出上限、记录完整事实；明确第一阶段不是强沙盒。
- **[文件写入工具扩大误修改风险]** → 严格 workspace 边界、精确 patch、显式 content、结构化失败和执行前意图提交。
- **[移除旧默认工具破坏已有提示或测试]** → 提供迁移表、更新所有示例与测试，并允许过渡期通过配置显式注册兼容工具，但不向默认模型集合同时暴露同义工具。
- **[完整原始输出导致数据库增长]** → 模型通道设置上限，大输出使用现有压缩/外置 payload；不牺牲可还原性去提前生成摘要标签。
- **[Browser 后端未确定导致实现范围漂移]** → 本 change 固定 adapter 契约和成对启停行为；若无稳定后端，完成禁用路径与契约测试，不阻塞核心九工具。
- **[长期更新请求被误解为已经学习]** → 用户可见结果和状态明确使用 `pending`，本 change 不提供自动消费逻辑。
- **[与未归档 Agent Loop change 发生规范冲突]** → 实施前先同步并归档 `simplify-agent-loop-with-trajectories`，再按本 change 的 delta 开发和归档。

## Migration Plan

1. 同步并归档 `simplify-agent-loop-with-trajectories`，验证 canonical Agent Loop 与 SQLite 轨迹规范。
2. 增加新工具与适配器，但先不改变默认注册集合；用单元测试验证 schema 和边界。
3. 接入 checkpoint、`needs-user` 与长期整理请求的 Runtime 映射，并验证完整轨迹。
4. 切换 bootstrap 默认工具集合，迁移配置、测试和文档。
5. 浏览器适配器仅在显式配置且启动成功时注册。
6. 运行完整测试、静态检查和严格 OpenSpec 验证后发布。

回滚时恢复旧默认注册配置和 schema，同时保留新代码与所有 SQLite 轨迹；任何向前 migration 必须允许旧 Runtime 明确拒绝未知高版本，而不是破坏数据。

## Open Questions

- 无阻塞问题。Browser adapter 的具体后端作为实现时的可替换选择，不改变本 change 的公开契约。
