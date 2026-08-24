# Windows CLI 输入框验收记录

变更：`polish-windows-cli-input-frame`

验收日期：2026-08-13

## 环境

- Windows PowerShell 主机
- Conda：`D:\software\miniconda\envs\memoli\python.exe`
- Python 3.11.15
- 主机初始 Console InputEncoding：GB2312（CP936）
- 主机初始 Console OutputEncoding：UTF-8（CP65001）
- 增强 CLI 启动时调用 Windows Console API 将输入/输出 code page 设为 65001；失败时降级 plain。

Windows Terminal 推荐使用 Cascadia Mono、Cascadia Code 或其他同时包含 box-drawing 与 CJK 字形的字体。

## 实现证据

- 输入区通过 prompt_toolkit 公共 `Application`、`Layout`、`Buffer`、container、control 和 completion menu API 实现。
- 未 monkey-patch prompt_toolkit 内部类，未读取 renderer 私有 screen，未生成 `_render_debug.log`。
- 青色圆角单线框标题固定为左侧“输入”，正文左右各保留一列 padding。
- idle 显示 `Enter 发送 · Esc+Enter 换行 · / 命令`；busy/queue 状态优先且内容有界。
- plain CLI 不输出边框或 ANSI，命令、提交、历史、排队和取消语义不变。

## 自动化结果

- `tests/test_interactive_cli.py`：`23 passed`。
- 影响面 Ruff：`All checks passed!`。
- 影响面 Pyright：`0 errors, 0 warnings, 0 informations`。
- change strict validation：通过。
- `openspec validate --all --strict`：`21 passed, 1 failed`；唯一失败为独立未完成 change `refine-memory-driven-system-prompt`。

覆盖内容包括 20/40/80/120 列、40→20 resize、中文宽字符、多行、自动折行、slash 候选、Tab/Enter、ghost suggestion、历史、Ctrl+C/Ctrl+D、异步 invalidate、busy/queue、生命周期和 plain fallback。

## 兼容与回滚

- 无配置、数据库、工具 schema 或持久化迁移。
- 非 TTY、禁用 interactive、UTF-8 初始化失败或增强 adapter 初始化失败时仍走 plain CLI。
- 回滚只需恢复原 PromptSession 输入布局；Runtime、Session、Provider、命令和数据无需回滚。

## 验收清单

- [x] 圆角、标题、青色样式和快捷提示合同已测试。
- [x] Windows 编码前提和 plain 降级已记录。
- [x] CJK、多行、窄窗口、resize、候选和异步恢复已回归。
- [x] 原有输入、补全、历史、取消和 EOF 行为保持。
- [x] 主规格和运行文档已同步。
- [x] 本 change 具备归档条件，本记录不自动归档。
