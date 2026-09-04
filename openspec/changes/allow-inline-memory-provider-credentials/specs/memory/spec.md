## MODIFIED Requirements

### Requirement: Optional semantic memory index

系统 SHALL 支持为合格的 Card、Claim 与 Episode 建立可选语义索引，并 SHALL 允许 OpenAI-compatible Embedding Provider 从直接配置值或命名环境变量中选择且仅选择一种凭据来源。语义向量 MUST 作为与稳定来源 ID、内容 hash、模型和版本关联的派生数据保存；来源记忆与原始轨迹 MUST 保持权威。

#### Scenario: Inline embedding credential is configured

- **WHEN** 操作者启用 OpenAI-compatible Embedding，并只配置非空 `api_key`
- **THEN** Runtime SHALL 在启动阶段接受该配置并将秘密仅传给 Embedding adapter
- **AND** diagnostics、trajectory、日志和错误 SHALL NOT 包含该值

#### Scenario: Environment embedding credential remains supported

- **WHEN** 操作者只配置 `api_key_env` 且对应环境变量非空
- **THEN** Runtime SHALL 使用环境变量值创建 Embedding adapter
- **AND** 旧配置 SHALL NOT 要求迁移

#### Scenario: Embedding credential sources conflict

- **WHEN** `api_key` 与 `api_key_env` 同时非空，或启用远程 Embedding 但二者都无法提供非空凭据
- **THEN** Runtime SHALL 在远程请求和后台 Worker 启动前返回不含秘密值的配置错误

### Requirement: Versioned candidate extraction

系统 SHALL 通过可替换 Extractor 从权威 Source Segment 生成固定 schema 的 Candidate Draft，并 SHALL 允许 OpenAI-compatible Extractor 从直接配置值或命名环境变量中选择且仅选择一种凭据来源。每个 run SHALL 记录 extractor、schema、prompt/policy、provider/model、segmenter 和输入内容版本，但 SHALL NOT 记录任何凭据值。

#### Scenario: Inline extractor credential is configured

- **WHEN** consolidation 已启用且 OpenAI-compatible Extractor 只配置非空 `api_key`
- **THEN** Runtime SHALL 启动离线 Worker并使用该 Extractor
- **AND** 公共配置摘要、持久化状态与失败信息 SHALL NOT 回显该值

#### Scenario: Extractor credential sources conflict or are absent

- **WHEN** Extractor 的 `api_key` 与 `api_key_env` 同时非空，或两种来源都无法产生非空凭据
- **THEN** Runtime SHALL 在读取轨迹、创建 consolidation 请求或调用 Provider 前快速失败
- **AND** 错误 SHALL 只标识冲突字段或缺失的环境变量名称
