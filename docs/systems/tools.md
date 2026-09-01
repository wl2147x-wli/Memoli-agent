# 极简工具系统

Memoli 默认采用参照 GenericAgent 公开 schema 与行为重写的极简工具集。工具仍
实现 Memoli 的显式异步协议，通过 `ToolRegistry` 注册；没有引入 GenericAgent
的反射分发、前端状态或进程内执行。GenericAgent 采用 MIT License。

## 默认工具

Skill Runtime 关闭时，默认模型可见集合由配置和运行环境决定；标准容器配置下为九个
工具：

| 工具 | 用途 |
| --- | --- |
| `code_run` | 在受限容器中执行 Python；可信宿主模式需显式开启 |
| `file_read` | 按一基行号分页读取 UTF-8 文件 |
| `file_patch` | 唯一精确匹配并替换文本 |
| `file_write` | 显式覆盖、追加或前插文本 |
| `update_working_checkpoint` | 替换当前会话的短期任务便笺 |
| `ask_user` | 以 `needs-user` 暂停并请求用户输入 |
| `start_long_term_update` | 保存 `waiting-for-trigger` 整理 hint，不直接提取 |
| `time` | 查询本地和 UTC 时间 |
| `memory_recall` | 检索已有长期记忆 |

`code_runner = "disabled"` 时不注册 `code_run`。容器 profile 的 `code_run` schema
只声明 Python；可信宿主 profile 仅在启动时探测到 PowerShell 后才声明 PowerShell，
因此模型看到的参数枚举与当前实例实际可执行能力一致。

遗留兼容实现已经从源码删除，不再支持手工导入注册；迁移关系如下：

- `filesystem_read` 改用 `file_read`。
- `calculator` 改用 `code_run` 执行 Python。
- `memory_write` 改用受证据约束的 `memory_manage` 或离线长期整理流程；未经处理的
  轨迹不能直接成为长期事实。benchmark 的同名 ingest mode 是独立导入策略，仍然保留。
- 旧版 SubAgent 委派实现已删除；`spawn_subagent` 仅指持久任务图版本，并在设置
  `tools.subagent_tool_enabled = true` 后附加注册。

请求三个已删除工具名时，`ToolRegistry` 会返回结构化“工具不存在”失败，不会自动
改写为替代工具。历史轨迹和归档文档中的旧名称作为审计记录保留。

工具数量很小时不启用主动发现，`tool_search_enabled` 默认关闭，此时全部启用工具按
名称稳定排序并进入完整 schema snapshot。启用后，基础工具与 `tool_search` 先组成
稳定前缀；后续插件、MCP 或其他延迟注册工具由 `tool_search` 返回有界、确定性候选，
仅选中的完整 schema 会写入 `(session_key, conversation_epoch)` 披露账本。下一次
Provider 请求由 Context Compiler 在原稳定前缀后按首次披露顺序追加这些 schema；
其他 Session/Epoch 不会继承。引用或发现结果不会扩大原工具权限，未进入本次有效
schema 集的延迟工具不能靠猜名称执行，安全撤销仍然 fail closed。详见
[Context Management](context-management.md)。

启用 `[skills].enabled=true` 且 Skill Registry 装配成功时，额外注册第十个只读
工具 `skill_load(name, reference?)`。它对应 GenericAgent 的 L1 紧凑目录与 L3
按需全文注入模式：Catalog 负责选择，Tool Result 负责固定版本说明。它不执行脚本、
不管理版本，也不扩大其他九个工具的权限。`related_sop` 仍只是 Working State 提示，
只有成功 `skill_load` 才在轨迹中计为 Skill 使用。

## 参数合同

所有已注册工具的参数 schema 都按 JSON Schema Draft 2020-12 在注册时校验，并在
执行前统一校验模型原始参数。若安全策略 hook 改写参数，改写后的参数还会再次校验；
失败统一返回结构化 `ToolArgumentsInvalid`，工具主体不会运行。工具自身的业务约束
仍保留，但不再承担通用类型、必填字段和未知字段检查。

`memory_recall` 只声明实际进入检索查询的过滤与展开参数。事实写入元数据
`fact_type`、`subject`、`entity`、`predicate`、`value` 和 `sensitivity` 归属于
`memory_manage` 的 remember/correct 合同，不再由只读检索工具声明后静默忽略。

## 文件边界

三个文件工具共享同一 workspace 解析器。相对路径以 workspace 为根，绝对路径、
符号链接或 junction 解析后的目标也必须仍在 workspace 内。第一阶段只处理 UTF-8
普通文件，目标父目录必须已经存在。

`file_patch` 不会修正模型参数中的空白、缩进、Unicode 引号或换行；
`old_content` 出现零次或多次都会失败。`file_write.content` 必须显式出现在工具
参数中，不会从 Assistant 普通回复或代码块提取内容。

## 代码执行边界

`code_run` 默认使用 `tools.code_runner = "container"`。容器镜像必须固定到 digest，
默认禁网、只读根文件系统、非 root、cap-drop、no-new-privileges，并限制 CPU、内存、
PID、执行时间和输出；只挂载配置的 workspace。镜像运行期不能安装任意依赖。

容器后端不可用时不会退回宿主执行，而是返回明确 unavailable。默认容器 profile 只
执行 Python；PowerShell 仅允许显式 `trusted-host`。trusted-host 必须配置绝对且存在
的 Python 解释器路径，不能隐式采用 Runtime 的 `sys.executable`。`disabled` 会完全
关闭执行。字符串级 `allow_network` 扫描仅是辅助检查，不构成安全沙箱。

```toml
[tools]
code_runner = "container" # container / trusted-host / disabled
code_container_cli = "docker"
code_container_image = "registry.example/memoli-code-runner@sha256:<digest>"
code_allow_network = false
code_memory_mb = 256
code_cpus = 0.5
code_pids = 64
```

开发镜像脚本位于 `docker/code-runner/`。示例中的全零 digest 是 fail-safe 占位符，
部署前必须用实际构建并验证的 digest 替换。

## 可选浏览器工具

`web_scan` 和 `web_execute_js` 依赖同一个 `BrowserAdapter`，只在
`tools.browser_enabled = true` 且 adapter 可用时成对注册。当前核心 Runtime 不
绑定 Playwright、MCP 或其他具体浏览器后端。保存 JavaScript 长结果时仍使用同一
workspace 文件边界。

## 原始轨迹与后处理

在线 Runtime 只保存客观事实：模型可见 schema、tool call id、模型原始参数、
实际执行参数、时序、错误、完整脱敏输出和返回模型的有界输出。副作用工具执行前
先提交意图；必需轨迹写入失败时不执行副作用。

超过模型 preview 预算的结果会先按 trajectory 脱敏策略写入受管 payload，再向模型
返回带 hash、大小、转换标志和稳定引用的冻结预览（`FrozenToolPreview`）。预览绑定
`conversation_epoch`、规范化 tool message hash 与 `tool_call_id`；稳定快照键为
`(session_key, conversation_epoch)`，新 epoch 取新快照与新预览，不复用旧 epoch 派生索引。
恢复时必须按 `(session_key, conversation_epoch, tool_call_id)` 取冻结预览并校验 preview hash、
canonical message hash、payload reference 与 `tool_call_id`；任一不一致时排除整
个旧 turn 或可观察协议错误结束，绝不拆散 assistant tool call 与 tool result 配对，
也不重新生成预览。相同 Session 重编译或恢复时复用同一预览；稳定引用本身不是文件
读取能力，重新读取仍经过 workspace/scope/tool 权限。

能力安全撤销采用 fail-closed：撤销立即阻止已撤销工具的执行，并使当前 snapshot
进入失效状态（记录 `invalidated_reason`），编译拒绝向模型宣称已撤销工具仍可用；
恢复需新 epoch 重新冻结当前 schema。`/clear` 在没有活动 turn 时原子创建新 epoch
并重置派生 context 状态（编译快照、frontier、失败计数、冻结预览可见索引）；旧
committed turn、原始 trajectory、受管 payload、长期记忆与 working-state 按各自
策略保留但不进入新 epoch 上下文——`/clear` 不隐式删除 payload，仅把早于新 epoch
的冻结预览派生索引标记不可见/清理。

原始事件不包含 reward、Rubric、成功标签、正确工具标签、失败归因或 SFT/RL
标签，也不会自动进入 Memory、Evolution 或 Post-training。轨迹清洗、评价和训练
样本生成必须从 SQLite 只读副本派生，并保持原始事件不变。
## Memory learning and review

`start_long_term_update` persists an idempotent session/unconsumed-boundary hint,
wakes the Trigger Coordinator, returns `waiting-for-trigger`, hint ID and pending
chat count, and never creates a runnable extraction request by itself.
`memory_recall` accepts `retrieval_mode`, `detail_level`,
statement IDs, and statement/Claim/Evidence expansion limits, and returns requested
and actual routes plus degradation diagnostics.

`memory_manage` supports Candidate `list`, `show`, `approve`, `reject`, and `review`
operations and long-term request list/status/retry/cancel diagnostics. Approve and
reject require an explicit instruction in the current user message; the ordinary
assistant, extractor, and worker cannot act as an approval subject.
Governance dead-letter retry and consolidation retry/suppress are conditional service
operations. Operator force-release is intentionally absent from model-visible tools.
