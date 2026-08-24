# Context Management Change 验收记录

变更：`build-cache-aware-context-compaction`

验收日期：2026-08-13

## 执行环境

- Python：`D:\software\miniconda\envs\memoli\python.exe`
- 版本：Python 3.11.15
- Pytest 临时目录固定在项目内，并禁用 cache provider，避免 Windows 临时目录权限和编码噪声。

## 功能与测试证据

- Context 相关最终回归：`93 passed, 2 skipped`。
- 覆盖 token 估算、SQLite/内存 repository、四区编译、稳定 snapshot、Tool Search、冻结工具预览、任务感知压缩、Reasoner 单次紧急恢复、Provider dialect、配置和端到端长工具循环。
- 本 change 影响面 Ruff：`All checks passed!`。
- 本 change 影响面 Pyright：`0 errors, 0 warnings, 0 informations`。
- 本 change strict 校验：通过。
- 主规格 `agent-runtime`、`context-management`、`tool-system` strict 校验：全部通过。

完整仓库测试曾运行到 `294 passed, 6 skipped, 1 failed`；唯一失败是另一个 CLI change 中 Windows 子进程 stdout 的 UTF-8 解码问题（`tests/test_cli_shell.py::test_legacy_main_uses_unified_echo_chat_entry`）。完整 Ruff 的既有问题位于其他 prompt/presentation/channel 修改；完整 Pyright 的既有问题位于 CLI command 代码。本 change 的相关测试与静态检查均已单独全量通过。

`openspec validate --all --strict` 结果为 `20 passed, 1 failed`。唯一失败是尚未完成的独立 change `refine-memory-driven-system-prompt`；本 change 及其三个主规格均通过 strict 校验。

## 迁移与回滚

- 新配置均有保守默认值，旧配置不需要一次性迁移；`history_window` 和各组件字符预算继续作为兼容硬上限。
- 持久化启用时只增量创建独立的 `context-state.db`，不迁移、不覆盖 trajectory、Personal Memory、Working State 或 Skill 数据库。
- 遇到未知 context-state schema version 时拒绝打开，不自动降级改写。
- 回滚时可设置 `[context].enabled = false` 或 `[context].compaction_enabled = false`；已有 context-state 数据保留但不消费，不应自动删除。
- Tool Search 默认关闭，保持完整确定性工具 schema；启用时才采用渐进披露。
- 压缩 Profile 留空时复用 agent/default；Echo 不允许提交正式 archive。

## 验收清单

- [x] 47 项实现任务均有对应代码、测试或文档证据。
- [x] 四区上下文、全局预算、KV/Prompt Cache 边界和稳定哈希已实现并记录。
- [x] 工具原文 payload、冻结预览与权限边界已验证。
- [x] soft/hard/emergency 压缩、不可变 archive、source refs 与熔断边界已验证。
- [x] OpenAI-compatible 与 Anthropic 消息/tool-call 合同已回归。
- [x] 配置兼容、SQLite schema 拒绝、迁移和回滚说明已完成。
- [x] 主规格与运行文档已同步。
- [x] 本 change 已具备归档条件；本记录不自动执行归档。
