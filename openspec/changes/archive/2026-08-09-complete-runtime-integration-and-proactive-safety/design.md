## Context

ProactiveLoop 启动即 tick，测试主要覆盖子系统而非完整消息闭环；Windows conda 测试还受临时目录权限和控制台编码影响。

## Goals / Non-Goals

**Goals:** 安全首次调度、完整闭环回归、可重复 Windows 测试入口、移除误导 API。

**Non-Goals:** SQLite 异步化、MCP 并发、生产消息重试队列。

## Decisions

- run_on_start 默认 false；首次等待 initial_delay_seconds，未配置时等于 interval。
- quiet-hours 默认关闭；启用时使用显式 IANA 时区，并支持跨午夜区间。
- E2E 使用确定性 Provider 和临时 SQLite，不依赖外网。
- PowerShell 脚本在仓库 `.test-tmp` 下创建唯一目录并设置 UTF-8。
- checkpoints 全量空快照属性先弃用后删除，仅保留按 session 查询。

## Risks / Trade-offs

- [主动提醒首次发送变慢] → 用户可显式 run_on_start=true 恢复。

## Open Questions

无。
