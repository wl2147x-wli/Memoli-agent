## Why

Memoli 当前只能通过共享 `PassiveTurnContext` 的轻量 hooks 扩展行为，缺少模型/工具完整观测、明确的修改与策略语义，也无法安全运行第三方或自动生成插件。需要在保持 GenericAgent 极简 Hook 思路的同时，建立类型化、可归因的 Hook 合同与进程外沙箱边界，为后续插件生态和持续进化提供可验证基础。

## What Changes

- 将插件 Hook 收敛为 Transformer、Policy 和 Observer 三类显式语义，并覆盖 turn、context、model、tool 与 runtime 生命周期。
- 使用类型化事件、结构化 Patch 和 Tool Decision 代替插件任意修改 Runtime 内部对象；Observer 保持只读并故障隔离。
- 为 Hook 建立确定性顺序、超时、失败策略和 SQLite 轨迹归因，记录插件版本、执行次序、耗时、修改摘要与拒绝原因，不在在线阶段生成评价标签。
- 将插件注册改为事务式激活：注册或初始化失败时撤销该插件已贡献的 hooks 和工具，避免半激活状态。
- 引入可替换的插件执行后端：可信内置插件继续进程内运行，第三方和自动生成插件使用进程外沙箱。
- 为沙箱插件定义版本化 JSON-RPC 协议和受控 Capability Broker；插件不直接取得 `AppConfig`、API key、Runtime 对象或宿主数据库连接。
- 第一版沙箱后端使用受约束容器，默认禁网、只读根文件系统、非 root 用户、最小挂载和 CPU/内存/PID/时间/输出限制；资源不可用或策略校验失败时拒绝激活沙箱插件。
- **BREAKING**：现有插件的 `register(context)`、共享可变 `PassiveTurnContext` hook 和直接注册表访问迁移到 `register(registrar)`、类型化事件与受限运行上下文；仓库内置插件随本 change 一并迁移。

**Non-Goals:**

- 不在本 change 中实现在线热重载、远程插件市场、自动依赖安装或跨机器调度。
- 不将同进程 Python 权限声明描述为强安全沙箱；未经信任的代码必须使用沙箱后端。
- 不允许插件替换 Agent Loop、基础 ToolPolicy、Trajectory Store、Memory Runtime 或 Provider。
- 不在本 change 中实现 Firecracker、Kata、gVisor 等多租户强隔离后端，只保留可替换后端边界。
- 不允许持续进化流程自动发布或激活生成插件。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `plugins`: 细化类型化 Hook、事务式激活、执行后端、沙箱协议、能力授权、故障策略和插件轨迹合同。

## Impact

- 影响 `memoli_agent/agent/plugins/`、Agent lifecycle、Reasoner 模型调用边界、工具执行边界、bootstrap 配置与现有内置插件。
- 需要扩展现有 SQLite trajectory 事件内容，但不改变其 append-only、脱敏和本地优先语义；数据库 schema 变化必须版本化迁移。
- 沙箱运行引入可选容器运行时集成；基础 Memoli 安装和可信进程内插件不得强制依赖 Docker。
- 配置将增加插件执行模式、权限和资源限制；未声明的敏感能力默认拒绝。
- 现有仓库内插件和相关测试需要迁移，插件开发文档需要同步更新。
