## MODIFIED Requirements

### Requirement: Secret-safe interactive presentation

CLI SHALL 只渲染明确允许的安全事件字段，SHALL 区分 Agent 主动生成的进度与提供商推理摘要，并 SHALL 从历史、自动补全、状态、工具卡片、错误和剪贴板模型中排除凭证、原始推理及不透明续接状态。

#### Scenario: Provider emits reasoning or tool argument deltas

- **WHEN** 提供商流包含原始推理、签名、加密内容、响应续接标识、原始工具参数或 SDK 对象
- **THEN** 展示边界 SHALL 丢弃这些内容，或将其投影为不含内容的安全阶段
- **AND** 系统 SHALL NOT 将其保存到输入历史、会话记录视图或剪贴板模型

#### Scenario: 提供商发送允许展示的推理摘要

- **WHEN** 模型配置明确启用摘要展示，且适配器发送有长度限制并带提供商标签的推理摘要事件
- **THEN** CLI MAY 按协议顺序渲染该事件，并明确标注“推理摘要”
- **AND** CLI SHALL NOT 将其描述为原始或完整思维链

#### Scenario: 未启用摘要展示

- **WHEN** 推理已经启用，但展示策略仍为隐藏
- **THEN** CLI SHALL 至多显示不含内容的推理阶段指示
- **AND** 最终文本、工具状态和取消操作 SHALL 保持可响应

#### Scenario: 兼容端点把推理内联到普通内容

- **WHEN** 已注册方言识别出普通内容中的协议级推理块及其最终回答边界
- **THEN** CLI SHALL 只接收并渲染分类后的最终回答
- **AND** 推理块的任何完整内容、部分流式片段或边界标记 SHALL NOT 进入终端输出

#### Scenario: Error contains sensitive material

- **WHEN** 提供商、工具或渲染器异常包含凭证、请求头、Cookie、地址查询密钥、不透明续接状态或主机路径内容
- **THEN** CLI SHALL 仅显示稳定的错误类别、是否可重试和安全的纠正指引
- **AND** CLI SHALL NOT 显示原始异常文本
