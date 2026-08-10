## Why

当前串行 AgentLoop 与 SQLite 轨迹边界仍存在单轮异常终止消息泵、轨迹写入失败后继续执行、敏感值泄漏和外部 payload 孤儿等风险。必须先建立可恢复、可审计且失败封闭的运行时基础，后续长期记忆和自进化才有可靠数据源。

## What Changes

- 统一工具调用 ID、空响应重试、无进展检测与结构化失败回复。
- 隔离单轮、发布和维护异常，核心轨迹写入继续 fail-closed。
- 加固 SQLite 事务、关闭、回滚、payload 清理、迁移、导出和递归脱敏。
- 增加轨迹 GC、旧 schema 导出和异常注入回归测试。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-runtime`: 修改串行循环的错误隔离、工具调用关联和终止行为。
- `tool-system`: 明确副作用后必需轨迹写入失败的终止边界。

## Impact

影响 AgentLoop、PassiveTurnPipeline、Reasoner、TrajectoryStore、出站错误 metadata、SQLite schema 和运行时测试；轨迹数据库需要向后兼容迁移。
