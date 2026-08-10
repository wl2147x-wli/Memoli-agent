# 版本化 Skill Runtime

Memoli 的 Skill 是可复用的程序性说明，不是新权限、新工具或自动执行器。短 SOP
直接写在 `SKILL.md` 正文，较长说明放在 `references/`；一次性进度仍写 Working
State，用户事实仍写 Personal Memory，原始运行过程仍写 trajectory。

## 渐进披露流程

```text
用户任务
  -> 基础 System Prompt
  -> 当前 Session 固定的 <available_skills> Catalog
  -> Memory / Working State / 会话历史
  -> 模型按 name 选择 Skill
  -> skill_load(name, reference?) 返回固定版本的 Tool Result
  -> 模型继续调用现有 file/code/web/MCP 等通用工具
```

Catalog 只包含名称、版本、来源和路由描述。`skill_load` 才读取去掉 frontmatter
的正文；需要更详细材料时可再读取 `references/` 下的 UTF-8 文本。正文被
`<skill_instruction name version hash reference>` 包围，明确其版本和低于静态
安全规则、插件策略及当前用户授权的信任层级。

## Package 合同

```text
my-skill/
  SKILL.md
  references/   # skill_load 可读取的只读说明
  templates/    # 随版本保存，首版 loader 不直接披露
  scripts/      # 随版本保存，loader 永不自动执行
  tests/        # 作者回归材料
```

最小 `SKILL.md`：

```markdown
---
name: my-skill
version: 1.0.0
description: Use when ...; do not use when ...
requires:
  tools: [file_read]
  mcp: []
  bins: []
  env: []
  platforms: [windows]
requested_permissions: {}
risk: low
---
# Procedure
...
```

名称使用小写 kebab-case，版本使用 SemVer。正文建议明确 `Use when`、`Do not
use when`、`Preconditions`、`Procedure`、`Failure recovery` 和
`Verification`。Parser 使用 PyYAML safe loader，并拒绝未知/重复字段、恶意
tag、类型混淆、治理字段、链接、硬链接、reparse point、越界路径及超限内容。

Skill 不能在文件中自称 `active`、`validated` 或 `approved`。这些状态、来源、
操作者、原因、active 指针和回滚历史只由宿主 Registry 保存。更新现有方法时必须
发布新 SemVer，不能覆盖同一 `name@version`。

## 配置与持久化

```toml
[skills]
enabled = true
database = "workspace/skills.db"
artifact_root = "workspace/skill-artifacts"
catalog_max_chars = 6000
skill_max_chars = 15000
reference_max_chars = 30000
max_skill_file_bytes = 262144
max_package_bytes = 2097152
verify_integrity_on_load = true
include_unavailable_in_catalog = false
allow_runtime_management = false
```

`enabled=false` 是兼容默认值：不创建数据库或制品目录，不注入 Catalog，也不注册
`skill_load`，原九工具 Agent Loop 保持不变。首版强制完整性检查，不披露不可用
Skill，也拒绝允许在线模型管理版本。

`skills.db` 使用显式 schema version，主要表为：

- `skills`、`skill_versions`：逻辑身份和不可变版本；
- `skill_active_versions`：唯一 active 与 previous active；
- `skill_session_snapshots`、`skill_session_bindings`：包括零绑定的 Session 快照；
- `skill_registry_events`：安装、激活、弃用、撤销和回滚审计；
- `skill_meta`：schema version 与并发 revision。

每个进程中新建 Session 都有随机 `session_instance_id`。第一次构造 Catalog 时一次性
绑定当前可见 active 版本；普通激活或弃用不会改变旧 Session，新 Session和进程
重启后的同名 channel/session key 使用最新 active。安全撤销会在每次加载时重查，
因此立即阻止旧绑定，且不会猜测回退其他版本。

## 可见性与安全边界

Catalog 和 load 都检查当前实际 Tool Registry、已连接 MCP server、bin、env 名称
存在性和平台。环境变量只检查名称是否存在，从不读取或返回值。SubAgent 共享只读
Registry，但使用独立 Session 快照和 profile 实际工具 allowlist；主 Agent 加载过的
正文、权限或版本选择不会复制给子 Agent。

`requested_permissions` 只是声明和未来审批输入。Skill 不能新增工具、绕过 Hook、
改变容器/文件边界、扩大 SubAgent budget 或直接执行 `scripts/`。真实动作仍必须走
现有通用工具及安全策略。只有成功的 `skill_load` 才算真实 Skill 使用；Working
Checkpoint 的 `related_sop` 仍是非权威文本提示。

内置 `research-report@1.0.0` 是无脚本只读示例，用于演示 Catalog、正文和 evidence
reference 的三级渐进披露，不增加研究专用业务工具。
