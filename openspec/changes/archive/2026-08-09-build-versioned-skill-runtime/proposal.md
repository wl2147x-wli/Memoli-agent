## Why

Memoli 当前只有 `skills/` 占位目录和 Working State 中非权威的 `related_sop` 字符串，模型既看不到可选择的程序性能力索引，也无法按不可变版本加载、审计和恢复 Skill。需要在不膨胀默认上下文和通用工具集的前提下，将 GenericAgent 的“L1 极简索引 → 按需读取 L3 SOP”模式工程化为可版本化、可约束、可回滚的 Skill Runtime，为后续 Skill 评测和 GEPA 离线进化提供稳定执行边界。

## What Changes

- 新增 SQLite-backed Skill Registry，保存逻辑 Skill、不可变版本、active 指针、来源、内容哈希、依赖、发布状态和管理事件。
- 新增标准 Skill package/manifest 合同，使用 `SKILL.md` 承载适用条件和程序性说明，并支持有界的 `references/`、`templates/`、`scripts/` 与 `tests/` 附属资源。
- 新增确定性安装与发布管理入口：校验、安装、激活、弃用、撤销和回滚均创建新版本或原子切换指针，不覆盖既有版本。
- 在静态上下文中加入有界 Skill catalog，只披露当前会话可用 Skill 的名称、版本和路由描述；完整正文仅在模型调用 `skill_load` 后作为 Tool Result 进入轨迹。
- 在启用 Skill Runtime 时，将只读 `skill_load(name, reference?)` 作为第十个内置工具注册；Skill 只提供说明，不执行脚本、不授予工具权限，也不提供在线创建、修改或发布能力。
- 为首次加载建立持久 Session-version binding；普通激活只影响新 Session，已绑定 Session 保持版本稳定，安全撤销可立即阻止所有 Session 继续加载。
- 对 Tool、MCP、bin、env 名称、平台和请求权限执行可用性检查，并对 reference 路径、大小、普通文件类型及链接逃逸执行严格限制。
- 将 Skill 选择、解析版本、加载 reference、拒绝原因和内容哈希写入现有 SQLite trajectory，使后续系统能区分“未选择 Skill”和“Skill 内容无效”。
- 保留 `related_sop` 的现有 Working State 行为，将其定义为非权威提示；本 change 不根据该字段自动注入或自动加载 Skill。
- 明确不在本 change 中实现从轨迹生成 Skill、GEPA、自动评测、canary 分流、Curator、Skill Hub、语义 Skill 检索或在线 Skill 修改。

## Capabilities

### New Capabilities

- `skill-runtime`: 定义 Skill package、可信 Registry、不可变版本、安装发布、Session 绑定、渐进披露、依赖检查、安全读取、SubAgent 可见性和轨迹审计。

### Modified Capabilities

- `agent-runtime`: 将有界 Skill catalog 纳入统一上下文装配，并规定 Skill catalog/正文的信任边界、预算和失败隔离。
- `tool-system`: 在 Skill Runtime 启用时增加只读 `skill_load` 工具，同时保持原九个 GenericAgent 风格工具和现有可选工具语义。

## Impact

- **代码**：新增 `memoli_agent/agent/skills/` 与 `memoli_agent/bootstrap/skills.py`，修改配置、应用装配、上下文构建、工具装配、Reasoner 轨迹元数据和 SubAgent Runtime 依赖注入。
- **持久化**：新增 `workspace/skills.db` 和 `workspace/skill-artifacts/`；数据库必须显式版本化，安装与 active 指针更新必须事务化，既有 `working-state.db`、`memory.db` 和 trajectory schema 保持兼容。
- **工具接口**：启用 Skill Runtime 后默认模型工具由九个增加为十个；禁用或无可用 Skill 时保持现有行为，不引入 Skill 管理工具。
- **上下文**：增加稳定、有界的 catalog block；Skill 正文和 reference 仅在调用点进入消息历史，不运行中改写静态 system 前缀。
- **安全**：Skill 声明只能表达需求，不能扩大 Tool/Plugin/Sandbox 权限；外部 Skill 安装需宿主侧校验和显式激活，在线 Agent 默认只读。
- **依赖**：Runtime 继续保持轻量，不引入 DSPy、GEPA、向量数据库或训练框架；manifest 解析优先使用项目已批准的轻量安全解析方案。
- **迁移**：现有 `related_sop` 不迁移为已验证 Skill 引用；内置 Skill 和未来本地 Skill 通过显式安装/同步进入 Registry，不扫描并自动信任任意 workspace 文件。
