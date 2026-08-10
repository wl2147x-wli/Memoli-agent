## ADDED Requirements

### Requirement: Versioned plugin manifest

插件 SHALL 使用 manifest 声明名称、版本、Runtime 兼容范围、配置 schema、工具、hooks、权限和依赖。

#### Scenario: Plugin is incompatible

- **WHEN** 插件声明的 Runtime 兼容范围不包含当前版本
- **THEN** 系统 SHALL 拒绝激活插件并报告原因

### Requirement: Deterministic hook ordering

插件 hooks SHALL 通过显式优先级或依赖关系形成确定性执行顺序，并检测循环依赖。

#### Scenario: Hook dependency cycle exists

- **WHEN** 启用插件的 hook 依赖形成循环
- **THEN** 系统 SHALL 阻止相关插件激活而不是使用不稳定顺序运行

### Requirement: Plugin permission enforcement

插件通过 context 获得的资源和注册的工具 SHALL 受声明权限与全局治理策略限制。

#### Scenario: Plugin requests undeclared capability

- **WHEN** 插件尝试访问未在 manifest 声明的受控能力
- **THEN** 系统 SHALL 拒绝访问并记录审计事件
