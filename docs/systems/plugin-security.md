# 插件安全边界与威胁模型

## 信任边界

`in_process` 只适合代码已经过审计的可信插件，它与 Runtime 同权，**不是沙箱**。
第三方或不受信任插件必须使用容器后端。容器用于限制常见插件攻击面，但不是
对抗内核漏洞的强隔离，也不替代 microVM；microVM 不属于当前版本目标。

## 容器默认限制

宿主通过参数数组调用容器 CLI，不经过 shell。runner 镜像必须固定到
`@sha256:` digest，运行时不会安装依赖，也不会自动拉取或回退镜像。容器使用：

- `--network none`，默认禁止外网、localhost 和内网访问；
- 只读根文件系统、非 root UID 65532、`cap-drop ALL`；
- `no-new-privileges` 与默认 seccomp；
- 独立 `noexec,nosuid` tmpfs；
- CPU、内存、swap、PID、墙钟、stdout/stderr 和 RPC payload 上限；
- 只读插件包和独立受管 `/data` 挂载。

禁止挂载 Docker socket、用户主目录、Memoli 根目录、trajectory/state 数据库、宿主
设备或 host namespace。超时、异常退出或协议违规会终止当前后端；不会扩大清理
范围，也不会影响已经提交的其他插件贡献和 SQLite 轨迹。

Observer hook 失败只影响可观测性，不能改变正常回答；Transformer 失败丢弃本次
修改，Policy 在工具副作用前保持 fail-closed。关闭插件时，贡献撤销、事务关闭和
后端 shutdown 相互独立执行，一个步骤失败不会跳过后续清理，并只记录错误类型。

## Broker 边界

容器看不到真实 workspace 和宿主凭证。需要宿主资源时只能发起版本化、有界的
`capability.call`。Broker 依次检查插件身份、manifest 声明、用户批准、系统上限和
参数范围，并只返回必要结果。错误和 trajectory 证据只记录脱敏后的能力名称、状态
和原因，不记录原始 Secret。

JSON-RPC 使用协议版本、请求 ID、插件 ID、method、deadline 和有界 payload；非
JSON stdout、身份不匹配、未知方法、重复响应、过深 JSON、超大消息和超时都会被
拒绝。插件日志只能写 stderr，宿主限长采集。

## 构建 runner 镜像

先取得可信 Python 基础镜像的不可变 digest，再运行：

```powershell
.\docker\plugin-runner\build.ps1 `
  -BaseImage "python@sha256:<64位digest>" `
  -Tag "memoli-plugin-runner:0.1.0"
```

脚本会记录并输出可直接用于本机配置的不可变 `sha256:<image-id>`。生产配置也可
填写镜像仓库返回的完整 `repository@sha256:<manifest-digest>`。Docker daemon 不可用时，协议测试使用
`FakeSandboxBackend`，真实容器测试会显式报告 skip。
