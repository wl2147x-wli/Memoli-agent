# Benchmarks 架构与代码功能说明

本文档说明 `benchmarks/` 中各模块的职责、数据流、Agent 接入方式、LoCoMo / LongMemEval 测评流程，以及结果文件的生成逻辑。

## 1. 总体目标

`benchmarks/` 是一个独立测评层，用于把不同长期记忆测评集接入 Memoli 或任意其他 Agent。

它的核心目标是：

```text
测评集数据
  -> 统一 Benchmark 数据对象
  -> 通用 Agent 接口
  -> Agent 预测结果
  -> 官方评测脚本 / 聚合指标
  -> 结果文件与报告
```

该层不把 LoCoMo、LongMemEval 的数据格式和评测逻辑写进 `memoli_agent/` 核心代码。Memoli 只是其中一种被测 Agent；也可以通过 HTTP、CLI 或自定义 Python 类切换到其他 Agent。

## 2. 目录结构

```text
benchmarks/
  run.py
  config.py
  config.locomo.toml
  config.longmemeval_oracle.toml
  config.longmemeval_s.toml
  config.longmemeval_m.toml

  datasets/
    base.py
    locomo.py
    longmemeval.py

  agents/
    base.py
    registry.py
    memoli.py
    http.py
    cli.py
    python.py

  metrics/
    common.py
    locomo.py

  reports/
    writer.py
```

模块分层如下：

| 层级 | 主要文件 | 职责 |
|---|---|---|
| 入口层 | `run.py` | 串联完整测评流程 |
| 配置层 | `config.py`、`*.toml` | 读取数据集、Agent、指标、输出配置 |
| 数据集层 | `datasets/` | 把原始数据集转成统一对象 |
| Agent 层 | `agents/` | 用统一接口调用 Memoli / HTTP / CLI / Python Agent |
| 指标层 | `metrics/` | 调官方评测脚本并聚合指标 |
| 报告层 | `reports/` | 写出 JSONL、JSON、Markdown 报告 |

## 3. 主入口：run.py

文件：

```text
benchmarks/run.py
```

这是命令行入口。运行：

```powershell
python -m benchmarks.run --config benchmarks/config.locomo.toml
```

会进入 `main()`，然后调用：

```python
run_benchmark(config)
```

完整流程：

```text
1. load_benchmark_config()
2. apply_overrides()
3. _build_dataset_adapter(config).load()
4. create_agent_adapter(...)
5. 遍历 samples
6. agent.reset(sample.id)
7. agent.ingest(sample)
8. agent.answer(sample, question)
9. _record(...) 生成预测明细
10. LoCoMo 调官方 evaluation.py 评分
11. aggregate(records) 聚合指标
12. ReportWriter 写输出文件
```

输出目录生成逻辑：

```python
run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
output_dir = (
    Path(config.output.dir)
    / config.dataset.name
    / config.dataset.split
    / run_id
)
```

例如：

```text
workspace/benchmark/results/locomo/locomo10/20260626_141845
```

## 4. 配置层：config.py 与 TOML

文件：

```text
benchmarks/config.py
```

该文件定义四类配置：

```python
DatasetConfig
AgentBenchmarkConfig
MetricsConfig
OutputConfig
```

对应 TOML 中的四个 section：

```toml
[dataset]
[agent]
[metrics]
[output]
```

### 4.1 DatasetConfig

```python
class DatasetConfig:
    name: str
    path: str
    split: str = "default"
    sample_size: int = 0
    seed: int = 42
    question_types: list[str] = []
    max_sessions: int = 0
```

含义：

| 字段 | 说明 |
|---|---|
| `name` | 数据集名称，如 `locomo` 或 `longmemeval` |
| `path` | 本地数据文件路径 |
| `split` | 输出目录中的 split 标识 |
| `sample_size` | 抽样数量，`0` 表示全量 |
| `seed` | 随机抽样种子 |
| `question_types` | 问题类型过滤 |
| `max_sessions` | LongMemEval 历史 session 截断数量 |

### 4.2 AgentBenchmarkConfig

```python
class AgentBenchmarkConfig:
    type: str = "memoli"
    config_path: str = "config.benchmark.toml"
    workspace_root: str = "workspace/benchmark"
    module: str = ""
    class_name: str = ""
    reset_per_sample: bool = True
    reset_memory_per_sample: bool = True
    ingest_mode: str = "memory_write"
    answer_mode: str = "agent_turn"
    capture_retrieved_context: bool = True
    base_url: str = ""
    reset_endpoint: str = "/reset"
    ingest_endpoint: str = "/ingest"
    answer_endpoint: str = "/answer"
    command: str = ""
    input_format: str = "json"
    timeout_seconds: int = 300
```

重点字段：

| 字段 | 说明 |
|---|---|
| `type` | Agent 类型：`memoli`、`http`、`cli`、`python`、`custom` |
| `config_path` | Memoli benchmark runtime 配置路径 |
| `workspace_root` | benchmark 样本 workspace 根目录 |
| `reset_per_sample` | 每个 sample 是否隔离状态 |
| `reset_memory_per_sample` | Memoli adapter 是否清空每个 sample 的 memory |
| `ingest_mode` | 历史对话注入方式 |
| `answer_mode` | QA 回答方式 |
| `capture_retrieved_context` | 是否记录回答前检索上下文 |

## 5. 统一数据对象：datasets/base.py

文件：

```text
benchmarks/datasets/base.py
```

统一数据对象是所有数据集和 Agent 的中间协议。

```python
BenchmarkMessage(id, role, speaker, content, timestamp, metadata)
BenchmarkSession(id, messages, timestamp, metadata)
BenchmarkQuestion(id, question, gold_answers, timestamp, question_type, evidence, metadata)
BenchmarkSample(id, sessions, questions, metadata)
BenchmarkPrediction(sample_id, question_id, prediction, gold_answers, retrieved_context, metadata)
```

关系：

```text
BenchmarkSample
  |-- sessions: list[BenchmarkSession]
  |     |-- messages: list[BenchmarkMessage]
  |
  |-- questions: list[BenchmarkQuestion]
```

这层的作用是屏蔽原始数据集差异。例如 LoCoMo 用 `conversation.session_1`，LongMemEval 用 `haystack_sessions`，但进入 Agent 前都变成 `BenchmarkSample`。

## 6. LoCoMo 数据适配：datasets/locomo.py

文件：

```text
benchmarks/datasets/locomo.py
```

职责：

1. 读取 `locomo10.json`。
2. 把每个顶层 item 转成一个 `BenchmarkSample`。
3. 把 `conversation.session_n` 转成 `BenchmarkSession`。
4. 把每个 turn 转成 `BenchmarkMessage`。
5. 把每个 `qa` 转成 `BenchmarkQuestion`。
6. 根据配置过滤 `question_types`。
7. 根据 `sample_size` 和 `seed` 抽样。

LoCoMo category 映射：

| 原始 `category` | 统一 `question_type` |
|---:|---|
| 1 | `multi-hop` |
| 2 | `temporal` |
| 3 | `open-domain` |
| 4 | `single-hop` |
| 5 | `adversarial` |

示例转换：

```json
{
  "question": "How do Jon and Gina both like to destress?",
  "answer": "by dancing",
  "evidence": ["D1:7", "D1:6"],
  "category": 4
}
```

会变成：

```python
BenchmarkQuestion(
    id="conv-30:qa_0",
    question="How do Jon and Gina both like to destress?",
    gold_answers=["by dancing"],
    question_type="single-hop",
    evidence=["D1:7", "D1:6"],
    metadata={"category": 4, "raw": qa}
)
```

## 7. LongMemEval 数据适配：datasets/longmemeval.py

文件：

```text
benchmarks/datasets/longmemeval.py
```

职责：

1. 读取 `longmemeval_oracle.json`、`longmemeval_s_cleaned.json` 或 `longmemeval_m_cleaned.json`。
2. 把 `haystack_sessions` 转成 `BenchmarkSession`。
3. 把 session 内每个 turn 转成 `BenchmarkMessage`。
4. 把问题转成 `BenchmarkQuestion`。
5. 把 `answer_session_ids` 放入 `evidence`。
6. 对大文件使用流式 JSON array 读取。

大文件判断：

```python
if path.stat().st_size > 400_000_000:
    raw_items = self._load_streaming(path)
```

LongMemEval_M 文件较大，因此会按 `sample_size` 早停，避免一次性读完整文件。

`question_id` 以 `_abs` 结尾时：

```python
question_type = "abstention"
```

## 8. Agent 通用接口：agents/base.py

文件：

```text
benchmarks/agents/base.py
```

该文件定义通用 Agent 协议：

```python
class BenchmarkAgentAdapter:
    async def reset(self, sample_id: str) -> None: ...
    async def ingest(self, sample: BenchmarkSample) -> None: ...
    async def answer(
        self, sample: BenchmarkSample, question: BenchmarkQuestion
    ) -> BenchmarkPrediction: ...
    async def close(self) -> None: ...
```

含义：

| 方法 | 作用 |
|---|---|
| `reset` | 开始一个新 sample，清空或切换 Agent 状态 |
| `ingest` | 把历史对话交给 Agent |
| `answer` | 向 Agent 提问并返回预测 |
| `close` | 释放资源 |

该文件还提供 JSON payload 辅助函数：

```python
sample_to_payload(sample)
question_to_payload(sample, question)
prediction_from_payload(sample, question, payload)
```

这些函数主要给 HTTP / CLI adapter 使用。

## 9. Agent 注册器：agents/registry.py

文件：

```text
benchmarks/agents/registry.py
```

根据配置创建 Agent：

```python
agent_type = config.type.lower()
```

支持：

| `agent.type` | Adapter |
|---|---|
| `memoli` | `MemoliAgentAdapter` |
| `http` | `HttpAgentAdapter` |
| `cli` | `CliAgentAdapter` |
| `python` / `custom` | `PythonAgentAdapter` |

因此，切换被测 Agent 不需要改 `run.py`，只需要改 TOML：

```toml
[agent]
type = "http"
```

## 10. Memoli Agent 适配：agents/memoli.py

文件：

```text
benchmarks/agents/memoli.py
```

这是当前默认 adapter。

### 10.1 reset

`reset(sample_id)` 会为每个 sample 创建独立 workspace：

```text
workspace/benchmark/<dataset>/<split>/<sample_id>
```

例如：

```text
workspace/benchmark/locomo/locomo10/conv-30
```

并把 Memoli 配置改写到该 sample 目录：

```python
config.runtime.workspace = sample_workspace
config.memory.path = sample_workspace / "memory"
config.subagent.root = sample_workspace / "subagents"
```

这样每个 sample 的 memory、history、subagents 都互相隔离。

### 10.2 ingest

支持两种模式。

#### memory_write

配置：

```toml
ingest_mode = "memory_write"
```

逻辑：

```python
runtime.memory_runtime.mutate(
    MemoryMutation(
        content=_render_message(sample.id, session.id, message),
        source=f"{dataset}:{sample.id}:{session.id}:{message.id}",
        metadata={...}
    )
)
```

写入内容类似：

```text
[sample=conv-30][session=session_1][message=D1:6][time=...] Gina: ...
```

这种模式不会让模型逐条阅读历史，而是 benchmark 直接把原始历史 turn 写入 Memoli 长期记忆。

#### agent_turn

配置：

```toml
ingest_mode = "agent_turn"
```

逻辑：

```python
runtime.runner.handle_inbound(
    InboundMessage(
        channel="benchmark",
        chat_id=sample.id,
        sender=message.speaker or message.role,
        content=message.content,
        metadata={...}
    )
)
```

这种模式会把历史对话当成普通用户输入喂给 Agent，由 Agent 自己决定是否调用工具写入长期记忆。

### 10.3 answer

回答阶段做两件事：

1. 如果 `capture_retrieved_context = true`，先用问题检索 memory：

```python
runtime.memory_runtime.query(MemoryQuery(query=question.question, limit=5))
```

结果保存到：

```json
"retrieved_context": [...]
```

2. 再调用 Memoli 正常 Agent：

```python
runtime.runner.handle_inbound(
    InboundMessage(content=question.question, ...)
)
```

最终返回：

```python
BenchmarkPrediction(
    prediction=outbound.content,
    retrieved_context=retrieved_context,
    metadata=outbound.metadata
)
```

## 11. HTTP Agent：agents/http.py

文件：

```text
benchmarks/agents/http.py
```

适合任意远程 Agent 服务。

配置示例：

```toml
[agent]
type = "http"
base_url = "http://localhost:8000"
reset_endpoint = "/benchmark/reset"
ingest_endpoint = "/benchmark/ingest"
answer_endpoint = "/benchmark/answer"
timeout_seconds = 300
```

调用方式：

```text
POST /benchmark/reset
POST /benchmark/ingest
POST /benchmark/answer
```

`answer` 返回格式：

```json
{
  "prediction": "模型输出",
  "retrieved_context": [],
  "metadata": {}
}
```

## 12. CLI Agent：agents/cli.py

文件：

```text
benchmarks/agents/cli.py
```

适合命令行 Agent。

配置示例：

```toml
[agent]
type = "cli"
command = "python D:/path/to/agent_cli.py"
input_format = "json"
```

benchmark 会通过标准输入发送 JSON：

```json
{"action": "answer", "sample_id": "...", "question": "..."}
```

CLI 程序需要向标准输出返回：

```json
{"prediction": "...", "retrieved_context": [], "metadata": {}}
```

## 13. Python Agent：agents/python.py

文件：

```text
benchmarks/agents/python.py
```

适合本地 Python 类。

配置示例：

```toml
[agent]
type = "python"
module = "custom_agents.my_agent"
class_name = "MyBenchmarkAgent"
```

它会动态执行：

```python
module = importlib.import_module(config.module)
adapter_class = getattr(module, config.class_name)
```

自定义类需要实现：

```python
reset(sample_id)
ingest(sample)
answer(sample, question)
close()  # 可选
```

`answer()` 必须返回 `BenchmarkPrediction`。

## 14. LoCoMo 指标：metrics/locomo.py

文件：

```text
benchmarks/metrics/locomo.py
```

该文件只保留官方评测通道，不再使用本地轻量复刻指标。

官方脚本路径：

```text
../locomo/task_eval/evaluation.py
```

调用方式：

```python
evaluation.eval_question_answering(
    qas,
    eval_key="prediction",
    metric="f1"
)
```

在调用前，benchmark 会把内部 record 转成 LoCoMo 官方 QA 格式：

```python
{
  "question": "...",
  "answer": "...",
  "evidence": ["D1:6", "D1:7"],
  "category": 4,
  "prediction": "模型输出",
  "prediction_context": ["D1:1", "D1:4"]
}
```

其中 `prediction_context` 来自 `retrieved_context`。代码会从上下文文本中提取 turn id：

```python
r"\bD\d+:\d+\b"
```

例如：

```text
[message=D1:6] Gina: ...
```

会提取：

```text
D1:6
```

官方脚本返回后写回 record：

```python
record["score"] = float(score)
record["retrieval_recall"] = float(recall)
record["metric_source"] = eval_script_path
record["official_qa"] = qa
```

## 15. 聚合指标：metrics/common.py

文件：

```text
benchmarks/metrics/common.py
```

作用是对所有 QA record 求平均。

输出：

```json
{
  "total_questions": 44,
  "overall": {
    "score": 0.0119,
    "retrieval_recall": 0.0454
  },
  "by_question_type": {
    "single-hop": {
      "count": 44,
      "score": 0.0119,
      "retrieval_recall": 0.0454
    }
  }
}
```

## 16. 报告输出：reports/writer.py

文件：

```text
benchmarks/reports/writer.py
```

负责生成输出文件。

| 文件 | 生成函数 | 说明 |
|---|---|---|
| `predictions.jsonl` | `write_predictions()` | 每个 QA 一行明细 |
| `metrics.json` | `write_metrics()` | 聚合指标和配置快照 |
| `report.md` | `write_report()` | 人类可读报告 |
| `interface_schema.md` | `write_interface_schema()` | 接口格式说明 |
| `official_hypotheses.jsonl` | `write_official_hypotheses()` | LongMemEval 官方评分输入 |

LoCoMo 不生成 `official_hypotheses.jsonl`，因为 LoCoMo 是在 benchmark 内部直接调用官方 `evaluation.py`。

LongMemEval 会生成 `official_hypotheses.jsonl`，后续交给原仓库 `evaluate_qa.py` 评分。

## 17. 输出文件字段

### 17.1 predictions.jsonl

每行一个 QA：

```json
{
  "dataset": "locomo",
  "split": "locomo10",
  "sample_id": "conv-30",
  "question_id": "conv-30:qa_2",
  "question_type": "single-hop",
  "question": "...",
  "prediction": "...",
  "gold_answers": ["..."],
  "score": 0.0,
  "retrieval_recall": 0.0,
  "evidence": ["D1:6", "D1:7"],
  "retrieved_context": ["..."],
  "agent_type": "memoli",
  "agent_metadata": {},
  "metadata": {}
}
```

### 17.2 metrics.json

包含：

```text
dataset
split
total_samples
metric_source
total_questions
overall
by_question_type
config
```

### 17.3 report.md

报告由代码模板生成，不是 LLM 生成。它读取：

```text
config
metrics
records
provider_warning
```

然后写出配置摘要、总体指标、指标来源、输出文件、按类型分数、低分样例。

## 18. 一次 LoCoMo 测评完整链路

```text
1. run.py 读取 benchmarks/config.locomo.toml
2. LocomoDatasetAdapter 读取 locomo10.json
3. 转成 BenchmarkSample / BenchmarkQuestion
4. registry 根据 agent.type 创建 MemoliAgentAdapter
5. agent.reset(sample_id)
6. agent.ingest(sample)
   - memory_write: 直接写 MEMORY.md
   - agent_turn: 逐条发给 Agent
7. agent.answer(question)
   - 先 memory query 得到 retrieved_context
   - 再调用 Memoli Agent 回答
8. _record() 生成 record
9. metrics/locomo.py 调官方 evaluation.py
10. metrics/common.py 聚合平均分
11. reports/writer.py 写结果文件
```

## 19. 一次 LongMemEval 测评完整链路

```text
1. run.py 读取 config.longmemeval_*.toml
2. LongMemEvalDatasetAdapter 读取数据
3. 转成 BenchmarkSample
4. 创建 Agent
5. reset / ingest / answer
6. 写 predictions.jsonl
7. 写 official_hypotheses.jsonl
8. 手动调用 LongMemEval 原仓库 evaluate_qa.py 评分
```

官方评分命令示例：

```powershell
Push-Location ../LongMemEval/src/evaluation
python evaluate_qa.py `
  gpt-4o-mini `
  ../../../Memoli-agent/workspace/benchmark/results/longmemeval/s/<run_id>/official_hypotheses.jsonl `
  ../../data/longmemeval_s_cleaned.json
Pop-Location
```

## 20. 常见运行命令

LoCoMo 小样本：

```powershell
conda activate memoli
python -m benchmarks.run `
  --config benchmarks/config.locomo.toml `
  --dataset.sample_size 1 `
  --dataset.question_types single-hop
```

LoCoMo 全配置运行：

```powershell
python -m benchmarks.run --config benchmarks/config.locomo.toml
```

LongMemEval_S：

```powershell
python -m benchmarks.run --config benchmarks/config.longmemeval_s.toml
```

临时切换注入模式：

```powershell
python -m benchmarks.run `
  --config benchmarks/config.locomo.toml `
  --agent.ingest_mode agent_turn
```

## 21. 关键设计点

### 21.1 benchmark 不评价 Agent 内部如何记忆

benchmark 只关心：

```text
历史是否已交给 Agent
Agent 是否给出答案
答案是否被官方指标判定正确
检索上下文是否命中官方 evidence
```

至于 Agent 内部用 Markdown、向量库、数据库、摘要、图谱还是其他机制，benchmark 不做假设。

### 21.2 LoCoMo recall 依赖 evidence id 对齐

Memoli 的 `memory_write` 会把 LoCoMo turn id 写入内容：

```text
[message=D1:6]
```

后续评测时会从 `retrieved_context` 中提取 `D1:6`，与官方 `evidence` 比较。

### 21.3 EchoProvider 不能作为真实分数

如果 `predictions.jsonl` 中出现：

```json
"provider": "echo"
```

或者报告中出现 EchoProvider 警告，说明没有真实调用 LLM，只能说明流程跑通，不能说明 Agent 能力。

## 22. 未来可扩展方向

当前架构已经支持多个 Agent 和多个数据集。后续可扩展：

1. 给 Memoli 增加 embedding retriever，提高 LoCoMo evidence recall。
2. 给 LongMemEval 增加内置 judge 调用。
3. 给 `reports/` 增加 HTML 报告。
4. 增加 token、耗时、成本统计。
5. 增加更细粒度错误分析，如按距离、session、evidence 数量统计。
6. 增加 Agent 注入日志，记录每条历史对话是否被 Agent 学习或写入记忆。
