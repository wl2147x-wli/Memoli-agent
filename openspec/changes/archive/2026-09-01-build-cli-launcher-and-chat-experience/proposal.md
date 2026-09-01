## Why

Memoli 当前只能通过仓库根目录的 `python main.py` 进入最小 CLI，缺少可安装、可发现且适合日常使用的统一命令，也无法在不询问模型的情况下查看当前任务的工作记忆 checkpoint。先形成稳定的 CLI 产品边界，可以用最低前端成本验证 Runtime、会话、流式输出、错误处理和工作状态展示，并为后续 TUI、桌面窗口及桌宠复用同一套只读状态接口。

## What Changes

- 新增可安装的 `memoli` 控制台入口；无参数运行 `memoli` SHALL 直接进入前台 CLI 对话，`memoli chat` 作为等价显式命令。
- 为启动命令提供 `--config`、`--workspace`、`--session`、`--help` 和 `--version`，保留 `python main.py` 兼容入口。
- 改进纯文本聊天体验：明确区分用户与助手提示符、展示非敏感启动摘要、支持可用时的文本流式输出，并在最终结果中提供稳定 trace 标识。
- 新增本地斜杠命令路由，至少支持 `/help`、`/status`、`/checkpoint`（别名 `/working`）、`/trace`、`/clear` 和 `/exit`；本地命令 SHALL NOT 发送给 LLM 或作为普通用户消息写入会话历史。
- 新增只读工作状态快照接口，将 Agent 维护的语义 checkpoint 与 Runtime 验证的硬状态分开呈现。
- `/checkpoint` SHALL 返回当前会话最新 checkpoint；`memoli checkpoint` SHALL 支持按 session 查询并提供人类可读和 JSON 输出，便于离线检查和脚本使用。
- 为无 checkpoint、stale、completed、未知 session、工作记忆关闭、配置错误、Provider 错误、取消和优雅关闭提供明确且不泄漏秘密的反馈。

### Non-goals

- 本 change 不实现常驻 daemon、IPC、HTTP/WebSocket Gateway、Streamlit、Textual、Tauri 或桌宠。
- 本 change 不新增持久化聊天 Session，不实现多客户端和并发 turn。
- 本 change 不修改 checkpoint 的自动更新策略，也不把工作 checkpoint 合并进长期个人 Memory Card。
- 本 change 不允许 CLI 查询命令修改 checkpoint、长期记忆或 Runtime 硬状态。

## Capabilities

### New Capabilities

- `cli-shell`: 定义 `memoli` 统一入口、前台串行聊天、启动参数、本地斜杠命令、流式终端输出、错误呈现和兼容行为。

### Modified Capabilities

- `working-memory`: 增加面向用户的只读 checkpoint/Runtime 状态快照和 CLI 查询行为，同时保持软状态与硬状态的信任边界。

## Impact

- 影响 `pyproject.toml` 的 console script、顶层入口、CLI channel、bootstrap channel 装配、Runtime 只读检查接口、Reasoner 模型事件回调及工作状态表示。
- 不迁移 `working-state.db` schema；继续读取现有最新版 checkpoint 和 revision 历史表。
- 不引入重量级 UI 依赖；命令解析优先使用 Python 标准库，终端增强必须保持无额外 UI 依赖时可用。
- `python main.py` 保持兼容；现有 `memoli-skills` 命令不变。
- checkpoint 可能包含用户任务信息；输出仅写入调用者终端或标准输出，不进入 Provider 请求，错误和启动摘要不得回显 API Key、Authorization 或原始敏感异常。
