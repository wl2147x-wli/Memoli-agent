# cli-shell Specification

## Purpose

定义 Memoli 命令行入口、交互式聊天体验、启动兼容性和终端呈现约束，使用户能够以一致、可诊断且可恢复的方式启动和操作本地 Agent Runtime。

## Requirements

### Requirement: Unified Memoli command entry

系统 SHALL 安装名为 `memoli` 的控制台入口；无子命令执行 `memoli` SHALL 启动前台纯文本聊天，`memoli chat` SHALL 提供等价显式入口，并 SHALL 保留 `python main.py` 的兼容启动行为。

#### Scenario: User starts Memoli without a subcommand

- **WHEN** 用户在已安装项目的环境中执行 `memoli`
- **THEN** 系统 SHALL 加载有效配置、启动一次 AppRuntime 并进入 CLI 对话
- **AND** SHALL NOT 要求用户从仓库根目录调用脚本

#### Scenario: User requests help or version

- **WHEN** 用户执行 `memoli --help`、`memoli chat --help` 或 `memoli --version`
- **THEN** 系统 SHALL 输出对应帮助或版本并以成功状态退出
- **AND** SHALL NOT 启动 Provider、AgentLoop、插件、MCP 或 Proactive 后台任务

#### Scenario: Legacy entry is used

- **WHEN** 用户执行 `python main.py`
- **THEN** 系统 SHALL 复用统一 CLI 启动路径进入与 `memoli` 等价的前台聊天

### Requirement: Explicit CLI configuration and session selection

CLI SHALL 支持显式选择配置文件、工作区和本地会话标识，并 SHALL 在启动 Runtime 前完成参数与配置校验。

#### Scenario: Explicit options are valid

- **WHEN** 用户通过 `--config`、`--workspace` 或 `--session` 提供有效值
- **THEN** CLI SHALL 使用解析后的有效配置和 `cli:<session>` session key 启动聊天
- **AND** 显式工作区仅 SHALL 覆盖 runtime workspace，不得静默重写配置中显式声明的其他绝对路径

#### Scenario: Startup configuration is invalid

- **WHEN** 配置文件不存在、参数缺值或配置形状无效
- **THEN** CLI SHALL 在启动 Runtime 或发出 Provider 请求前返回可操作的配置错误和非零退出码
- **AND** 错误输出 SHALL NOT 包含 API Key、Authorization、Cookie 或原始敏感配置值

### Requirement: Foreground serial chat experience

CLI SHALL 将普通非空输入作为当前 `cli:<session>` 的 InboundMessage 交给现有被动 turn 流程，并 SHALL 按提交顺序串行显示对应回复。

#### Scenario: User completes a normal turn

- **WHEN** 用户输入一条非空普通消息且 Runtime 成功完成 turn
- **THEN** CLI SHALL 明确区分用户输入与助手回复
- **AND** SHALL 显示最终回复及其稳定 trace 标识

#### Scenario: Multiple messages are entered

- **WHEN** 用户在前一 turn 仍运行时继续提交消息
- **THEN** 系统 SHALL 按接收顺序排队处理消息
- **AND** SHALL NOT 并发执行两个主 Agent turn 或将回复关联到错误输入

#### Scenario: Empty input is submitted

- **WHEN** 用户只提交空白输入
- **THEN** CLI SHALL 忽略该输入并继续等待
- **AND** SHALL NOT 创建 Session 消息、模型请求或轨迹

### Requirement: Safe terminal progress and response rendering

CLI SHALL 在不暴露隐藏推理、部分工具参数或秘密的前提下显示有界运行状态；当最终用户可见响应具有文本增量时 SHALL 按顺序呈现，并 SHALL 避免在最终 Outbound 到达后重复已呈现文本。

#### Scenario: Provider streams a final text response

- **WHEN** 当前模型响应产生有序文本增量并最终被 Agent Loop 接受为用户可见回复
- **THEN** CLI SHALL 按顺序显示该文本并在最终 Outbound 到达时只补充尚未显示的尾部
- **AND** SHALL 将该回复与最终 trace 标识关联

#### Scenario: A model step requests tools

- **WHEN** 模型流包含 thinking delta、工具名或工具参数增量且该响应进入后续工具轮次
- **THEN** CLI SHALL NOT 输出隐藏 thinking 或原始工具参数增量
- **AND** 任何进度提示 SHALL 明确标识为非最终状态并保持有界

#### Scenario: Streaming is disabled or unavailable

- **WHEN** Provider 或配置不提供流式增量
- **THEN** CLI SHALL 在 Outbound 完成后输出一次完整最终回复

### Requirement: Local slash command routing

CLI SHALL 在发布 InboundMessage 前识别本地斜杠命令，至少支持 `/help`、`/status`、`/checkpoint`、`/working`、`/trace`、`/clear` 和 `/exit`；这些命令 SHALL NOT 被发送给 LLM 或作为普通 turn 写入 Session 历史与轨迹。

#### Scenario: User requests checkpoint

- **WHEN** 用户执行 `/checkpoint` 或 `/working`
- **THEN** CLI SHALL 使用当前 `cli:<session>` 查询只读工作状态快照并直接渲染结果
- **AND** SHALL NOT 调用 Provider、工具或长期记忆检索

#### Scenario: User requests status or last trace

- **WHEN** 用户执行 `/status` 或 `/trace`
- **THEN** CLI SHALL 返回当前 Runtime 的非敏感组件状态或当前会话最后一个已知 trace 标识
- **AND** 不可用字段 SHALL 明确显示为 unavailable

#### Scenario: User clears visible conversation context

- **WHEN** 用户执行 `/clear`
- **THEN** CLI SHALL 清除当前进程中当前会话的短期聊天历史并确认结果
- **AND** SHALL NOT 删除工作 checkpoint、长期记忆、Skill binding 或已提交轨迹

#### Scenario: User needs a literal slash prompt

- **WHEN** 用户输入以 `//` 开头的非空内容
- **THEN** CLI SHALL 移除一个前导 `/` 并将剩余文本作为普通用户消息提交

#### Scenario: Slash command is unknown

- **WHEN** 用户输入未注册的单斜杠命令
- **THEN** CLI SHALL 返回本地未知命令提示和 `/help` 指引
- **AND** SHALL NOT 将未知命令回退发送给模型

### Requirement: Predictable CLI shutdown and failure presentation

CLI SHALL 在 `/exit`、输入流结束、键盘中断或启动后故障时有序关闭已启动组件，并 SHALL 将单轮结构化失败呈现为可继续交互的安全错误。

#### Scenario: User exits normally

- **WHEN** 用户执行 `/exit`、`/quit` 或标准输入到达 EOF
- **THEN** CLI SHALL 停止接收新消息并调用 Runtime 的有序关闭流程
- **AND** SHALL 以成功退出码结束正常退出

#### Scenario: Keyboard interrupt occurs

- **WHEN** CLI 收到键盘中断
- **THEN** 系统 SHALL 取消当前前台运行、执行有界清理并退出
- **AND** SHALL NOT 将取消转换为普通助手回复

#### Scenario: One turn fails safely

- **WHEN** AgentLoop 为某条消息返回结构化错误 Outbound
- **THEN** CLI SHALL 显示安全错误分类和可重试性并继续接受后续输入
- **AND** SHALL NOT 回显原始异常、路径内容或秘密

### Requirement: Scriptable checkpoint command

系统 SHALL 提供 `memoli checkpoint` 命令，以便在不启动 Provider 和 AgentLoop 的情况下读取指定本地 CLI session 的最新工作 checkpoint，并 SHALL 支持人类可读与 JSON 输出。

#### Scenario: Existing checkpoint is queried

- **WHEN** 用户执行 `memoli checkpoint --session <id>` 且 `cli:<id>` 存在 checkpoint
- **THEN** 命令 SHALL 输出该 checkpoint 的结构化字段、revision、状态、stale 标记和更新时间
- **AND** SHALL 以成功状态退出

#### Scenario: JSON output is requested

- **WHEN** 用户执行 `memoli checkpoint --session <id> --json`
- **THEN** 标准输出 SHALL 只包含单个 schema-versioned JSON 对象
- **AND** SHALL 适合由脚本确定性解析

#### Scenario: Checkpoint is absent or working memory is disabled

- **WHEN** 指定 session 没有 checkpoint、工作记忆关闭或数据库不可用
- **THEN** 命令 SHALL 返回可区分的 unavailable/not-found/error 状态和约定退出码
- **AND** SHALL NOT 创建空 checkpoint、重建未知 schema 数据库或调用模型生成替代内容

