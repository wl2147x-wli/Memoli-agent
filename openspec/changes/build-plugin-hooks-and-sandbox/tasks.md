## 1. 回归基线与配置契约

- [x] 1.1 为当前插件白名单加载、加载失败隔离、注册、初始化和逆序终止行为补充回归测试
- [x] 1.2 为现有 lifecycle hooks 与 `tool_pre` 的调用位置、异常行为和执行顺序补充回归测试
- [x] 1.3 记录 `memory_default`、`shell_safety` 和无插件配置下的启动行为基线
- [x] 1.4 定义并测试插件 manifest、信任级别、执行模式、Hook deadline 和沙箱资源上限的配置解析契约
- [x] 1.5 验证默认配置不探测容器运行时、不下载镜像且保持基础 Agent 可启动

## 2. 类型化 Hook 合同

- [x] 2.1 定义 `runtime.start`、`turn.before`、`context.contribute`、`model.before`、`model.after`、`tool.before`、`tool.after`、`response.transform`、`turn.after` 和 `runtime.stop` 事件类型
- [x] 2.2 定义 Transformer Patch、Tool Policy Decision 和只读 Observer 事件的 schema 与序列化合同
- [x] 2.3 实现仅应用 Hook 允许字段的 Patch 校验与合并逻辑，并拒绝未知或越界字段
- [x] 2.4 实现 `allow`、`deny`、`rewrite` 和 `require_confirmation` Decision 处理，并确保 rewrite 参数重新经过核心 ToolPolicy
- [x] 2.5 实现 Hook deadline、Transformer/Observer fail-open 与 Policy fail-closed 的分类失败策略
- [x] 2.6 实现按插件依赖、priority 和 plugin ID 排序的串行 Hook Bus
- [x] 2.7 为稳定顺序、依赖缺失、循环依赖、非法 Patch、非法 Decision、异常和超时增加单元测试

## 3. 事务式插件生命周期

- [x] 3.1 定义只负责声明 Hook、工具和 Observer 贡献的 PluginRegistrar 接口
- [x] 3.2 实现 RegistrationTransaction 与可撤销注册句柄，支持逆序 commit/rollback
- [x] 3.3 将 PluginManager 调整为 manifest 校验、依赖排序、后端启动、注册、初始化和提交的原子激活流程
- [x] 3.4 在导入、握手、注册或初始化失败时撤销全部贡献并释放后端资源
- [x] 3.5 实现按依赖和加载顺序逆序终止插件，并对终止失败生成结构化诊断
- [x] 3.6 为初始化中途失败、重复注册、工具名冲突、Hook 冲突、回滚和重复关闭增加测试
- [x] 3.7 回归验证单个关闭步骤失败不会跳过事务撤销、后端 shutdown 或其他插件

## 4. 受限上下文与进程内后端

- [x] 4.1 将 PluginContext 收敛为插件身份、版本、插件配置、私有状态和受控能力集合
- [x] 4.2 从插件公共上下文移除完整 AppConfig、Provider 凭证、裸 ToolRegistry、MemoryRuntime 和数据库连接
- [x] 4.3 定义 PluginExecutionBackend 协议并实现可信插件使用的 InProcessPluginBackend
- [x] 4.4 实现系统策略对插件请求执行模式的收紧，禁止插件把强制 sandbox 降级为 in-process
- [x] 4.5 为上下文 Secret 不可见、未声明能力拒绝和可信模式诊断增加测试

## 5. Agent Loop、Provider 与工具链集成

- [x] 5.1 在 Runtime 启停边界接入 `runtime.start` 与 `runtime.stop` Observer
- [x] 5.2 在被动 turn 和上下文组装边界接入 `turn.before` 与 `context.contribute` Transformer
- [x] 5.3 在每次真实模型请求前后接入 `model.before` 与 `model.after` Observer
- [x] 5.4 在工具执行前接入 `tool.before` Policy，并保持核心 ToolPolicy 为不可绕过边界
- [x] 5.5 在工具成功、失败和拒绝路径接入 `tool.after` Observer
- [x] 5.6 在出站回复和 turn 完成边界接入 `response.transform` 与 `turn.after`
- [x] 5.7 迁移仓库内置插件到新 PluginRegistrar 和类型化事件合同
- [x] 5.8 将基础 workspace/文件访问安全收归核心 ToolPolicy，并把 `memory_default` 调整为示例或契约测试插件
- [x] 5.9 为直接回复、多轮模型工具循环、工具拒绝、Provider fallback 和插件禁用增加集成测试
- [x] 5.10 回归验证 Observer 故障不改变回答、Policy 故障阻止工具副作用

## 6. 沙箱 RPC 与 Runner

- [x] 6.1 定义包含协议版本、请求 ID、插件 ID、方法、deadline 和有界 payload 的 JSON-RPC schema
- [x] 6.2 实现 `plugin.handshake`、`plugin.register`、`plugin.initialize`、`hook.invoke`、`tool.invoke`、`capability.call` 和 `plugin.shutdown` 协议处理
- [x] 6.3 实现宿主侧异步 stdio RPC client，并将 stdout 限定为协议帧、stderr 限长采集
- [x] 6.4 实现通用插件 runner，校验插件身份和协议版本后加载沙箱插件
- [x] 6.5 对消息大小、JSON 深度、未知方法、重复响应、身份不匹配、非 JSON 输出和超时实施拒绝策略
- [x] 6.6 实现 FakeSandboxBackend，使无容器环境能够运行完整协议与失败测试
- [x] 6.7 为握手成功、协议不兼容、恶意输出、超大消息、超时和 runner 崩溃增加契约测试

## 7. Capability Broker 与插件状态

- [x] 7.1 实现 manifest 请求、用户批准和系统上限取交集的有效能力计算
- [x] 7.2 实现按 plugin ID 隔离的 State Capability，禁止插件直接打开状态数据库
- [x] 7.3 实现 Workspace Read/Write Capability 的路径规范化、普通文件检查、大小限制和授权范围匹配
- [x] 7.4 拒绝绝对路径、父级逃逸、符号链接、junction/reparse point 和授权目录外访问
- [x] 7.5 为 Network、Memory、LLM 和 Secret 能力定义默认拒绝的占位合同，未实现能力不得被批准
- [x] 7.6 确保需要宿主凭证的能力由 Broker 使用凭证，且请求、响应和错误不向插件泄露原始 Secret
- [x] 7.7 为能力成功、未声明、未批准、路径逃逸、状态跨插件访问和 Secret 泄露增加测试

## 8. 容器沙箱后端

- [x] 8.1 实现通过参数数组而非 shell 字符串启动容器 CLI 的 SandboxPluginBackend
- [ ] 8.2 构建并记录固定 digest 的最小插件 runner 镜像，禁止运行时安装任意依赖
- [x] 8.3 应用默认禁网、只读根文件系统、非 root、cap-drop、no-new-privileges、seccomp 和独立 tmpfs
- [x] 8.4 仅挂载只读插件包与独立受管沙箱目录，禁止 Docker socket、用户主目录、Memoli 根目录和数据库挂载
- [x] 8.5 应用 CPU、内存、swap、PID、墙钟时间、stdout/stderr 和 RPC payload 限制
- [x] 8.6 在沙箱要求满足但容器运行时或固定镜像不可用时拒绝激活，且不得回退到 InProcessPluginBackend
- [x] 8.7 实现超时、异常退出和协议违规后的容器终止与范围校验清理
- [x] 8.8 增加真实容器集成测试标记，并明确报告无容器环境下的 skip 状态

## 9. SQLite 插件轨迹

- [x] 9.1 使用现有 SQLite trajectory 合同记录插件后端启动、停止、终止和失败事件
- [x] 9.2 记录 Hook 开始、完成、失败、插件 ID、版本、后端、执行次序、耗时和状态
- [x] 9.3 为 Transformer Patch、Policy Decision 与 Capability 请求保存脱敏且有界的证据表示
- [x] 9.4 确保插件轨迹写入复用现有 schema version、顺序号、payload 限制和必需写入失败语义
- [x] 9.5 验证关闭 trajectory 时插件行为不变且不会单独写入插件数据库
- [x] 9.6 为多插件顺序还原、能力拒绝、沙箱终止、脱敏和确定性 JSONL 导出增加测试

## 10. 安全回归与恶意插件测试

- [x] 10.1 创建尝试读取 AppConfig、环境 Secret、用户主目录和宿主数据库的恶意插件夹具并验证拒绝
- [x] 10.2 创建尝试直接联网、访问 localhost/内网和请求未授权 Network Capability 的插件夹具并验证拒绝
- [x] 10.3 创建路径穿越、符号链接和 reparse point 逃逸夹具并验证 Broker 拒绝
- [x] 10.4 创建无限循环、内存耗尽、进程炸弹、无限输出和超大 RPC payload 夹具并验证资源边界
- [x] 10.5 创建试图请求 privileged、host namespace、宿主设备和 Docker socket 的 manifest/配置夹具并验证激活失败
- [x] 10.6 验证任一恶意插件失败后其他插件、Agent Runtime 和已提交 SQLite 轨迹保持可用

## 11. 文档与质量门禁

- [x] 11.1 更新插件开发文档，说明新 Hook 映射、Patch/Decision、Registrar、manifest、状态和迁移示例
- [x] 11.2 更新安全文档，明确 in-process 非沙箱、容器威胁模型、默认限制、Broker 边界和 microVM 非目标
- [x] 11.3 更新配置示例，覆盖可信插件、沙箱插件、权限、deadline 和资源限制且不包含真实 Secret
- [x] 11.4 运行 `python -m pytest -q` 并记录真实容器测试是否执行
- [x] 11.5 运行 `python -m ruff check memoli_agent benchmarks tests` 和 `python -m pyright`
- [x] 11.6 运行 `openspec validate --all --strict` 并修复全部错误和警告
- [x] 11.7 在母变更 `design-lifelong-agent-evolution` 中记录本 change 对插件细化任务的承接关系，归档前消除重复或冲突 requirement
