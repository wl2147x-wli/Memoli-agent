## 1. 固化基线并准备依赖与配置

- [x] 1.1 为现有 plain CLI 的启动、普通输入、空白输入、全部本地命令、流式前缀去重、EOF 和有序关闭补充不改变行为的回归基线
- [x] 1.2 为 OpenAI-compatible、OpenAI 和 Anthropic 的流式文本、工具 delta、usage、partial-stream 与取消关闭行为补充基线测试
- [x] 1.3 在 `pyproject.toml` 增加受版本约束的 `prompt_toolkit` 与 Rich 直接依赖，并验证 wheel/editable install 包含两个现有 console script
- [x] 1.4 扩展 `CLIChannelConfig`，增加 `interactive`、`color`、`refresh_hz`、`queue_limit` 和 `max_tool_rows`，实现严格范围校验和向后兼容默认值
- [x] 1.5 将正式交互聊天的 `llm.stream` 默认值与 `config.example.toml` 调整为 true，同时保留显式 false 的非流式路径
- [x] 1.6 增加 TTY/非 TTY、`NO_COLOR`、Windows UTF-8 和增强终端初始化失败的能力探测合同，不在探测阶段构建或调用 Provider

## 2. 建立中心化本地命令注册表

- [x] 2.1 定义不可变 `CommandSpec`、规范化解析结果、命令上下文、可用性结果和异步 handler 合同
- [x] 2.2 实现 `CommandRegistry` 注册、稳定排序、名称/别名解析和重复冲突 fail-fast 校验
- [x] 2.3 将 `/help`、`/status`、`/checkpoint`、`/working`、`/trace`、`/clear`、`/exit` 与 `/quit` 从条件链迁移到 Registry，保持原有绕过 LLM/Session/trajectory 行为
- [x] 2.4 注册 `/stop`、`/workspace`、`/model`、`/tools`、`/memory` 和 `/skills`，实现分类、参数提示和运行状态前置条件
- [x] 2.5 使首版组件检查命令保持只读；收到切换参数时返回对应 `memoli` 启动参数或 `config.toml` 指引，不修改当前 Runtime
- [x] 2.6 由 Registry 生成 `/help`、候选说明和命令别名提示，删除重复维护的静态帮助文本
- [x] 2.7 增加命令解析、别名、冲突、参数错误、busy availability、未知命令和 `//` 字面 slash 的单元测试

## 3. 扩展安全表现事件合同

- [x] 3.1 扩展 PresentationEvent，加入 session、trace、turn、step、时间和有界安全 payload，并定义 turn/model/tool/usage/checkpoint/终止事件枚举
- [x] 3.2 在 Reasoner 模型回调中投影 `MODEL_STARTED`、`TEXT_DELTA` 和 `USAGE_UPDATED`，在进入表现队列前过滤 thinking/reasoning 与工具参数 delta
- [x] 3.3 在工具执行边界投影 `TOOL_STARTED` 与 `TOOL_FINISHED`，只包含规范化工具名、枚举状态、耗时和安全错误分类
- [x] 3.4 在被动 turn 生命周期投影 `TURN_STARTED`、`CHECKPOINT_CHANGED`、`TURN_COMPLETED`、`TURN_FAILED` 和 `TURN_CANCELLED`
- [x] 3.5 为有界事件队列实现同 step 文本合并、latest-wins usage/status、终止事件优先和 observer 故障隔离
- [x] 3.6 防御性清除事件文本中的控制字符、超长值、凭证模式和未经允许的宿主路径，同时保持最终 Outbound 为权威结果
- [x] 3.7 增加事件顺序、跨 session/trace 隔离、队列饱和合并、敏感过滤、observer 抛错和最终事件不丢失测试

## 4. 实现当前 turn 取消与有界排队

- [x] 4.1 在 AgentLoop 中分离长期 message-pump task 与被 await 的 per-turn task，并暴露最小 `TurnController` 只读状态和取消接口
- [x] 4.2 实现 `/stop` 对活动 turn 的幂等取消和 idle 提示，禁止其停止整个 AgentLoop 或 Runtime
- [x] 4.3 使 Provider stream 取消关闭 SDK stream 且不启动 fallback，并阻止该 turn 后续工具或模型步骤
- [x] 4.4 使工具等待取消停止后续循环；对已发生或不可撤销副作用记录真实状态而不声称回滚
- [x] 4.5 将用户取消持久化为 `cancelled/user-cancelled` trace 终止状态，并生成不包含原始异常的安全 Outbound/表现事件
- [x] 4.6 在 CLI 提交侧维护有界待处理计数，busy 时显示队列深度，达到 `queue_limit` 时拒绝新普通输入但继续允许本地检查和 `/stop`
- [x] 4.7 验证取消 Provider、取消工具、重复 `/stop`、idle `/stop`、取消后下一条成功、Runtime shutdown 取消和消息/trace 不串线

## 5. 扩展只读 Runtime 检查视图

- [x] 5.1 为 Inspector 定义带版本的 Provider/模型/stream、workspace/session、busy/queue 和功能开关 DTO
- [x] 5.2 增加工具列表及 available/unavailable 原因视图，不暴露 Tool 实例、可变 Registry 或完整策略配置
- [x] 5.3 增加 Memory、Embedding、Consolidation 和工作状态可用性视图，并复用现有 checkpoint presenter 的信任边界
- [x] 5.4 增加当前 session Skill catalog 摘要视图，限制数量、字符和来源字段且不触发 Skill load
- [x] 5.5 将 `/workspace`、`/model`、`/tools`、`/memory`、`/skills`、`/status` 和状态栏全部接到结构化 Inspector DTO
- [x] 5.6 增加关闭组件、空列表、超长名称、敏感 base URL/路径、运行中状态和 Inspector 故障降级测试

## 6. 构建单一终端 Renderer 与状态归约器

- [x] 6.1 定义可独立测试的 `RenderState`、已提交消息块、活动文本、工具行、palette、输入状态、usage 和状态栏模型
- [x] 6.2 实现单 asyncio render queue 与 reducer，保证所有 UI mutation 按序且只能由一个 render task 写终端
- [x] 6.3 实现 dirty/invalidate 调度与 `refresh_hz` 帧率限制，文本增量只追加并为活动显示设置有界窗口
- [x] 6.4 实现工具步骤按 step ID 原位更新、`max_tool_rows` 限制和完成后单一安全摘要
- [x] 6.5 实现最终 Outbound 前缀校验、live block 清理、Rich Markdown 离屏渲染和一次性 scrollback 提交，避免重复最终文本
- [x] 6.6 实现 resize 后重排、中文宽字符、超长无空格文本、ANSI/OSC 控制字符过滤与 `NO_COLOR` 行为
- [x] 6.7 实现 renderer 异常隔离和 plain renderer 兜底，表现失败不得取消 Agent turn 或改变轨迹
- [x] 6.8 增加 reducer 确定性、事件乱序拒绝、12 FPS 合帧、Markdown 完成提交、流式去重、工具原位更新、resize 和输出失败测试

## 7. 实现 prompt_toolkit 交互式 CLI

- [x] 7.1 建立 `InteractiveCLIAdapter` 和 `PlainCLIAdapter` 公共 Channel 合同，由 bootstrap 根据配置、TTY 和初始化结果选择一次
- [x] 7.2 使用 `prompt_toolkit.Application` 的非全屏 live region 组合活动输出、候选面板、输入 Buffer 和 bottom status bar
- [x] 7.3 实现 Registry 驱动的 Completer，输入 `/` 即展示有界候选，按前缀实时过滤并显示 description/args metadata
- [x] 7.4 实现 slash AutoSuggest 和普通输入进程内 history suggestion，确保输入历史按 session 隔离且不含内部/敏感事件
- [x] 7.5 实现候选上下键选择、Tab 补全、Enter 补全/提交、Esc 关闭、普通历史导航和 palette 选择状态复位
- [x] 7.6 实现单行提交、多行编辑、Alt+Enter/Esc+Enter 换行、光标移动、中文 IME、括号粘贴和空白输入忽略
- [x] 7.7 实现 Ctrl+C 活动时取消 turn、idle 时清空输入，以及 Ctrl+D 空 buffer 正常退出的有界键位语义
- [x] 7.8 允许 turn 运行时继续编辑和提交排队消息，在 live region 明确展示 busy、queue depth 与停止提示
- [x] 7.9 实现启动摘要、status bar 和工具活动区的统一主题 token；颜色关闭后仍依靠文本标签传达状态
- [x] 7.10 增加虚拟终端输入测试，覆盖 `/` 初始面板、实时过滤、方向键、Tab/Enter/Esc、ghost text、多行、历史、Ctrl+C/Ctrl+D 和 resize

## 8. 完成流式、降级与端到端集成

- [x] 8.1 验证 `llm.stream=true` 时 OpenAI-compatible、OpenAI 与 Anthropic 的文本增量按序进入 live region，并与最终 Outbound 一致
- [x] 8.2 验证 `llm.stream=false`、Echo Provider 和无增量测试 Provider 只输出一次完整最终回复
- [x] 8.3 验证部分流中断不会跨 Provider 拼接，CLI 清除未完成块并显示安全错误分类和 retryable 状态
- [x] 8.4 增加普通回答、两轮工具调用、工具失败/no-progress、checkpoint 更新、needs-user、用户取消和取消后恢复的交互 CLI 端到端测试
- [x] 8.5 增加管道 stdin、重定向 stdout、`interactive=false`、增强依赖/终端初始化失败和 plain CLI 自动降级端到端测试
- [x] 8.6 验证本地命令和 palette 操作均不调用 Provider、不写普通 Session 消息、不产生被动 turn 轨迹
- [ ] 8.7 在 Windows Terminal/PowerShell 与至少一个 Unix-like PTY 手工检查 UTF-8、颜色、粘贴、resize、流式和退出行为，并记录可复现结果

## 9. 文档、质量门禁与 OpenSpec 同步

- [x] 9.1 更新 README 启动与交互说明，记录默认 streaming、`/` palette、键位、排队、`/stop`、组件检查命令和 plain 降级方式
- [x] 9.2 更新 Agent Runtime 与 CLI 系统文档，说明 CommandRegistry、presentation 安全边界、renderer 数据流和 per-turn cancellation
- [x] 9.3 更新 `config.example.toml` 注释和迁移说明，明确 `interactive=false`、`llm.stream=false` 与 `NO_COLOR` 回滚路径
- [x] 9.4 运行 `python -m pytest -q`、`python -m ruff check memoli_agent benchmarks tests` 和 `python -m pyright`，修复全部回归并记录实际基线
- [x] 9.5 运行 `openspec validate --all --strict`，同步 canonical specs，复核不包含宠物、热切换或多页面 TUI 的范围漂移
