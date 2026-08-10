# Memoli-agent 测试方案

> 生成日期：2026-08-09
> 项目版本：0.1.0
> 目标：覆盖 memoli-agent 已有的所有功能模块，验证正确性并发现潜在 bug

---

## 一、测试环境前置条件

| 项目 | 要求 |
|------|------|
| Python | ≥ 3.11（当前系统 **未安装**，见阻塞项 #1） |
| 依赖安装 | `pip install -e ".[dev]"` |
| LLM API | 需要有效的 DeepSeek API Key（config.toml 中已配置） |
| Docker | 插件沙箱测试需要（标记为 `container`，可选） |
| SQLite | Python 3.11 标准库自带 |

### 测试执行命令

```bash
# 安装项目
pip install -e ".[dev]"

# 运行全部测试（排除 Docker 测试）
pytest -v

# 运行全部测试（包含 Docker 测试）
pytest -v -m ""

# 运行特定模块测试
pytest tests/test_reasoner_loop.py -v
pytest tests/test_evidence_memory.py -v

# 运行代码质量检查
ruff check .
pyright
```

---

## 二、按模块测试方案

### 2.1 配置系统（`bootstrap/config.py`）

**测试文件**: `tests/test_runtime_config.py`（已存在）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.1.1 | 加载完整 config.toml | `config.toml` | 所有字段正确解析为 dataclass | P0 |
| 2.1.2 | 加载最小 config.toml | 仅 `[runtime]` 和 `[llm]` | 其余字段使用默认值 | P0 |
| 2.1.3 | 缺失必填字段 | 无 `api_key` 的 openai-compatible | `__post_init__` 验证失败 | P0 |
| 2.1.4 | 环境变量覆盖 | `MEMOLI_LLM_API_KEY=xxx` | 环境变量优先于 TOML | P1 |
| 2.1.5 | 非法枚举值 | `provider = "unknown"` | 抛出验证错误 | P0 |
| 2.1.6 | 数值边界 | `max_iterations = 0` | 验证失败或默认值 | P1 |
| 2.1.7 | 嵌入配置验证 | `embedding.enabled=true` 但无 API key | 验证失败或降级 | P1 |
| 2.1.8 | 混合检索权重 | `keyword_weight=0, semantic_weight=0, metadata_weight=0` | 验证失败或降级 | P2 |

### 2.2 应用运行时装配（`bootstrap/app.py`）

**测试文件**: 无专用测试（需新建）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.2.1 | 完整 runtime 构建 | 完整 AppConfig | 所有组件正确初始化，无 None 依赖 | P0 |
| 2.2.2 | 最小 runtime 构建 | 仅必要配置 | 可选组件为 None | P0 |
| 2.2.3 | memory disabled | `memory.enabled=false` | `memory_runtime` 为 None，工具注册不含 memory 工具 | P1 |
| 2.2.4 | subagent disabled | `subagent_tool_enabled=false` | 不注册 spawn/manage_subagent 工具 | P1 |
| 2.2.5 | proactive disabled | `proactive.enabled=false` | `proactive_loop` 为 None | P2 |
| 2.2.6 | mcp disabled | `mcp.enabled=false` | `mcp_manager` 为 None | P2 |
| 2.2.7 | provider 选择 | `provider="echo"` | 使用 EchoProvider | P0 |
| 2.2.8 | fallback provider | `provider="openai-compatible"` | fallback_provider 为 EchoProvider | P1 |

### 2.3 消息总线（`bus/queue.py`）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.3.1 | 入站消息发布 | InboundMessage | 从 inbound 队列可取出 | P0 |
| 2.3.2 | 出站消息发布 | OutboundMessage | 从 outbound 队列可取出 | P0 |
| 2.3.3 | 空队列等待 | 无消息 | `await` 阻塞直到有消息 | P1 |
| 2.3.4 | session_key 计算 | 不同 session_id | 正确生成 session_key | P2 |

### 2.4 AgentLoop（`agent/loop.py`）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.4.1 | 消息消费循环 | 入站消息 | 正确路由到 runner | P0 |
| 2.4.2 | 出站消息发布 | runner 结果 | 发布到 outbound 队列 | P0 |
| 2.4.3 | maintenance tick | 配置了 maintenance | 每轮后调用 maintenance | P1 |
| 2.4.4 | 优雅停止 | stop() | 循环退出，无资源泄漏 | P0 |

### 2.5 推理循环（`agent/core/reasoner.py`）

**测试文件**: `tests/test_reasoner_loop.py`（已存在）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.5.1 | 单工具调用 | 1 次工具调用后完成 | `COMPLETED` | P0 |
| 2.5.2 | 多工具轮次 | 3 次工具调用后完成 | `COMPLETED`，所有工具执行 | P0 |
| 2.5.3 | ask_user 终止 | 工具=ask_user | `NEEDS_USER` | P0 |
| 2.5.4 | provider fallback | 主 provider 抛异常 | 回退到 EchoProvider | P0 |
| 2.5.5 | 完成重试 | 空响应 | 自动重试 | P1 |
| 2.5.6 | 迭代预算耗尽 | 达到 max_iterations | `BUDGET_EXHAUSTED` | P0 |
| 2.5.7 | 时间预算耗尽 | 超过 max_elapsed_seconds | `BUDGET_EXHAUSTED` | P1 |
| 2.5.8 | 无进度检测 | 连续相同工具调用 | 达到 no_progress_limit 后终止 | P0 |
| 2.5.9 | 进度指纹 | 不同工具序列 | 指纹不同 | P1 |
| 2.5.10 | 轨迹优先 | 工具执行前记录 | 事件顺序正确 | P0 |
| 2.5.11 | 轨迹写入失败 | trajectory_store 抛异常 | 终止操作 | P0 |

### 2.6 PassiveTurnPipeline（`agent/core/passive_turn.py`）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.6.1 | 6 阶段顺序执行 | 正常用户消息 | BeforeTurn → BeforeReasoning → PromptRender → Reasoner → AfterReasoning → AfterTurn | P0 |
| 2.6.2 | Hook 集成 | 每个阶段 | HookBus 对应事件被触发 | P0 |
| 2.6.3 | 记忆预召回 | auto_recall=true | 在 BeforeReasoning 阶段调用 pre_recall | P1 |
| 2.6.4 | 记忆禁用 | auto_recall=false | 跳过 pre_recall | P1 |
| 2.6.5 | 工作状态注入 | working_memory.enabled=true | ContextBuilder 包含 working block | P1 |

### 2.7 LLM Provider（`agent/provider.py`）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.7.1 | EchoProvider | 任意消息 | 返回固定回声 | P0 |
| 2.7.2 | OpenAICompatibleProvider | 合法请求 | 返回 LLMResponse | P0 |
| 2.7.3 | API Key 无效 | 错误 api_key | 抛出认证错误 | P0 |
| 2.7.4 | 网络超时 | 不可达 base_url | 超时错误 | P1 |
| 2.7.5 | 工具调用解析 | function_call 响应 | ToolCall 正确解析 | P0 |
| 2.7.6 | 线程池执行 | 并发请求 | 不阻塞 asyncio 事件循环 | P1 |
| 2.7.7 | 重试机制 | 429/5xx 响应 | 自动重试 | P2 |

### 2.8 会话管理（`agent/session.py`）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.8.1 | 历史窗口 | 超过 history_window 条消息 | 旧消息被裁剪 | P0 |
| 2.8.2 | 多会话隔离 | 不同 session_id | 历史独立 | P0 |
| 2.8.3 | 空会话 | 新 session_id | 返回空历史 | P1 |

### 2.9 ContextBuilder（`agent/context.py`）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.9.1 | 完整 prompt 组装 | system + memory + working + history + user | 各部分正确拼接 | P0 |
| 2.9.2 | 无记忆块 | memory=None | 不包含 memory block | P1 |
| 2.9.3 | 无工作状态 | working=None | 不包含 working block | P1 |
| 2.9.4 | 空历史 | [] | 不包含历史消息 | P1 |

### 2.10 证据化记忆系统（`agent/memory/`）

**测试文件**: `tests/test_evidence_memory.py`（已存在）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.10.1 | Claim 追加 | content + evidence + scope | 成功写入，状态=candidate | P0 |
| 2.10.2 | Claim 去重 | 相同 content | 不重复写入 | P0 |
| 2.10.3 | Claim 生命周期 | candidate → active → approved → frozen | 状态转换正确 | P0 |
| 2.10.4 | Claim 关系 | supports/corrects/contradicts | 关系正确建立 | P1 |
| 2.10.5 | Card 投影 | 多条 approved claims | 自动生成/更新卡片 | P0 |
| 2.10.6 | Card 版本化 | 更新 claim | Card 新版本生成 | P1 |
| 2.10.7 | Episode 投影 | 完成的 trace | 生成 trajectory segment | P1 |
| 2.10.8 | FTS5 检索 | 关键词查询 | 返回匹配 claims | P0 |
| 2.10.9 | CJK n-gram | 中文查询 | 正确分词和匹配 | P0 |
| 2.10.10 | 混合 RRF 检索 | 多通道结果 | RRF 分数正确计算 | P0 |
| 2.10.11 | 类型配额 | 超过 card_limit | 按配额裁剪 | P1 |
| 2.10.12 | 溢出顺序 | recall_chars 超限 | 按溢出顺序裁剪 | P1 |
| 2.10.13 | 核心卡片注入 | 核心卡片 | 始终出现在 prompt 中 | P0 |
| 2.10.14 | 记忆整理 | consolidation run | 候选提取+幂等性 | P1 |
| 2.10.15 | Legacy 迁移 | MEMORY.md | 预览→导入→备份 | P1 |
| 2.10.16 | 语义索引 | embedding enabled | 索引任务正确排队 | P2 |
| 2.10.17 | maintenance tick | 定期调用 | 过期 claim 处理、索引作业 | P1 |

### 2.11 混合检索（`agent/memory/hybrid.py`）

**测试文件**: `tests/test_memory_hybrid_indexing.py`（已存在）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.11.1 | 三通道 RRF | keyword + semantic + metadata | 合并排序正确 | P0 |
| 2.11.2 | FTS5 不可用 | 无 FTS5 | 降级为 LIKE | P0 |
| 2.11.3 | 语义通道禁用 | embedding disabled | 仅 keyword + metadata | P1 |
| 2.11.4 | 权重配置 | 不同权重 | RRF 分数反映权重 | P1 |
| 2.11.5 | 空结果 | 无匹配 | 返回空列表 | P0 |
| 2.11.6 | 单通道结果 | 仅 keyword 有结果 | 正确返回 | P1 |

### 2.12 轨迹存储（`agent/trajectory.py`）

**测试文件**: `tests/test_trajectory_store.py`（已存在）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.12.1 | Trace 创建 | start_trace | trace_id 生成 | P0 |
| 2.12.2 | Span 创建 | start_span | span_id 生成，关联 trace | P0 |
| 2.12.3 | Event 记录 | record_event | 事件按序存储 | P0 |
| 2.12.4 | Payload 存储 - inline | <64KB | 内联存储 | P0 |
| 2.12.5 | Payload 存储 - zlib | 64KB-4MB | zlib 压缩 | P1 |
| 2.12.6 | Payload 存储 - external | >4MB | 外置文件 | P2 |
| 2.12.7 | 敏感键脱敏 | api_key=xxx | 值被替换为 *** | P0 |
| 2.12.8 | 隐藏推理键 | reasoning=xxx | 值被替换为 *** | P0 |
| 2.12.9 | JSONL 导出 | trace_id | 完整导出 | P1 |
| 2.12.10 | 内容捕获模式 | metadata-only | 不记录 payload | P1 |

### 2.13 工作记忆（`agent/working/`）

**测试文件**: `tests/test_dynamic_working_status.py`（已存在）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.13.1 | Checkpoint 创建 | WorkingCheckpoint | 写入 SQLite | P0 |
| 2.13.2 | Checkpoint 读取 | revision=1 | 返回正确数据 | P0 |
| 2.13.3 | Patch 更新 | CheckpointPatch | 合并更新 | P0 |
| 2.13.4 | Revision 冲突 | 过期 revision | 抛出冲突错误 | P0 |
| 2.13.5 | RuntimeStatus 投影 | 迭代后 | 状态正确更新 | P1 |
| 2.13.6 | XML 渲染 | WorkingStateRenderResult | 生成 `<agent_status>` 块 | P1 |
| 2.13.7 | stale_policy=mark | 过期 checkpoint | 标记为 stale | P1 |

### 2.14 工具注册与执行（`agent/tools/`）

**测试文件**: `tests/test_generic_tools.py`（已存在）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.14.1 | FileRead | 正常文件 | 返回内容 | P0 |
| 2.14.2 | FileRead 行分页 | offset + limit | 返回指定行范围 | P1 |
| 2.14.3 | FileRead 大文件 | 超过 max_lines | 截断 | P1 |
| 2.14.4 | FileWrite 创建 | 新文件 | 成功写入 | P0 |
| 2.14.5 | FileWrite 追加 | mode=append | 追加到末尾 | P0 |
| 2.14.6 | FileWrite 前插 | mode=prepend | 插入到开头 | P1 |
| 2.14.7 | FilePatch | old_string → new_string | 精确替换 | P0 |
| 2.14.8 | FilePatch 不唯一 | 多处匹配 | 失败 | P0 |
| 2.14.9 | FilePatch 不存在 | old_string 不在文件中 | 失败 | P0 |
| 2.14.10 | CodeRun Python | python 代码 | 正确执行 | P0 |
| 2.14.11 | CodeRun 超时 | 死循环 | 超时终止 | P0 |
| 2.14.12 | CodeRun 输出截断 | 超长输出 | 截断到 max_output_chars | P1 |
| 2.14.13 | CodeRun 网络检测 | socket 调用 | 检测并警告 | P1 |
| 2.14.14 | 工具搜索 | tool_search_enabled=true | 按关键词查找工具 | P2 |
| 2.14.15 | Workspace 限制 | 越界路径 | 拒绝访问 | P0 |
| 2.14.16 | 符号链接限制 | symlink 到 workspace 外 | 拒绝访问 | P0 |

### 2.15 控制工具（`agent/tools/control.py`）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.15.1 | UpdateWorkingCheckpoint | patch 参数 | 成功更新 | P0 |
| 2.15.2 | UpdateWorkingCheckpoint 冲突 | 过期 revision | 返回冲突错误 | P0 |
| 2.15.3 | AskUser | 问题文本 | 设置 needs_user 标志 | P0 |
| 2.15.4 | StartLongTermUpdate | 请求内容 | 创建待处理请求 | P1 |
| 2.15.5 | Time | 无参数 | 返回本地和 UTC 时间 | P2 |
| 2.15.6 | MemoryRecall | 查询文本 | 返回检索结果 | P0 |
| 2.15.7 | MemoryRecall 过滤 | scope/sensitivity/status | 结果符合过滤条件 | P1 |
| 2.15.8 | MemoryManage | remember/correct/freeze/forget | 治理操作正确 | P0 |

### 2.16 浏览器工具（`agent/tools/browser.py`）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.16.1 | WebScan | URL | 返回简化页面内容 | P1 |
| 2.16.2 | WebExecuteJS | JS 代码 | 执行并返回结果 | P1 |
| 2.16.3 | 无 adapter | browser_enabled=true 但无 adapter | 工具不可用 | P0 |

### 2.17 插件系统（`agent/plugins/`）

**测试文件**: `tests/test_plugin_*.py`（已存在）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.17.1 | HookBus 分发 | 事件 | 正确分发到注册 hook | P0 |
| 2.17.2 | Transformer hook | 修改载荷 | 载荷被修改 | P0 |
| 2.17.3 | Policy hook - 允许 | 返回 allow | 操作继续 | P0 |
| 2.17.4 | Policy hook - 拒绝 | 返回 deny | 操作被阻止 | P0 |
| 2.17.5 | Policy hook - 错误 | hook 抛异常 | fail-closed（拒绝） | P0 |
| 2.17.6 | Observer hook | 观察事件 | 不影响主流程 | P0 |
| 2.17.7 | Observer hook 错误 | hook 抛异常 | 仅记录，不阻塞 | P0 |
| 2.17.8 | Manifest 解析 | 合法 manifest | 正确加载 | P0 |
| 2.17.9 | Manifest 验证 | 非法 manifest | 加载失败 | P0 |
| 2.17.10 | PluginManager 加载 | enabled 列表 | 按序加载 | P0 |
| 2.17.11 | 事务性注册 | 注册失败 | 回滚 | P1 |
| 2.17.12 | Sandbox 隔离 | force_sandbox=true | Docker 容器运行 | P1 |
| 2.17.13 | Sandbox 资源限制 | 256MB/0.5CPU/32PIDs | 超限被 kill | P2 |
| 2.17.14 | RPC 协议 | 请求/响应 | 正确序列化 | P0 |
| 2.17.15 | hook_deadline_seconds | 超时 | 超时处理 | P1 |
| 2.17.16 | 内置插件 memory_default | TURN_AFTER | 观察事件 | P1 |
| 2.17.17 | 内置插件 shell_safety | TOOL_BEFORE | 阻止危险路径 | P0 |

### 2.18 子Agent 系统（`agent/subagent/`）

**测试文件**: `tests/test_subagent_graph.py`（已存在）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.18.1 | 任务创建 | description + profile | 状态=PENDING | P0 |
| 2.18.2 | 依赖调度 | A → B → C | 按序执行 | P0 |
| 2.18.3 | 循环检测 | A → B → A | 检测到循环并拒绝 | P0 |
| 2.18.4 | 状态转换 | PENDING → COMPLETED | 转换合法 | P0 |
| 2.18.5 | 非法状态转换 | COMPLETED → RUNNING | 拒绝 | P0 |
| 2.18.6 | 后台执行 | spawn_background() | 立即返回 task_id | P1 |
| 2.18.7 | 完成事件 | 任务完成 | 发布 InboundMessage | P1 |
| 2.18.8 | 取消任务 | cancel() | 状态=CANCELLED | P0 |
| 2.18.9 | 恢复任务 | resume() | 状态=RUNNABLE | P1 |
| 2.18.10 | 并发限制 | max_concurrent=2 | 最多 2 个并行 | P0 |
| 2.18.11 | Profile 工具集 | research/coding/general | 不同工具访问权限 | P1 |
| 2.18.12 | 深度限制 | max_depth=1 | 嵌套超过限制被拒绝 | P1 |

### 2.19 主动循环（`agent/proactive/`）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.19.1 | 周期性 tick | interval_seconds=60 | 每 60 秒触发一次 | P0 |
| 2.19.2 | 冷却时间 | cooldown_seconds=300 | 冷却期内不触发 | P0 |
| 2.19.3 | Sensor 读取 | 状态 | 返回最小状态 | P1 |
| 2.19.4 | Decision 逻辑 | 冷却期内 | 不行动 | P0 |
| 2.19.5 | 消息注入 | action | 发布 InboundMessage | P0 |
| 2.19.6 | 启停 | start()/stop() | 正确启动和停止 | P0 |

### 2.20 MCP 集成（`agent/mcp/`）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.20.1 | 客户端连接 | stdio 服务器 | 成功连接 | P0 |
| 2.20.2 | 工具发现 | 服务器声明工具 | 注册为 `mcp__{server}__{tool}` | P0 |
| 2.20.3 | 工具调用 | MCP 工具 | 正确转发和返回 | P0 |
| 2.20.4 | 多服务器 | 多个 MCP 配置 | 独立连接 | P1 |
| 2.20.5 | 服务器断连 | 服务器关闭 | 错误处理 | P1 |
| 2.20.6 | 关闭清理 | close_all() | 所有连接关闭 | P0 |

### 2.21 CLI 通道（`channels/cli.py`）

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.21.1 | 标准输入 | 用户消息 | 发布为 InboundMessage | P0 |
| 2.21.2 | 标准输出 | OutboundMessage | 打印到 stdout | P0 |
| 2.21.3 | 优雅退出 | Ctrl+C / EOF | 正确停止 | P0 |

### 2.22 端到端集成测试

| # | 测试项 | 输入 | 预期结果 | 优先级 |
|---|--------|------|----------|--------|
| 2.22.1 | 完整对话流程 | 用户消息 | EchoProvider 返回响应 | P0 |
| 2.22.2 | 记忆查询流程 | "记住我叫小明" → "我叫什么？" | 正确召回 | P0 |
| 2.22.3 | 工具调用流程 | 需要文件操作的请求 | 工具正确执行 | P0 |
| 2.22.4 | 轨迹记录 | 完整对话 | trace/span/event 完整 | P0 |
| 2.22.5 | 工作状态更新 | 多轮对话 | checkpoint 正确更新 | P1 |
| 2.22.6 | 子Agent 委派 | spawn_subagent | 后台执行并返回结果 | P1 |
| 2.22.7 | 插件拦截 | shell_safety 阻止 | 危险操作被拒绝 | P0 |

---

## 三、基准测试

| # | 测试项 | 说明 | 优先级 |
|---|--------|------|--------|
| 3.1 | LoCoMo 数据集 | 长对话记忆评估 | P1 |
| 3.2 | LongMemEval 数据集 | 长期记忆评估 | P1 |
| 3.3 | Agent 适配器 | Memoli/HTTP/CLI/Python | P1 |
| 3.4 | 指标计算 | 准确率/召回率 | P1 |
| 3.5 | 报告生成 | Markdown 报告 | P2 |

---

## 四、代码质量检查

| # | 检查项 | 命令 | 优先级 |
|---|--------|------|--------|
| 4.1 | Ruff lint | `ruff check .` | P0 |
| 4.2 | Pyright 类型检查 | `pyright` | P0 |
| 4.3 | Import 排序 | `ruff check --select I .` | P1 |
| 4.4 | 未使用导入 | `ruff check --select F401 .` | P1 |

---

## 五、测试结果记录模板

| 测试项 | 状态 | 实际结果 | 备注 |
|--------|------|----------|------|
| 2.1.1 | ⬜ 待执行 | | |
| ... | | | |

状态说明：
- ✅ 通过
- ❌ 失败
- ⚠️ 部分通过
- ⬜ 待执行
- 🚫 阻塞（环境问题）

---

## 六、执行优先级说明

- **P0**：核心功能，必须通过
- **P1**：重要功能，应当通过
- **P2**：辅助功能，尽量通过

建议执行顺序：
1. 先解决环境阻塞问题（Python 安装）
2. 安装依赖并运行 `pytest -v`
3. 执行 P0 测试项
4. 执行 P1 测试项
5. 执行 P2 测试项
6. 执行基准测试
7. 执行代码质量检查
