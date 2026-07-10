# Memoli-agent 插件系统说明

本文档说明第八阶段引入的最小插件系统。

## 插件目录

当前只支持本地内置插件：

```text
memoli_agent/plugins/<plugin_name>/plugin.py
```

启用插件由 `config.toml` 控制：

```toml
[plugins]
enabled = ["memory_default", "shell_safety"]
```

## 插件入口

插件模块需要暴露以下任一入口：

```python
def create_plugin():
    return MyPlugin()
```

或：

```python
plugin = MyPlugin()
```

插件对象建议实现：

```python
name: str
async def initialize(context): ...
def register(context): ...
async def terminate(context): ...
```

## PluginContext

插件通过 `PluginContext` 获取受控资源：

- `config`
- `workspace`
- `tool_registry`
- `memory_runtime`
- `hook_registry`

插件应该通过 context 注册工具和 hooks，不直接修改 `AppRuntime`。

## 支持的 hooks

| Hook 名称 | 触发时机 |
| --- | --- |
| `before_turn` | Session 和 TurnState 准备完成后。 |
| `before_reasoning` | 推理前，记忆查询阶段附近。 |
| `prompt_render` | prompt/messages 渲染后。 |
| `after_reasoning` | 模型回复后、会话保存后。 |
| `after_turn` | OutboundMessage 创建后。 |
| `tool_pre` | 工具执行前。 |

hook 异常不会拖垮主流程；lifecycle hook 异常会写入 `ctx.metadata["plugin_errors"]`。

## 默认插件

### memory_default

用于验证 lifecycle hook 能正常被调用。当前只写 metadata 标记，不重复实现记忆系统。

### shell_safety

当前主要保护 `filesystem_read`，拒绝绝对路径、`..` 和隐藏路径读取。后续如果加入 shell 工具，可以继续在这里扩展安全规则。

## 当前限制

- 不支持热加载。
- 不支持远程插件。
- 不自动安装插件依赖。
- 不做进程级沙箱隔离。
