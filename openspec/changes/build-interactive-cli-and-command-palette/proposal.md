## Why

Memoli 已有可安装的基础 CLI，但标准库 `input()` 只能在回车后处理整行，无法提供 `/` 命令面板、补全、稳定的异步重绘和成熟的流式体验；当前配置还默认关闭 streaming，使真实 Agent 执行看起来像一次性阻塞。现在需要在不改变核心 Agent Loop 的前提下，把 CLI 提升为适合日常使用和项目展示的交互式终端产品。

## What Changes

- 引入基于 `prompt_toolkit` 与 Rich 的交互式 CLI，并在非 TTY、重定向输入或增强依赖不可用时保留现有纯文本降级路径。
- 建立中心化 `CommandRegistry`，统一命令执行、别名、分类、参数提示、`/help` 与自动补全，消除路由器和帮助文本的重复事实源。
- 输入 `/` 时实时展示并过滤命令候选，支持方向键选择、Tab/Enter 补全、Esc 关闭、命令 ghost suggestion、历史建议和多行输入。
- 扩展安全表现事件与单一终端 renderer，按顺序展示最终文本增量、工具开始/结束、任务完成/失败、usage 与耗时，同时继续过滤隐藏 reasoning、原始工具参数和秘密。
- 增加轻量状态栏，展示当前模型、session、workspace、turn/iteration、耗时和工作状态可用性；本 change 不引入宠物。
- 在现有本地命令基础上增加 `/stop`、`/workspace`、`/model`、`/tools`、`/memory` 和 `/skills` 的安全检查能力；首版除 `/stop` 外保持只读，不在运行中热切换 Runtime 安全边界。
- 使交互式 chat 默认请求流式模型响应，同时允许配置显式关闭，并对 Provider 不支持 streaming 的情况给出受控降级或错误。
- 保持单主 Agent turn 串行；任务运行中提交的普通输入进入有界队列，`/stop` 只取消当前 turn，不关闭整个 CLI。

### Non-goals

- 不实现宠物、桌宠、动画角色或情绪系统。
- 不实现 Textual 全屏多页面应用、桌面 GUI、Web UI、daemon、IPC 或多客户端。
- 不在本 change 中实现模型、workspace、工具、记忆或 Skill 的在线重配置；相应命令只检查当前有效状态并给出重启指引。
- 不展示 chain-of-thought、原始工具参数、Provider SDK 对象或未脱敏异常。
- 不改变 SQLite trajectory、Memory、Working Checkpoint 和 Skill Registry 的持久化 schema。

## Capabilities

### New Capabilities

- `interactive-cli`: 定义增强终端输入、中心命令注册表、命令面板、流式 renderer、状态栏、TTY 降级和用户可见交互行为。

### Modified Capabilities

- `agent-runtime`: 增加面向表现层的结构化 turn/tool/usage 事件和只取消当前 turn 的控制边界，并保持主 Agent 串行执行与安全事件过滤。

## Impact

- 影响 `pyproject.toml` 运行依赖、CLI channel、命令路由、表现事件、Reasoner/AgentLoop 观察接口、RuntimeInspector、配置默认值和 bootstrap channel 装配。
- 新增 `prompt_toolkit` 与 Rich 直接依赖；交互增强仅在 TTY 中启用，脚本、管道和测试可继续使用 plain renderer。
- `memoli`、`memoli chat`、`memoli checkpoint` 和 `python main.py` 命令保持兼容；现有斜杠命令语义保持兼容。
- 不迁移已有数据库；用户只需重新安装依赖并可按需显式设置 `llm.stream = false` 回到非流式模型调用。
- 终端输出仍属于本地敏感界面，状态栏和事件 payload 必须使用有界、脱敏、来源明确的数据。
