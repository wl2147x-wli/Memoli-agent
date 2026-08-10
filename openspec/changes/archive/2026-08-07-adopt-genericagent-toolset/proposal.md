## Why

Memoli 当前只有时间、计算器、记忆读写、单文件读取和 SubAgent 委派等零散工具，尚不能像 GenericAgent 一样用少量通用原子工具完成代码、文件、浏览器和长任务协作。现在需要建立一套保持 Agent Loop 简洁、可直接用于实际任务的最小工具集，并让现有 SQLite 轨迹忠实保存工具执行事实，为后续独立的轨迹处理与后训练提供原始输入。

## What Changes

- 参照 GenericAgent 的公开工具 schema 和行为，提供 `code_run`、`file_read`、`file_patch`、`file_write`、`update_working_checkpoint`、`ask_user` 与 `start_long_term_update` 七个核心工具。
- 将 `time` 与 `memory_recall` 保留为 Memoli 核心补充，组成默认九工具集合；现有 `calculator`、`memory_write`、`filesystem_read` 和 `spawn_subagent` 不再全部默认暴露，其中计算由 `code_run` 覆盖，文件读取由 `file_read` 替代，长期记忆写入改由后续处理流程控制，SubAgent 工具改为可选注册。
- 将 `web_scan` 和 `web_execute_js` 定义为成对启停的可选浏览器工具集；本 change 不强制绑定具体浏览器后端。
- 文件工具限定在 workspace 内；`file_patch` 使用唯一精确匹配且不得静默转换参数；`code_run` 使用受超时和输出上限约束的子进程，不支持把 Runtime 内部对象暴露给脚本的进程内 `eval/exec`。
- `update_working_checkpoint` 仅更新当前任务的短期工作状态；`ask_user` 使当前 turn 以 `needs-user` 结束；`start_long_term_update` 仅记录一个待后续消费的长期整理请求，不直接更新记忆、Prompt、Skill、工具或模型参数。
- 复用现有 SQLite 轨迹边界，保存模型实际可见 schema、模型原始工具参数、实际执行参数、原始工具输出、返回模型的有界输出、错误和时序等客观事实。
- 明确本 change 不增加 reward、Rubric、成功标签、工具选择评价、轨迹清洗或 SFT/RL 数据生成；这些能力由后续独立 change 从只读原始轨迹派生。
- **BREAKING**：默认模型可见工具名称与 schema 将从现有内建工具集合调整为 GenericAgent 风格的最小集合；依赖 `calculator`、`memory_write`、`filesystem_read` 或默认 `spawn_subagent` schema 的调用方需要迁移。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `tool-system`：修改默认工具集合、文件与代码执行契约、短期 checkpoint、用户询问、长期整理请求、可选浏览器工具集，以及工具执行事实进入完整原始轨迹的行为。

## Impact

- 主要影响 `memoli_agent/agent/tools/`、`memoli_agent/bootstrap/tools.py`、工具配置、当前任务状态和 Agent Loop 的工具结果映射。
- 复用 `memoli_agent/agent/trajectory.py` 的 SQLite 事件、span 与 payload 存储，不在本 change 中引入评价表或训练数据表；若现有事件载荷不足，只做向后兼容的 schema migration。
- 文件写入与代码执行扩大了本地副作用面，必须保留 workspace 路径约束、超时、输出限制、错误结构化和执行前轨迹提交。
- GenericAgent 源码仅作为 schema 与行为参考；移植后的实现遵守 Memoli 的 asyncio、类型标注、统一工具协议和 bootstrap 装配边界，不引入 GenericAgent 的前端、会话后端或全局反射分发。
- 本 change 依赖已完成的 `simplify-agent-loop-with-trajectories` 先同步并归档，以消除 canonical `tool-system` 中单次工具往返与已实现多轮串行循环之间的冲突。
