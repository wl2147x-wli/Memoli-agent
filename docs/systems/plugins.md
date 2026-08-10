# 插件、Hook 与沙箱

Memoli 的插件层保持 GenericAgent 风格的极简边界：插件只能通过
`PluginRegistrar` 声明 Hook 和工具，不能获得 `AppConfig`、Provider 凭证、裸
`ToolRegistry`、`MemoryRuntime` 或数据库连接。完整对话与工具结果仍由统一
SQLite trajectory 保存，插件不自行维护轨迹数据库。

## 激活流程

Runtime 严格按以下顺序激活白名单插件：

1. 在导入 Python 前读取并校验 `plugin.toml`；
2. 验证 Runtime 版本和依赖 DAG，并按依赖、priority、插件 ID 确定顺序；
3. 根据 manifest、用户批准和系统上限计算执行模式及有效能力；
4. 启动 in-process 或 sandbox 后端；
5. 在 `RegistrationTransaction` 中暂存贡献；
6. 完成 `register` 和 `initialize` 后原子提交；任何失败都会逆序回滚；
7. Runtime 关闭时按加载顺序逆序撤销贡献并终止后端。

默认配置只加载两个可信内置插件，不探测 Docker，也不下载镜像。未列入
`trusted` 的插件即使请求 `in_process`，也会被系统收紧为 `sandbox`；沙箱不可用
时激活失败，不会降级到进程内执行。

## Manifest

每个插件目录必须包含 `plugin.toml` 和入口模块：

```toml
schema_version = 1
id = "example"
version = "0.1.0"
runtime = ">=0.1,<0.2"
entrypoint = "plugin:create_plugin"
execution = "sandbox"
dependencies = []
hooks = ["context.contribute", "tool.after"]
tools = []

[permissions]
capabilities = ["state.get", "state.set", "workspace.read"]
workspace_read = ["notes/*.md"]

[resources]
hook_deadline_seconds = 1.0
memory_mb = 128
cpus = 0.25
pids = 16
max_output_bytes = 262144
max_rpc_bytes = 131072
```

未知字段（包括 `privileged`、host namespace、设备或 Docker socket 请求）会在
导入前被拒绝。插件声明的资源值是请求值，最终值还会被宿主配置收紧。

## Registrar 与生命周期

```python
class ExamplePlugin:
    def register(self, registrar):
        registrar.add_transformer(
            HookName.CONTEXT_CONTRIBUTE, self.contribute, priority=10
        )
        registrar.add_observer(HookName.TOOL_AFTER, self.observe_tool)

    async def initialize(self, context):
        # context 只含身份、版本、插件配置、私有状态和能力客户端
        self.context = context

    async def terminate(self):
        pass

    def contribute(self, event):
        return ContextPatch(
            sections=(ContextSection("example", "有来源的上下文"),)
        )
```

旧插件迁移时需要把 `register(context)` 改为 `register(registrar)`，把字符串
`before_turn`/`prompt_render`/`tool_pre` 映射为下表的类型化 Hook，并删除对完整
Runtime 对象的访问。

| Hook | 类型 | 失败语义 |
| --- | --- | --- |
| `runtime.start`, `runtime.stop` | Observer | fail-open |
| `turn.before` | Transformer (`TurnPatch`) | fail-open |
| `context.contribute` | Transformer (`ContextPatch`) | fail-open |
| `model.before`, `model.after` | Observer | fail-open |
| `tool.before` | Policy (`ToolDecision`) | fail-closed |
| `tool.after` | Observer | fail-open |
| `response.transform` | Transformer (`ResponsePatch`) | fail-open |
| `turn.after` | Observer | fail-open |

Transformer 只能返回对应 Patch，不能任意修改共享上下文。工具策略可返回
`allow`、`deny`、`rewrite` 或 `require_confirmation`；重写后的参数仍必须通过核心
工具的 `WorkspacePathResolver` 等不可绕过策略。所有 Hook 串行执行，第一版不做
并发。

## 状态和能力

`context.state` 是按 plugin ID 隔离的 SQLite KV；插件看不到连接。沙箱插件通过
双向 JSON-RPC `capability.call` 使用同一能力代理。当前只实现：

- `state.get`、`state.set`
- `workspace.read`、`workspace.write`（UTF-8 普通文件、模式和大小受限）

绝对路径、`..`、符号链接、junction/reparse point 和授权范围外路径会被拒绝。
Network、Memory、LLM、Secret 目前是默认拒绝的预留合同，不能被配置批准。

详见 [插件安全边界](plugin-security.md)。
