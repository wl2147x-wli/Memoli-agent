## Why

当前 SQLite 记忆在软删除重记、跨 scope 去重、并发写入、迁移恢复和检索排序上存在一致性缺口，可能导致记忆丢失、错误复用或不可解释召回。

## What Changes

- 引入 Memory schema v3、scope 内活动记忆唯一性和显式事务。
- 校验状态机、批量 consolidation、Card 证据和 Legacy 快照导入。
- 修正 scope、BM25、fallback LIMIT、统计、导出和截断诊断。
- 增加迁移、双连接、中英文混合检索和资源关闭测试。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `memory`: 修改记忆持久化、治理状态、检索、导出、迁移和诊断合同。

## Impact

影响 SQLiteMemoryStore、MemoryRuntime、HybridMemoryRetriever、Consolidator、Legacy migrator、memory.db schema 和相关 benchmark。
