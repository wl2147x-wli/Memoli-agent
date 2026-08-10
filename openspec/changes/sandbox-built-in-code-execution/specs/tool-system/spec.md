## ADDED Requirements

### Requirement: Isolated built-in code execution

`code_run` SHALL 默认在固定、非 root、无网络且受 CPU、内存、PID、时间和输出限制的容器中执行，并 SHALL NOT 在容器不可用时回退宿主进程。

#### Scenario: Default runner executes Python
- **WHEN** container runner 可用且模型执行 Python
- **THEN** 代码 SHALL 在受限容器和指定 workspace 挂载内运行

#### Scenario: Container backend is unavailable
- **WHEN** 默认 container runner 健康检查失败
- **THEN** 系统 SHALL 不注册 `code_run` 或返回 unavailable
- **AND** SHALL NOT 使用宿主 Python 代替

#### Scenario: Network access is attempted
- **WHEN** 默认容器中的代码尝试访问网络
- **THEN** 容器网络边界 SHALL 阻止访问

### Requirement: Explicit trusted-host execution

宿主代码执行 SHALL 仅在 `trusted-host` profile 下启用，并要求显式、已校验的解释器路径；PowerShell SHALL 仅在该 profile 下可用。

#### Scenario: Trusted interpreter is missing
- **WHEN** trusted-host 未配置有效解释器
- **THEN** 系统 SHALL 在执行前报告配置错误
