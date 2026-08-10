## Context

Memoli 当前已经具备有界串行 Agent Loop、统一上下文装配、九个 GenericAgent 风格通用工具、SQLite 完整轨迹、SQLite 个人记忆、Working State、插件策略/容器沙箱和持久 SubAgent graph。程序性能力仍停留在两个占位边界：`memoli_agent/skills/README.md` 只约定未来放置 `SKILL.md`，`WorkingCheckpoint.related_sop` 只把模型提供的字符串注入后续 prompt，既不解析文件，也不验证、绑定或审计 Skill。

GenericAgent 的有效经验是把极简 L1 索引放入 system prompt，由模型根据任务选择 L3 SOP，再通过 `file_read` 按需加载全文；它避免把全部 SOP 注入上下文，但缺少版本、发布状态、依赖检查和稳定审计。Akashic 提供 builtin/workspace 扫描、catalog、依赖过滤和 active Skill 注入；Hermes 提供三级渐进披露和生命周期维护。Memoli 需要保留 GA 的极简选择路径，同时用 SQLite Registry、不可变 artifact、显式 `skill_load` 和现有安全边界解决工程治理问题。

本 change 面向在线 Runtime 使用者、Skill 作者和宿主管理者。离线学习系统是未来消费者：它将读取本 change 产生的精确 Skill 版本和 trajectory，但无权通过本 Runtime 直接修改 stable Skill。

关键约束：

- 在线 Runtime 保持轻量，不能导入 GEPA、DSPy 或训练框架。
- Skill 不能扩大 Tool Registry、Plugin Hook、SubAgent profile 或容器沙箱授予的权限。
- Skill 正文不得全部常驻 prompt；catalog 必须稳定、有界且可缓存。
- 当前 Session 历史只存在内存，因此版本快照必须绑定一次具体 Session 实例，而不是永久绑定通道使用的 `session_key=cli:local`。
- 现有 `related_sop`、九工具关闭路径、无 Skill 行为和 SQLite 数据必须向后兼容。

## Goals / Non-Goals

**Goals:**

- 定义兼容常见 Agent Skill 的 `SKILL.md` package，并把 SOP 统一视为 Skill 正文或 reference 中的程序性说明。
- 为 builtin、本地安装和未来 learned candidate 提供同一版本化数据合同，但仅向在线模型披露 active、可用且允许的版本。
- 使用 SQLite 原子管理版本、active 指针、撤销、回滚、Session 快照和管理事件。
- 使用一个只读 `skill_load(name, reference?)` 完成第二、三级渐进披露，不增加 Skill 专用执行器或在线管理工具。
- 在 catalog 与 Tool Result 中保留精确版本、内容哈希、来源和可用性，并写入现有 trajectory。
- 复用工具依赖、MCP 状态、插件策略、SubAgent allowlist 和文件安全边界，不建立第二套权限系统。
- 在 Skill Runtime 关闭、无可用 Skill或局部故障时保持普通 Agent Loop 可用且可观察降级。

**Non-Goals:**

- 不从单条或多条轨迹自动创建、修订或发布 Skill。
- 不实现 GEPA、Best-of-N、Skill fitness、replay、holdout、canary 分流或自动回滚。
- 不实现 Skill Hub、远程安装、签名信任链、Curator 或自动归档。
- 不实现 embedding/向量 Skill 检索；第一版由模型读取紧凑 catalog 自主选择。
- 不提供 `skill_create`、`skill_patch`、`skill_execute`、`skill_delete` 或 `skill_activate` 模型工具。
- 不自动执行 `scripts/`；脚本仅是 package artifact，执行仍经过现有通用工具和安全策略。
- 不把 `related_sop` 自动解析为可信 Skill，也不把 Working State 当作发布或授权来源。

## Decisions

### 1. 将 SOP 收敛为 Skill package，而不是建设并行 SOP Runtime

一次性任务进度继续进入 Working State，用户事实进入 Personal Memory，原始过程进入 trajectory；跨任务可复用的操作方法进入 Skill。短 SOP 写在 `SKILL.md`，长说明放入 `references/`，模板放入 `templates/`，机械资产放入 `scripts/`，回归样例放入 `tests/`。

选择统一模型是为了避免 `related_sop`、Markdown SOP、Skill Registry 和未来 GEPA 同时维护四套发现/版本语义。替代方案是保留 GA 的任意 `memory/*_sop.md` 扫描；它更简单，但无法可靠处理版本、权限、来源、回滚和评测归因。

### 2. Package 自声明运行需求，Registry 保存可信治理事实

`SKILL.md` 使用安全 YAML frontmatter，至少包含 `name`、`version`、`description`；可声明 `requires.tools`、`requires.mcp`、`requires.bins`、`requires.env`、`requires.platforms`、`requested_permissions` 和 `risk`。正文推荐包含 `Use when`、`Do not use when`、`Preconditions`、`Procedure`、`Failure recovery` 和 `Verification`。

`active/validated/approved`、来源轨迹、批准者、评测报告和上一版本不能由 Skill 文件自证，必须由 Registry 保存。解析使用 `yaml.safe_load` 并拒绝非映射、重复/未知关键字段的危险形态、非法名称、非法版本和超限文本；因此主依赖增加受约束的 PyYAML，而不复制 Akashic 的不完整手写 YAML 解析器。

### 3. 所有已安装版本复制到 workspace 不可变 artifact store

布局为：

```text
workspace/
  skills.db
  skill-artifacts/
    <name>/
      <version>/
        SKILL.md
        references/
        templates/
        scripts/
        tests/
```

builtin 和本地 package 都先进入 staging，完成结构、链接、大小、manifest 和 hash 校验后再原子移动到 artifact store，并在同一管理操作中注册 SQLite 元数据。`name@version` 已存在且规范内容哈希相同视为幂等；同版本不同哈希拒绝，更新必须使用新版本。

选择复制而不是直接引用 Python package 或任意 workspace 源目录，是为了避免包升级、文件编辑或路径移动静默改变 active 内容。候选目录不在 Runtime 扫描根中；未来 Evolution 只能显式注册 candidate。

### 4. SQLite Registry 是发布真相源，Markdown 是内容 artifact

首版 schema 包含：

- `skill_meta`：schema version。
- `skills`：稳定 `skill_id`、唯一名称、owner、source type、创建时间。
- `skill_versions`：版本、artifact path、规范内容哈希、manifest JSON、状态、上一版本和时间。
- `skill_active_versions`：每个 Skill 唯一 active version、上一 active、操作者与切换时间。
- `skill_session_snapshots`：记录 Session 实例的快照已创建事实，使“零个可见 Skill”的空快照也保持稳定。
- `skill_session_bindings`：Session 实例、session key、Skill、版本和绑定时间。
- `skill_registry_events`：installed、activated、deprecated、revoked、rolled_back 等审计事件及原因。

发布状态允许 `draft/candidate/validated/canary/active/deprecated/rejected/revoked`，但本 change 的宿主管理入口只要求安装、active、deprecated、revoked 和 rollback。active pointer 是解析权威，版本状态与指针在同一事务更新；运行时持有只读 Catalog/Resolver 端口，只允许另行写入 Session binding。

选择独立 `skills.db` 而不是修改 trajectory 或 memory schema，是因为三者生命周期、写权限和查询负载不同；trajectory 仍是运行证据，Registry 是版本和发布状态。

### 5. 使用 Session 实例快照，不永久绑定通道 session key

`SessionManager` 创建 `Session` 时生成不可变 `session_instance_id`。首次为该实例构造 catalog 时，在一个事务中把当时所有可见 active 版本写入 `skill_session_bindings`；后续 turn 和重启前的同一实例继续使用该快照。当前 Session 是内存对象，进程重启会创建新实例，因此自然获得最新 active catalog；历史 binding 仍保留审计但不会让固定的 `cli:local` 永久停留在旧版本。

普通 activate/deprecate 只影响之后创建的 Session 实例。已绑定 deprecated 版本允许当前 Session 完成；`revoked` 是安全例外，Resolver 每次加载均重新检查并立即拒绝所有 Session。替代方案是首次 `skill_load` 才绑定单项版本，但这会让同一会话的 catalog 在发布中途变化，违反新会话生效原则。

### 6. Catalog 是 Session 稳定的轻量路由索引

ContextBuilder 在基础 system 规则之后、动态记忆和 Working State 之前插入 `<available_skills>` block。每项只包含名称、绑定版本、路由 description 和必要来源标记；按名称确定性排序并应用字符预算。默认只披露依赖满足且通过当前 Agent/SubAgent 工具可见性检查的 Skill，不把缺失 env 值或宿主秘密写入模型上下文。

Catalog 对同一 Session 实例保持字节稳定，不随每轮状态变化重写。若预算不足，使用确定性顺序裁剪并记录总数、披露数和字符数；不允许截断单条 XML/结构边界。Description 负责 `Use when/Do not use when` 路由，首版不增加向量检索。

### 7. 一个 `skill_load` 工具完成渐进披露

启用 Skill Runtime 时注册第十个内置工具：

```text
skill_load(name, reference?)
```

无 `reference` 时返回去除 frontmatter 后的 `SKILL.md` 正文；提供相对 reference 时只允许读取绑定 package 内 `references/` 或经 manifest 明确披露的只读附属文本。结果使用 `<skill_instruction name version hash>` 边界，作为 Tool Result 固定在调用位置；后续模型使用现有 `file_read/file_write/code_run/web/MCP` 执行流程。

不选择让模型直接 `file_read` artifact 路径，是因为专用只读加载器能够隐藏物理路径、固定版本、限制引用、检查撤销并稳定记录 Skill 使用。也不选择把全文变成 system block，因为那会污染缓存、挤占每轮上下文并模糊选择时点。

### 8. Skill 声明不产生权限，依赖决定可见性和可加载性

Requirement evaluator 接收当前 Tool Registry、已连接 MCP server、bin、env 名称是否存在和平台信息。Catalog 生成时过滤不可用 Skill；`skill_load` 时再次检查，处理调用后环境变化。`requested_permissions` 只用于校验、展示和未来审批，实际动作仍必须通过现有 Tool Registry、`tool.before` Hook、用户确认和插件/容器策略。

SubAgent 使用共享 Registry，但基于 profile 实际 tool allowlist、MCP 可见性和独立 Session 实例生成过滤后的 catalog；主 Agent 可用 Skill 不自动对子 Agent 可见。Skill 加载不会改变 SubAgent depth、budget 或工具集合。

### 9. Package 读取采取拒绝逃逸和内容完整性校验

安装时枚举精确文件，拒绝绝对路径、`..`、符号链接、junction/reparse point、特殊文件、根目录外解析结果、超限文件和不允许目录。内容哈希按排序后的规范相对路径与文件字节计算。每次 load 至少校验目标路径仍位于 artifact 根；Skill 正文加载校验注册哈希或安全的 package 完整性缓存，发现缺失/篡改时拒绝而不自动回退到其他版本。

`scripts/` 不由 `skill_load` 执行，也不能通过 manifest 获得额外权限。若正文引导模型调用 `code_run`，仍适用当前 Shell 安全 Hook 和用户授权边界。

### 10. Skill 使用复用通用工具轨迹并增加领域事件

`skill_load` 仍产生现有 `tool_intent_recorded/tool_started/tool_completed` 事件，其 `ToolResult.metadata` 包含 `skill_name`、`skill_version`、`content_hash`、`source`、`reference` 和 `session_instance_id`。同时记录 `skill_load_requested`、`skill_loaded` 或 `skill_load_rejected` 领域事件，关联同一 trace/span/tool call。

领域事件不复制正文，只保存精确版本和原因；正文仍遵守 trajectory 的 `metadata-only/redacted/full-local` 捕获政策。这样后续评测可以计算选择率、加载时机、重复加载和任务结果，而无需改变每个通用工具产生评价字段。

### 11. 管理与运行边界分离

宿主侧管理入口提供 validate、install、list/show、activate、deprecate、revoke 和 rollback；它们调用 Registry Admin API，不注册为模型工具。所有状态变化要求 actor/reason 并写审计事件。Runtime 只能列举 Session snapshot 和加载正文/reference，不能写 Skill artifact、切换 active 或取消撤销。

第一版可通过独立 CLI 模块暴露管理命令，`main.py` 继续只负责 Runtime 启动。未来 GEPA 使用同一 Admin/Repository 合同写 candidate，但仍不能调用 activate。

### 12. `related_sop` 保持非权威兼容提示

`update_working_checkpoint.related_sop` 继续按原 schema 保存和注入，不自动解析、不触发加载、不绑定版本，也不授予权限。若它恰好等于 catalog 中的 Skill 名，模型可以据此调用 `skill_load`；不存在、拼写错误、deprecated 或 revoked 时由加载器返回确定性结果。

选择兼容而不是立即迁移 Working State schema，是因为历史 `related_sop` 可能是文件路径、自然语言或不存在的名称，不能安全转换成 verified Skill ref。未来 Durable Working State change 可新增结构化 `related_skills`。

### 13. 故障隔离和禁用路径保持现有行为

`[skills].enabled=false` 时不创建数据库、不注入 catalog、不注册 `skill_load`。Registry 打不开、schema 不兼容、catalog 生成失败或 artifact 损坏时，Skill 子系统 fail closed；普通九工具 Agent Loop继续运行，并通过 Runtime/trajectory 记录降级。不得扫描任意 workspace 文件作为隐式回退，也不得自动加载上一版本掩盖篡改。

配置增加：

```toml
[skills]
enabled = true
database = "workspace/skills.db"
artifact_root = "workspace/skill-artifacts"
catalog_max_chars = 6000
skill_max_chars = 15000
reference_max_chars = 30000
include_unavailable_in_catalog = false
allow_runtime_management = false
```

`allow_runtime_management` 首版只接受 `false`，防止配置看似允许但实现没有完整治理的危险状态。

## Risks / Trade-offs

- **[Catalog 随 Skill 数量增长]** → 施加确定性字符预算，只保留路由元数据；语义检索留给独立 change，并用压力测试验证选择质量。
- **[Description 写得差导致模型未加载]** → 规范要求包含适用/不适用条件，轨迹显式区分未选择和加载后失败；后续评测分别优化 routing 与 procedure。
- **[第三方 Skill 成为提示注入载体]** → 不自动信任 workspace，安装前安全解析与人工激活，Skill 权限低于 system/用户授权，无法扩大工具权限。
- **[文件与 SQLite 不一致]** → staging、内容哈希、原子移动和事务注册；load 时完整性检查，异常时拒绝而不猜测回退。
- **[Session 更新语义不清]** → 用独立 `session_instance_id` 定义快照寿命；进程重启产生新实例并获得新 active，管理文档明确这一边界。
- **[revoked 破坏正在运行任务]** → 安全撤销优先于连续性，返回明确拒绝；普通升级和弃用仍保持 Session 稳定。
- **[新增 PyYAML 扩大供应链]** → 固定兼容版本范围、只使用 `safe_load`、限制 schema；相比手写半套 YAML，行为更一致且更易安全审计。
- **[Skill scripts 被误认为可信可执行文件]** → Loader 只读取说明/reference，不执行脚本；所有实际执行继续通过现有工具、Hook 和沙箱。
- **[历史 related_sop 看似已正式化]** → Prompt 和文档明确其为 agent-maintained hint，trajectory 只把成功 `skill_load` 视为真实 Skill 使用。

## Migration Plan

1. 增加配置合同、Skill 模型、SQLite repository 和 manifest/package validator，默认测试环境可独立禁用。
2. 增加宿主管理入口和一个最小 builtin 示例 Skill；只注册到 staging/inactive，不改变 Runtime。
3. 接入 Session instance、snapshot resolver、catalog 渲染和 `skill_load`，在无 Skill/禁用路径运行现有回归基线。
4. 接入 Tool/MCP/SubAgent 可见性、内容完整性、安全路径和 trajectory 领域事件。
5. 显式激活 builtin 示例，在 CLI 完成“catalog → skill_load → 通用工具 → trace”端到端测试。
6. 更新配置示例、Skill 编写/管理文档和架构文档，执行 pytest、ruff、pyright 与 OpenSpec strict validation。

回滚时先将 `[skills].enabled=false`，Runtime 恢复九工具和无 catalog 行为；`skills.db` 与 artifact store 保留，不删除。若只回滚某版本，管理入口在事务中把 active pointer 切回 `previous_version_id`；既有 Session 保持原快照，新 Session 使用回滚版本。schema 升级必须先备份并拒绝未知未来版本，不能重建覆盖用户 Skill。

## Open Questions

- 第一批 builtin Skill 只提供用于端到端验证的 `research-report`，还是同时迁入一个现有 Memoli 操作流程？建议 change 实施时只交付一个小型、无脚本、只读研究 Skill，避免把内容质量与 Runtime 正确性混在一起。
- catalog 超预算时只按名称确定性截断，还是允许配置 pinned Skill？建议第一版只按名称和预算处理，pinned/usage-aware routing 留给评测后决定。
- reference 是否允许读取 `templates/`？建议 `skill_load(reference=...)` 第一版只读 `references/` 文本；模板仍由正文说明并通过受限 artifact-read 扩展在后续 change 加入，减少接口歧义。
