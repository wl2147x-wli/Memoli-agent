# Plugin System Specification

## Purpose

定义配置驱动的本地插件发现、加载、初始化和终止行为，以及插件通过受控上下文扩展工具与生命周期 hooks 时必须遵守的故障隔离边界。

## Requirements

### Requirement: Configured local plugin loading

系统 SHALL 仅加载配置中启用的本地插件模块，并支持工厂函数或模块级插件对象入口。

#### Scenario: Enabled plugin is valid

- **WHEN** 插件模块暴露 `create_plugin()` 或 `plugin`
- **THEN** 系统 SHALL 加载插件并允许其注册工具与 hooks

#### Scenario: Plugin cannot load

- **WHEN** 插件导入失败或缺少有效入口
- **THEN** 系统 SHALL 记录结构化加载失败
- **AND** 其他插件及主运行时 SHALL 继续工作

### Requirement: Controlled plugin context

插件 SHALL 通过受控上下文访问配置、workspace、工具注册表、记忆运行时和 hook 注册表。

#### Scenario: Plugin extends behavior

- **WHEN** 插件需要增加工具或生命周期行为
- **THEN** 插件 SHALL 通过上下文提供的注册表完成注册
- **AND** 插件 SHALL NOT 直接替换应用运行时核心组件

### Requirement: Lifecycle and tool hooks

系统 SHALL 支持 `before_turn`、`before_reasoning`、`prompt_render`、`after_reasoning`、`after_turn` 与 `tool_pre` hooks。

#### Scenario: Lifecycle hook fails

- **WHEN** 生命周期 hook 抛出异常
- **THEN** 系统 SHALL 在当前回合元数据中记录插件错误
- **AND** 主对话 SHALL 继续执行

#### Scenario: Plugin shutdown

- **WHEN** 应用关闭
- **THEN** 已加载插件 SHALL 按加载顺序的逆序终止
