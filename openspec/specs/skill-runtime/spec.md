# skill-runtime Specification

## Purpose
TBD - created by archiving change build-versioned-skill-runtime. Update Purpose after archive.
## Requirements
### Requirement: Validated Skill package contract

系统 SHALL 仅将通过 schema、名称、版本、描述、目录结构、文件类型、大小和内容完整性校验的 `SKILL.md` package 注册为 Skill 版本；Skill 自声明的运行需求 SHALL 与 Registry 保存的来源、批准和发布状态分离。

#### Scenario: Valid package is inspected

- **WHEN** 宿主管理入口校验包含合法 frontmatter 和允许附属目录的 Skill package
- **THEN** 系统 SHALL 返回规范化名称、版本、description、依赖、请求权限、文件清单和内容哈希
- **AND** SHALL NOT 因校验本身安装或激活该 package

#### Scenario: Package claims trusted state

- **WHEN** `SKILL.md` 自行声明 `active`、`validated`、`approved` 或等价治理状态
- **THEN** 系统 SHALL 拒绝该字段或忽略其治理含义
- **AND** Registry SHALL 只接受宿主管理流程产生的发布状态

### Requirement: Immutable Skill artifacts

每个已安装 `name@version` SHALL 对应 workspace 内不可变 artifact 和规范内容哈希；同版本不得被不同内容覆盖，更新必须创建新版本。

#### Scenario: Same version is installed repeatedly

- **WHEN** 同一 `name@version` 及相同规范内容哈希被重复安装
- **THEN** 安装 SHALL 幂等返回既有版本
- **AND** SHALL NOT 重写 artifact 或重复创建版本

#### Scenario: Same version has different content

- **WHEN** 已注册 `name@version` 收到不同内容哈希的 package
- **THEN** 系统 SHALL 拒绝覆盖
- **AND** 既有 artifact、active 指针和 Session binding SHALL 保持不变

### Requirement: Versioned SQLite Skill Registry

系统 SHALL 使用显式 schema 版本的 SQLite Registry 保存逻辑 Skill、不可变版本、active 指针、Session binding 和管理事件，并 SHALL 在未知或未来 schema 版本下拒绝启动 Skill 子系统而不重建数据。

#### Scenario: Registry is initialized

- **WHEN** 启用 Skill Runtime 且目标数据库尚未存在
- **THEN** 系统 SHALL 原子创建完整 schema 和版本标记
- **AND** SHALL 支持重复启动而不丢失既有记录

#### Scenario: Registry has unsupported schema

- **WHEN** Skill Registry 的 schema 版本不受当前 Runtime 支持
- **THEN** Skill 子系统 SHALL 拒绝读写该数据库并报告降级原因
- **AND** SHALL NOT 删除、重建或部分迁移既有数据

### Requirement: Governed install and release operations

宿主管理入口 SHALL 提供 validate、install、inspect/list、activate、deprecate、revoke 和 rollback 操作；所有发布状态变化 SHALL 带 actor、原因和时间并在事务中更新 active 指针与审计事件。

#### Scenario: Installed version is activated

- **WHEN** 授权宿主管理者激活一个已安装且可发布的版本
- **THEN** Registry SHALL 原子保存新的 active 指针、上一 active 版本和管理事件
- **AND** 失败时 SHALL 保持切换前状态

#### Scenario: Active version is rolled back

- **WHEN** 授权宿主管理者要求回滚且存在上一稳定版本
- **THEN** Registry SHALL 原子将 active 指针切回上一版本
- **AND** SHALL 保存回滚 actor、原因和被替换版本

#### Scenario: Model attempts Skill management

- **WHEN** 在线模型查看可用工具
- **THEN** 工具集合 SHALL NOT 暴露 install、activate、patch、delete、revoke 或 rollback Skill 的管理能力

### Requirement: Session-stable Skill snapshot

Runtime SHALL 为每次新建的 Session 实例分配不可变实例标识，并在首次构造 catalog 时绑定当时可见的 active Skill 版本；普通激活或弃用 SHALL 仅影响后续新 Session 实例。

#### Scenario: Active version changes during a Session

- **GIVEN** 当前 Session 已绑定 `research-report@1.0.0`
- **WHEN** 宿主管理者激活 `research-report@1.1.0`
- **THEN** 当前 Session 的 catalog 和后续加载 SHALL 继续解析到 `1.0.0`
- **AND** 新建 Session SHALL 解析到 `1.1.0`

#### Scenario: Runtime restarts for a fixed channel key

- **WHEN** 进程重启后为相同 channel/session key 创建新的内存 Session 实例
- **THEN** 系统 SHALL 分配新的 Session 实例标识并使用当时 active 版本
- **AND** 历史 binding SHALL 保留审计但不得永久固定新实例

#### Scenario: Bound version is revoked

- **WHEN** 已绑定版本因安全原因被标记 `revoked`
- **THEN** 所有 Session 的后续加载 SHALL 立即拒绝该版本
- **AND** SHALL NOT 自动回退到未绑定版本

### Requirement: Bounded Skill catalog disclosure

Runtime SHALL 为每个 Session 生成确定性、有界的 Skill catalog，仅披露当前快照中允许且可用版本的名称、版本和路由 description，不注入完整正文或秘密依赖值。

#### Scenario: Initial context contains available Skills

- **WHEN** 新 Session 至少存在一个依赖满足且对当前 Agent 可见的 active Skill
- **THEN** 首次模型上下文 SHALL 包含按确定性顺序排列的 Skill catalog
- **AND** 每项 SHALL 包含名称、绑定版本和适用/不适用路由描述

#### Scenario: Catalog exceeds its budget

- **WHEN** 可见 Skill 元数据总量超过配置字符预算
- **THEN** Runtime SHALL 按确定性规则保留完整 catalog 条目并裁剪低优先级条目
- **AND** SHALL 记录候选数、披露数和实际字符数而不产生半条结构

#### Scenario: Requirement includes a secret environment variable

- **WHEN** Skill 声明需要某环境变量且系统检查其可用性
- **THEN** catalog 和错误信息 SHALL 最多披露变量名称及存在性
- **AND** SHALL NOT 披露变量值

### Requirement: Progressive Skill loading

Runtime SHALL 通过只读 `skill_load(name, reference?)` 按 Session 绑定版本加载 Skill 正文或允许的 reference，并 SHALL 将内容作为带名称、版本和哈希边界的 Tool Result 固定在调用位置。

#### Scenario: Active Skill body is loaded

- **WHEN** 模型调用 `skill_load` 请求 catalog 中可用的 Skill 且不指定 reference
- **THEN** 工具 SHALL 返回绑定版本去除 frontmatter 后的有界正文
- **AND** 后续模型调用 SHALL 能从该 Tool Result 使用程序性说明

#### Scenario: Allowed reference is loaded

- **WHEN** 模型为已绑定 Skill 请求 package 内允许且大小合规的文本 reference
- **THEN** 工具 SHALL 返回该精确版本的 reference 内容及来源元数据
- **AND** SHALL NOT 切换 Skill 版本或执行 reference 中的命令

#### Scenario: Skill is absent from the snapshot

- **WHEN** 模型请求未绑定、未披露或不存在的 Skill 名称
- **THEN** `skill_load` SHALL 返回确定性失败结果
- **AND** SHALL NOT 扫描任意 workspace 路径寻找同名文件

### Requirement: Requirement-aware availability

Skill Runtime SHALL 根据当前 Tool Registry、MCP 连接、可执行文件、环境变量存在性、平台和 Agent/SubAgent 可见能力检查 Skill 可用性，并在 catalog 生成和实际加载时分别校验。

#### Scenario: Required tool is unavailable

- **WHEN** Skill 依赖当前 Agent 不可见的工具
- **THEN** 该 Skill SHALL 不进入默认 catalog
- **AND** 显式加载 SHALL 返回缺失能力而不注册或暴露该工具

#### Scenario: Environment changes after catalog creation

- **WHEN** Skill 在 catalog 生成时可用但加载前所需 MCP 或 bin 变为不可用
- **THEN** `skill_load` SHALL 拒绝本次加载并记录缺失需求
- **AND** SHALL NOT 返回可能诱导执行的不完整正文

### Requirement: Non-escalating Skill authority

Skill 的依赖、请求权限、正文、reference 和 script SHALL NOT 改变当前用户授权、Tool Registry、Plugin Hook、Sandbox、SubAgent profile 或 Runtime 安全规则。

#### Scenario: Skill requests a privileged action

- **WHEN** 已加载 Skill 指示模型调用高风险或当前禁用工具
- **THEN** 实际动作 SHALL 继续经过现有工具可见性、策略 Hook、确认和沙箱边界
- **AND** Skill 的 active 状态 SHALL NOT 被视为动作授权

#### Scenario: Package contains a script

- **WHEN** 已安装 Skill 包含 `scripts/` 文件
- **THEN** `skill_load` SHALL NOT 自动执行该脚本或为其创建专用权限
- **AND** 任何后续执行 SHALL 使用现有工具并接受其安全策略

### Requirement: Confined and integrity-checked package reads

安装和加载 SHALL 拒绝绝对路径、父目录逃逸、符号链接、junction/reparse point、特殊文件、根目录外解析结果、内容超限和哈希不一致，并 SHALL NOT 在完整性失败时静默选择其他版本。

#### Scenario: Reference escapes the package

- **WHEN** `reference` 包含绝对路径、`..` 或解析到绑定 artifact 根之外
- **THEN** `skill_load` SHALL 拒绝读取并记录安全原因
- **AND** SHALL NOT 返回目标文件的任何内容

#### Scenario: Active artifact was modified out of band

- **WHEN** 加载时发现 artifact 缺失或内容与 Registry 哈希不一致
- **THEN** Runtime SHALL 拒绝加载并报告完整性失败
- **AND** SHALL NOT 自动读取源目录、上一版本或同名 workspace 文件

### Requirement: Skill trajectory audit

每次 Skill 加载请求 SHALL 在现有 trace 中记录名称、绑定版本、内容哈希、来源、reference、Session 实例、成功状态或拒绝原因，并遵循当前 trajectory 内容捕获和脱敏策略。

#### Scenario: Skill is loaded successfully

- **WHEN** `skill_load` 成功返回正文或 reference
- **THEN** trace SHALL 同时保留通用工具事件和可查询的 `skill_loaded` 领域证据
- **AND** 领域证据 SHALL 可关联到相同 tool call 和精确 Skill 版本

#### Scenario: Skill load is rejected

- **WHEN** 加载因不存在、撤销、依赖、路径、预算或完整性失败被拒绝
- **THEN** trace SHALL 记录 `skill_load_rejected` 及稳定原因类别
- **AND** SHALL NOT 将受保护正文复制到拒绝事件

### Requirement: SubAgent-scoped Skill visibility

SubAgent SHALL 使用共享 Skill Registry 和独立 Session snapshot，但其 catalog 与加载结果 SHALL 受 profile 实际工具 allowlist、MCP 可见性和预算限制，不继承主 Agent 的更高权限或已加载正文。

#### Scenario: Parent-visible Skill needs a denied SubAgent tool

- **WHEN** 主 Agent 可见 Skill 依赖当前 SubAgent profile 禁止的工具
- **THEN** 该 Skill SHALL 不出现在 SubAgent catalog
- **AND** SubAgent 显式加载 SHALL 返回不可用

#### Scenario: Parent delegates after loading a Skill

- **WHEN** 主 Agent 已加载某 Skill 后创建 SubAgent task
- **THEN** SubAgent SHALL 根据自己的 snapshot 和能力独立选择是否加载该 Skill
- **AND** 主 Agent 的 Tool Result SHALL NOT 被隐式复制为 SubAgent system instruction

### Requirement: Legacy related_sop compatibility

现有 `related_sop` SHALL 继续作为 Agent 维护的非权威 Working State 提示保存和注入，但 SHALL NOT 自动解析、绑定、加载、发布 Skill 或授予权限。

#### Scenario: related_sop matches a Skill name

- **WHEN** 工作状态包含与 catalog Skill 同名的 `related_sop`
- **THEN** 模型 MAY 根据提示显式调用 `skill_load`
- **AND** 只有成功加载事件 SHALL 被视为该 Skill 的真实使用

#### Scenario: related_sop is stale or invalid

- **WHEN** `related_sop` 指向不存在、弃用或撤销的名称或旧文件路径
- **THEN** Runtime SHALL 保留其提示兼容语义但不得自动读取目标
- **AND** 普通 Agent Loop SHALL 继续运行

### Requirement: Disabled and degraded isolation

Skill Runtime 关闭时 SHALL 不创建 Skill 存储、不注入 catalog 且不注册 `skill_load`；子系统局部故障时 SHALL fail closed 并以可观察降级继续不依赖 Skill 的普通 Agent Loop。

#### Scenario: Skill Runtime is disabled

- **WHEN** 配置显式关闭 Skill Runtime
- **THEN** 模型 SHALL 保持现有九个默认工具和无 catalog 上下文
- **AND** 系统 SHALL NOT 创建 `skills.db` 或 artifact 目录

#### Scenario: Catalog or Registry fails

- **WHEN** Registry、snapshot 或 catalog 无法可靠读取
- **THEN** Runtime SHALL 不注入伪造或陈旧 Skill 内容并继续普通 Agent Loop
- **AND** SHALL 记录 Skill 子系统降级原因

