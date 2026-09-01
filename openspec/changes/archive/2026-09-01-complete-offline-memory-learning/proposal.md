## Why

Memoli 当前已有 candidate-only consolidation 的数据模型、原子批次提交和派生 Card/语义索引，但实际 Runtime 未装配 Extractor 或离线 Worker，`start_long_term_update` 只创建进程内 pending 请求且没有消费者、重启后还会丢失。需要把“已提交轨迹 → 可审计候选记忆 → 独立治理 SubAgent 分级审核 → 用户处理高风险候选 → 派生投影”补成持久、可恢复的完整闭环，才能让长期记忆学习真正可用而不牺牲证据、隐私和用户控制。

## What Changes

- 将显式长期整理请求持久化，提供稳定 request ID、scope、状态、尝试次数、租约、版本和错误分类，并支持重启恢复与幂等查询。
- 增加独立于在线 turn 的有界离线记忆 Worker；Worker 只从已完成且当前主体有权访问的 SQLite trajectory 读取权威证据，不接收调用者提供的任意文本作为事实来源。
- 引入可替换、版本化的 Candidate Extractor 合同和固定结构输出，记录 extractor、schema、prompt/policy 与模型版本；所有隐式提取结果先进入 `candidate`。
- 在提交前回查 message/trace、role、逐字引用、scope、敏感等级和来源哈希；无效或越权证据不得生成候选。
- 为候选增加 subject/card kind、事实类型、实体、有效时间、重要度和置信度等可选结构字段，并在相关已有记忆上执行去重、时态与冲突关系判断。
- 增加最小权限的 `MemoryGovernanceSubAgent`，在独立于 Extractor 的治理任务中输出结构化 approve、reject、needs-user-review 或 defer 决定；确定性 Policy Gate 仅对满足证据、scope、风险、冲突、版本和并发规则的低风险候选执行自动批准。
- 扩展用户记忆治理和 CLI，允许按 scope 查看候选证据、自动审核记录及 `needs_user_review` 数量，并执行 approve、reject 或带新证据的修正；批准后才登记 Card 和语义索引投影。
- 为离线请求、提取批次、候选、派生投影和语义索引任务增加可恢复状态机、租约超时恢复、有界重试、dead-letter 与安全诊断；积压可在没有新用户 turn 时继续有界排空。
- 将 Episode 投影、Card 投影和远程 Embedding 从主消息泵的关键路径中隔离；用户回复和下一轮 turn 不等待非必要离线维护。
- 将记忆召回扩展为 Card-first 分层策略：稳定画像/偏好优先检索当前 Card statement，摘要不足时沿结构化 Statement→Claim→Evidence 关系按需展开；精确/高风险/最新事实保留 Claim 直达回退，事件型查询继续独立检索 Episode。
- 保持 `consolidation_enabled = false` 的兼容默认值；旧数据库通过原子迁移增加新表/字段，现有 Claim、Card、Episode、Trajectory ID 与历史关系保持不变。
- 非目标：Extractor、离线 Worker 或普通 Assistant 不得直接发布隐式候选；本变更不允许 Governance SubAgent 绕过 Policy Gate，不自动修改 Prompt、Skill、程序或模型参数，不引入在线自进化，不把任意 Assistant 文本或摘要提升为用户事实，也不要求部署外部队列、向量数据库或 GPU 服务。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `memory`: 将 candidate-only consolidation 从可手工调用的内核扩展为持久请求、权威轨迹读取、版本化提取、证据回查、自治分级治理、用户升级、冲突处理、可恢复派生维护和 Card-first 分层召回的完整离线学习闭环。
- `tool-system`: 扩展 `start_long_term_update` 的持久请求语义，增加仅供治理 SubAgent 使用的受限候选读取/决定合同，并为用户记忆管理、分层召回和 CLI 增加待审候选查看、批准、拒绝和状态查询合同。
- `agent-runtime`: 增加离线 Worker 与 Governance SubAgent 的启动、停止、租约恢复、非阻塞调度、最小权限 Profile、故障隔离与运行诊断边界。

## Impact

- **持久化**：`memory.db` 将新增长期整理请求、Worker 租约/尝试、提取版本、候选结构字段、governance job/decision、Card statement/Claim 映射、策略版本、升级原因和 dead-letter/诊断数据；迁移必须原子、幂等且可备份恢复。`trajectories.db` 继续作为只读权威证据，不迁移或复制原始轨迹正文。
- **代码边界**：影响 `agent/memory`、`agent/subagent`、`agent/tools/control.py`、`agent/tools/builtin.py`、`agent/working`、`agent/trajectory.py`、`channels`、`bootstrap/memory.py`、`bootstrap/app.py`、Agent Runtime 生命周期与相关测试。
- **公共合同**：`start_long_term_update` 返回持久 request 状态；增加 Governance SubAgent 专用决定合同；`memory_recall` 增加 auto/card-first/claim-first/episode-first/hybrid 路由和 summary/fact/evidence 细节层级；个人记忆治理工具与 CLI 增加候选和待用户审核操作。旧调用不带新参数时保持兼容。
- **安全与隐私**：离线 Worker 只能读取已提交、已脱敏且授权 scope 内的证据；敏感 Episode/Claim 是否允许进入远程 Extractor 或 Embedding 必须由独立策略决定，凭证、原始向量和越权正文不得进入诊断。
- **运行时**：在线 Agent Loop 不等待远程提取、治理 SubAgent、Card 构建或 Embedding；离线审核失败不得改变已发布记忆或终止普通对话，CLI 只读取治理状态并通过受管服务提交用户决定。
- **依赖**：默认实现保持 SQLite-first 和 asyncio；远程/本地 Extractor 通过可替换端口注入，本变更不强制新增外部基础设施。
