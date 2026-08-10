# Skill 宿主管理手册

Skill 发布管理与在线模型完全分离。模型只看见 `skill_load`；validate、install、
activate、deprecate、revoke 和 rollback 只能由宿主 CLI 调用。

## 常用命令

```powershell
# 仅检查，不复制、不注册、不激活
python -m memoli_agent.skills_cli --config config.toml validate path/to/skill

# 复制到不可变 artifact store 并注册为 draft
python -m memoli_agent.skills_cli --config config.toml install path/to/skill

python -m memoli_agent.skills_cli --config config.toml list
python -m memoli_agent.skills_cli --config config.toml show my-skill 1.0.0

# 状态变化必须给出 reason；actor 默认 cli，也可显式指定
python -m memoli_agent.skills_cli --config config.toml activate my-skill 1.0.0 --actor wli --reason "manual review passed"
python -m memoli_agent.skills_cli --config config.toml deprecate my-skill 1.0.0 --actor wli --reason "superseded"
python -m memoli_agent.skills_cli --config config.toml revoke my-skill 1.0.0 --actor wli --reason "unsafe instruction"
python -m memoli_agent.skills_cli --config config.toml rollback my-skill --actor wli --reason "new version regressed"
```

也可以使用安装后的 `memoli-skills` 入口。install 对同版本同哈希幂等；同版本不同
内容会被拒绝。复制先进入 staging，通过二次哈希校验后原子发布；失败 staging 会
清理，既有制品、active 指针和 Session binding 不变。

rollback 只切回 Registry 保存的 previous active。deprecated 让已有 Session 继续
使用但阻止新绑定；revoked 会立即阻止所有 load。恢复撤销内容应发布和审查新版本，
不要直接修改 artifact 或 SQLite。

## 端到端演示

1. 在 `[skills]` 中启用 Runtime，启动 Memoli。
2. 输入“调研某主题并给出证据报告”。模型先看到 `research-report` Catalog 条目。
3. 模型调用 `skill_load({"name":"research-report"})`，正文成为 tool message。
4. 如需证据格式，再调用
   `skill_load({"name":"research-report","reference":"references/evidence-template.md"})`。
5. 模型使用现有 file/web/MCP 工具收集证据并完成报告。
6. 查询 Registry 和 trajectory：

```powershell
python -m memoli_agent.skills_cli --config config.toml show research-report 1.0.0

@'
import sqlite3
for database, query in [
    ("workspace/skills.db", "select event_type, actor, reason, created_at from skill_registry_events order by id"),
    ("workspace/trajectories.db", "select trace_id, span_id, event_type from events where event_type like 'skill_%' order by event_id"),
]:
    connection = sqlite3.connect(database)
    print(database, connection.execute(query).fetchall())
    connection.close()
'@ | python -
```

领域事件只保存 name/version/hash/source/reference/session instance、成功状态或拒绝
原因，不复制正文；完整 Tool Result 继续遵守 trajectory 的 metadata-only、redacted
或 full-local 捕获策略。

## 故障与恢复

- Registry schema 未知、数据库打不开或 builtin 安装失败：Skill 子系统 fail closed，
  普通九工具 Agent Loop 继续；先备份数据再排查，禁止自动重建。
- artifact 哈希不一致：load 拒绝且不回退源目录、上一版本或同名 workspace 文件；
  从可信源以新版本重新安装。
- 需要整体回滚 Runtime：设 `skills.enabled=false` 并重启；数据库和制品保留，不删除。
- active 错误：使用 rollback；若 previous active 不存在，显式审查并 activate 目标版本。

首版不包含 GEPA、轨迹自动生成 Skill、fitness/evaluation、canary、自动回滚、远程
Skill Hub 或签名信任链。后续评测与 GEPA 应复用 immutable version、Registry event
和 trajectory evidence 合同，candidate 仍不能自行激活。
