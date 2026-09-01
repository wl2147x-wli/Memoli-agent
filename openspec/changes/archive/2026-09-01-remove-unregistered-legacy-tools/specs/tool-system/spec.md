## MODIFIED Requirements

### Requirement: Built-in utility tools

系统 SHALL 保持 `code_run`、`file_read`、`file_patch`、`file_write`、`update_working_checkpoint`、`ask_user`、`start_long_term_update`、`time` 和 `memory_recall` 九个 GenericAgent 风格默认工具；当 Skill Runtime 启用时 SHALL 额外注册只读 `skill_load` 作为第十个内置工具，并 SHALL NOT 提供已被替代的 `calculator`、`memory_write`、`filesystem_read` 或旧版 SubAgent 工具实现。

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
- **THEN** 当前持久任务图版本的 `spawn_subagent` SHALL 在默认工具之外注册
- **AND** SHALL NOT 注册或回退到旧版 SubAgent 委派实现

#### Scenario: Removed legacy tool is requested

- **WHEN** 模型或调用方请求 `calculator`、`memory_write` 或 `filesystem_read`
- **THEN** 当前工具注册表 SHALL 将其作为不存在的工具返回结构化失败
- **AND** Runtime SHALL NOT 提供兼容实现或隐式改写为替代工具
