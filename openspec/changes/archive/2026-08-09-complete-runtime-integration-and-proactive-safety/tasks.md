## 1. 主动循环与兼容清理

- [x] 1.1 增加 run_on_start、initial_delay_seconds 配置和首次等待行为
- [x] 1.2 弃用并移除未使用的 WorkingStateStore.checkpoints 空快照

## 2. 集成测试

- [x] 2.1 增加 AgentLoop 两消息恢复、发布、取消和维护异常测试
- [x] 2.2 增加 Session 隔离/history window 与 Context 预算测试
- [x] 2.3 增加 Proactive quiet-hours 和首次调度测试
- [x] 2.4 增加 Inbound 到 Outbound 的确定性完整 E2E
- [x] 2.5 增加 workspace 临时目录和 UTF-8 PowerShell 测试入口

## 3. 验证

- [x] 3.1 更新运行时与 Proactive 文档
- [x] 3.2 执行 pytest、Ruff、Pyright、OpenSpec strict
