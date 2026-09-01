## Why

Memoli 当前通过 Session 消息窗口、Memory/Skill/Working State 各自的字符上限控制上下文，但缺少面向模型窗口的统一 token 预算、稳定缓存前缀和输入超限恢复；长工具循环仍可能因滑动删除、动态块前置或累计工具结果而出现 Prompt Cache 失效、上下文腐化和 `context_length_exceeded` 失败。现在需要把现有分块能力收敛到一个可审计的上下文编译边界，在不削弱证据、权限和记忆治理的前提下支持长任务。

## What Changes

- 在每次 Provider 调用前统一编译模型可见上下文，明确稳定静态前缀、不可变归档、近期完整轨迹和动态尾部的顺序及信任边界。
- 为模型 Profile 增加输入窗口、输出预留、安全余量和压缩阈值配置，并按模型 tokenizer 或保守估算执行全局 token 预算。
- 固定基础 system prompt、Session Skill catalog 和工具 schema 的规范化内容及顺序；动态记忆、插件扩展和最新 Working State 不得改写高复用静态前缀。
- 用按完整 turn 保留的近期尾部和不可变归档摘要替代纯消息条数滑窗作为主要长上下文策略，同时保留 `history_window` 作为兼容/安全上限。
- 为大体积工具结果建立“完整受管 payload/artifact + 冻结模型预览 + 稳定引用”的表示，避免仅截断后不可恢复。
- 实现分层压缩：确定性噪声剔除、工具结果批量压缩、带证据引用的任务感知归档，以及最后手段的全量压缩；已压缩内容不得反复摘要。
- 当 Provider 报告输入上下文超限时，在同一 trace 内强制执行一次有界紧急压缩和重编译；连续压缩失败必须熔断并返回可观察错误。
- 记录每次编译的上下文块、实际/估算 token、稳定前缀哈希、工具 schema 哈希、压缩代次、裁剪原因和 Provider 缓存 usage，支持验证缓存命中与信息保留。
- 明确压缩只服务于当前任务，不自动发布 Personal Memory、Skill 或训练数据；原始轨迹和受管 payload 继续作为可追溯证据。
- 非目标：本 change 不重新设计长期记忆检索算法、不改变 Skill 包发布流程、不引入新的模型训练流程，也不要求所有 Provider 支持服务端上下文编辑或显式 Prompt Cache 控制。

## Capabilities

### New Capabilities

- `context-management`: 定义统一上下文布局、token 预算、缓存稳定性、分层压缩、不可变归档、超限恢复及编译审计。

### Modified Capabilities

- `agent-runtime`: 将 Session 被动 turn 和动态上下文装配改为统一、缓存感知且可压缩的 Provider 前编译流程，并规定配置兼容和失败边界。
- `tool-system`: 规定工具 schema 的确定性快照/排序，以及大型工具结果的可恢复模型预览和压缩引用合同。

## Impact

- 主要影响 `agent/context.py`、`agent/core/reasoner.py`、`agent/session.py`、`agent/trajectory.py`、`agent/tools/registry.py`、Provider 路由/合同、bootstrap 配置与装配，以及相关测试和运行文档。
- 配置将新增 context window 与 compaction 参数；旧配置缺少这些字段时使用保守默认值，现有 `history_window`、Memory、Working State 和 Skill 字符预算继续兼容。
- 可能新增 schema-versioned 的 Session context archive/preview 元数据存储；迁移只能增量创建，不得重写或删除既有 trajectory、memory、working-state 或 Skill 数据。
- 工具公开名称和调用参数保持兼容；工具结果的模型可见长内容可能改为带引用的有界预览，但原始脱敏内容仍可通过受管本地证据恢复。
- 安全上保持静态规则优先，Memory、外部内容、插件段和压缩摘要均为低权限数据；摘要中的命令式文本不得提升为用户授权或 system rule。
- 与 `refine-memory-driven-system-prompt` 的边界：后者负责静态提示内容，本 change 只负责其版本化、稳定放置、预算和运行时编排，不重复定义提示词正文。
