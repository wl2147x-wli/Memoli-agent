# 实施摘要

## 已交付边界

- 新增安全 `SKILL.md` package validator：PyYAML safe load、严格字段与类型、SemVer、
  UTF-8/预算、标准附属目录、链接/reparse/hard-link/越界拒绝和规范 SHA-256。
- 新增宿主 validate/install/list/show/activate/deprecate/revoke/rollback CLI；状态变化
  保存 actor/reason，在线模型没有发布管理工具。
- 新增只读 Session Catalog 与 `skill_load(name, reference?)` 渐进披露。关闭 Runtime
  或装配失败时仍为原九工具；启用成功时 `skill_load` 是第十个内置工具。
- 新增主 Agent 与 SubAgent 独立 Session snapshot、实际工具/MCP/环境依赖过滤、
  完整性重查、撤销立即失效和故障隔离。
- 内置并显式激活无脚本 `research-report@1.0.0` 及 evidence reference。

## SQLite schema

`workspace/skills.db` schema version 1 包含：

- `skill_meta`：schema version 与管理并发 revision；
- `skills`：逻辑名称、owner、source type；
- `skill_versions`：SemVer、description、状态、previous version、artifact path、内容哈希
  与规范 manifest JSON；
- `skill_active_versions`：active/previous active、actor、reason 与切换时间；
- `skill_session_snapshots`：包括零绑定在内的稳定快照事实；
- `skill_session_bindings`：Session 实例到不可变版本的绑定；
- `skill_registry_events`：安装、激活、弃用、撤销和回滚审计。

制品位于 `workspace/skill-artifacts/<name>/<version>/`，通过 staging、二次哈希和
原子目录发布生成，并设置平台可表达的只读权限；加载仍以 Registry 哈希为权威。

## 公开工具变化与示例 trace

启用后新增的唯一模型工具：

```text
skill_load(name: string, reference?: string)
```

成功正文使用 `<skill_instruction name version hash reference>` 边界。典型 trace：

```text
trace_started
  -> model_called（读取 <available_skills>）
  -> tool_intent_recorded: skill_load
  -> skill_load_requested
  -> skill_loaded
  -> tool_finished: skill_load
  -> model_called（Tool Result 中包含固定版本正文）
  -> tool_intent_recorded: file_read/time/web/MCP...
  -> tool_finished
  -> trace_finished
```

拒绝路径记录 `skill_load_rejected`。领域事件保存 name/version/hash/source/reference/
session instance/状态或原因，不复制正文；通用 Tool Result 继续服从现有 trajectory
capture/redaction/payload 政策。`related_sop` 同名文本不会产生 Skill 使用证据。

## 已知限制与后续 Evaluation/GEPA 接口

首版只做按名称排序的有界 Catalog，不包含 embedding routing、远程 Hub、签名信任
链、自动生成/修订 Skill、fitness、replay、holdout、canary 或自动回滚；loader 只披露
正文和 `references/` UTF-8 文本，不执行 `scripts/`。

后续 Skill Evaluation/GEPA 应复用下列稳定接口，不绕过宿主治理：

- immutable `name@version`、content hash 与 source；
- Registry candidate/version/event 合同和并发 revision；
- Session binding 作为实验版本归因；
- `skill_load_requested/loaded/rejected` 与后续通用工具/最终 trace 作为离线评测证据；
- GEPA 只能安装 candidate，不能自行 activate；发布、canary 与回滚必须由新的
  OpenSpec change 定义审批、数据集、指标和安全边界。

## 验证结果

- `python -m pytest -q`：137 passed，4 skipped；
- `python -m ruff check memoli_agent benchmarks tests`：通过；
- `python -m pyright`：0 errors；
- `openspec validate build-versioned-skill-runtime --strict`：valid。
