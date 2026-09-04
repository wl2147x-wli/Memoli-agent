## 1. 持久化合同与迁移

- [x] 1.1 为 ContextSnapshot 和 ToolDisclosure 增加能力 revision 与规范指纹/差异合同，并通过序列化往返和稳定哈希单元测试验证。
- [x] 1.2 将 context-state schema 升级为按 `(session, epoch, revision)` 保存不可变快照及披露记录，并通过旧版数据库 fixture 验证 revision 1 原子迁移、幂等重开和失败回滚。
- [x] 1.3 扩展 Repository 的最新 revision、精确 revision 和并发追加接口，并通过内存/SQLite 共享合同测试验证相同指纹收敛、不同指纹单调追加且旧 revision 不被覆盖。

## 2. Turn 级能力协调

- [x] 2.1 在 Context Compiler 首次编译时比较当前规范能力指纹，复用相同 revision 或创建新 revision，并通过新增、删除、schema 修改和无变化重启测试验证。
- [x] 2.2 在 Reasoner 与生命周期 phase 中保存 turn-local revision，并传递到工具续接、压缩后重编译和 emergency 重试；通过多工具循环测试验证一个 turn 内工具集合字节级不变、下一 turn 自动更新。
- [x] 2.3 将 Tool Search 披露绑定 revision，并通过披露工具保持、移除、schema 变化、同名重叠和并发 turn 测试验证不会跨 revision 错误复活能力。
- [x] 2.4 保持安全撤销立即 fail closed，并通过启动后删除工具和活动 turn 撤销测试验证模型不再收到或执行已撤销工具。

## 3. 诊断与回归

- [x] 3.1 在编译诊断、模型 span 和轨迹载荷中记录 capability revision、聚合 hash 与有界名称级差异，并通过敏感 schema 注入扫描验证不泄漏完整秘密内容。
- [x] 3.2 增加 `memory_manage_enabled` 从 false 变为 true 的真实重启/持久会话回归，验证无需 `/clear`、历史仍保留、下一 turn 请求包含 `memory_manage` 且能够成功调用。
- [x] 3.3 增加持久化失败回归，验证检测到漂移但无法保存新 revision 时在联网前明确失败且不复用过期 schema。

## 4. 文档与验收

- [x] 4.1 更新 Context Management、工具和运维文档，说明 epoch、capability revision、重启复用、安全撤销及 `/clear` 的不同边界，并通过文档链接检查验证。
- [x] 4.2 运行 `python -m pytest -q`、`python -m ruff check memoli_agent benchmarks tests`、`python -m pyright` 和 `openspec validate --all --strict`，四项通过后完成实施验收。
