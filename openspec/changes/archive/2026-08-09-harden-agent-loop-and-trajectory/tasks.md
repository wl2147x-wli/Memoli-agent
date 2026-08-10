## 1. Agent loop 与 Reasoner

- [x] 1.1 统一规范化 Tool Call ID 并增加缺失 ID 回归测试
- [x] 1.2 隔离 AgentLoop 单轮、发布和维护异常并增加连续消息测试
- [x] 1.3 将 prepare_trace 和 checkpoint 轨迹失败转换为受控终止
- [x] 1.4 统一空白/截断响应恢复并按连续全失败轮次检测无进展

## 2. Trajectory 持久化

- [x] 2.1 改为显式事务并保护 rollback、close 与构造失败清理
- [x] 2.2 实现外部 payload 原子写入、回滚清理和受限孤儿 GC
- [x] 2.3 包装解压/读取错误并实现递归值级脱敏和键冲突保护
- [x] 2.4 增加 schema 迁移、span 索引和版本安全导出

## 3. 验证

- [x] 3.1 补齐轨迹与运行时故障注入测试
- [x] 3.2 更新运行时/轨迹文档并执行 pytest、Ruff、Pyright、OpenSpec strict
