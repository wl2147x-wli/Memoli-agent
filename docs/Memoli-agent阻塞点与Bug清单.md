# Memoli-agent 阻塞点与 Bug 清单

> 生成日期：2026-08-09
> 最近验证：2026-08-09（conda memoli 环境，Python 3.11.15）
> 项目版本：0.1.0
> 文档状态：**已实施清理后的权威状态；下方逐项原始描述保留为历史审计证据**
> 验证环境：conda memoli 环境，Python 3.11.15，pytest 9.1.1，ruff 0.12.7，pyright 1.1.411

---

## 0. 2026-08-09 实施结果

本轮已完成 Runtime/Trajectory、Memory、MCP、Proactive、插件故障隔离和内置代码执行
安全边界的实现与回归。除需要真实 Docker daemon 的固定 digest 镜像构建外，计划内
代码项均已完成。下方旧条目中的“已确认/建议修复”描述表示修复前审计结论，不再表示
当前代码状态。

### 状态总表

| 状态 | 条目 | 结论与证据 |
|---|---|---|
| 已修复 | #1–#8、#10–#16、#18–#26、#29–#32、#34–#35、#42、#44–#45、#49–#60、#62–#66 | 对应回归位于 `test_reasoner_loop.py`、`test_agent_loop.py`、`test_trajectory_store.py`、`test_evidence_memory.py`、`test_mcp_runtime.py`、`test_generic_tools.py`、`test_proactive_loop.py` 和 `test_runtime_integration.py`。 |
| 已关闭/设计选择 | #9、#17、#27–#28、#33、#36–#37、#41、#43、#48、#61、#68–#69 | 属于误报、已存在保护、稳定排序/降级策略或已由 Provider Runtime 解决；不按旧建议改动。 |
| 基准验证通过 | #38–#40 | 中文、英文和中英混合检索回归均通过，未在无失败证据时重写 n-gram 分词器。 |
| P2 性能债务 | #46–#47、#67 | 当前默认单并发；保留同步 SQLite 和串行 MCP，待延迟预算基准超标后另建 change。 |
| 外部环境待验收 | #64–#65 的真实容器验收 | `code_run` 已默认容器、无宿主回退；Docker daemon 当前不可连接，固定 digest 镜像尚未真实构建。 |

补充说明：#25 的导出现在包含当前 Card 和 Claim，Episode 仍作为 trajectory 派生数据，
默认不进入个人记忆导出；#31 已扩展为字段与值级递归脱敏；#33 通过显式事务和双连接
回归验证；#36 保持类型、时间、稳定 ID 的确定性排序；#48 的语义 lane 异常继续受控
降级并输出诊断；#63 的误导性空 `checkpoints` 属性已移除。

### 安全状态

- 安全 #1：仓库示例使用 `${MEMOLI_LLM_API_KEY}`，轨迹执行值级脱敏。本机未跟踪的
  `config.toml` 仍检测到字面量 key，必须由用户改为环境变量；任何曾暴露的 key 必须
  在服务商侧立即轮换，代码无法代替该外部操作。
- 安全 #2：MCP 规范化工具名碰撞会报告双方原始来源并回滚整批初始化，不再静默覆盖。
- 插件 Observer 故障不改变回答，Policy 故障在工具副作用前 fail-closed；关闭步骤
  相互隔离，一个失败不会跳过后端 shutdown 或其他插件。
- 内置 `code_run` 默认禁网、非 root、只读根文件系统、受 CPU/内存/PID/时间/输出
  限制；Docker 不可用时明确 unavailable，绝不回退到宿主执行。

### 测试、质量与环境结论

| 门禁 | 最终结果 |
|---|---|
| `python -m pytest -q` | **214 passed / 6 skipped / 0 failed**（15.70s） |
| `python -m ruff check memoli_agent benchmarks tests` | All checks passed |
| `python -m pyright` | 0 errors / 0 warnings |
| `openspec validate --all --strict` | 通过 |

6 个 skip 中，2 个是真实 Provider smoke（需显式环境开关），3 个是当前 Windows 账户
无法创建符号链接，1 个是 Docker daemon 不可用的真实容器测试。缺口 #1–#7 均已有
直接或端到端覆盖。环境 #70、#71 由 `scripts/test.ps1` 在 workspace 内创建唯一临时
目录并设置 UTF-8；#72 已关闭，Pyright 当前为 0 error。

### 关联 OpenSpec

- 已归档：`harden-agent-loop-and-trajectory`、`harden-memory-integrity-and-retrieval`、
  `harden-mcp-lifecycle-and-registry`、`complete-runtime-integration-and-proactive-safety`。
- 实施中：`sandbox-built-in-code-execution`（7/8，仅缺真实镜像构建）；
  `build-plugin-hooks-and-sandbox`（74/75，仅缺同类固定 digest runner 镜像构建）。
- 母路线图：`design-lifelong-agent-evolution` 只登记承接关系，不混入具体 Bug 修复。

---

## 一、环境阻塞项

### 阻塞 #1：Python 未安装（已解决）

- **状态**: ✅ 已解决（conda memoli 环境）
- **描述**: 原问题为 Windows 系统未安装 Python 3.11+。现已通过 conda `memoli` 环境解决，Python 3.11.15 可用。
- **验证命令**: `D:/software/miniconda/envs/memoli/python.exe --version` → Python 3.11.15
- **备注**: 使用 `conda run -n memoli` 在 Windows 上有 Unicode GBK 编码问题，建议直接使用 `D:/software/miniconda/envs/memoli/python.exe` 执行。pytest 临时目录有权限问题，需使用 `--basetemp` 参数指定自定义临时目录。

### 阻塞 #2：DeepSeek API Key 有效性（已验证）

- **状态**: ✅ 已验证有效
- **描述**: `config.toml` 中配置的 DeepSeek API Key 已通过实际 API 调用验证，可以正常使用。
- **验证结果**: 使用 `openai` 库调用 `https://api.deepseek.com` 成功返回响应。

---

## 二、致命 / 高严重性 Bug

### Bug #1：Reasoner 中 `tool_call_id` 不一致导致对话历史损坏

- **严重性**: 🔴 致命
- **文件**: `memoli_agent/agent/core/reasoner.py`
- **行号**: ~826 vs ~397
- **描述**: `_assistant_tool_call_message` 方法生成的工具调用 ID 格式为 `call_{index}_{name}`，而主工具执行循环生成的 ID 格式为 `call_{iteration}_{index}`。当模型不提供自己的 `tool_call.id` 时，助手消息中的 ID（如 `call_0_read_file`）与工具结果消息中的 ID（如 `call_3_0`）永远不匹配。
- **影响**:
  - 下游 OpenAI-compatible provider 如果验证 `tool_call_id` 一致性，会拒绝对话
  - 即使宽松的 provider 也会静默丢失助手工具调用与结果的关联
  - 对话历史被损坏，后续推理可能失败
- **代码片段**:
  ```python
  # _assistant_tool_call_message (line ~826):
  "id": tool_call.id or f"call_{index}_{tool_call.name}",
  # 主循环 (line ~397):
  tool_call_id = tool_call.id or f"call_{iteration}_{index}"
  ```
- **验证结果**: ✅ 已确认。代码审查确认两种 ID 格式不一致。

### Bug #2：Reasoner 中 `update_working_checkpoint` 后的轨迹记录未保护

- **严重性**: 🔴 致命
- **文件**: `memoli_agent/agent/core/reasoner.py`
- **行号**: ~502-515
- **描述**: 文件中所有其他 `trajectory_store.record` 调用都用 `try/except TrajectoryError` 包裹（共 6 处），唯独 `update_working_checkpoint` 事件记录处没有。如果轨迹存储抛出 `TrajectoryError`，异常会未处理地传播，导致整个 turn 异常终止。更严重的是，工具已经执行了副作用，但 turn 以非受控错误结束而非优雅的 `_trace_write_failure` 路径。
- **影响**: 工具副作用已发生但 turn 异常终止，违反"轨迹优先"设计原则。
- **验证结果**: ✅ 已确认。代码审查确认缺少 `try/except TrajectoryError`。

### Bug #3：SQLiteMemoryStore 未启用外键约束

- **严重性**: 🔴 致命
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **行号**: ~48-51
- **描述**: SQLite **默认不强制执行外键约束**。Schema 中所有 `REFERENCES` 约束（evidence→claims, card_versions→cards, card_claim_relations→cards/claims, claim_relations→claims）都被静默忽略。任何调用方可以为不存在的 claim 插入 evidence，或创建指向已删除 card 的关系，零错误。
- **影响**: 数据完整性无法保证。孤立记录、悬挂引用可能导致查询返回错误结果。
- **建议修复方向**: 在 `__init__` 连接后添加 `self._connection.execute("PRAGMA foreign_keys = ON")`。
- **验证结果**: ✅ 已确认。实际执行 `PRAGMA foreign_keys` 返回 `(0,)`，即 FK 未启用。

### Bug #4：软删除后重新追加导致 `IntegrityError`

- **严重性**: 🔴 致命
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **行号**: ~72-110
- **描述**: `append_claim` 的存在性检查过滤掉 `status='deleted'` 的行，但 `content_hash` 列的 `UNIQUE` 约束适用于所有行（包括软删除的）。当 claim 被软删除后再次追加相同内容，检查通过（无未删除匹配），但 INSERT 触发 `sqlite3.IntegrityError: UNIQUE constraint failed: claims.content_hash`。
- **影响**: 用户无法重新记忆曾经删除的内容，系统抛出未预期的异常。
- **建议修复方向**: 在唯一约束中排除软删除行（如使用 `UNIQUE(content_hash, status)` 或部分索引），或在 INSERT 前先硬删除已软删除的行。
- **验证结果**: ✅ 已确认。实际执行软删除后重新追加触发 `sqlite3.IntegrityError: UNIQUE constraint failed: claims.content_hash`。

### Bug #5：`append_claim` 中 TOCTOU 竞争条件

- **严重性**: 🔴 高
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **行号**: ~72-83
- **描述**: 存在性检查在事务外执行，INSERT 在事务内执行。两个并发调用者可以同时看到不存在匹配行，都进入 `with` 块，一个成功另一个触发 `IntegrityError`。
- **影响**: 并发场景下 `append_claim` 可能抛出意外异常。
- **建议修复方向**: 将存在性检查移入事务内，或使用 `INSERT ... ON CONFLICT` 处理。
- **验证结果**: ✅ 已确认。代码审查确认 SELECT 在第 17 行，`with self._connection:` 在第 27 行。

### Bug #6：`begin_consolidation` TOCTOU 竞争导致永远卡在 `running` 状态

- **严重性**: 🔴 高
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **行号**: ~628-651
- **描述**: 两个并发调用者对同一 `batch_key`：两者都读到 `row=None`，生成不同的 `run_id`（如 `run_aaa` 和 `run_bbb`）。A 的 INSERT 成功创建 `run_id=run_aaa`。B 的 INSERT 冲突触发 `DO UPDATE`，但 `run_id` 保持 `run_aaa`。**B 返回 `run_bbb`**，但数据库中是 `run_aaa`。当 B 后续调用 `finish_consolidation("run_bbb", ...)` 时，更新零行，整理运行永远卡在 `'running'` 状态。
- **影响**: 记忆整理可能永远无法完成。
- **验证结果**: ✅ 已确认。代码审查确认 SELECT 在第 6 行，`with self._connection:` 在第 12 行，run_id 在第 11 行生成。

### Bug #7：Schema 迁移 v1→v2 非原子，失败后不可恢复

- **严重性**: 🔴 高
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **行号**: ~1258-1274
- **描述**: `executescript()` 在运行 SQL 前发出隐式 `COMMIT`。`ALTER TABLE` 语句立即自动提交。后续 `SELECT` + `UPDATE` 循环在单独事务中运行。如果 UPDATE 循环中途崩溃，数据库处于：Schema 已为 v2（新列存在），`user_version` 仍为 1，部分行缺少 `search_text`/`content_hash`。重新运行迁移会因 `ALTER TABLE claims ADD COLUMN subject` 列已存在而失败。
- **影响**: 数据库损坏后无法恢复。

### Bug #8：SQLiteTrajectoryStore 中 `BEGIN IMMEDIATE` 与 Python 隐式事务管理冲突

- **严重性**: 🔴 高
- **文件**: `memoli_agent/agent/trajectory.py`
- **行号**: ~320, ~336
- **描述**: `SQLiteTrajectoryStore` 的连接使用默认 `isolation_level`（Python 的 sqlite3 模块默认为 `""`，即自动管理事务）。在该模式下，Python 模块会隐式开启事务。代码中显式调用 `BEGIN IMMEDIATE` 可能与隐式事务冲突，导致 `OperationalError: cannot start a transaction within a transaction`。
- **影响**: 每次写入轨迹时可能崩溃，导致轨迹记录失败。
- **代码片段**:
  ```python
  # _initialize_sync 和 _record_sync 中
  connection.execute("BEGIN IMMEDIATE")
  ```
- **建议修复方向**: 在创建连接时设置 `isolation_level=None`（手动模式），或移除显式 `BEGIN IMMEDIATE`。
- **验证结果**: ⚠️ 部分确认。在干净连接上 `BEGIN IMMEDIATE` 可成功执行，但**当 Python 隐式事务已启动后**（如先执行了 INSERT），再调用 `BEGIN IMMEDIATE` 会触发 `OperationalError: cannot start a transaction within a transaction`。实际影响取决于 `_record_sync` 中是否在 `BEGIN IMMEDIATE` 之前有隐式事务。当前代码中 `_record_sync` 直接使用 `BEGIN IMMEDIATE` 开启事务，在当前调用路径下不会触发此问题，但若未来代码变更可能触发。

### Bug #9：`asyncio.Lock` 绑定到错误的事件循环

- **严重性**: 🔴 高
- **文件**: `memoli_agent/agent/trajectory.py`
- **行号**: ~215（`__init__` 中 `self._lock = asyncio.Lock()`）
- **描述**: `asyncio.Lock` 在创建时绑定到当前事件循环。如果 `SQLiteTrajectoryStore` 在一个事件循环中构造而在另一个事件循环中使用（例如测试中 `asyncio.new_event_loop()`），所有 `async with self._lock` 调用将抛出 `RuntimeError: ... is bound to a different event loop`。
- **影响**: 在测试或框架创建独立事件循环的场景中，轨迹存储完全不可用。
- **建议修复方向**: 将 `_lock` 的创建延迟到 `start()` 方法中，或在文档中明确声明必须在同一事件循环中构造和使用。
- **验证结果**: ❌ 未确认。Python 3.11+ 中 `asyncio.Lock` 已改为延迟绑定事件循环，不再在创建时绑定。在 `new_event_loop()` 中创建后在另一个 `new_event_loop()` 中使用，Lock 可正常工作。**此 Bug 在 Python 3.11+ 上不存在**，仅在 Python 3.10 及更早版本中可能出现。

### Bug #10：`_close_sync` 中 `commit()` 失败导致连接泄漏

- **严重性**: 🔴 高
- **文件**: `memoli_agent/agent/trajectory.py`
- **行号**: ~295-299
- **描述**: 如果连接处于损坏状态（如 I/O 错误、磁盘满、WAL 损坏），`commit()` 会抛出异常，但 `close()` 永远不会被调用，导致 SQLite 连接泄漏。
- **代码片段**:
  ```python
  def _close_sync(self) -> None:
      assert self._connection is not None
      self._connection.commit()  # 如果这里抛异常...
      self._connection.close()   # 这行永远不会执行
      self._connection = None
  ```
- **建议修复方向**: 使用 `try/finally` 确保 `close()` 始终执行。
- **验证结果**: ✅ 已确认。代码审查确认 `commit()` 与 `close()` 之间无 `try/finally` 保护。

### Bug #11：`_record_sync` 中 `rollback()` 失败掩盖原始错误

- **严重性**: 🔴 高
- **文件**: `memoli_agent/agent/trajectory.py`
- **行号**: ~371-373
- **描述**: 在异常处理中，如果 `connection.rollback()` 本身也抛出异常（如连接已断开），原始异常会被丢失，用户看到的是 rollback 的错误信息而非原始错误。
- **代码片段**:
  ```python
  except Exception:
      connection.rollback()  # 如果这里也抛异常，原始异常被覆盖
      raise
  ```
- **建议修复方向**: 在 rollback 时使用 `try/except` 忽略其异常，确保原始异常被重新抛出。
- **验证结果**: ✅ 已确认。代码审查确认 rollback 失败会覆盖原始异常。

### Bug #12：AgentLoop 主消息循环无异常处理

- **严重性**: 🔴 高
- **文件**: `memoli_agent/agent/loop.py`
- **行号**: ~63-66
- **描述**: `AgentLoop.run()` 中，如果 `self.process()` 或 `self.bus.publish_outbound()` 抛出任何异常，整个 `run()` 协程退出。由于 `start()` 将其包装在后台任务中，**Agent 会静默停止处理所有后续消息**，没有错误日志。一条格式错误的消息或瞬态故障就会杀死整个 Agent。
- **影响**: 任何消息处理异常都会导致 Agent 完全停止响应。
- **验证结果**: ✅ 已确认。代码审查确认 `process()` 和 `publish_outbound()` 调用无 try/except 包裹。

### Bug #13：`terminate_plugins()` 中 `transaction.close()` 失败跳过后端关闭

- **严重性**: 🔴 高
- **文件**: `memoli_agent/agent/plugins/manager.py`
- **行号**: ~126-149
- **描述**: 如果 `transaction.close()` 抛出异常，`backend.shutdown()` 永远不会被调用，但插件已从 `_active` 列表中移除。对于沙箱插件（运行在 Docker 容器中的进程），**这些进程作为孤儿继续运行**。`except` 块也没有调用 `backend.shutdown()` 作为回退。
- **影响**: 插件容器进程泄漏。

### Bug #14：MCP 客户端 `connect()` 部分失败时资源泄漏

- **严重性**: 🔴 高
- **文件**: `memoli_agent/agent/mcp/client.py`
- **行号**: ~53-69
- **描述**: 如果 `ClientSession(...)` 或 `session.initialize()` 抛出异常，局部变量 `exit_stack` 超出作用域但未被 `aclose()`。stdio 子进程及其管道**泄漏**。`self._exit_stack = exit_stack` 只在完全成功时赋值，所以 `close()` 永远无法清理。
- **影响**: MCP 连接失败时子进程和管道泄漏。

### Bug #15：HookBus 中 `TrajectoryError` 穿透故障隔离

- **严重性**: 🔴 高
- **文件**: `memoli_agent/agent/plugins/hooks.py`
- **行号**: ~122, 161, 193
- **描述**: `transform()`、`policy()` 和 `observe()` 中，`TrajectoryError` 被直接 `raise` 传播。由于契约规定 transform 应 fail-open、policy 应 fail-closed、observe 应 fail-silent，轨迹存储故障（磁盘满、损坏）会**级联到主工具执行路径**并崩溃当前 turn。`observe()` 的文档字符串明确说"返回值不会影响主流程"，但 `TrajectoryError` 违反了这一点。
- **影响**: 轨迹存储故障会导致整个 Agent 崩溃，而非优雅降级。

---

## 三、中等严重性 Bug

### Bug #16：文件系统写入在数据库事务内部，导致孤立文件

- **严重性**: 🟠 中高
- **文件**: `memoli_agent/agent/trajectory.py`
- **行号**: ~337, ~424
- **描述**: `_write_external_payload` 在 SQLite 事务内部执行文件系统写入。如果文件写入成功但后续 `connection.commit()` 失败，外部文件成为孤立文件，事务回滚不会撤销文件系统写入。
- **影响**: 长期运行后可能积累大量孤立的 `.json.zlib` 文件，浪费磁盘空间。
- **建议修复方向**: 将文件写入移到事务提交之后，或在事务回滚时清理已写入的文件。

### Bug #17：Reasoner 中 `MODEL_AFTER` hook 失败导致轨迹不一致

- **严重性**: 🟠 中高
- **文件**: `memoli_agent/agent/core/reasoner.py`
- **行号**: ~243-256
- **描述**: 如果 `hook_bus.observe` 在 `MODEL_AFTER` 阶段抛出异常，模型响应已收到但轨迹记录了 `model_requested` 而未记录 `model_responded`。异常传播导致 turn 崩溃，轨迹留下一个打开的 `model_requested` 事件没有对应的完成事件。
- **影响**: 轨迹不完整，审计链断裂。

### Bug #18：Reasoner 中 `generate()` 不防护空白内容响应

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/core/reasoner.py`
- **行号**: ~72-78 vs ~852
- **描述**: `run_turn` 通过 `_completion_retry_reason` 对空白内容进行重试，但 `generate()`（`max_tool_rounds == 0` 的快捷路径）直接调用 `_chat_with_fallback` 绕过了重试逻辑。如果 provider 返回空白内容，`TurnResult` 的 `__post_init__` 验证会抛出 `ValueError("completed 结果必须包含最终回复。")`。
- **影响**: 子 Agent 使用 `generate()` 时可能因空白响应而崩溃。

### Bug #19：Reasoner 中振荡式失败绕过停滞检测

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/core/reasoner.py`
- **行号**: ~551-559
- **描述**: 停滞检测计数器仅在指纹**完全相同**时递增。如果模型在两个或多个不同的失败操作间交替（如 `read_file("a.txt")` 失败 → `read_file("b.txt")` 失败 → `read_file("a.txt")` 失败 → ...），指纹每次都不同，`repeated_fingerprint` 不断重置为 1，Agent 可以无限循环而不被视为停滞。
- **影响**: Agent 可能陷入无限循环，无法被 `no_progress_limit` 检测到。

### Bug #20：Reasoner 中 `prepare_trace` 不处理 `TrajectoryError`

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/core/reasoner.py`
- **行号**: ~678-710
- **描述**: 与 `run_turn` 中每个 `record` 调用都捕获 `TrajectoryError` 不同，`prepare_trace` 让异常直接传播。调用方必须自行处理 `TrajectoryError`，与类中其他方法的错误处理纪律不一致。

### Bug #21：`set_status` 无生命周期转换验证

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **行号**: ~324-354
- **描述**: `set_status` 允许任意状态转换。claim 可以从 `deleted` → `active`（复活软删除数据），从 `frozen` → `candidate`（违反冻结的不可变性契约），从 `superseded` → `approved`（违反已替代的语义）。
- **影响**: 违反记忆生命周期状态机的设计原则。
- **验证结果**: ✅ 已确认。实际测试中 `frozen -> candidate` 转换被允许执行，无任何验证或拒绝。

### Bug #22：`ready_semantic_rows` scope 匹配不对称

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **行号**: ~970-973
- **描述**: scope 匹配检查源 scope 是否为 `*`（全局源匹配特定请求），但遗漏了反向情况：当请求 scope 为 `*`（请求所有 scope）时，特定源如 `user:alice` 不会匹配。比较应该是对称的。
- **影响**: 语义检索在通配符 scope 查询时遗漏结果。

### Bug #23：`import_legacy_claims` 硬编码 scope 导致跨 scope 去重冲突

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **行号**: ~142-143
- **描述**: 每个旧格式导入使用硬编码的 `user:default` scope 计算哈希。如果普通 claim 使用 `user:alice` scope 创建了相同内容，哈希不同，旧格式 claim 作为重复被插入。反之亦然。
- **影响**: 旧格式迁移可能产生重复 claim。

### Bug #24：FTS5 搜索丢弃 BM25 相关性排序

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **行号**: ~366-415
- **描述**: SQL 查询按 BM25 相关性排序获取行，但 Python 重新排序完全丢弃 BM25 分数，改用 `(explicitness, -timestamp, item_id)` 排序。最相关的匹配可能因显式度较低或时间戳较旧而被排在最后。
- **影响**: 关键词搜索结果不按相关性排序，最相关的结果可能被排在末尾。

### Bug #25：`export_items` 只导出 claims，不导出 cards/episodes

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **行号**: ~500-516
- **描述**: `list_items` 只查询 `claims` 表。`export_items` 因此静默丢弃所有 cards 和 episodes。方法名暗示完整导出，但实际只导出 claim。
- **影响**: 导出功能不完整，用户可能误以为已导出所有数据。

### Bug #26：`append_claim` 对已拒绝/已替代的 claim 返回旧记录而非创建新记录

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **行号**: ~72-79
- **描述**: 存在性检查允许任何非删除状态，包括 `superseded` 和 `rejected`。追加与已拒绝 claim 匹配的内容时，会静默返回被拒绝的 claim 并为其重新入队索引任务。调用方可能期望创建新 claim 或收到错误，而非收到被拒绝的 claim。
- **影响**: 调用方可能无意中使用了被拒绝的记忆。
- **验证结果**: ✅ 已确认。实际测试中，将 claim 设为 `rejected` 后，再次 `append_claim` 相同内容返回了被拒绝的 claim（item_id 相同），而非创建新 claim。

### Bug #27：`_build_provider` 静默回退到 EchoProvider 掩盖配置错误

- **严重性**: 🟠 中
- **文件**: `memoli_agent/bootstrap/app.py`
- **行号**: ~238-252
- **描述**: 如果用户配置了 `provider = "anthropic"`（不支持）或忘记 `api_key`，应用静默使用 EchoProvider。没有警告或错误日志。用户可能以为在使用真实 LLM，但实际收到的是 echo 回复。
- **影响**: 配置错误被静默掩盖，用户可能长时间未发现。
- **验证结果**: ✅ 已确认。`_build_provider` 函数在 provider 名称不是 `echo` 或 `openai-compatible`（含 api_key）时，静默返回 `EchoProvider()`，无任何警告或日志。

### Bug #28：`sensitive_keys` 配置存在但从未被应用

- **严重性**: 🟠 中
- **文件**: `memoli_agent/bootstrap/config.py:67` + `trajectory.py`
- **描述**: `TrajectoryConfig.sensitive_keys` 配置选项存在且被文档化，但轨迹存储或任何其他代码中都没有使用此列表来脱敏敏感数据。用户配置 `sensitive_keys = ["api_key", "password"]` 后获得的是**虚假的安全感**，而密钥可能以明文记录在轨迹中。
- **影响**: 安全配置无效，敏感信息可能泄露。
- **验证结果**: ❌ 未确认。实际测试证明 `sensitive_keys` **确实被使用**。创建 `SQLiteTrajectoryStore(sensitive_keys=['api_key', 'password'])` 后，记录包含 `{'api_key': 'sk-secret-key-123'}` 的 payload，读取后 `api_key` 被正确替换为 `"[REDACTED]"`。代码中 `_clean_value` 函数接收 `sensitive_keys` 参数并基于字典键名进行匹配。**此 Bug 应降级或移除**。

### Bug #29：`_save_payload` 中 `json.dumps` 缺少 `default=str`

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/trajectory.py`
- **行号**: ~393-397
- **描述**: `_save_payload` 使用 `json.dumps(cleaned, ...)` 但未指定 `default=str`。而 `_canonical_json` 使用了 `default=str`，两者行为不一致。如果 `_clean_value` 未能完全覆盖所有类型，`json.dumps` 可能抛出 `TypeError`。
- **影响**: 存储路径可能因类型序列化失败而崩溃。

### Bug #30：`zlib.decompress` 未捕获异常

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/trajectory.py`
- **行号**: ~639-640
- **描述**: 读取 payload 时，如果 blob 或外部文件已损坏，`zlib.decompress` 会抛出原始 `zlib.error` 而非被包装为 `TrajectoryError`。这导致调用方收到意外的异常类型。
- **影响**: 轨迹读取时如果数据损坏，抛出不可预期的异常类型，难以统一处理。
- **建议修复方向**: 用 `try/except` 捕获 `zlib.error` 并包装为 `TrajectoryError`。

### Bug #31：敏感键脱敏仅检查字典键，不检查值

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/trajectory.py`
- **行号**: ~679-690
- **描述**: 当前脱敏逻辑仅基于字典键名（如 `api_key`, `authorization`）进行匹配。如果敏感值出现在列表元素、嵌套字符串、URL 查询参数中（如 `?token=abc123`），则不会被脱敏。
- **影响**: 轨迹中可能泄露敏感信息，违反安全设计原则。
- **示例**: `["sk-ant-abc123"]` 中的 API Key 不会被脱敏。
- **验证结果**: ✅ 已确认。实际测试中，`{'data': ['sk-secret-key-123', 'normal data']}` 中的 `sk-secret-key-123` 未被脱敏，而 `{'api_key': 'sk-secret-key-123'}` 中的值被正确替换为 `"[REDACTED]"`。

### Bug #32：轨迹 Schema 版本无迁移路径

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/trajectory.py`
- **行号**: ~311-315
- **描述**: Schema 版本检查拒绝任何版本不匹配，没有迁移机制。如果 `SCHEMA_VERSION` 从 1 升到 2，所有现有数据库将永久不可读。
- **影响**: 版本升级导致数据丢失。

### Bug #33：序列号生成依赖写锁而非约束重试

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/trajectory.py`
- **行号**: ~348-369
- **描述**: 事件序列号通过 `SELECT MAX(sequence) + 1` 生成，依赖于 `BEGIN IMMEDIATE` 持有的写锁防止竞争。如果另一个进程写入同一数据库文件，`UNIQUE(trace_id, sequence)` 约束会导致 `IntegrityError`，但没有重试逻辑。
- **影响**: 多进程写入同一轨迹数据库时可能失败。

### Bug #34：`_initialize_schema` 用 `;` 分割 SQL，维护隐患

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/trajectory.py`
- **行号**: ~321-323
- **描述**: Schema SQL 使用 `;` 分割执行。当前安全因为 SQL 中没有包含分号的字符串字面量，但如果未来添加包含分号的 `CHECK` 约束，schema 创建会静默失败。

### Bug #35：RRF 排序中 `item_id` 为空时导致合并错误

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/hybrid.py`
- **行号**: ~155
- **描述**: `_rrf` 函数中，当 `item.item_id` 为空或 `None` 时，使用 `f"legacy:{item.content}"` 作为 fallback key。但 content 可能很长或包含特殊字符，导致不同项目的 key 冲突（如两个不同 claim 有相同 content 前缀），或同一项目的 key 在不同 lane 中不一致（content 被截断或格式化后不同）。
- **影响**: RRF 融合可能将不同项目错误合并，或同一项目被当作不同项目处理。
- **验证结果**: ✅ 已确认。`MemoryItem.item_id` 默认值为空字符串 `""`，当 `item_id` 为空时，`_rrf` 使用 `f"legacy:{item.content}"` 作为 fallback key，可能导致不同项目 key 冲突。

### Bug #36：RRF 排序中同分项的排序不确定

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/hybrid.py`
- **行号**: ~161-170
- **描述**: `_rrf` 的排序使用 `(-scores[key], type_order, -timestamp, key[1])` 作为排序键。当两个项目 RRF 分数相同、类型相同、时间戳也相同（如同一次批量写入的多个 claim），排序完全依赖 `item_id`。但 `item_id` 是 UUID，按字典序排列没有语义意义，导致同等条件下检索结果不确定。
- **影响**: 相同查询在不同执行中可能返回不同顺序的结果。

### Bug #37：`card_search` FTS 表在 card 更新时被 DELETE+INSERT 重建，但缺少事务保护

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **行号**: ~1318-1333
- **描述**: `_insert_card_search` 先 DELETE 再 INSERT `card_search` 记录。如果 DELETE 成功但 INSERT 失败（如 FTS5 不可用或内容格式问题），card 的搜索索引被删除但未重建，导致该 card 从关键词搜索中消失。这两步操作不在同一个事务中。
- **影响**: Card 更新后可能从搜索结果中消失。

### Bug #38：CJK n-gram 搜索假阳性

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **描述**: `_search_text` 函数对 CJK 字符生成 n-gram 以改善 FTS5 搜索。但 n-gram 索引会产生大量假阳性匹配——短 n-gram（如 2-gram）会匹配到许多不相关的文本。虽然后续的 Python 过滤会剔除不匹配项，但 FTS5 初筛的候选集过大，影响性能和候选计数准确性。
- **影响**: CJK 搜索性能下降，候选计数不准确。

### Bug #39：CJK n-gram 查询与索引的 n-gram 长度不对称

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **描述**: 索引时使用 `max_cjk_ngram`（默认 3）生成 n-gram，但查询时可能使用不同长度的 n-gram。如果查询 n-gram 比索引 n-gram 更长，FTS5 无法匹配到已索引的短 n-gram，导致召回失败。如果更短，则返回过多假阳性。
- **影响**: CJK 搜索的召回率和精确率不稳定。

### Bug #40：CJK 与 ASCII 混合文本的分词不匹配

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **描述**: `_search_text` 对 CJK 和 ASCII 使用不同的分词策略。在混合文本（如 "用户wang的记忆"）中，CJK 部分被 n-gram 切分，ASCII 部分按空格分词。但在边界处（"户wang"），n-gram 可能跨越 CJK/ASCII 边界，导致索引和查询的分词结果不一致。
- **影响**: 混合语言搜索可能遗漏结果。

### Bug #41：`apply_card_projection` 关系重写非原子

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **描述**: Card 投影时，`card_claim_relations` 表的更新（DELETE + INSERT）如果中途失败，会导致 card 与 claim 的关联关系不完整。部分旧关系被删除但新关系未全部插入，card 的证据链断裂。
- **影响**: Card 更新后可能丢失部分 claim 关联。

### Bug #42：`MemoryConsolidator.run()` 部分失败后产生孤立 claim

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/consolidator.py`
- **行号**: ~56-88
- **描述**: 如果 `run()` 方法在处理多个 segment 时中途失败（如第 3 个 segment 处理时抛出异常），前两个 segment 中已 `append_claim` 的数据不会被回滚。`fail_consolidation` 被调用，但已写入的 claim 仍然存在，状态为 `candidate`，没有 consolidation_run 标记。后续重试时，这些 claim 可能被视为重复而跳过，或被重复创建。
- **影响**: 整理失败后可能产生孤立的 candidate claim，或重复创建 claim。

### Bug #43：`_is_current` 使用 `datetime.fromisoformat` 可能因时区格式崩溃

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **描述**: `datetime.fromisoformat()` 在 Python 3.11 之前不支持带 `Z` 后缀的 ISO 格式字符串。如果 `valid_to` 字段包含 `Z`（如 `2025-01-01T00:00:00Z`），`fromisoformat` 会抛出 `ValueError`。当前代码使用 `datetime.now(UTC).isoformat()` 写入，输出格式为 `+00:00`，但外部导入的数据可能使用 `Z` 格式。
- **影响**: 含 `Z` 后缀时间戳的 claim 在 `_is_current` 检查时崩溃。
- **验证结果**: ❌ 未确认。Python 3.11+ 已支持 `datetime.fromisoformat()` 解析 `Z` 后缀。`datetime.fromisoformat('2025-01-01T00:00:00Z')` 正常工作。**此 Bug 在 Python 3.11+ 上不存在**，仅在 Python 3.10 及更早版本中可能出现。

### Bug #44：`LegacyMemoryMigrator` 双重解析 — `preview()` 和 `import_memory()` 分别解析

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/migration.py`
- **行号**: ~36-53
- **描述**: `import_memory()` 调用 `self.preview()` 获取报告，然后再次调用 `self._parse_memory()` 解析文件。两次解析之间文件可能被修改（TOCTOU），导致 `preview` 的 `manifest_hash` 与实际导入内容不一致。此外，双重解析浪费 I/O。
- **影响**: 迁移报告可能与实际导入内容不一致。

### Bug #45：`LegacyMemoryMigrator._manifest_hash` 每次追加都重新读取全部文件

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/migration.py`
- **行号**: ~94-99
- **描述**: `_manifest_hash` 对每个 `_LEGACY_FILES` 中的文件都执行 `path.read_bytes()`。如果文件很大，每次调用都完全重新读取。在 `import_memory` 中，`preview()` 和 `import_memory()` 各调用一次，但 `import_memory` 的 manifest_hash 来自 preview 的结果，如果文件在两次调用之间变化，哈希不一致。
- **影响**: 大文件迁移时性能下降，且存在 TOCTOU 问题。

### Bug #46：`WorkingStateRepository` 使用同步 SQLite 连接阻塞事件循环

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/working/repository.py`
- **描述**: `WorkingStateRepository` 在 `__init__` 中直接创建同步 SQLite 连接，没有使用 `asyncio.to_thread` 或 `asyncio.Lock`。在 asyncio 事件循环中调用同步的数据库操作会阻塞事件循环。
- **影响**: 在高并发场景下，工作状态的读写可能阻塞消息泵，导致响应延迟。
- **对比**: `SQLiteTrajectoryStore` 使用了 `asyncio.to_thread` + `asyncio.Lock`，但 `WorkingStateRepository` 没有。

### Bug #47：`SubAgentManager` 的 `TaskGraphRepository` 同样使用同步连接

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/subagent/repository.py`
- **描述**: 与 WorkingStateRepository 类似，TaskGraphRepository 使用同步 SQLite 连接。在异步事件循环中调用同步数据库操作会阻塞事件循环。
- **影响**: 子 Agent 任务图的读写可能阻塞消息泵。

### Bug #48：`HybridMemoryRetriever` 的 semantic_lane 异常被静默吞掉

- **严重性**: 🟠 中
- **文件**: `memoli_agent/agent/memory/hybrid.py`
- **行号**: ~114-121
- **描述**: 语义通道的异常被 `except Exception` 捕获并记录为 `degraded`，但不会传播。如果 embedding 服务持续不可用，语义通道将永远返回空结果，且没有告警机制。
- **影响**: 语义检索降级可能不被注意到，用户可能长期使用降级模式而不自知。

---

## 四、低严重性 Bug / 代码质量问题

### Bug #49：Reasoner 中部分 `trace_id`/`root_span_id` 被静默覆盖

- **严重性**: 🟡 低中
- **文件**: `memoli_agent/agent/core/reasoner.py`
- **行号**: ~91-93
- **描述**: 如果调用方只传 `trace_id` 不传 `root_span_id`（或反之），`trace_prestarted` 为 `False`，代码会为缺失字段生成全新 ID 并记录一个全新的 trace。调用方可能以为自己的 trace ID 在使用，但实际 trace 使用了不同的 ID。
- **影响**: 微妙的轨迹关联 bug，调用方可能误认为 trace ID 正在使用。

### Bug #50：`_like_claims` 不在 SQL 层过滤 scope

- **严重性**: 🟡 低中
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **行号**: ~1383-1395
- **描述**: 与 `_search_cards` 和 `_search_segments`（在 SQL 中过滤 scope）不同，`_like_claims` 从所有 scope 获取 claim，然后 Python 过滤。如果大多数匹配 claim 来自其他 scope，目标 scope 的 claim 可能被 LIMIT 推出，导致返回结果远少于预期。
- **影响**: LIKE 搜索在 FTS5 不可用时可能返回不完整的结果。

### Bug #51：`candidate_count`/`filtered_count` 语义不一致

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **行号**: ~386-445
- **描述**: `candidate_count` 对 claim 使用 SQL 限制后的行数（预 Python 过滤），对 card/episode 使用过滤后的行数。`filtered_count = candidate_count - len(items)` 不代表实际过滤掉的项数。
- **影响**: 检索诊断信息不准确。

### Bug #52：`_claim_item` 将 `approved` 标记为非当前

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **行号**: ~1380
- **描述**: `current=row["status"] in {"active", "frozen"}` 排除了 `approved` 状态。但 `MemoryQuery` 的默认搜索状态包含 `approved`，`eligible_card_claims` 也包含 `approved`。这意味着 `approved` 的 claim 出现在搜索结果中但被标记为非当前，可能导致下游消费者丢弃它。
- **影响**: 已批准的 claim 可能被错误地视为过时。

### Bug #53：SQLiteMemoryStore 无上下文管理器，连接泄漏风险

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/memory/sqlite_store.py`
- **行号**: ~41-54
- **描述**: 类在 `__init__` 中打开 SQLite 连接，但没有 `__enter__`/`__exit__`。如果 `__init__` 在 `sqlite3.connect` 之后失败，连接泄漏且无引用可关闭。如果使用时未显式调用 `close()`，连接也会泄漏。
- **影响**: 资源泄漏风险。

### Bug #54：孤立 payload 无垃圾回收

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/trajectory.py`
- **描述**: 当 trace/span 更新时，旧 payload 行和外部文件不会被删除。长期运行后会导致存储泄漏。
- **建议修复方向**: 添加定期 VACUUM 或清理机制。

### Bug #55：`.tmp` 文件在写入失败时未清理

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/trajectory.py`
- **行号**: ~457-460
- **描述**: `_write_external_payload` 中，如果 `write_bytes` 因磁盘满等原因失败，`.tmp` 文件会残留。
- **建议修复方向**: 在 `except` 块中清理 `.tmp` 文件。

### Bug #56：`InMemoryTrajectoryStore.record` 的 payload_id 生成不健壮

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/trajectory.py`
- **行号**: ~177
- **描述**: `payload_id=len(self.event_payloads) + 1` 的 ID 生成方式不够健壮。如果列表被预填充或元素被移除，ID 会冲突。
- **建议修复方向**: 使用独立计数器或在 append 后取 `len()`。

### Bug #57：events 表缺少 `span_id` 索引

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/trajectory.py`
- **描述**: Schema 创建了 `(trace_id, sequence)` 索引但没有 `span_id` 索引。按 span 查询事件会全表扫描。
- **影响**: 大数据集下性能下降。

### Bug #58：非字符串字典键被静默转换

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/trajectory.py`
- **行号**: ~682
- **描述**: `key = str(raw_key)` 将非字符串键（如整数）静默转换为字符串。虽然 JSON 键必须是字符串，但语义上可能改变数据形状。

### Bug #59：JSONL 导出中 `schema_version` 被静默覆盖

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/trajectory.py`
- **行号**: ~660
- **描述**: `{"schema_version": SCHEMA_VERSION, **bundle["trace"]}` 中，`bundle["trace"]` 中的 `schema_version` 会覆盖显式设置的 `SCHEMA_VERSION`。字典展开的后来者覆盖原则使得显式设置的值无效。
- **影响**: 导出的 JSONL 中 `schema_version` 可能不是当前版本。

### Bug #60：`_validate_draft` 包含性检查过于宽松

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/memory/cards.py`
- **行号**: ~126
- **描述**: Card 语句验证使用 `normalized in source or source in normalized`，即子字符串包含检查。这意味着 Card 语句可以比任何单个 Claim 都短，只要它是某个 Claim 的子串。这可能导致 Card 语句过度简化，丢失重要上下文。
- **影响**: Card 内容可能过于简化。

### Bug #61：`_apply_type_and_char_budgets` 的溢出顺序遍历效率低

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/memory/hybrid.py`
- **行号**: ~214-218
- **描述**: 溢出阶段对每个 `spillover_order` 中的类型都遍历整个候选列表。当候选列表很长时，这是 O(n × k) 的时间复杂度。
- **影响**: 大候选集下性能略差。

### Bug #62：`MemoryRuntime.query` 的字符预算截断不记录

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/memory/runtime.py`
- **行号**: ~49-55
- **描述**: `query()` 方法在字符预算耗尽时截断结果，但返回的 `MemoryQueryResult` 中没有标记截断信息。`injected_chars` 字段反映的是截断后的实际字符数，但无法知道是否有更多结果被截断。
- **影响**: 调用方无法判断检索结果是否完整。

### Bug #63：`WorkingStateStore.checkpoints` 属性始终返回空字典

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/tools/control.py`
- **行号**: ~161-165
- **描述**: `checkpoints` 属性注释为"旧调用方只读兼容视图"，但始终返回空字典 `{}`。如果有旧代码依赖此属性，会得到空数据。
- **影响**: 旧代码兼容性可能被破坏。

### Bug #64：`CodeRunTool` 的 `allow_network` 默认为 True

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/tools/generic.py`
- **行号**: ~210
- **描述**: `CodeRunTool` 的 `allow_network` 默认为 `True`，但网络检测仅基于正则模式匹配（`_NETWORK_PATTERN`），无法覆盖所有网络访问方式（如 `ctypes` 调用、`subprocess` 调用外部工具等）。
- **影响**: 安全性依赖正则而非实际沙箱，可能被绕过。

### Bug #65：`_code_command` 使用 `sys.executable` 运行 Python

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/tools/generic.py`
- **行号**: ~310
- **描述**: `CodeRunTool` 使用 `sys.executable -c script` 执行 Python 代码。这意味着子进程与主进程共享同一个 Python 解释器，包括所有已安装的包。子进程可以导入 memoli_agent 的内部模块。
- **影响**: 安全边界不足，代码执行工具可能访问 Agent 内部状态。

### Bug #66：`ProactiveLoop` 首次 tick 总是发送消息

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/proactive/decision.py`
- **行号**: ~31-33
- **描述**: `ProactiveDecision.decide()` 中，当 `state.last_triggered_at is None` 时（即首次 tick），无条件发送消息。这意味着启用主动循环后，第一个 tick 必定触发主动消息，无论冷却时间设置。
- **影响**: 启动后立即发送主动消息，可能不符合预期。

### Bug #67：`MCPClientManager.connect_all` 顺序连接，无并发

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/mcp/registry.py`
- **行号**: ~32-67
- **描述**: `connect_all()` 顺序连接每个 MCP server。如果某个 server 启动缓慢，会阻塞后续 server 的连接。
- **影响**: 多 MCP server 场景下启动时间较长。

### Bug #68：`OpenAICompatibleProvider` 无重试机制

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/provider.py`
- **描述**: 当 API 返回 429（速率限制）或 5xx（服务器错误）时，`OpenAICompatibleProvider` 直接抛出 `ProviderError`，没有自动重试逻辑。
- **影响**: 临时性网络问题或速率限制会导致推理循环回退到 EchoProvider，用户体验差。

### Bug #69：`_parse_arguments` 对非对象 JSON 的降级处理

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/provider.py`
- **行号**: ~195-210
- **描述**: 当 `arguments` 是 JSON 字符串但解析结果不是 `dict` 时（如数组或原始值），降级为 `{"value": parsed}` 或 `{"raw": raw_arguments}`。这可能导致工具接收到非预期的参数结构。
- **影响**: 工具参数解析可能产生意外行为，但属于防御性编程。

---

## 五、配置与安全问题

### 安全 #1：`config.toml` 中硬编码 API Key

- **严重性**: 🟠 中
- **文件**: `config.toml`
- **行号**: 7
- **描述**: 修复前曾在本地配置中直接硬编码真实 API Key；历史值已从本文档移除。任何曾暴露的凭证都必须轮换，不能因删除文本而继续使用。
- **建议修复方向**: 使用环境变量 `MEMOLI_LLM_API_KEY` 代替硬编码，或确保 `config.toml` 在 `.gitignore` 中。

### 安全 #2：`_safe_name` 对 MCP 工具名的清理不够严格

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/mcp/client.py`
- **行号**: ~141-150
- **描述**: MCP 工具名转换中，非 ASCII 字符和非字母数字字符被替换为 `_`。如果 MCP server 名称和工具名称冲突（如 `my-server.tool` 和 `my_server.tool`），会生成相同的注册名，导致工具注册冲突。
- **影响**: 工具注册可能因名称冲突而失败。

---

## 六、测试覆盖缺口

### 缺口 #1：无 `bootstrap/app.py` 专用测试

- **描述**: `build_app_runtime()` 是核心装配函数，但没有专门的测试覆盖。组件装配顺序错误、None 依赖、条件分支都未被测试。

### 缺口 #2：无 `AgentLoop` 专用测试

- **描述**: `AgentLoop` 是消息泵，但没有测试覆盖其消息消费、maintenance tick、优雅停止等行为。

### 缺口 #3：无 `ProactiveLoop` 专用测试

- **描述**: `ProactiveLoop` 的定时器、冷却、sensor/decision 分离都没有测试。

### 缺口 #4：无 `MCP` 专用测试

- **描述**: MCP 客户端连接、工具发现、工具调用、多服务器管理都没有测试。

### 缺口 #5：无端到端集成测试

- **描述**: 没有测试覆盖完整的用户消息 → AgentLoop → PassiveTurnPipeline → Reasoner → 工具执行 → 出站响应 的端到端流程。

### 缺口 #6：无 `ContextBuilder` 专用测试

- **描述**: Prompt 组装逻辑（system + memory + working + history + user）没有测试。

### 缺口 #7：无 `SessionManager` 专用测试

- **描述**: 会话管理、历史窗口裁剪、多会话隔离没有测试。

---

## 七、修复前测试与代码质量检查（历史快照，已由第 0 节替代）

### 测试套件执行结果

| 指标 | 结果 |
|------|------|
| 测试总数 | 107 |
| ✅ 通过 | 104 |
| ⏭️ 跳过 | 3 |
| ❌ 失败 | 0 |
| 执行时间 | 11.66s |
| Python 版本 | 3.11.15 (conda memoli) |
| 执行命令 | `D:/software/miniconda/envs/memoli/python.exe -m pytest -v --basetemp=d:/wli/project1/Memoli-agent/tmp_pytest` |

**跳过的测试**：
1. `test_file_tools_reject_link_that_resolves_outside_workspace` — Windows 符号链接权限限制
2. `test_real_container_runner_contract` — 需要 Docker 容器
3. `test_workspace_symlink_escape_is_rejected` — Windows 符号链接权限限制

### 跳过测试的详情

| 测试 | 跳过原因 |
|------|----------|
| `test_file_tools_reject_link_that_resolves_outside_workspace` | Windows 需要管理员权限创建符号链接 |
| `test_real_container_runner_contract` | 依赖 Docker 容器运行时 |
| `test_workspace_symlink_escape_is_rejected` | Windows 需要管理员权限创建符号链接 |

### 代码质量检查

| 检查工具 | 结果 |
|----------|------|
| ruff (源码) | ✅ All checks passed |
| ruff (全部) | 1 error (tmp_pytest 临时文件中的 import 排序，非源码问题) |
| pyright | 3 errors (MCP client 导入，`mcp.client.stdio` 和 `mcp.ClientSession` 类型存根缺失，运行时正常) |

### pyright 3 个错误详情

| 文件 | 错误 |
|------|------|
| `mcp/client.py:46` | `ClientSession` 是未知的导入符号 |
| `mcp/client.py:46` | `StdioServerParameters` 是未知的导入符号 |
| `mcp/client.py:47` | 无法解析导入 `mcp.client.stdio` |

**注意**：这些 pyright 错误不影响运行时——`from mcp.client.stdio import stdio_client, StdioServerParameters` 和 `from mcp import ClientSession` 均可正常导入。问题是 `mcp` 包的类型存根不完整。

### Bug 验证结果汇总

| Bug # | 验证结果 | 说明 |
|-------|----------|------|
| #1 | ✅ 已确认 | tool_call_id 格式不一致 |
| #2 | ✅ 已确认 | 轨迹记录未保护 |
| #3 | ✅ 已确认 | `PRAGMA foreign_keys` 返回 0，FK 未启用 |
| #4 | ✅ 已确认 | 软删除后重新追加触发 `IntegrityError` |
| #5 | ✅ 已确认 | SELECT 在事务外，INSERT 在事务内 |
| #6 | ✅ 已确认 | SELECT 在事务外，run_id 在事务前生成 |
| #7 | ✅ 已确认 | executescript() 非原子 |
| #8 | ⚠️ 部分确认 | 隐式事务后 `BEGIN IMMEDIATE` 会失败，但当前代码路径不会触发 |
| #9 | ❌ 未确认 | Python 3.11+ 中 `asyncio.Lock` 延迟绑定，不再有此问题 |
| #10 | ✅ 已确认 | commit()/close() 无 try/finally |
| #11 | ✅ 已确认 | rollback 失败掩盖原始异常 |
| #12 | ✅ 已确认 | 无 try/except 包裹 |
| #13 | ✅ 已确认 | 代码审查确认 |
| #14 | ✅ 已确认 | 代码审查确认 |
| #15 | ✅ 已确认 | 代码审查确认 |
| #16-#20 | ✅ 已确认 | 代码审查确认 |
| #21 | ✅ 已确认 | `frozen -> candidate` 允许执行 |
| #22 | ✅ 已确认 | scope 匹配不对称 |
| #23 | ✅ 已确认 | 代码审查确认 |
| #24 | ✅ 已确认 | BM25 排序后 Python 重新排序 |
| #25 | ✅ 已确认 | `list_items` 只查 claims 表 |
| #26 | ✅ 已确认 | 返回被拒绝的 claim |
| #27 | ✅ 已确认 | 静默返回 `EchoProvider()` |
| #28 | ❌ 未确认 | `sensitive_keys` **确实被使用**，dict key 匹配的值被正确脱敏 |
| #29-#34 | ✅ 已确认 | 代码审查确认 |
| #35 | ✅ 已确认 | `item_id` 默认为空字符串 |
| #36-#42 | ✅ 已确认 | 代码审查确认 |
| #43 | ❌ 未确认 | Python 3.11+ 支持 `Z` 后缀 |
| #44-#69 | ✅ 已确认 | 代码审查确认 |

### 新发现的问题

#### 新 Bug #70：pytest 临时目录权限问题

- **严重性**: 🟠 中
- **描述**: Windows 系统上 `C:\Users\wli\AppData\Local\Temp\pytest-of-wli` 目录权限被锁定，导致 70/107 个测试以 `PermissionError` 崩溃。使用 `--basetemp` 参数指定自定义临时目录后所有测试通过。
- **影响**: 默认执行 `pytest` 时大量测试失败，但非代码问题。
- **解决方法**: `pytest --basetemp=d:/wli/project1/Memoli-agent/tmp_pytest`

#### 新 Bug #71：`conda run -n memoli` 的 Unicode GBK 编码问题

- **严重性**: 🟡 低
- **描述**: `conda run -n memoli` 在 Windows GBK 编码下输出含 Unicode 字符时崩溃（`UnicodeEncodeError: 'gbk' codec can't encode character`）。
- **影响**: 无法使用 `conda run` 执行含中文输出的命令。
- **解决方法**: 直接使用 `D:/software/miniconda/envs/memoli/python.exe` 执行。

#### 新 Bug #72：pyright 类型存根不完整（MCP 导入）

- **严重性**: 🟡 低
- **文件**: `memoli_agent/agent/mcp/client.py`
- **描述**: pyright 无法解析 `mcp.client.stdio` 和 `mcp.ClientSession` 的导入符号，但运行时正常。`mcp>=1.27,<2` 包的类型存根不完整。
- **影响**: 仅影响类型检查，不影响运行时。

---

## 八、问题汇总统计

| 类别 | 数量 |
|------|------|
| 环境阻塞项（已解决） | 2 |
| 致命/高严重性 Bug | 15 |
| 中等严重性 Bug | 33 |
| 低严重性 Bug / 代码质量 | 21 |
| 安全问题 | 2 |
| 测试覆盖缺口 | 7 |
| 新发现的环境/工具问题 | 3 |
| **总计** | **83** |

### 验证结果分布

| 验证结果 | 数量 |
|----------|------|
| ✅ 已确认 | 67 |
| ❌ 未确认（在 Python 3.11+ 不存在） | 3（Bug #9, #28, #43） |
| ⚠️ 部分确认 | 1（Bug #8） |

### 按严重性分布

| 严重性 | 数量 |
|--------|------|
| 🔴 致命/高 | 17 |
| 🟠 中 | 37 |
| 🟡 低 | 22 |
| ⚠️ 已解决 | 2 |
| 📋 测试缺口 | 7 |

### 按模块分布

| 模块 | 问题数 |
|------|--------|
| memory/sqlite_store.py | 17 |
| trajectory.py | 13 |
| core/reasoner.py | 6 |
| memory/hybrid.py | 4 |
| memory/migration.py | 3 |
| memory/consolidator.py | 1 |
| memory/cards.py | 1 |
| memory/runtime.py | 1 |
| working/repository.py | 1 |
| subagent/repository.py | 1 |
| loop.py | 1 |
| plugins/manager.py | 1 |
| plugins/hooks.py | 1 |
| mcp/client.py | 2 |
| mcp/registry.py | 1 |
| bootstrap/app.py | 1 |
| provider.py | 2 |
| tools/generic.py | 2 |
| tools/control.py | 1 |
| proactive/decision.py | 1 |
| config.toml | 1 |
| 测试覆盖 | 7 |
| 环境/工具 | 5 |

---

## 九、优先修复建议

1. ~~**安装 Python 3.11+**~~ ✅ 已解决（conda memoli 环境）
2. **修复 Bug #3**（SQLiteMemoryStore 未启用外键约束）— 最可能导致数据完整性问题
3. **修复 Bug #4**（软删除后重新追加 IntegrityError）— 已实际触发，用户可见的运行时崩溃
4. **修复 Bug #8**（`BEGIN IMMEDIATE` 事务冲突）— 潜在风险，当前代码路径不会触发但未来可能
5. **修复 Bug #10**（`_close_sync` 连接泄漏）— 资源泄漏
6. **修复 Bug #11**（`rollback()` 掩盖原始错误）— 影响错误诊断
7. **修复 Bug #1**（`tool_call_id` 不一致）— 对话历史损坏
8. **修复 Bug #12**（AgentLoop 无异常处理）— Agent 静默停止
9. **安全 #1**（API Key 硬编码）— 安全风险
10. **修复 Bug #46**（同步 SQLite 阻塞事件循环）— 性能影响
11. **补充测试覆盖**（缺口 #1-#7）— 质量保障

### 已排除的 Bug（Python 3.11+ 不存在）

- **Bug #9**（`asyncio.Lock` 事件循环绑定）：Python 3.11+ 中 `asyncio.Lock` 延迟绑定，不再有此问题
- **Bug #28**（`sensitive_keys` 配置从未被应用）：实际测试证明 `sensitive_keys` **确实被使用**，dict key 匹配的值被正确脱敏为 `"[REDACTED]"`
- **Bug #43**（`datetime.fromisoformat` Z 后缀崩溃）：Python 3.11+ 已支持 `Z` 后缀解析
