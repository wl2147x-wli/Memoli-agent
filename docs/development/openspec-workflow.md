# OpenSpec 开发工作流

Memoli-agent 使用 OpenSpec 管理可观察行为和后续变更。当前能力事实源位于
`openspec/specs/`；`docs/` 继续承载架构、实现背景、配置示例和运维说明。

## 日常流程

在开始新功能、行为修复、兼容性变化或非平凡重构前：

```text
/opsx:explore                  可选：梳理问题和影响范围
/opsx:propose <change-name>    生成 proposal、delta specs、design、tasks
评审并修改变更材料
/opsx:apply <change-name>      按 tasks 实现并验证
/opsx:sync <change-name>       需要时先同步规格，不结束变更
/opsx:archive <change-name>    完成后归档并合并到当前规格
```

CLI 用于查看和校验状态：

```powershell
openspec list
openspec list --specs
openspec show <change-name>
openspec validate --all --strict
```

仓库当前 OpenSpec 能力与变更索引见 `openspec/README.md`。状态解释统一为：

- `openspec/specs/`：当前已经实现并通过归档流程合并的行为。
- `changes/<name>/`：尚未完成或尚未归档，不能当作当前能力。
- `changes/archive/`：历史交付记录；当前行为仍以 canonical specs 为准。
- 架构母 change：用于保存总体方向，实施时必须拆分为独立的小型 change。

## 变更边界

- `openspec/specs/` 只描述当前已经成立、可验证的行为，不记录实现步骤。
- `openspec/changes/<name>/` 描述拟议变化；未评审前不要开始实现。
- `design.md` 记录模块边界、数据流、取舍和迁移方案。
- `tasks.md` 同时包含实现、测试、OpenSpec 校验和关联文档同步。
- 仅排版、拼写或注释修改可直接提交；修复行为缺陷时应补充回归场景。
- 归档后不要修改历史 change 来描述新工作，应创建新的 change。

## 完成标准

实现结束时至少运行：

```powershell
python -m pytest -q
python -m ruff check memoli_agent benchmarks tests
python -m pyright
openspec validate --all --strict
```

如果变更影响配置、运行方式或架构，同时更新对应的 `README.md` 或 `docs/` 文档。
