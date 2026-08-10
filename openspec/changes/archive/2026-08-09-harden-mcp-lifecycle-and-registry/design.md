## Context

MCP client 通过 AsyncExitStack 管理 transport，但失败前未把本地 stack 交给实例；工具名通过安全化函数映射到统一 Registry。

## Goals / Non-Goals

**Goals:** 部分失败无资源泄漏、名称碰撞可见、重复生命周期幂等。

**Non-Goals:** 并发连接、自动重命名、远程服务重试策略。

## Decisions

- connect 使用局部 stack，成功后才转移所有权；异常路径无条件 aclose。
- 在注册前建立规范名到原始 server/tool 的映射，碰撞时拒绝并报告双方来源。
- 无碰撞名称保持不变，避免破坏 prompt、Skill 和测试。

## Risks / Trade-offs

- [一个冲突工具阻止该 MCP server 上线] → 以明确启动诊断换取不可混淆的工具身份。

## Open Questions

无。
