## Context

CodeRunTool 直接创建宿主 Python 或 PowerShell 子进程。字符串网络检测无法构成安全边界，且插件 runner 不覆盖内置工具。

## Goals / Non-Goals

**Goals:** 默认容器隔离、无隐式宿主回退、固定运行环境、显式可信开发模式。

**Non-Goals:** 完整恶意内核隔离、容器内任意依赖安装、默认网络访问。

## Decisions

- 配置 runner 为 container/trusted-host/disabled，默认 container。
- container 以非 root、network none、资源限制和固定镜像运行，只挂载 workspace。
- container 第一版只支持 Python；PowerShell 限 trusted-host。
- bootstrap 健康检查失败时不注册 code_run；绝不回退宿主。
- trusted-host 需要显式解释器绝对路径并记录高风险 profile。

## Risks / Trade-offs

- [Docker 不可用导致工具减少] → 在启动诊断和 catalog 中明确 unavailable，保持安全默认。
- [workspace 可写仍允许业务文件破坏] → 继续依赖 workspace confinement、审批策略和完整轨迹。

## Migration Plan

示例配置新增默认 container；现有必须使用宿主脚本的用户显式迁移到 trusted-host 并配置解释器。

## Open Questions

无。
