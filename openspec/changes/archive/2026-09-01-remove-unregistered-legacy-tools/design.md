## Context

主 Runtime 已只装配 GenericAgent 风格九工具及条件能力，但 `builtin.py` 仍保留四段不可达实现。其中 `calculator` 还被主规范描述为可由调用方显式注册，导致规范与“彻底删除遗留源码”的目标冲突。benchmark 的 `memory_write` 是独立的数据导入模式，不引用模型工具类，必须保留。

## Goals / Non-Goals

**Goals:**

- 删除三个未注册工具类和旧版 SubAgent 工具类。
- 删除只服务于这些类的安全算术 AST、路径读取和旧式委派代码。
- 让规范、文档、测试与实际支持的工具集合一致。
- 保持新版 `SpawnSubAgentTool`、`MemoryManageTool` 和 benchmark 导入路径不变。

**Non-Goals:**

- 不删除历史轨迹、归档 OpenSpec 或学习笔记中的历史名称。
- 不重命名 benchmark 的 `memory_write` ingest mode。
- 不改变当前主 Agent Schema、数据库或配置格式。

## Decisions

1. **直接删除实现，不保留抛出 deprecated 错误的空壳。** 这些工具已不在 bootstrap、插件或 profile 中注册，保留空壳只会延续误导。若模型或外部调用方请求旧名称，统一 Registry 已能返回“工具不存在”的结构化失败。
2. **保留历史和数据语义中的同名文本。** 归档变更与轨迹属于审计记录；benchmark `ingest_mode="memory_write"` 是适配器策略，不是 `MemoryWriteTool`，机械替换会破坏无关合同。
3. **保留 Registry 的旧名称 internal 分类仅在确有历史兼容价值时。** `memory_write` 不再可能被当前 Runtime 注册，也不再参与当前工具用途判定，因此从 internal 名称集合删除；历史轨迹读取不依赖该集合。
4. **用静态无引用检查和 Registry 集合回归验证删除。** 测试确认默认/可选工具仍可装配，并确认四个旧类不能再从模块导入。

## Risks / Trade-offs

- [外部 Python 调用方仍手工导入旧类] → 这是明确的破坏性删除；迁移到 `code_run`、`file_read`、`memory_manage`/离线整理和新版 `SpawnSubAgentTool`。
- [误删 benchmark 同名模式] → 仅删除 `memoli_agent.agent.tools` 实现与对应工具规范，保留 benchmark 配置和适配器。
- [文档仍将旧工具写成“可兼容注册”] → 同步当前工具文档；归档设计保留历史原貌。

## Migration Plan

1. 先同步当前规范，移除 calculator 兼容合同并声明旧名称不可用。
2. 删除类、辅助函数和孤立 import，更新回归测试与当前文档。
3. 运行工具测试、完整静态检查和 OpenSpec strict validation。
4. 回滚时恢复同一变更中的规范、源码和测试；无需数据库回滚。

## Open Questions

无。
