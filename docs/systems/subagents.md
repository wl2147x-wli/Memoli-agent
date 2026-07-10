# SubAgent 系统说明

第 9 阶段实现的是本地进程内 SubAgent：主 agent 可以通过 `spawn_subagent`
工具把边界清晰的子任务委派出去，子 agent 执行完成后把结果交回主 agent。

## 运行链路

```text
主 agent
  -> spawn_subagent 工具
  -> SubAgentManager
  -> SubAgentRuntime
  -> SubAgentResult
  -> 工具结果
  -> 主 agent 汇总回复
```

后台任务链路：

```text
spawn_subagent(background=true)
  -> 立即返回 task_id
  -> 后台执行子任务
  -> MessageBus.publish_inbound()
  -> channel=subagent 的完成消息
```

## 任务目录

默认目录：

```text
workspace/subagents/
```

每个子任务都会创建独立目录：

```text
workspace/subagents/<task_id>/
  task.json
  result.md
```

- `task.json` 保存任务说明、profile、父会话和元数据。
- `result.md` 保存子 agent 输出、成功状态和调试元数据。

## Profile

当前内置三个 profile：

- `general`：通用分析、总结、轻量推理。
- `research`：研究归纳，允许读取 workspace 内文件。
- `coding`：代码阅读和实现建议，默认不允许写文件。

profile 是进程内逻辑约束，不是系统级沙箱。后续如果接入独立进程、
MCP 或 peer agent，可以继续把 profile 扩展为真实权限策略。

## 工具参数

工具名：

```text
spawn_subagent
```

参数：

- `instruction`：必填，子 agent 要完成的任务。
- `profile`：可选，默认 `general`。
- `background`：可选，默认 `false`。
- `parent_session_key`：可选，用于后台完成事件回流。

同步调用会等待子任务完成，并把子任务结果作为工具结果返回。
后台调用会立即返回 task_id，完成后向 MessageBus 投递一条完成消息。

## 当前限制

- 不启动独立 Python 进程。
- 不做远程 agent 调用。
- 不做系统级沙箱隔离。
- 子 agent 默认复用主 provider，但使用独立 prompt 和独立任务目录。
