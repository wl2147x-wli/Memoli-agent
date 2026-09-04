## MODIFIED Requirements

### Requirement: Offline memory lifecycle

Runtime SHALL 在个人记忆和 consolidation 显式启用且 Extractor 模型、协议与互斥凭据来源配置有效时，将离线记忆 Worker 作为独立、有序启动和停止的后台生命周期组件；在线 Agent Turn、出站回复和下一条消息处理 SHALL NOT 等待远程提取、Card 投影或 Embedding 完成。

#### Scenario: Inline local credential enables the worker

- **WHEN** OpenAI-compatible Extractor 配置非空直接凭据且未配置环境凭据来源
- **THEN** Runtime SHALL 将该配置视为有效并启动离线 Worker
- **AND** SHALL NOT 要求进程环境重复提供同一凭据

#### Scenario: Memory provider credential configuration is invalid

- **WHEN** 启用的远程 Memory Provider 同时声明直接值和环境变量来源，或没有可解析的非空来源
- **THEN** Runtime SHALL 在组件启动前返回可操作且不泄密的配置错误
- **AND** SHALL NOT 迁移记忆数据库、启动后台 Worker或发出远程请求
