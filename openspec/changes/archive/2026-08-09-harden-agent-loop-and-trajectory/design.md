## Context

Reasoner、PassiveTurnPipeline、AgentLoop 与 TrajectoryStore 共同形成一次 turn 的可靠性边界。当前异常处理分散，轨迹 payload 同时跨 SQLite 与文件系统，需定义统一失败语义。

## Goals / Non-Goals

**Goals:** 单轮故障隔离、必需证据 fail-closed、稳定工具关联、递归脱敏、可迁移且可清理的轨迹存储。

**Non-Goals:** 并发 turn、分布式消息确认、远程轨迹后端。

## Decisions

- 在 Reasoner 每轮入口生成缺失 Tool Call ID，后续消息与执行复用同一对象。
- AgentLoop 捕获除取消外的单消息异常并构造无敏感信息的错误 Outbound；发布失败只记录诊断，不重试副作用。
- 核心轨迹失败终止 turn；Observer fail-open，Policy 在工具调用前 fail-closed。
- SQLite 连接使用 autocommit 加显式 `BEGIN IMMEDIATE`；rollback/close 独立保护原异常。
- 外部 payload 使用临时文件、原子 rename 和本次事务创建清单；维护命令按引用与宽限期回收孤儿。
- schema 版本只在迁移全部成功后推进；导出总是声明当前格式并保留来源版本。

## Risks / Trade-offs

- [副作用已发生后轨迹失败无法回滚] → 立即停止后续操作并在错误 metadata 标记副作用可能已提交。
- [值级脱敏误伤普通文本] → 只匹配明确 Header、URL 参数和高置信密钥模式并增加反例测试。
- [GC 误删审计数据] → 仅删除无数据库引用且超过宽限期的受管文件，默认 dry-run。

## Migration Plan

启动时备份或在事务内升级 schema，创建缺失索引后再更新版本；失败回滚并保持旧数据库可重试。

## Open Questions

无。
