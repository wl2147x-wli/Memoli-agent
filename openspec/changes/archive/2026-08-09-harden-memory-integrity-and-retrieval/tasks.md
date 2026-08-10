## 1. Schema 与事务

- [x] 1.1 实现 Memory schema v3、外键、busy timeout 和原子迁移
- [x] 1.2 实现 scope 内活动 Claim 唯一性及软删除后重记
- [x] 1.3 原子化 append、状态转移、关系改写和 consolidation run
- [x] 1.4 增加上下文管理、幂等关闭和双连接回归测试

## 2. 检索与治理

- [x] 2.1 校验状态机并把 approved 纳入 current
- [x] 2.2 修正 scope 通配、fallback LIMIT、BM25 排名和稳定 lane ID
- [x] 2.3 统一候选统计并增加截断诊断字段
- [x] 2.4 批量提交 consolidation 并强化 Card 证据验证
- [x] 2.5 导出当前 Card/Claim 并重构 Legacy 单快照导入

## 3. 验证

- [x] 3.1 增加 v1/v2 迁移中断、跨 scope 和软删除回归测试
- [x] 3.2 增加中文、英文、混合检索基准并只按失败证据调整分词
- [x] 3.3 更新记忆文档并执行 pytest、Ruff、Pyright、OpenSpec strict
