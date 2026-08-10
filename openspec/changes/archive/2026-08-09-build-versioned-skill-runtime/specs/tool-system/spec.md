## MODIFIED Requirements

### Requirement: Built-in utility tools

系统 SHALL 保持 `code_run`、`file_read`、`file_patch`、`file_write`、`update_working_checkpoint`、`ask_user`、`start_long_term_update`、`time` 和 `memory_recall` 九个 GenericAgent 风格默认工具；当 Skill Runtime 启用时 SHALL 额外注册只读 `skill_load` 作为第十个内置工具，并 SHALL NOT 默认同时暴露被替代、Skill 管理或需要显式启用的其他工具。

#### Scenario: Default tool schemas are requested

- **WHEN** Runtime 使用默认工具配置构造一次模型请求
- **THEN** 模型可见工具 SHALL 至少包含九个默认工具
- **AND** SHALL NOT 包含 `calculator`、`memory_write`、`filesystem_read`、`web_scan`、`web_execute_js` 或 `spawn_subagent`

#### Scenario: Default tool schemas are requested with Skills enabled

- **WHEN** Runtime 使用默认工具配置且 Skill Runtime 可用
- **THEN** 模型可见工具 SHALL 包含九个既有默认工具和 `skill_load`
- **AND** SHALL NOT 包含 `calculator`、`memory_write`、`filesystem_read`、`web_scan`、`web_execute_js`、`spawn_subagent` 或任何 Skill 管理工具

#### Scenario: Default tool schemas are requested with Skills disabled

- **WHEN** Skill Runtime 被配置关闭或未可靠装配
- **THEN** 模型可见工具 SHALL 保持九个既有默认工具
- **AND** SHALL NOT 暴露不可工作的 `skill_load`

#### Scenario: Optional SubAgent tool is enabled

- **WHEN** SubAgent 工具通过配置显式启用且管理器可用
- **THEN** `spawn_subagent` SHALL 在当前默认工具之外注册

#### Scenario: Calculator evaluates allowed syntax

- **GIVEN** 兼容用 `calculator` 被显式注册，而不是作为默认工具暴露
- **WHEN** 输入只包含数值、括号以及受支持的算术运算符
- **THEN** `calculator` SHALL 返回计算结果

#### Scenario: Calculator receives unsupported syntax

- **GIVEN** 兼容用 `calculator` 被显式注册，而不是作为默认工具暴露
- **WHEN** 表达式包含函数调用、变量或不受支持的 AST 节点
- **THEN** `calculator` SHALL 拒绝计算并返回失败结果

## ADDED Requirements

### Requirement: Read-only Skill loading tool

`skill_load` SHALL 只通过已装配 Skill Runtime 解析当前 Session 绑定版本并读取允许内容，不得接受物理 artifact 路径、执行脚本、修改 Registry、写入 package 或改变工具权限。

#### Scenario: Model supplies a physical path

- **WHEN** 模型尝试用 `skill_load` 传入绝对路径、artifact path 或未定义参数
- **THEN** 工具 SHALL 按严格 schema 拒绝调用
- **AND** SHALL NOT 将该请求转交通用文件读取器

#### Scenario: Model asks to execute a Skill

- **WHEN** 模型加载 Skill 后需要执行其步骤
- **THEN** 模型 SHALL 使用当前已授权的通用、浏览器、MCP 或 SubAgent 工具完成动作
- **AND** `skill_load` SHALL 只返回说明内容而不产生业务副作用
