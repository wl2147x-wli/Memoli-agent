# MCP 系统说明

第 11 阶段实现的是最小 MCP client 接入。Memoli 可以连接本地 stdio
MCP server，发现 server 暴露的工具，并把这些工具注册到现有
`ToolRegistry`。

## 运行链路

```text
config.toml
  -> MCPClientManager.connect_all()
  -> MCPClient.list_tools()
  -> MCPToolAdapter
  -> ToolRegistry.register()
  -> Reasoner 调用 MCP 工具
  -> MCPClient.call_tool()
```

MCP 工具进入 `ToolRegistry` 后，主 agent 会像调用内置工具一样调用它们。

## 配置示例

```toml
[mcp]
enabled = true

[[mcp.servers]]
name = "demo"
transport = "stdio"
command = "python"
args = ["path/to/server.py"]
enabled = true
```

当前只支持 `transport = "stdio"`。

## 工具命名规则

为了避免和内置工具、插件工具重名，MCP 工具注册名固定为：

```text
mcp__<server_name>__<tool_name>
```

例如：

```text
mcp__demo__search
```

## 当前限制

- 只实现 MCP client，不实现 MCP server。
- 只支持本地 stdio server。
- 暂不支持远程 HTTP、OAuth、resources 和 prompts。
- MCP server 连接失败不会阻止主程序启动，但对应工具不会注册。

## 安全注意

MCP server 是外部进程。启用前应确认 server 来源可信，并理解它可能访问的
本地文件、网络或系统资源。
