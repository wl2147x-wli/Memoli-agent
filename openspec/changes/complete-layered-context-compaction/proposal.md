## Why

Memoli Agent 已具备工具结果预览、近期 tail、上下文 archive 和超限重试等压缩部件，但这些部件尚未形成可靠的分层闭环：Session 会在压缩前按消息条数丢弃历史，soft/hard 阈值没有驱动同一套任务感知压缩流程，archive 会无总预算地逐代累积，持久化提交与会话清理边界也不一致。结果是长会话中仍可能无提示丢失上下文、重复摘要、恢复旧对话或最终再次超出模型窗口。

## What Changes

- 把模型可见上下文明确为五层：稳定前缀、受治理动态材料、冻结工具结果预览、近期完整 turn、分层任务 archive；统一由 Provider 前编译器按全局 token 预算选择。
- 以可重放的规范化 turn 事实作为跨轮上下文来源，使压缩发生在原始完整 turn 被短期窗口删除之前；Session 不再拥有一套会提前破坏工具协议和归档来源的消息窗口。
- 引入持久化 conversation epoch；`/clear` 创建新 epoch 并清除该 epoch 的派生上下文视图，同时保留审计轨迹和长期记忆，防止旧轨迹或旧 archive 在清理后重新注入。
- 让 soft threshold 触发批量任务感知压缩，hard threshold 触发更强的同步降载，Provider context-length error 只作为最后一次紧急重编译；三种路径复用同一选择、去重、校验和熔断合同。
- 为 archive 增加总 token/代数预算、层级合并与覆盖引用；只注入有界的当前 archive frontier，不再把所有历史 generation 永久全量发送给模型。
- 压缩事务原子提交 archive、源引用覆盖关系、generation/frontier 和失败状态；失败不得改变当前可见视图，也不得留下孤立 archive。
- 使用结构化 Context Block 类型和显式 trust/priority/required 元数据代替基于正文 XML 标记的分类，避免用户文本被误分类或提升权限。
- 为模型 tokenizer/保守估算、各层预算、裁剪收益、archive frontier、降级状态和紧急恢复记录可验证诊断。
- 为冻结工具结果预览增加 epoch 归属、生命周期清理和可恢复引用校验，保持 tool call/result 协议完整。
- **BREAKING**：移除 `[agent].history_window`；旧配置出现该字段时返回带迁移指引的配置错误，改用 `[context]` 下按 turn、token 和读取字节定义的有界候选读取配置。
- 非目标：不改变个人记忆 Claim/Card 的检索与治理，不把 context archive 发布为长期记忆或训练数据，不依赖供应商专有 Prompt Cache API，也不恢复隐藏 reasoning。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `context-management`: 完整定义分层上下文来源、阈值状态机、有界 archive frontier、原子提交、结构化信任边界和诊断合同。
- `agent-runtime`: 修改跨轮会话恢复、conversation epoch、`/clear`、配置迁移及主 Agent/SubAgent 隔离行为。
- `tool-system`: 补充冻结工具结果预览的 epoch 生命周期、引用完整性和压缩期间协议保护要求。

## Impact

- 主要影响 `agent/session.py`、`agent/context.py`、`agent/core/reasoner.py`、`agent/trajectory.py`、`agent/context_management/`、生命周期阶段、CLI `/clear`、bootstrap 配置与装配。
- `context-state.db` 与 `trajectories.db` 需要增量 schema 迁移，新增 conversation epoch、规范化 turn 消息、archive coverage/frontier 和提交状态；迁移不得删除现有轨迹、payload、memory 或 working-state 数据。
- 公开工具名称与参数保持兼容；`[agent].history_window` 配置不再兼容，需迁移为新的 `[context]` 候选读取与预算配置。
- Context archive 仍是可重建的派生视图；原始可见交互与受管 payload 是事实来源。轨迹关闭或内容捕获不足时，Runtime 必须显式降级为进程内上下文，不能声称可跨重启恢复。
- 安全上不再通过正文标记推断块类型或信任等级；archive、memory、插件和工具输出始终按低权限数据处理，受管引用不授予额外读取权限。
