## Why

Memory Embedding 与离线 Extractor 当前只接受 `api_key_env`，即使本地 OpenAI-compatible 服务不校验认证，也要求用户在每个新 PowerShell 中设置非空环境变量。用户希望在已被 Git 忽略的本地 `config.toml` 中直接填写 `EMPTY`，并要求每个有效配置项都有详细中文注释。现有合同无法表达这一合法的本地部署方式，直接添加 `api_key` 会因未知字段导致启动失败。

## What Changes

- 为 `[memory.embedding]` 与 `[memory.offline.extractor]` 增加可选 `api_key` 配置，允许直接凭据或 `api_key_env` 二选一。
- 同时配置两种来源时拒绝启动，避免不明确的优先级；远程 Provider 启用但两种来源都为空时继续快速失败。
- 确保直接凭据不会进入 dataclass repr、运行轨迹、诊断、错误、日志或导出。
- 保持 `api_key_env` 完全向后兼容，并继续作为生产部署推荐方式。
- 将本地 `config.toml` 改为直接使用 `api_key = "EMPTY"`，并为每个有效配置项补充详细中文注释。
- 同步示例配置、记忆系统文档和 Windows 本地启动文档。

### Non-goals

- 不把任何真实密钥提交到 Git；`config.toml` 继续被忽略。
- 不改变主 LLM Provider 的凭据合同。
- 不将 `.env` 自动加载引入 Runtime。
- 不改变记忆数据库 schema、记忆治理策略或检索算法。

## Capabilities

### Modified Capabilities

- `memory`: 扩展 Embedding 与 Extractor 的凭据来源配置，同时保持秘密不进入可观察输出。
- `agent-runtime`: 明确启用远程记忆 Provider 时的启动校验和冲突配置失败行为。

## Impact

- 影响 `memoli_agent/bootstrap/config.py`、`memoli_agent/bootstrap/memory.py`、远程 Embedding/Extractor adapter 的凭据注入、配置测试和安全回归测试。
- 旧 `api_key_env` 配置无需迁移；新 `api_key` 是显式可选能力。
- `config.toml` 将使用本地占位凭据 `EMPTY`，不再要求用户每次启动前设置两个环境变量。
- 直接写真实密钥会增加本地文件泄漏风险，因此文档必须继续提示权限、备份和分享边界。
