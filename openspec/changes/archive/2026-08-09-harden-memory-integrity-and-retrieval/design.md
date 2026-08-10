## Context

Memory SQLite 同时保存 Claim、Card、Episode、关系、索引任务和 consolidation run。当前全局 content hash、隐式事务和分步 consolidation 无法满足 scope 隔离与历史治理。

## Goals / Non-Goals

**Goals:** schema v3 原子迁移、scope 内活动去重、显式生命周期、原子 consolidation、相关性可解释的混合检索。

**Non-Goals:** 远程向量库、异步 SQLite 重写、反馈评测闭环。

## Decisions

- 活动状态为 candidate/active/approved/frozen，唯一键为 scope kind、scope id、content hash；历史状态可重复保存。
- 写操作使用显式立即事务；跨连接冲突读取数据库胜者。
- Consolidator 先收集验证，再单事务批量落库；失败 run 单独记录。
- 关键词 lane 保留 BM25 主排名，治理与稳定 ID 仅处理并列；scope 过滤先于 LIMIT。
- 默认导出 Card 与 Claim，Episode 继续作为轨迹派生索引。

## Risks / Trade-offs

- [重建 claims 表迁移成本] → 小批本地数据库在单事务中复制并故障注入验证。
- [严格 Card 证据降低生成率] → 第一版只接受完整 Claim 或确定性组合，后续另设 verifier。

## Migration Plan

v3 创建新表、复制数据、替换旧表、重建外键/FTS/索引并最后设置 user_version；失败完整回滚。

## Open Questions

无。
