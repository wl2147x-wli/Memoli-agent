## Why

内置 `code_run` 当前直接使用宿主解释器并默认允许网络，插件容器沙箱无法保护该执行路径。这是长期个人助手中不可接受的宿主机执行风险。

## What Changes

- **BREAKING**：新增 container、trusted-host、disabled 三种 runner，默认 container。
- 容器默认无网络、非 root、固定镜像并限制 CPU、内存、PID、时间和输出。
- 容器不可用时禁止回退宿主；PowerShell 仅允许 trusted-host。
- trusted-host 必须显式配置并校验解释器。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `tool-system`: 修改代码执行工具的默认安全、配置和降级合同。

## Impact

影响 ToolsConfig、工具装配、CodeRunTool、Docker runner、示例配置和安全测试；部署环境需准备固定 digest 镜像。
