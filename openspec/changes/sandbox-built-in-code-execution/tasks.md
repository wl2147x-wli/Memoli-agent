## 1. 配置与 Runner

- [x] 1.1 增加 container、trusted-host、disabled 配置及严格校验
- [x] 1.2 实现固定镜像、无网络、非 root 和资源受限的容器 runner
- [x] 1.3 实现显式解释器的 trusted-host runner，限制 PowerShell
- [x] 1.4 容器不可用时禁用 code_run 且禁止宿主回退

## 2. 验证与部署

- [ ] 2.1 构建并记录固定 digest 的 code runner 镜像
- [x] 2.2 覆盖网络、挂载、资源、超时和后端不可用安全测试
- [x] 2.3 更新示例配置和工具安全文档
- [x] 2.4 执行 pytest、Ruff、Pyright、OpenSpec strict
