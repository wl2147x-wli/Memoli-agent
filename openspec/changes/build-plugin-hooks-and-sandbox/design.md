## Context

Memoli 当前通过配置白名单导入本地 Python 模块，插件在主进程中获得完整 `AppConfig`、workspace、工具注册表、记忆运行时和 Hook 注册表。生命周期 Hook 共用可变 `PassiveTurnContext`，普通 Hook 异常被写成字符串后忽略，`tool_pre` 则直接传播异常；注册与初始化分离且没有统一撤销句柄，因此初始化失败可能留下已注册行为。

GenericAgent 证明了在 Agent Loop 的 agent、turn、LLM 和 tool 边界放置少量 hooks 就能支持项目上下文注入和完整 tracing，但其自动导入全部插件、传递 `locals()` 和同进程全权限不适合作为 Memoli 的安全边界。《AI Agent Book》要求插件作为 Harness 扩展进入统一工具治理和轨迹证据链，外部能力与不可信代码必须最小授权，持续进化生成的候选也不能直接进入稳定 Runtime。

本 change 是 `design-lifelong-agent-evolution` 中插件细化任务的实施子 change，只覆盖 Hook 合同与安全沙箱；其中已有的 manifest、顺序和权限原则由本设计落成可测试协议，后续应在母变更中消除重复 delta。

## Goals / Non-Goals

**Goals:**

- 保持类似 GenericAgent 的小型 Hook 内核，同时用类型化事件和显式返回值降低对 Agent Loop 内部变量的耦合。
- 让上下文修改、工具策略与只读观测具有不同且可测试的失败语义。
- 让插件注册和初始化成为可回滚事务，消除半激活插件。
- 以同一插件协议支持可信进程内执行和不可信沙箱执行。
- 通过 Capability Broker 强制最小权限，避免插件直接获得秘密、宿主对象和数据库连接。
- 将插件版本、Hook 次序、Patch/Decision、耗时和失败写入现有 SQLite 轨迹，不在运行期添加评价标签。
- 在没有容器运行时的环境中保持基础 Agent 和可信插件可运行，同时禁止沙箱插件静默降级为同进程执行。

**Non-Goals:**

- 不实现热重载、远程插件市场、运行时依赖安装或插件自动升级。
- 不使用 Python audit hook、受限 builtins 或普通 subprocess 声称提供强沙箱。
- 不让插件替换核心 ToolPolicy、Trajectory Store、Memory Runtime、Provider 或 Agent Loop。
- 不实现多租户 microVM；Firecracker、Kata 和 gVisor 仅作为未来后端。
- 不实现自动生成插件的发布门禁，只保证这类候选可以被强制放入沙箱。

## Decisions

### 1. 使用一个类型化 Hook Bus，不引入 PhaseModule/Slot 双层扩展

Hook Bus 暴露以下稳定事件：

| 类别 | Hook | 作用 |
|---|---|---|
| Transformer | `turn.before` | 回合开始时给出受限的中止或元数据 Patch |
| Transformer | `context.contribute` | 向模型上下文追加有名称、有来源、受预算约束的 section |
| Transformer | `response.transform` | 在出站前返回受限回复或媒体 Patch |
| Policy | `tool.before` | 返回 `allow`、`deny`、`rewrite` 或 `require_confirmation` |
| Observer | `runtime.start`、`model.before`、`model.after`、`tool.after`、`turn.after`、`runtime.stop` | 只读观测和外部导出 |

Transformer 接收不可替换的事件快照并返回 schema 约束的 Patch；Runtime 只应用该 Hook 允许修改的字段。Policy 返回结构化 Decision，不通过抛异常表达正常拒绝。Observer 的返回值被忽略，且不得影响主流程。

选择稳定边界而不是 akashic-agent 的内部 slot 拓扑，是因为 Memoli 当前 Agent Loop 较小，slot 会让插件依赖内部模块名。替代方案是继续传递 `PassiveTurnContext`；其实现最少，但无法限制修改范围，也难以记录可重放差异。

现有 `before_turn`、`before_reasoning`、`prompt_render`、`after_reasoning`、`after_turn` 和 `tool_pre` 插件迁移到上述事件，不长期保留两套公共 Hook API。仓库内插件与测试在同一 change 中迁移。

### 2. Hook 顺序由依赖、优先级和插件 ID 唯一确定

PluginManager 先按插件 manifest 的依赖关系拓扑排序，再按 Hook `priority` 降序，最后按 `plugin_id` 字典序稳定排序。依赖缺失或形成环时，相关插件在导入代码前被拒绝激活。

Transformer 和 Policy 串行执行，以便后一 Hook 接收前一 Hook 已应用后的快照；Observer 第一版也串行执行，符合当前不做并发的约束。未来可在保持观察顺序号的前提下增加异步 fan-out。

### 3. 不同 Hook 类别使用不同失败策略

- Transformer 超时、异常或返回非法 Patch：丢弃该次 Patch、记录失败，主流程继续。
- Observer 超时或异常：记录失败，主流程继续。
- Policy 超时、异常或非法 Decision：当前工具调用 fail-closed，返回结构化拒绝；核心 ToolPolicy 始终独立执行。
- 任一 Hook 都不能通过结果削弱核心 ToolPolicy；插件策略只能增加约束或改写为仍会再次经过核心校验的参数。

每个 Hook 有全局默认 deadline，manifest 可以请求更短值，不能自行放宽系统上限。

### 4. 通过事务式 Registrar 激活插件

加载过程为：

```text
读取并校验 manifest（不导入代码）
  → 解析依赖与有效执行模式
  → 创建 RegistrationTransaction
  → 启动执行后端并握手
  → register hooks/tools
  → initialize
  → commit
```

Registrar 为每项贡献保存撤销句柄。导入、握手、注册或初始化任一步失败都按逆序撤销工具和 hooks、终止后端并清理临时资源。终止时按插件依赖逆序关闭。

选择显式事务而不是在错误处理中分别删除列表，是因为未来贡献类型会增加，集中撤销更容易验证。

### 5. 同一管理器支持 `in_process` 与 `sandbox` 两种执行后端

- `in_process` 仅用于仓库内置或配置明确标记为可信的插件，追求低延迟。
- `sandbox` 用于第三方、来源不明和自动生成候选。系统策略可以把任意插件强制提升到 sandbox，插件自身不能要求降级到 in-process。
- 沙箱后端不可用、镜像不匹配或启动失败时，插件保持未激活；系统不得回退到 in-process。

第一版使用 `asyncio.create_subprocess_exec` 调用容器 CLI，不引入常驻 Docker Python SDK。基础安装不依赖容器库；只有启用 sandbox 插件时才检查容器运行时。

### 6. 沙箱插件通过版本化 JSON-RPC over stdio 通信

一个沙箱插件在一次 Runtime 生命周期内使用一个长驻容器，依次处理串行 Hook/Tool 请求。协议至少包含：

- `plugin.handshake`
- `plugin.register`
- `plugin.initialize`
- `hook.invoke`
- `tool.invoke`
- `capability.call`
- `plugin.shutdown`

每条消息包含协议版本、请求 ID、插件 ID、方法、deadline 和有界 JSON payload。stdout 仅承载协议帧，stderr 单独采集并限长；未知方法、重复响应、越界消息、非 JSON 输出或协议版本不兼容均视为协议错误。主进程对响应做 schema 校验，不反序列化任意 Python 对象。

选择 stdio 是因为第一版单机串行、无需开放端口，且容易同时支持本地进程测试替身与容器。替代方案是 HTTP/gRPC；它们增加端口、认证和依赖管理，对当前规模没有收益。

### 7. 所有宿主资源访问经 Capability Broker

沙箱不获得 `AppConfig`、环境 Secret、workspace 根目录、数据库文件、Docker socket 或 Runtime 对象。插件只能调用 manifest 已声明且系统配置批准的能力，例如：

- `workspace.read`
- `workspace.write`
- `memory.search`
- `memory.propose`
- `network.fetch`
- `llm.complete`
- `state.get/set`

Broker 对每次请求执行权限匹配、路径/URL 规范化、参数 schema、大小/频率限制、脱敏和轨迹记录。Secret 默认不返回插件；需要鉴权的网络调用由 Broker 添加凭据并只返回受限响应。

第一版至少实现 workspace 和插件私有 state 能力；网络默认关闭，后续开放时必须经 Broker 域名 allowlist，不能直接给容器通用网络。

### 8. 第一版容器策略采用 deny-by-default

容器以固定镜像 digest 启动，并应用：默认无网络、只读根文件系统、非 root UID、删除 Linux capabilities、`no-new-privileges`、默认或更严格 seccomp、独立临时目录、仅插件包与单次沙箱数据目录的最小只读/读写挂载，以及 CPU、内存、PID、墙钟时间和输出大小限制。

不得使用 privileged、host network/PID/IPC、宿主设备、Docker socket 或 Memoli/用户主目录整体挂载。容器超时、退出或违反协议时由宿主终止并清理；清理失败产生结构化诊断但不扩大删除范围。

容器共享宿主内核，因此该后端面向个人助手的第三方插件隔离，不宣称满足敌对多租户边界。更高风险场景应实现 microVM Backend。

### 9. 插件状态与轨迹使用命名空间和现有证据存储

插件状态通过 `plugin_id` 命名空间的受控 KV 接口访问，不向插件暴露 SQLite 文件。沙箱临时目录与持久状态目录分离，禁用或失败不会自动删除持久状态。

现有 trajectory schema 能承载新事件时不新增独立数据库；记录 `plugin_hook_started/completed/failed`、`plugin_capability_requested/denied` 和 `plugin_backend_started/stopped/killed` 等事件。事件至少包含插件 ID、版本、执行后端、Hook、次序、耗时、状态，以及脱敏且有界的 Patch/Decision 或错误分类。运行轨迹不自动进入 Memory、Evolution 或 Post-training。

### 10. 配置与 manifest 分工

manifest 声明插件希望贡献的 hooks/tools、运行时兼容、依赖、权限和资源请求；用户配置决定启用状态、信任级别、有效执行后端、批准权限和系统资源上限。最终权限取 manifest 请求与系统批准的交集，未声明或未批准能力一律拒绝。

基础默认配置继续启用可信内置插件，不启用任何沙箱插件。配置文件缺失时不得触发容器探测或下载镜像。

## Risks / Trade-offs

- **[同进程插件仍可读取宿主资源]** → 仅允许内置或明确可信插件使用 in-process，并在文档和诊断中标明其不是安全边界。
- **[容器共享内核，隔离并非绝对]** → 使用最小权限和资源限制；高威胁、多租户场景升级到 microVM Backend。
- **[Hook 迁移破坏已有插件]** → 同 change 迁移所有仓库内插件，提供迁移文档和契约测试；版本不兼容的外部插件在导入前拒绝。
- **[沙箱 RPC 增加延迟]** → 每个插件长驻容器、串行复用；记录每次 RPC 耗时，为后续优化提供证据。
- **[Policy 插件故障导致工具不可用]** → 核心策略与插件策略分离，结构化呈现拒绝原因；用户可禁用故障插件，但单次调用坚持 fail-closed。
- **[Broker 路径或 URL 校验错误导致逃逸]** → 使用解析后路径边界、拒绝链接/重解析点、DNS/IP 二次校验，并建立恶意插件回归集。
- **[轨迹泄露插件输入或 Secret]** → 复用递归脱敏和 payload 上限，Broker 在添加凭据前后分离可记录数据。
- **[Docker 不可用于 CI 或 Windows 开发机]** → 用协议级 fake sandbox 完成必跑测试；真实容器集成测试显式检测环境并单独报告，不静默当作通过。

## Migration Plan

1. 为现有 Hook 调用顺序、内置插件和完整 trajectory 保存回归基线。
2. 引入类型化事件、Patch/Decision、Hook Bus 和事务式 Registrar，但先在进程内 Backend 下迁移现有插件。
3. 从 PluginContext 移除完整 `AppConfig` 和裸注册表，迁移 `memory_default` 为示例/契约插件，将基础文件安全收归核心 ToolPolicy。
4. 在 Agent Loop、Provider 和 ToolExecutor 稳定边界接入新 hooks，并写入现有 SQLite trajectory 事件。
5. 增加 JSON-RPC runner、Capability Broker 和 fake sandbox 契约测试。
6. 增加容器 Backend 与 deny-by-default 启动配置，默认不启用沙箱插件。
7. 运行现有回归、恶意插件用例、Ruff、Pyright 和严格 OpenSpec 校验，随后同步插件与安全文档。

回滚时可禁用所有 sandbox 插件并保留可信进程内插件；新轨迹事件为追加记录，不修改既有事件。若 Hook API 回滚，必须同时回滚已迁移插件版本，不能让新旧公共 Hook API 同时无期限存在。

## Open Questions

- 第一版容器镜像由仓库构建并固定 digest，还是允许用户配置经过 allowlist 的 runner image？实施前默认采用仓库提供的固定 runner image。
- 真实容器集成测试在本地/CI 无 Docker 时采用显式 skip 还是独立测试命令？实施前默认采用独立标记并在验证报告中明确是否执行。

