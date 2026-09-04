## MODIFIED Requirements

### Requirement: Controlled plugin context

插件 SHALL 通过与其身份、执行后端和批准权限绑定的受控上下文访问运行期能力，并 SHALL NOT 获得完整应用配置、Provider 凭证、裸数据库连接或可替换 Runtime 核心组件的对象。

#### Scenario: Plugin extends behavior

- **WHEN** 插件需要增加工具或生命周期行为
- **THEN** 插件 SHALL 通过上下文提供的注册表完成注册
- **AND** 插件 SHALL NOT 直接替换应用运行时核心组件

#### Scenario: Trusted plugin extends behavior

- **WHEN** 可信进程内插件需要增加工具或生命周期行为
- **THEN** 插件 SHALL 通过事务式注册接口声明其贡献
- **AND** 插件 SHALL 仅获得系统批准的配置、私有状态和能力接口

#### Scenario: Plugin requests an undeclared capability

- **WHEN** 插件请求 manifest 未声明或用户配置未批准的受控能力
- **THEN** 系统 SHALL 拒绝该请求并记录插件身份、能力名称和拒绝原因
- **AND** 系统 SHALL NOT 向插件返回目标资源或相关秘密

#### Scenario: Plugin needs an authenticated external operation

- **WHEN** 已获授权的插件请求需要宿主凭证的外部操作
- **THEN** 系统 SHALL 由受控能力代理使用凭证执行操作
- **AND** SHALL NOT 将原始凭证、Authorization 信息或完整应用配置交给插件

### Requirement: Lifecycle and tool hooks

系统 SHALL 使用类型化事件支持 `runtime.start`、`turn.before`、`context.contribute`、`model.before`、`model.after`、`tool.before`、`tool.after`、`response.transform`、`turn.after` 与 `runtime.stop` hooks，并 SHALL 区分 Transformer、Policy 和 Observer 三类行为合同。

#### Scenario: Lifecycle hook fails

- **WHEN** 生命周期 hook 抛出异常
- **THEN** 系统 SHALL 在当前回合元数据中记录插件错误
- **AND** 主对话 SHALL 继续执行

#### Scenario: Transformer contributes context

- **WHEN** `context.contribute` Transformer 返回符合 schema 的上下文 Patch
- **THEN** 系统 SHALL 只把该 Hook 被允许修改的字段应用到模型上下文
- **AND** SHALL 保留 section 的插件来源和执行次序

#### Scenario: Transformer returns an invalid patch

- **WHEN** Transformer 超时、抛出异常或返回不符合 schema 的 Patch
- **THEN** 系统 SHALL 丢弃该 Hook 的本次修改并记录结构化失败
- **AND** 主对话 SHALL 继续执行

#### Scenario: Policy denies a tool call

- **WHEN** `tool.before` Policy 返回 `deny` 或 `require_confirmation`
- **THEN** 系统 SHALL NOT 在未满足 Decision 条件时执行目标工具
- **AND** SHALL 将结构化原因作为工具结果和轨迹证据

#### Scenario: Policy hook fails

- **WHEN** `tool.before` Policy 超时、抛出异常或返回非法 Decision
- **THEN** 系统 SHALL 对当前工具调用 fail-closed
- **AND** SHALL NOT 因插件失败跳过核心 ToolPolicy

#### Scenario: Observer hook fails

- **WHEN** Observer 超时或抛出异常
- **THEN** 系统 SHALL 记录插件、Hook 和错误分类
- **AND** Observer 失败 SHALL NOT 修改事件或中断主对话

#### Scenario: Plugin shutdown

- **WHEN** 应用关闭
- **THEN** 已激活插件 SHALL 按依赖与加载顺序的逆序终止
- **AND** 系统 SHALL 撤销其运行期贡献并释放执行后端资源

#### Scenario: One plugin cleanup step fails

- **WHEN** 贡献撤销、注册事务关闭或执行后端 shutdown 中任一步骤失败
- **THEN** 系统 SHALL 继续尝试该插件剩余清理步骤和其他插件终止
- **AND** SHALL 记录不包含原始异常文本的结构化错误分类

## ADDED Requirements

### Requirement: Deterministic typed hook execution

系统 SHALL 在导入插件代码前验证 Hook 声明，并按插件依赖、Hook 优先级和插件 ID 形成确定性执行顺序；Transformer 与 Policy hooks SHALL 在第一版中串行执行。

#### Scenario: Multiple plugins register the same hook

- **WHEN** 多个已启用插件注册同一 Hook
- **THEN** 系统 SHALL 先满足插件依赖，再按优先级降序和插件 ID 稳定顺序执行
- **AND** 相同配置的重复启动 SHALL 得到相同顺序

#### Scenario: Hook dependency cycle exists

- **WHEN** 已启用插件的依赖形成循环
- **THEN** 系统 SHALL 在执行相关插件代码前拒绝激活这些插件
- **AND** SHALL 报告构成循环的插件标识

### Requirement: Transactional plugin activation

插件的 Hook、工具和其他运行期贡献 SHALL 在同一激活事务中注册，只有注册和初始化全部成功后才可对 Agent Runtime 生效。

#### Scenario: Plugin initializes successfully

- **WHEN** 插件完成协议握手、贡献注册和初始化
- **THEN** 系统 SHALL 原子提交其贡献并将插件标记为 active

#### Scenario: Plugin initialization fails

- **WHEN** 插件在导入、握手、注册或初始化阶段失败
- **THEN** 系统 SHALL 按逆序撤销该插件已经注册的全部贡献
- **AND** SHALL 终止其执行后端并使其他插件及主 Runtime 继续工作

### Requirement: Policy-governed execution backend

系统 SHALL 根据插件来源、manifest 请求和用户信任策略，为插件选择 `in_process` 或 `sandbox` 执行后端；第三方、来源不明和自动生成候选 SHALL 能被强制使用 sandbox。

#### Scenario: Trusted built-in plugin starts

- **WHEN** 仓库内置插件被配置为可信且选择 `in_process`
- **THEN** 系统 SHALL 在主进程激活该插件
- **AND** SHALL 明确记录该模式不构成不可信代码安全边界

#### Scenario: Sandbox is required but unavailable

- **WHEN** 插件的有效策略要求 sandbox 而容器运行时、固定 runner 镜像或沙箱配置不可用
- **THEN** 系统 SHALL 拒绝激活该插件并报告可操作原因
- **AND** SHALL NOT 静默降级为 `in_process`

#### Scenario: No sandbox plugin is enabled

- **WHEN** 用户仅启用可信进程内插件或没有启用插件
- **THEN** 基础 Runtime SHALL NOT 要求容器运行时存在
- **AND** SHALL NOT 自动下载或启动沙箱镜像

### Requirement: Versioned sandbox protocol

沙箱插件 SHALL 通过有界、schema-versioned 的 JSON-RPC 协议与宿主通信，宿主 SHALL 对请求身份、方法、payload、响应和 deadline 进行验证，并 SHALL NOT 反序列化插件提供的任意语言对象。

#### Scenario: Sandbox handshake succeeds

- **WHEN** 插件 runner 返回兼容协议版本、匹配的插件身份和有效贡献声明
- **THEN** 系统 SHALL 继续注册与初始化流程

#### Scenario: Sandbox sends malformed output

- **WHEN** 插件返回非 JSON、未知方法、重复响应、身份不匹配或超过大小限制的消息
- **THEN** 系统 SHALL 将其标记为协议错误并停止处理该插件的后续请求
- **AND** SHALL 终止或隔离对应沙箱而不影响其他插件

#### Scenario: Sandbox hook exceeds deadline

- **WHEN** 沙箱 Hook 在规定 deadline 内没有返回有效响应
- **THEN** 系统 SHALL 按该 Hook 类别的失败策略处理本次调用
- **AND** SHALL 记录超时并终止不再响应的沙箱进程

### Requirement: Deny-by-default sandbox containment

沙箱后端 SHALL 默认禁用直接网络，使用只读根文件系统和非 root 身份，移除非必要进程能力，并限制可见文件、CPU、内存、PID、墙钟时间和输出大小。

#### Scenario: Sandbox plugin starts with default policy

- **WHEN** 系统启动一个未获得额外能力的沙箱插件
- **THEN** 插件 SHALL NOT 直接访问宿主网络、用户主目录、Memoli 配置、数据库、Docker socket 或 workspace 根目录
- **AND** 其临时文件和持久状态 SHALL 位于独立受管目录

#### Scenario: Plugin exhausts a resource limit

- **WHEN** 插件超过 CPU、内存、PID、墙钟时间或输出大小限制
- **THEN** 系统 SHALL 终止或限制该沙箱并记录命中的资源边界
- **AND** 其他插件和主 Runtime SHALL 继续工作

#### Scenario: Plugin requests privileged container access

- **WHEN** 插件请求 privileged、host network、host PID/IPC、宿主设备、Docker socket 或宽泛宿主目录挂载
- **THEN** 系统 SHALL 拒绝激活或拒绝该请求

### Requirement: Brokered sandbox capabilities

沙箱插件对 workspace、记忆、网络、LLM、Secret 和持久状态的访问 SHALL 通过宿主 Capability Broker，并 SHALL 受 manifest 请求、用户批准和系统上限的交集约束。

#### Scenario: Plugin reads an allowed workspace file

- **WHEN** 插件通过 Broker 请求读取其授权范围内的普通文件
- **THEN** Broker SHALL 在路径规范化和边界检查通过后返回有界内容
- **AND** SHALL 记录能力调用的插件身份、目标摘要和结果状态

#### Scenario: Plugin attempts path escape

- **WHEN** 插件请求的路径通过绝对路径、父级跳转、符号链接或重解析点逃出授权范围
- **THEN** Broker SHALL 拒绝访问并记录安全审计事件

#### Scenario: Plugin requests network without approval

- **WHEN** 插件未获批准却请求直接联网或调用网络能力
- **THEN** 系统 SHALL 拒绝请求
- **AND** SHALL NOT 为该插件启用通用容器网络

### Requirement: Plugin execution trajectory

启用 SQLite 轨迹记录时，系统 SHALL 将插件后端、Hook、Policy Decision 和 Capability Broker 行为作为原始执行证据关联到当前 trace，并保持脱敏、有界和 append-only。

#### Scenario: Plugin hook completes

- **WHEN** 任一插件 Hook 执行完成
- **THEN** 轨迹 SHALL 记录插件 ID、版本、执行后端、Hook 名称、执行次序、耗时和状态
- **AND** Transformer 或 Policy SHALL 记录脱敏且有界的 Patch 或 Decision 表示

#### Scenario: Plugin capability is denied

- **WHEN** Capability Broker 拒绝插件请求
- **THEN** 轨迹 SHALL 记录插件身份、能力名称和拒绝分类
- **AND** SHALL NOT 记录 Secret 值或未授权资源内容

#### Scenario: Trajectory recording is disabled

- **WHEN** 用户显式关闭轨迹记录并执行插件 Hook
- **THEN** Hook 的运行语义 SHALL 保持不变
- **AND** 系统 SHALL NOT 因插件可观测性要求单独写入轨迹数据库

#### Scenario: Plugin trajectory is later considered for learning

- **WHEN** 后续 Memory、Evolution 或 Post-training 组件希望读取插件轨迹
- **THEN** 在线插件系统 SHALL NOT 自动授予该用途或生成评价标签
- **AND** 数据 SHALL 经过独立的授权、脱敏与轨迹处理流程
