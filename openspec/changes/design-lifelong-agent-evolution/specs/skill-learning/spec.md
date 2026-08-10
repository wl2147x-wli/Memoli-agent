## ADDED Requirements

### Requirement: Versioned skill contract

系统 SHALL 使用版本化 Skill manifest 描述适用条件、参数、所需工具、权限、前置条件、后置条件、来源和验证状态。

#### Scenario: Runtime loads a skill

- **WHEN** 当前任务匹配一个 active Skill
- **THEN** Runtime SHALL 加载不可变的已发布版本
- **AND** 轨迹 SHALL 记录所使用的 Skill 名称和版本

### Requirement: Multi-trajectory skill candidates

系统 SHALL 仅从多条独立且经过结果验证的相关轨迹中生成 Skill 候选。

#### Scenario: Only one successful trajectory exists

- **WHEN** 某任务族只有一条成功轨迹支持
- **THEN** 系统 MAY 保存经验草稿
- **AND** SHALL NOT 自动将其提升为可发布 Skill candidate

### Requirement: Replay validation and release states

Skill SHALL 经历 draft、candidate、validated、canary、active、deprecated 或 rejected 等显式状态，并在发布前通过隔离重放和回归检查。

#### Scenario: Candidate fails a retained case

- **WHEN** Skill candidate 提升目标案例但破坏保留案例
- **THEN** 系统 SHALL 拒绝候选或保持其非 active 状态

### Requirement: Skill provenance and rollback

系统 SHALL 保留每个 Skill 版本的来源轨迹、评测报告、批准记录和上一稳定版本。

#### Scenario: Active skill regresses in canary

- **WHEN** canary 指标低于发布门槛
- **THEN** 系统 SHALL 能切回上一稳定版本并记录回滚原因
