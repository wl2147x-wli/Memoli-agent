# Memoli-agent OpenSpec 索引

`openspec/specs/` 是当前已实现、可验证行为的唯一事实源。设计文档和活跃 change
可以描述未来方向，但不得据此宣称能力已经交付。

## 当前 canonical capabilities

| Capability | 当前范围 |
| --- | --- |
| `agent-runtime` | Provider、Session-aware turn、有界多步 Agent Loop、SQLite 完整轨迹和记忆/工作状态接入 |
| `tool-system` | GenericAgent 风格默认九工具、串行执行、workspace 边界、工具轨迹和记忆管理工具 |
| `memory` | SQLite claims/cards/evidence、FTS5 检索、候选整理、冲突生命周期、用户治理和 Markdown 迁移 |
| `working-memory` | 独立 SQLite 工作状态、revision patch、checkpoint 投影、恢复、stale 和清理 |
| `plugins` | 当前已归档的基础插件发现、生命周期和失败隔离合同 |
| `subagents` | 本地受限 SubAgent、任务目录、前后台执行和完成回注 |
| `proactive` | opt-in 定时触发、cooldown、主循环回注和关闭语义 |
| `mcp-tools` | 本地 stdio MCP、命名空间、工具适配、失败隔离和清理 |
| `benchmarking` | TOML 驱动的 LoCoMo/LongMemEval 适配、指标和报告 |

## 活跃 changes

### `build-plugin-hooks-and-sandbox`

状态：实施中，72/73。Hook、manifest、Capability Broker、进程内和 Docker 后端代码
及安全回归已经完成；固定 digest runner 镜像尚未在可用 Docker daemon 上完成真实
构建验证。因此其 delta specs 尚未进入 canonical `plugins` spec。

### `design-lifelong-agent-evolution`

状态：架构母蓝图，1/40。它描述 Durable Tasks、Skill Learning、Evolution、
Post-training 和 Safety Governance 等未来能力，不是一次性 implementation change。
后续必须按依赖关系拆成小型 change，分别评审、实现、验证和归档。

## 已归档的近期 changes

- `2026-08-06-simplify-agent-loop-with-trajectories`
- `2026-08-07-adopt-genericagent-toolset`
- `2026-08-07-build-evidence-backed-memory-system`

## 下一步维护顺序

1. 在 Docker 可用环境完成插件 runner 镜像构建、digest 固定和真实容器测试，然后归档插件 change。
2. 为当前 canonical specs 建立并保存完整回归基线。
3. 将母蓝图的下一项实现拆为 `build-durable-task-execution`，不要直接 apply 母 change。
4. 每个实现 change 完成后同步文档并立即归档，避免代码、delta 与 canonical spec 再次漂移。

## 常用检查

```powershell
openspec list
openspec list --specs
openspec validate --all --strict
openspec doctor
```
