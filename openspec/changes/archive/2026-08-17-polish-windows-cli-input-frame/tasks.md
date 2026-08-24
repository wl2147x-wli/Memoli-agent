## 1. 稳定基线与布局合同

- [x] 1.1 为现有输入、补全、历史、多行、Ctrl+C/Ctrl+D 和 plain 降级补充不改变语义的基线断言
- [x] 1.2 定义输入框颜色、圆角字符、标题、最小宽度和快捷提示的可测试表现合同

## 2. 公共 prompt_toolkit 输入框实现

- [x] 2.1 使用公共 `Application`、layout container、control 和 Buffer API 构建带标题的输入区，不 monkey-patch prompt_toolkit 内部实现
- [x] 2.2 实现青色 `╭─ 输入 ─…─╮`、左右边框和底边，并为正文保留稳定内边距与可见光标
- [x] 2.3 将现有 Completer、AutoSuggest、History、KeyBindings、候选菜单和 bottom toolbar 接入新布局
- [x] 2.4 保持 `patch_stdout`、异步 renderer、busy/queue invalidate 和关闭生命周期稳定，不创建渲染诊断文件

## 3. Windows 与边界验证

- [x] 3.1 增加 20/40/80/120 列虚拟终端与 resize 测试，验证四角、标题和水平线不越界
- [x] 3.2 增加中文宽字符、多行、自动折行、slash 候选、ghost suggestion 和异步输出后的边框/光标恢复测试
- [x] 3.3 验证非 TTY、DummyOutput 或增强初始化失败仍使用无 ANSI/无边框的 plain 路径
- [x] 3.4 在 Windows PowerShell 下执行交互 smoke，记录 PowerShell/Windows Terminal、字体和编码前提及结果
- [x] 3.5 修复 slash 候选菜单的上下方向键优先级，并增加虚拟终端选择与提交回归测试
- [x] 3.6 将已提交输入持久显示到滚动区，修复 Rich 标签泄漏和终端宽度错配，并增加异步重绘回归测试
- [x] 3.7 禁止无换行流式片段直接 flush，按完整 Outbound 渲染 Markdown，并将历史输入保留为静态圆角输入框
- [x] 3.8 在提交后擦除 prompt_toolkit 临时 live 输入区，确保滚动区每轮仅保留一个静态历史输入框

## 4. 轻量体验与文档

- [x] 4.1 在 idle 状态显示 `Enter 发送 · Esc+Enter 换行 · / 命令`，busy/queue 时优先展示真实状态且保持内容有界
- [x] 4.2 更新 Interactive CLI/Agent Runtime 文档，说明输入框、键位、终端兼容与 plain 降级

## 5. 验收与规格同步

- [x] 5.1 使用 `D:\software\miniconda\envs\memoli\python.exe` 运行相关 pytest、Ruff 和 Pyright 并修复本 change 问题
- [x] 5.2 运行 change strict validation 与 `openspec validate --all --strict`，记录其他独立 change 的既有失败
- [x] 5.3 同步 `openspec/specs/interactive-cli`，完成验收证据并确认具备归档条件
