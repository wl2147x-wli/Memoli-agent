## 1. 固化重构基线

- [x] 1.1 统计现有 CLI 模块职责、私有兼容入口和对应测试引用，确认可删除边界
- [x] 1.2 为 interactive/plain 相同命令、普通提示、队列拒绝和退出结果增加等价性回归测试

## 2. 建立共享控制器与适配器合同

- [x] 2.1 定义最小异步 `CLIAdapter` 合同和不含流式重复状态的 `CLIState`
- [x] 2.2 实现 `CLIController`，统一命令执行、空白过滤、队列背压、InboundMessage 发布和 stop 决定
- [x] 2.3 实现极薄 `PlainCLIAdapter`，只负责逐行读取、纯文本写出、EOF 和可注入 I/O
- [x] 2.4 调整 `InteractiveCLIAdapter` 实现相同合同，同时保留补全、history、键位和状态栏

## 3. 收敛生命周期和渲染路径

- [x] 3.1 重写 `run_cli`，只做能力探测、adapter 选择、共享 controller/renderer 装配和有序关闭
- [x] 3.2 合并 interactive/plain 的 Outbound 与 PresentationEvent 消费路径，保持 session/trace 隔离
- [x] 3.3 为 plain renderer profile 保证无 ANSI、无动画、非流式 Provider 单次输出和流式前缀去重
- [x] 3.4 删除旧 `CLICommandRouter`、`_render_outbound`、`_render_presentation`、重复循环和 `streamed_text/tool_step`

## 4. 测试迁移与文档

- [x] 4.1 将旧私有函数测试迁移到 `CLIController`、adapter 和 reducer 的公开边界
- [x] 4.2 验证管道 stdin、重定向 stdout、初始化失败、EOF、`interactive=false` 和本地命令旁路
- [x] 4.3 更新 README、Agent Runtime 和交互 CLI 验证文档，说明 plain 是共享控制器下的最小降级层

## 5. 质量门禁与同步

- [x] 5.1 运行全量 pytest、Ruff、Pyright 和 `git diff --check`
- [x] 5.2 运行 `openspec validate --all --strict` 并同步 `interactive-cli` canonical spec
