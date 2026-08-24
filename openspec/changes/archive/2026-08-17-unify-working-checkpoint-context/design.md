## Context

当前 `PromptRenderPhase` 从 repository 读取 checkpoint 并通过 `render_checkpoint()` 生成只含 `key_info`/`related_sop` 的遗留 system message。随后 Reasoner 的统一调用前装配器过滤 `<working_checkpoint>` 与 `<agent_status>`，再调用 `render_status()` 追加最新动态状态。生产装配把同一个 store 传入两处，因此通常能得到正确最终请求，但 Phase 输出、Hook 上下文与简化测试仍可能观察到旧格式，且维护者容易误以为存在两套权威状态。

## Goals / Non-Goals

**Goals:**

- 让 Reasoner 的调用前动态装配成为模型工作状态的唯一文本入口。
- 每次 Provider 调用只含一个最新 `<agent_status>`，工具循环、重试与 fallback 行为一致。
- 完整表达 Agent checkpoint 字段，并明确区分 Runtime 硬产物与 Agent 软产物。
- 保持 checkpoint repository、tool schema、snapshot/UI 与配置兼容。

**Non-Goals:**

- 不改变 checkpoint 创建时机、自动完成/恢复策略或 task scope 模型。
- 不迁移 SQLite schema，不改变长期记忆和 context archive。
- 不把 Agent 声称的 artifacts 提升为 Runtime 已验证事实。

## Decisions

### 1. Phase 不再生成工作状态文本

`PromptRenderPhase` 只组合稳定 system prompt、Skill catalog、Memory、Session 历史和当前用户消息，`working_prompt_block` 保持空。工作状态具有高变化频率，放在调用前动态尾部更符合 KV Cache 稳定前缀和最新状态要求。

替代方案是让 Phase 直接调用新版 `render_status()`；这仍会在工具循环中变旧，并要求 Reasoner继续替换，因此不采用。

### 2. 保留 Reasoner 的防御性去重

调用前装配仍过滤历史或 Hook 贡献中的 `<agent_status>`/`<working_checkpoint>`，再追加唯一新版状态。这既兼容已有 Session 内容，也防止插件或测试夹具形成重复动态块。真正发送给 Provider 的消息与审计 revision 均来自这一处。

### 3. 单一 renderer 完整表达软硬状态

`render_status()` 的 Runtime section 继续承载 iteration、elapsed、last tool/status 与经过 Runtime 验证的 artifacts；Agent section增加 constraints、decisions、Agent artifacts，并保留 objective/current step/next action/key info/related SOP/status/stale。列表使用确定性顺序与明确空值，沿用现有字符上限。

### 4. 删除遗留内部接口

移除无生产调用价值的 `render_checkpoint()`，测试改为验证 Phase 不预置工作状态，以及 Provider 每次调用获得唯一完整动态块。该方法不是公开 CLI/API/Tool 协议，不提供弃用周期。

## Risks / Trade-offs

- [依赖 Phase 输出旧块的内部测试或自定义模块失效] → 更新仓库测试并以调用前 Provider 请求作为权威验收点。
- [完整 Agent 字段增加动态 token] → 继续使用 `max_chars` 有界渲染；字段按结构化短行输出，不复制 revision 历史。
- [Hook 注入伪造状态] → Reasoner 过滤已知状态标签并由 store 重建，保持 trust 边界。

## Migration Plan

1. 增加唯一注入与完整字段回归测试。
2. 停止 Phase 遗留注入并删除旧 renderer。
3. 更新架构文档和 canonical specs，运行 pytest、Ruff、Pyright 与 OpenSpec strict validation。
4. 无数据迁移；回滚可恢复旧方法和 Phase 调用，SQLite 内容不受影响。

## Open Questions

无阻塞问题。自动创建、complete/restore 生命周期作为后续独立行为变更处理。
