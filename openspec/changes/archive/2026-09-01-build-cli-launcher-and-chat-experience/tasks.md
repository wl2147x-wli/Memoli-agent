## 1. 固化现有 CLI 与工作状态基线

- [x] 1.1 为当前 `python main.py`、空白输入、普通消息、`/exit` 和 Runtime 有序关闭补充不改变行为的回归测试
- [x] 1.2 为现有 `WorkingCheckpoint` 字段、revision 持久化、stale/completed 读取和 `RuntimeStatus` 信任边界补充基线测试
- [x] 1.3 检查并修正 `pyproject.toml` 中 project metadata 与 `[project.scripts]` 的表归属，确保现有 `memoli-skills` 安装入口不回归

## 2. 建立统一 `memoli` 命令入口

- [x] 2.1 新增标准库 `argparse` CLI 模块，定义无子命令默认 chat、显式 `chat`、`checkpoint`、`--help` 和 `--version`
- [x] 2.2 在 `pyproject.toml` 注册 `memoli` console script，并保持 `memoli-skills` 不变
- [x] 2.3 实现 `--config`、`--workspace`、`--session` 解析、`cli:<session>` 规范化和启动前校验，不在错误中回显秘密
- [x] 2.4 将 `main.py` 改为委托统一 chat 入口的薄兼容层，避免复制 Runtime 生命周期逻辑
- [x] 2.5 验证帮助、版本和 checkpoint 查询路径不会构建 AppRuntime 或启动 Provider、插件、MCP、Proactive 与 AgentLoop

## 3. 实现只读工作状态快照

- [x] 3.1 定义带 presentation schema version 的 `WorkingStateSnapshot` 合同，结构化区分 Agent checkpoint、Runtime 硬状态、availability、截断和省略信息
- [x] 3.2 为 `WorkingStateStore` 增加当前 session 的原子只读 snapshot，并用中文注释说明软状态与硬状态的信任边界
- [x] 3.3 实现共享的人类可读工作卡片 presenter，优先保留 session、revision、状态、stale、目标、当前步骤、下一步和约束
- [x] 3.4 实现确定性 JSON presenter，保证 stdout 可由脚本解析且不混入日志或提示文本
- [x] 3.5 实现不创建目录或数据库的 SQLite 只读 checkpoint reader，校验 schema 并区分 found、not-found、disabled、busy 和 error
- [x] 3.6 暴露最小 `RuntimeInspector` 供在线 CLI 查询现有 WorkingStateStore，而不向 Channel 暴露完整 AppRuntime、Provider 或数据库连接

## 4. 实现 checkpoint 查询命令

- [x] 4.1 实现聊天内 `/checkpoint` 与 `/working` 别名，按当前 `cli:<session>` 返回在线快照且绕过 MessageBus、LLM、工具和长期记忆
- [x] 4.2 实现 `memoli checkpoint --session <id>` 的离线人类可读输出和约定退出码
- [x] 4.3 实现 `memoli checkpoint --session <id> --json` 的单对象输出，并将所有诊断限制到 stderr
- [x] 4.4 验证查询 stale/completed checkpoint 不会调用 restore/patch、增加 revision、创建空记录或改变生命周期
- [x] 4.5 验证在线查询可展示 Runtime 硬状态，离线查询明确将 Runtime 状态标识为 unavailable

## 5. 完成本地斜杠命令路由

- [x] 5.1 新增 `CLICommandRouter` 与最小 `CLICommandContext`，在构造 InboundMessage 前识别本地命令
- [x] 5.2 实现 `/help`、`/status` 和 `/trace`，只显示非敏感 Runtime 摘要与当前会话最后一个已知 trace
- [x] 5.3 为 `SessionManager` 增加按 session 清理内存历史的显式接口并实现 `/clear`，确认不删除 checkpoint、长期记忆、Skill binding 和轨迹
- [x] 5.4 统一 `/exit`、`/quit` 和 EOF 的退出路径，实现未知命令提示及 `//` 字面 slash 转义
- [x] 5.5 验证所有本地命令均不调用 Provider、不写普通 Session 消息、不创建被动 turn 轨迹

## 6. 改进前台聊天与表现事件

- [x] 6.1 输出有界启动摘要，展示版本、Provider/模型、workspace、session 和主要功能开关但不展示 Key、Header、Cookie 或敏感 URL
- [x] 6.2 建立最小有界 presentation event 合同，将 session、trace、阶段和安全文本与原始 Provider SDK 事件隔离
- [x] 6.3 接入最终文本增量和非最终状态展示，过滤 thinking 与工具参数 delta，并在最终 Outbound 到达时避免重复文本
- [x] 6.4 统一终端 renderer，保证异步输出、提示符恢复、中文文本和非交互 stdin 下的输出顺序稳定
- [x] 6.5 使用 Outbound metadata 更新 last trace，并为非流式 Provider 输出一次完整最终回复
- [x] 6.6 确保用户连续输入只按队列串行执行主 turn，不引入并发 Runtime 或错误的回复关联

## 7. 完善失败处理与生命周期

- [x] 7.1 统一 chat 的 build/start/run/shutdown 所有权，保证启动中途失败也按已创建资源逆序清理
- [x] 7.2 处理键盘中断和 asyncio 取消，使其触发有界关闭而不转换成普通助手回复
- [x] 7.3 将单轮结构化失败显示为安全错误分类和 retryable 状态，并验证下一条消息仍可完成
- [x] 7.4 为配置错误、Provider 不可用、checkpoint 数据库 busy/未知 schema 和终端输出失败补充不泄密错误路径

## 8. 自动化测试与文档

- [x] 8.1 增加 CLI parser、入口分发、参数覆盖、help/version 不启动 Runtime 和 console script metadata 单元测试
- [x] 8.2 增加 slash 命令绕过 LLM、`//` 转义、`/clear` 边界、未知命令、EOF 与键盘中断测试
- [x] 8.3 增加 checkpoint found/not-found/disabled/stale/completed、JSON schema、只读不建库、并行提交读取和敏感错误测试
- [x] 8.4 增加 Echo/测试 Provider 的 CLI 端到端用例，覆盖普通回复、流式去重、工具轮次、trace 显示、首轮失败后恢复和连续消息串行处理
- [x] 8.5 更新 README 和相关运行文档，以 `memoli` 为推荐启动命令，记录 `memoli chat`、`memoli checkpoint`、本地斜杠命令及 `python main.py` 兼容方式
- [x] 8.6 运行 `python -m pytest -q`、`python -m ruff check memoli_agent benchmarks tests`、`python -m pyright` 和 `openspec validate --all --strict`，修复全部回归并记录实际基线（235 passed，6 skipped；其余检查全部通过）
