## Context

主 LLM Provider 已支持 TOML 直接凭据或环境占位符，但 Memory Embedding 与离线 Extractor 仅保存环境变量名称，并在创建 adapter 或请求时读取进程环境。本地 Infinity/vLLM 服务通常不认证，却仍因“凭据必须非空”的 fail-fast 规则要求设置 `EMPTY` 环境变量。用户需要一个完全由本地 `config.toml` 描述、重启后无需重复设置环境变量的启动路径。

## Goals / Non-Goals

**Goals:**

- 两个远程 Memory Provider 都支持 `api_key` 与 `api_key_env` 二选一。
- 保持旧配置兼容，并对缺失或冲突配置提供清晰但不泄密的错误。
- adapter 只接收已解析的秘密值，不在公共配置摘要或持久化状态中暴露。
- 本地配置中的所有有效配置项具有邻近、具体的中文说明。

**Non-Goals:**

- 不实现密钥管理器、Windows Credential Manager 或 `.env` 自动加载。
- 不允许从轨迹、记忆、插件或模型消息读取凭据。
- 不改变远程 API 协议与模型能力。

## Decisions

### 1. 配置使用互斥凭据来源

`MemoryEmbeddingConfig` 和 `MemoryExtractorConfig` 新增 `api_key`，并保留 `api_key_env`。启用 `openai-compatible` 时：

- `api_key` 非空且 `api_key_env` 为空：使用直接值。
- `api_key` 为空且 `api_key_env` 非空：启动时解析环境变量。
- 两者都非空：配置错误，不定义隐式优先级。
- 两者都为空：配置错误。

`disabled` 与 `deterministic` Provider 不要求凭据。

### 2. 在 bootstrap 边界解析秘密

bootstrap 将直接值或环境变量解析为单个非空秘密，并以构造参数传给远程 adapter。adapter 不再保存“环境变量名称并在每次请求读取”的双重语义。秘密字段使用 `repr=False`，公共 diagnostics 只展示 Provider、模型、地址的安全摘要和凭据来源类型，不展示值。

### 3. 冲突配置 fail fast

互斥校验在任何远程请求、数据库迁移或后台 Worker 启动前完成。错误只指出字段冲突或环境变量名，不回显凭据。

### 4. 本地配置直接使用 EMPTY

用户的两个本地服务不验证认证，因此本地 `config.toml` 使用：

```toml
api_key = "EMPTY"
api_key_env = ""
```

生产与共享示例仍优先展示环境变量方式，避免鼓励提交真实密钥。

### 5. 注释采用“配置项前置说明”

每个有效 TOML table 和 key 前增加中文注释，解释用途、允许值、风险、单位或与其他开关的关系。空行无需注释；已注释掉的备选示例作为说明文本处理，不要求逐行重复注释。

## Risks / Trade-offs

- 直接凭据可能被本地备份或屏幕分享暴露：继续 Git-ignore `config.toml`，文档明确仅建议本机占位值或受控环境使用。
- 同时配置两种来源会使既有手工配置启动失败：这是有意的 fail-fast，错误提供修复方法。
- 改变 adapter 构造参数可能影响测试替身：同步更新测试并保留外部协议不变。
- 大量注释可能降低配置浏览速度：按 table 分组，保持注释紧邻对应项。

## Migration Plan

1. 增加配置字段、互斥验证和秘密解析助手。
2. 更新远程 Embedding/Extractor 装配和 adapter。
3. 增加直接值、环境变量、缺失、冲突和脱敏测试。
4. 更新本地配置与示例、系统文档、启动文档。
5. 运行测试、静态检查和 OpenSpec 严格验证。

回滚时删除本地 `api_key`，恢复 `api_key_env` 并在启动进程中设置环境变量；不涉及数据库迁移。
