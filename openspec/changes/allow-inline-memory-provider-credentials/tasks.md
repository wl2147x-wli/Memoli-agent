## 1. 配置合同与秘密解析

- [ ] 1.1 为 Memory Embedding 与 Extractor 配置增加 `api_key`，并确保秘密字段不进入 repr
- [ ] 1.2 实现 `api_key`/`api_key_env` 互斥、缺失和 Provider 类型校验
- [ ] 1.3 在 bootstrap 边界统一解析直接值或环境变量，并返回不泄密的配置错误

## 2. Adapter 与 Runtime 装配

- [ ] 2.1 让 OpenAI-compatible Embedder 接收已解析凭据，不再于请求时自行读取环境变量
- [ ] 2.2 让 OpenAI-compatible Candidate Extractor 接收已解析凭据，并保持请求协议不变
- [ ] 2.3 验证 diagnostics、trajectory、异常和导出不包含直接凭据

## 3. 自动化测试

- [ ] 3.1 增加直接 `EMPTY` 凭据启动与请求测试
- [ ] 3.2 增加旧 `api_key_env` 兼容测试
- [ ] 3.3 增加双来源冲突、空环境变量和缺失凭据的 fail-fast 测试
- [ ] 3.4 增加配置 repr、错误、轨迹和诊断脱敏回归测试

## 4. 配置与文档

- [ ] 4.1 将本地 `config.toml` 的两个记忆 Provider 改成 `api_key = "EMPTY"`
- [ ] 4.2 为本地 `config.toml` 每个有效 table/key 添加具体中文注释
- [ ] 4.3 更新 `config.example.toml`、记忆系统文档和 Windows 本地启动文档，说明两种凭据来源与安全边界

## 5. 验证

- [ ] 5.1 运行相关配置、Embedding、离线记忆和安全测试
- [ ] 5.2 运行 `python -m ruff check memoli_agent benchmarks tests` 与 `python -m pyright`
- [ ] 5.3 运行完整测试和 `openspec validate --all --strict`
