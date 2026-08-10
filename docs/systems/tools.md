# 极简工具系统

Memoli 默认采用参照 GenericAgent 公开 schema 与行为重写的极简工具集。工具仍
实现 Memoli 的显式异步协议，通过 `ToolRegistry` 注册；没有引入 GenericAgent
的反射分发、前端状态或进程内执行。GenericAgent 采用 MIT License。

## 默认工具

Skill Runtime 关闭时，默认模型可见集合固定为九个工具：

| 工具 | 用途 |
| --- | --- |
| `code_run` | 在受限容器中执行 Python；可信宿主模式需显式开启 |
| `file_read` | 按一基行号分页读取 UTF-8 文件 |
| `file_patch` | 唯一精确匹配并替换文本 |
| `file_write` | 显式覆盖、追加或前插文本 |
| `update_working_checkpoint` | 替换当前会话的短期任务便笺 |
| `ask_user` | 以 `needs-user` 暂停并请求用户输入 |
| `start_long_term_update` | 创建 `pending` 的长期整理请求 |
| `time` | 查询本地和 UTC 时间 |
| `memory_recall` | 检索已有长期记忆 |

旧工具迁移关系：

- `filesystem_read` 改用 `file_read`。
- `calculator` 改用 `code_run` 执行 Python。
- `memory_write` 不再默认暴露；未经处理的轨迹不能直接成为长期事实。
- `spawn_subagent` 设置 `tools.subagent_tool_enabled = true` 后才附加注册。

工具数量很小时不启用主动发现，`tool_search_enabled` 默认关闭。MCP 或插件工具
规模增长后的按需发现应由独立 OpenSpec change 设计。

启用 `[skills].enabled=true` 且 Skill Registry 装配成功时，额外注册第十个只读
工具 `skill_load(name, reference?)`。它对应 GenericAgent 的 L1 紧凑目录与 L3
按需全文注入模式：Catalog 负责选择，Tool Result 负责固定版本说明。它不执行脚本、
不管理版本，也不扩大其他九个工具的权限。`related_sop` 仍只是 Working State 提示，
只有成功 `skill_load` 才在轨迹中计为 Skill 使用。

## 文件边界

三个文件工具共享同一 workspace 解析器。相对路径以 workspace 为根，绝对路径、
符号链接或 junction 解析后的目标也必须仍在 workspace 内。第一阶段只处理 UTF-8
普通文件，目标父目录必须已经存在。

`file_patch` 不会修正模型参数中的空白、缩进、Unicode 引号或换行；
`old_content` 出现零次或多次都会失败。`file_write.content` 必须显式出现在工具
参数中，不会从 Assistant 普通回复或代码块提取内容。

## 代码执行边界

`code_run` 默认使用 `tools.code_runner = "container"`。容器镜像必须固定到 digest，
默认禁网、只读根文件系统、非 root、cap-drop、no-new-privileges，并限制 CPU、内存、
PID、执行时间和输出；只挂载配置的 workspace。镜像运行期不能安装任意依赖。

容器后端不可用时不会退回宿主执行，而是返回明确 unavailable。默认容器 profile 只
执行 Python；PowerShell 仅允许显式 `trusted-host`。trusted-host 必须配置绝对且存在
的 Python 解释器路径，不能隐式采用 Runtime 的 `sys.executable`。`disabled` 会完全
关闭执行。字符串级 `allow_network` 扫描仅是辅助检查，不构成安全沙箱。

```toml
[tools]
code_runner = "container" # container / trusted-host / disabled
code_container_cli = "docker"
code_container_image = "registry.example/memoli-code-runner@sha256:<digest>"
code_allow_network = false
code_memory_mb = 256
code_cpus = 0.5
code_pids = 64
```

开发镜像脚本位于 `docker/code-runner/`。示例中的全零 digest 是 fail-safe 占位符，
部署前必须用实际构建并验证的 digest 替换。

## 可选浏览器工具

`web_scan` 和 `web_execute_js` 依赖同一个 `BrowserAdapter`，只在
`tools.browser_enabled = true` 且 adapter 可用时成对注册。当前核心 Runtime 不
绑定 Playwright、MCP 或其他具体浏览器后端。保存 JavaScript 长结果时仍使用同一
workspace 文件边界。

## 原始轨迹与后处理

在线 Runtime 只保存客观事实：模型可见 schema、tool call id、模型原始参数、
实际执行参数、时序、错误、完整脱敏输出和返回模型的有界输出。副作用工具执行前
先提交意图；必需轨迹写入失败时不执行副作用。

原始事件不包含 reward、Rubric、成功标签、正确工具标签、失败归因或 SFT/RL
标签，也不会自动进入 Memory、Evolution 或 Post-training。轨迹清洗、评价和训练
样本生成必须从 SQLite 只读副本派生，并保持原始事件不变。
