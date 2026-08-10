## 1. 回归基线与配置合同

- [x] 1.1 为当前无 Skill 的 System Prompt、九个默认工具、Working State `related_sop` 和完整工具轨迹增加不改变行为的回归测试
- [x] 1.2 在应用配置中增加强类型 `SkillsConfig`，覆盖 enabled、database、artifact root、catalog/正文/reference 预算和运行时管理禁用项
- [x] 1.3 实现 `[skills]` TOML 解析、默认值、非法预算、非法路径和 `allow_runtime_management=true` 的启动校验
- [x] 1.4 将 PyYAML 安全解析依赖加入受约束的项目依赖，并验证最小安装环境可导入
- [x] 1.5 增加 Skill Runtime 关闭配置测试，确认不创建数据库/artifact、不改变上下文且不注册 `skill_load`

## 2. Skill 数据合同与 Manifest 校验

- [x] 2.1 新建 `memoli_agent/agent/skills/` 包并定义 Skill identity、version、manifest、requirements、permissions、artifact 和解析结果 dataclass
- [x] 2.2 使用 `yaml.safe_load` 实现 `SKILL.md` frontmatter 解析，拒绝非映射、缺失 name/version/description、非法名称和非法版本
- [x] 2.3 实现 requires.tools、requires.mcp、requires.bins、requires.env、requires.platforms、requested_permissions 和 risk 的严格类型校验
- [x] 2.4 明确拒绝或去信任 Skill 自声明的 active、validated、approved 等治理字段
- [x] 2.5 实现正文必需边界、UTF-8、单文件大小、package 总大小和允许附属目录校验
- [x] 2.6 为合法 manifest、未知字段、恶意 YAML tag、类型混淆、超限内容和治理字段伪造增加单元测试

## 3. Package 安全与不可变 Artifact

- [x] 3.1 实现 package 文件精确枚举，限制为 SKILL.md 和允许的 references/templates/scripts/tests 目录
- [x] 3.2 实现绝对路径、父目录逃逸、符号链接、junction/reparse point、特殊文件和 artifact 根外解析结果检查
- [x] 3.3 按排序后的规范相对路径和文件字节计算稳定 package SHA-256 内容哈希
- [x] 3.4 实现 staging 复制、完整校验和到 `workspace/skill-artifacts/<name>/<version>/` 的原子发布
- [x] 3.5 实现同 `name@version` 同哈希幂等、不同哈希拒绝和失败 staging 清理
- [x] 3.6 增加路径逃逸、链接、篡改、同版本冲突、部分复制失败和重复安装测试

## 4. SQLite Skill Registry

- [x] 4.1 定义 `skill_meta`、`skills`、`skill_versions`、`skill_active_versions`、`skill_session_snapshots`、`skill_session_bindings` 和 `skill_registry_events` schema，其中 snapshot 表必须能表达零绑定的稳定空快照
- [x] 4.2 实现 schema 创建与显式版本检查，保证 DDL 和版本号同事务提交
- [x] 4.3 实现未知/未来 schema fail closed，验证不会重建、删除或留下部分表
- [x] 4.4 实现逻辑 Skill 和不可变 version 注册、查询、按名称解析和内容哈希校验
- [x] 4.5 实现 active 指针、previous active、版本状态和管理事件的事务化写入
- [x] 4.6 实现 Registry Reader、Session Binder 和 Admin Repository 的最小分权端口，避免在线 Runtime 获得发布写权限
- [x] 4.7 为首次创建、重复启动、事务回滚、并发 revision 冲突和未知 schema 增加 SQLite 测试

## 5. 宿主侧安装与发布管理

- [x] 5.1 实现 validate 操作，输出规范 manifest、文件清单、依赖、请求权限和内容哈希但不修改状态
- [x] 5.2 实现 install 操作，将通过校验的 builtin 或本地 package 原子复制并注册为非 active 版本
- [x] 5.3 实现 list/show 操作，展示来源、版本、状态、active 指针、哈希、依赖和缺失条件且不泄露 env 值
- [x] 5.4 实现 activate 操作，在一个事务中更新 active/previous 指针、状态和 actor/reason 审计事件
- [x] 5.5 实现 deprecate、revoke 和 rollback 操作及其非法状态转换检查
- [x] 5.6 提供独立宿主 CLI 入口调用管理 API，不把管理命令注册为模型工具且不加厚 `main.py`
- [x] 5.7 为安装不激活、激活失败原子回滚、撤销、上一版本回滚和无权限管理入口增加测试

## 6. Session 实例与版本快照

- [x] 6.1 为每次 `SessionManager` 新建的内存 Session 生成不可变 `session_instance_id`，保持现有 session_key 路由语义
- [x] 6.2 实现首次 catalog 构造时对全部可见 active Skill 的事务化 Session snapshot/binding
- [x] 6.3 实现同一 Session 多轮稳定解析绑定版本，不受普通 activate 或 deprecate 影响
- [x] 6.4 实现进程内新 Session 使用最新 active，进程重启后固定 channel/session key 获得新实例而历史 binding 只供审计
- [x] 6.5 实现 revoked 每次加载重查并立即阻止已绑定版本，禁止自动回退未绑定版本
- [x] 6.6 增加 Session 内升级、跨 Session 升级、重启、deprecated 延续和 revoked 立即失效测试

## 7. Skill 可用性与 Catalog

- [x] 7.1 实现 Requirement Evaluator，检查当前 Tool Registry、MCP server、bin、env 存在性和平台
- [x] 7.2 确保依赖检查只披露 env 名称及存在性，不读取或返回秘密值
- [x] 7.3 实现按 Session snapshot 和当前 Agent 能力过滤、按名称确定性排序的 Skill catalog
- [x] 7.4 实现 catalog 字符预算和完整条目裁剪，记录候选数、披露数、实际字符数及省略状态
- [x] 7.5 在 ContextBuilder 中将 catalog 放在基础系统规则之后、动态 Memory 与 Working State 之前，并保持同一 Session 字节稳定
- [x] 7.6 实现 catalog/Registry 故障隔离：不注入伪造内容，普通 Agent Loop 继续并记录降级
- [x] 7.7 为依赖满足/缺失、环境变化、排序稳定、预算裁剪、空 catalog 和故障降级增加测试

## 8. 只读 skill_load 工具

- [x] 8.1 实现严格 schema 的 `skill_load(name, reference?)`，拒绝物理 artifact path、未知参数和管理意图
- [x] 8.2 实现按 Session binding 加载去除 frontmatter 的 Skill 正文，并返回名称、版本、哈希和来源边界
- [x] 8.3 实现允许 reference 的规范相对路径解析、文本类型、大小和 artifact 根限制
- [x] 8.4 在实际加载时重新检查撤销状态、依赖变化、目标路径和 package 内容完整性
- [x] 8.5 对正文/reference 超预算返回明确失败，禁止成功状态下静默截断关键程序说明
- [x] 8.6 保证 `skill_load` 不执行 scripts、不写 package、不切换 active 且不修改 Tool/Plugin/Sandbox 权限
- [x] 8.7 在 Skill Runtime 可用时将 `skill_load` 作为第十个内置工具注册，关闭或装配失败时保持九工具集合
- [x] 8.8 为正文加载、reference 加载、不存在、未绑定、路径逃逸、超限、篡改、撤销和依赖丢失增加工具测试

## 9. Runtime、轨迹与相关 SOP 兼容

- [x] 9.1 将 Skill Runtime、Registry 生命周期和关闭顺序接入 `AppRuntime` 与 bootstrap，保持 I/O async 边界和其他组件可替换
- [x] 9.2 在通用 Skill 工具事件元数据中写入 skill name/version/hash/source/reference/session instance 和稳定状态
- [x] 9.3 增加 `skill_load_requested`、`skill_loaded`、`skill_load_rejected` 领域事件并关联同一 trace/span/tool call
- [x] 9.4 使领域事件遵守 trajectory 的 metadata-only、redacted、full-local、payload 大小和敏感字段策略
- [x] 9.5 保留 `related_sop` 的现有保存、revision 和 prompt 注入，不自动解析、加载、绑定或授权
- [x] 9.6 增加测试证明只有成功 `skill_load` 才算真实 Skill 使用，`related_sop` 同名提示本身不产生加载事件
- [x] 9.7 增加从 catalog 选择、skill_load、下一轮使用通用工具到 trace 完成的端到端 Runtime 测试

## 10. SubAgent 能力隔离

- [x] 10.1 将共享只读 Skill Registry 注入 SubAgent Runtime，并为每个 SubAgent Session 创建独立 snapshot
- [x] 10.2 根据 SubAgent profile 的实际 tool allowlist、MCP 可见性和预算生成过滤后的 catalog
- [x] 10.3 保证主 Agent 已加载 Skill 的正文和更高权限不会隐式复制给 SubAgent
- [x] 10.4 保证 SubAgent 加载 Skill 不改变 depth、iteration、elapsed、并发和取消边界
- [x] 10.5 为主可见/子不可见 Skill、独立选择、版本绑定和轨迹 lineage 增加 SubAgent 集成测试

## 11. 示例 Skill 与运行演示

- [x] 11.1 创建一个小型、无脚本、只读的 builtin `research-report` 示例 Skill，包含明确 Use when、Do not use when、Procedure、Failure recovery 和 Verification
- [x] 11.2 为示例 Skill 增加一个受限 reference，验证第三级渐进披露而不引入业务专用工具
- [x] 11.3 编写安装、显式激活和新 Session 生效的测试 fixture，默认测试不得依赖用户 workspace
- [x] 11.4 增加 CLI 演示：用户研究任务 → catalog → `skill_load` → 通用工具 → 最终结果 → SQLite Skill/trajectory 查询
- [x] 11.5 验证禁用 Skill、无 active Skill 和撤销示例版本后，Agent 仍能通过原九工具完成普通任务

## 12. 文档、质量门禁与 OpenSpec

- [x] 12.1 更新 `config.example.toml` 和配置文档，说明 Skill 开关、路径、预算、Session 快照及安全默认值
- [x] 12.2 编写 Skill 作者文档，说明 package 布局、manifest、SOP/reference/script 边界、版本更新和禁止自证治理状态
- [x] 12.3 编写宿主管理文档，说明 validate/install/activate/deprecate/revoke/rollback、不可变版本和恢复流程
- [x] 12.4 更新架构和工具文档，说明 GA L1/L3 模式到 catalog/skill_load 的映射、`related_sop` 非权威语义和第十工具条件
- [x] 12.5 执行 `python -m pytest -q` 并修复全部回归
- [x] 12.6 执行 `python -m ruff check memoli_agent benchmarks tests` 和 `python -m pyright` 并修复静态问题
- [x] 12.7 执行 `openspec validate build-versioned-skill-runtime --strict` 并修复所有 OpenSpec 问题
- [x] 12.8 生成最终实施摘要，列出 SQLite schema、公开工具变化、示例 trace、已知限制和后续 Skill Evaluation/GEPA 接口
