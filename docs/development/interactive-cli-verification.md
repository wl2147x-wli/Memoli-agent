# Interactive CLI 验证记录

## 自动化验证

- Windows 2026-08-10，Conda `memoli` / Python 3.11。
- `prompt_toolkit` 虚拟终端覆盖 `/` 候选过滤、别名、Tab/Enter、ghost suggestion、
  多行中文、进程内历史、Ctrl+C、Ctrl+D 和安全历史过滤。
- plain CLI 覆盖管道输入、EOF、本地命令旁路、流式前缀去重和 Echo 端到端。
- AgentLoop 覆盖活动 turn 取消、排队消息顺序和取消后继续处理。
- editable install 已生成 `memoli.exe` 与 `memoli-skills.exe` 两个 console script。
- interactive/plain 已收敛到共享 `CLIController` 与 renderer；plain adapter 仅保留
  逐行 I/O。等价性测试覆盖命令、普通提示、队列拒绝、退出、EOF 和初始化失败降级。
- 圆角输入框覆盖 20/40/80/120 列、40→20 resize、中文宽字符、多行、slash 候选、
  异步 invalidate、busy/queue 快捷提示和 plain 无框降级；实现只使用 prompt_toolkit
  公共 Application/Layout/Buffer/Control API，不产生渲染诊断文件。

复现命令：

```powershell
$env:PYTHONUTF8 = '1'
python -m pytest -q tests/test_interactive_cli.py tests/test_cli_shell.py
python -m ruff check memoli_agent benchmarks tests
python -m pyright
openspec validate --all --strict
```

## 人工终端验收

2026-08-13 在 Windows PowerShell 主机完成自动化交互 smoke：Conda `memoli` / Python
3.11.15，主机初始 Console InputEncoding 为 GB2312、OutputEncoding 为 UTF-8；增强
启动边界会把两个 Windows console code page 切到 65001，失败则 plain 降级。使用
prompt_toolkit pipe input/记录型 Windows Output 验证圆角、青色样式、中文、多行、
候选、resize 和提交结果。推荐 Windows Terminal 使用 Cascadia Mono、Cascadia Code
或其他包含 box-drawing/CJK 字形的字体。

发布前人工检查步骤：

1. 运行 `memoli`，输入 `/` 并检查候选、颜色和键位。
2. 粘贴中文多行提示，在流式输出期间调整窗口宽度。
3. 触发一个工具调用，确认只显示安全工具名、状态和耗时。
4. 运行中输入 `/stop`，再提交下一条消息，确认 Runtime 未退出。
5. 设置 `NO_COLOR=1` 以及 `channels.cli.interactive=false` 验证降级。

当前执行环境没有可用的 Unix 发行版/PTY，Docker Desktop daemon 也未运行，因而
不能把真实 Unix-like PTY 人工验收标记为已完成；虚拟终端回归不冒充人工验收。
