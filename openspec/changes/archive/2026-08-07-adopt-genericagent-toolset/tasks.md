## 1. 前置规范与兼容基线

- [x] 1.1 同步并归档 `simplify-agent-loop-with-trajectories`，确认 canonical Agent Runtime 已描述当前串行多轮循环和 SQLite 原始轨迹行为。
- [x] 1.2 为现有默认工具 schema、配置和 SQLite 工具事件建立回归基线，记录 `filesystem_read`、`calculator`、`memory_write` 与 `spawn_subagent` 的迁移影响。
- [x] 1.3 核对 GenericAgent MIT 许可证及被采用的 schema/行为来源；若复制实质代码或文本，补充所需许可证和来源声明。

## 2. 共享工具基础设施

- [x] 2.1 整理 GenericAgent 风格的公开工具 schema，保持工具名、参数语义、使用时机和失败恢复提示一致，并适配 Memoli 的显式 `Tool` 协议。
- [x] 2.2 实现共享 workspace 路径解析器，拒绝规范化越界、符号链接或 junction 逃逸和非普通文件目标。
- [x] 2.3 为工具原始输出与模型可见有界输出增加统一表示，保留截断、脱敏、压缩或 payload 外置标记。
- [x] 2.4 扩展工具配置默认值，覆盖代码超时、代码输出上限、文件分页上限、浏览器工具集开关和 SubAgent 工具显式开关，并验证旧配置仍可启动。

## 3. 文件工具

- [x] 3.1 实现 `file_read` 的 UTF-8 文本分页、可选行号、明确截断和结构化错误，并替代默认 `filesystem_read`。
- [x] 3.2 实现 `file_patch` 的非空唯一精确匹配，确保零匹配或多匹配时不写文件且不静默转换参数。
- [x] 3.3 实现 `file_write` 的显式 `content` 与 `overwrite`、`append`、`prepend` 模式，不从 Assistant 回复正文隐式提取内容。
- [x] 3.4 如支持文件片段引用，实现受 workspace 约束的显式展开，并分别保留模型原始参数与实际执行参数。
- [x] 3.5 添加文件读取、三种写入模式、唯一 patch、空或多重匹配、Unicode/换行保真、路径越界、链接逃逸、非 UTF-8 和输出截断测试。

## 4. 代码执行工具

- [x] 4.1 实现 `code_run` 的 Python 子进程执行，支持显式脚本、workspace 内 `cwd`、超时、stdout、stderr 和退出码。
- [x] 4.2 在当前平台可用时实现 PowerShell 子进程执行，并对不可用解释器返回结构化启动错误。
- [x] 4.3 禁用进程内 `eval/exec` 和 Runtime 对象注入，确保脚本只通过子进程边界执行。
- [x] 4.4 实现代码输出的模型侧上限与原始脱敏 payload 保存，确保截断状态对模型和轨迹都可见。
- [x] 4.5 添加正常退出、非零退出码、stderr、超时、无效 `cwd`、workspace 越界、解释器不可用和长输出测试。

## 5. 长任务与用户控制工具

- [x] 5.1 实现当前 task/session 的 working checkpoint 投影以及 `key_info`、`related_sop` 替换更新。
- [x] 5.2 将最新 working checkpoint 注入后续 turn 的上下文，并验证它不会写入长期记忆。
- [x] 5.3 实现通道无关的 `ask_user` 结构化结果，并将其映射为 Agent Loop 的 `needs-user` 终止结果。
- [x] 5.4 实现 `start_long_term_update` 的稳定请求标识、当前 trace 关联和 `pending` 状态，不增加自动消费或学习逻辑。
- [x] 5.5 添加 checkpoint 多次替换与历史保留、非 CLI `ask_user`、候选项传递、长期请求幂等关联和无自动记忆更新测试。

## 6. 可选工具集与默认装配

- [x] 6.1 定义可替换 Browser adapter 契约和 GenericAgent 风格的 `web_scan`、`web_execute_js` schema。
- [x] 6.2 实现浏览器工具集成对启停与初始化失败隔离，并确保保存长结果时复用 workspace 文件边界。
- [x] 6.3 将 bootstrap 默认模型可见集合切换为七个 GenericAgent 核心工具加 `time`、`memory_recall`。
- [x] 6.4 将 `spawn_subagent` 改为显式配置后附加注册，并确保 `calculator`、`memory_write`、`filesystem_read` 和浏览器工具默认不可见。
- [x] 6.5 添加默认九工具精确集合、浏览器成对启停、浏览器失败隔离、SubAgent 可选注册和无同义工具重复暴露测试。

## 7. Agent Loop 与完整原始轨迹

- [x] 7.1 将新工具统一接入现有串行 Agent Loop，保持同一模型响应内按声明顺序执行且不引入并发。
- [x] 7.2 在每次 Provider 请求证据中保存实际模型可见工具 schema 快照或可解析版本引用。
- [x] 7.3 在工具证据中分别保存 tool call id、工具名、模型原始参数、实际执行参数、时序、状态、错误、原始脱敏输出和模型可见输出。
- [x] 7.4 确保副作用工具执行前提交工具意图、执行后提交结果，并在必需轨迹写入失败时停止副作用。
- [x] 7.5 验证 SQLite 原始事件不包含 reward、Rubric、成功标签、正确工具标签、失败归因或 SFT/RL 标签，且不会自动进入 Memory、Evolution 或 Post-training。
- [x] 7.6 添加多轮文件任务、代码失败恢复、`needs-user`、未启用时不隐式展开参数、长输出 payload 和轨迹写入失败的端到端测试。

## 8. 迁移、文档与验证

- [x] 8.1 更新示例配置与操作文档，说明默认九工具、可选浏览器/SubAgent、代码执行边界和旧工具迁移表。
- [x] 8.2 更新架构文档，说明 GenericAgent 行为参考、Memoli 显式工具协议、原始轨迹与后置轨迹处理的分层边界。
- [x] 8.3 运行 `python -m pytest -q` 并修复本 change 引入的失败。
- [x] 8.4 运行 `python -m ruff check memoli_agent benchmarks tests` 和 `python -m pyright` 并确保通过。
- [x] 8.5 运行 `openspec validate --all --strict`，核对所有任务与场景后再归档本 change。
