# Memoli-agent 多测评集与通用 Agent 接入说明

本文说明当前 `benchmarks/` 如何接入 LoCoMo、LongMemEval，并如何把测评对象从 Memoli 切换成任意 Agent。

benchmark 层只负责四件事：

1. 把测评集原始数据转换成统一样本对象。
2. 按统一协议把历史对话交给 Agent。
3. 把问题交给 Agent 并收集答案。
4. 调用官方评测通道或输出官方可评分文件。

benchmark 不依赖具体 Agent 的内部记忆实现。Memoli 只是其中一个 adapter；HTTP 服务、CLI 程序、本地 Python 类也可以按同一接口接入。

## 1. 本地资源

推荐的项目相对布局：

```text
Memoli-agent/
../locomo/data/locomo10.json
../locomo/task_eval/evaluation.py
../LongMemEval/data/longmemeval_oracle.json
../LongMemEval/data/longmemeval_s_cleaned.json
../LongMemEval/data/longmemeval_m_cleaned.json
../LongMemEval/src/evaluation/evaluate_qa.py
```

当前 benchmark 输出目录：

```text
workspace/benchmark/results
```

## 2. 当前目录结构

```text
Memoli-agent/
  config.benchmark.toml
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

## 3. 统一数据对象

数据集 adapter 会把 LoCoMo / LongMemEval 转成统一对象：

```python
BenchmarkMessage(id, role, speaker, content, timestamp, metadata)
BenchmarkSession(id, messages, timestamp, metadata)
BenchmarkQuestion(id, question, gold_answers, timestamp, question_type, evidence, metadata)
BenchmarkSample(id, sessions, questions, metadata)
BenchmarkPrediction(sample_id, question_id, prediction, gold_answers, retrieved_context, metadata)
```

## 4. 通用 Agent 接口

所有 Agent 后端都实现同一接口：

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
| `reset(sample_id)` | 开始一个新样本；如果配置开启隔离，应清空或切换到该样本独立状态。 |
| `ingest(sample)` | 把该样本的历史 sessions/messages 交给 Agent。具体如何记忆由 Agent 自己决定。 |
| `answer(sample, question)` | 向 Agent 提问，返回文本预测和可选检索上下文。 |
| `close()` | 运行结束时释放资源。 |

## 5. Agent 类型切换

通过 `[agent].type` 切换后端：

| `agent.type` | 适用场景 |
|---|---|
| `memoli` | 当前本地 Memoli Python runtime。 |
| `http` | 任意远程 Agent 服务。 |
| `cli` | 任意命令行 Agent。 |
| `python` / `custom` | 任意本地 Python adapter 类。 |

### 5.1 Memoli

```toml
[agent]
type = "memoli"
config_path = "config.benchmark.toml"
workspace_root = "workspace/benchmark"
reset_per_sample = true
reset_memory_per_sample = true
ingest_mode = "memory_write"
answer_mode = "agent_turn"
capture_retrieved_context = true
```

说明：

- `memory_write`：benchmark 直接把历史消息写入 Memoli 记忆，速度快、成本低，适合流程验证和基线。
- `agent_turn`：把历史消息作为普通输入喂给 Memoli，是否形成长期记忆取决于 Memoli 自身逻辑。
- `answer_mode = "agent_turn"`：QA 阶段通过 Memoli 正常 `AgentRunner.handle_inbound()` 获得答案。

### 5.2 HTTP Agent

```toml
[agent]
type = "http"
base_url = "http://localhost:8000"
reset_endpoint = "/benchmark/reset"
ingest_endpoint = "/benchmark/ingest"
answer_endpoint = "/benchmark/answer"
reset_per_sample = true
timeout_seconds = 300
```

HTTP adapter 会对三个 endpoint 发起 `POST`，请求和响应均为 JSON。

`ingest` 输入：

```json
{
  "sample_id": "conv-30",
  "metadata": {},
  "sessions": [
    {
      "session_id": "session_1",
      "timestamp": "...",
      "metadata": {},
      "messages": [
        {
          "id": "D1:3",
          "role": "user",
          "speaker": "Alice",
          "content": "...",
          "timestamp": "...",
          "metadata": {}
        }
      ]
    }
  ]
}
```

`answer` 输入：

```json
{
  "sample_id": "conv-30",
  "question_id": "conv-30:qa_2",
  "question": "...",
  "question_type": "single-hop",
  "timestamp": "...",
  "gold_answers": ["..."],
  "evidence": ["D1:3"],
  "metadata": {}
}
```

`answer` 输出：

```json
{
  "prediction": "模型输出",
  "retrieved_context": ["可选检索上下文"],
  "metadata": {
    "model": "...",
    "latency_ms": 1234
  }
}
```

### 5.3 CLI Agent

```toml
[agent]
type = "cli"
command = "python D:/path/to/agent_cli.py"
input_format = "json"
reset_per_sample = true
timeout_seconds = 300
```

CLI adapter 会把 JSON 写入标准输入，并从标准输出读取 JSON。

每次调用会带上：

```json
{"action": "reset", "sample_id": "..."}
{"action": "ingest", "sample_id": "...", "sessions": []}
{"action": "answer", "sample_id": "...", "question": "..."}
```

`answer` 时需要输出：

```json
{"prediction": "模型输出", "retrieved_context": [], "metadata": {}}
```

### 5.4 Python Agent

```toml
[agent]
type = "python"
module = "custom_agents.my_agent"
class_name = "MyBenchmarkAgent"
reset_per_sample = true
```

自定义类需要实现 `reset / ingest / answer / close`。其中 `close` 可选，`answer` 必须返回 `BenchmarkPrediction`。

## 6. LoCoMo 接入

推荐配置：

```powershell
python -m benchmarks.run --config benchmarks/config.locomo.toml
```

LoCoMo 类型映射：

| 原始 `qa.category` | 统一 `question_type` |
|---:|---|
| 1 | `multi-hop` |
| 2 | `temporal` |
| 3 | `open-domain` |
| 4 | `single-hop` |
| 5 | `adversarial` |

LoCoMo 指标只走官方脚本：

```text
../locomo/task_eval/evaluation.py
```

benchmark 会把预测重组成官方 QA 格式：

```python
{
  "question": "...",
  "answer": "...",
  "evidence": ["D1:3"],
  "category": 4,
  "prediction": "模型输出",
  "prediction_context": ["D1:3"]
}
```

然后调用 `eval_question_answering(qas, eval_key="prediction", metric="f1")`，将官方返回的分数写入 `score` 和 `retrieval_recall`。

## 7. LongMemEval 接入

运行 Oracle：

```powershell
python -m benchmarks.run --config benchmarks/config.longmemeval_oracle.toml
```

运行 S：

```powershell
python -m benchmarks.run --config benchmarks/config.longmemeval_s.toml
```

运行 M 小样本：

```powershell
python -m benchmarks.run `
  --config benchmarks/config.longmemeval_m.toml `
  --dataset.sample_size 1 `
  --dataset.question_types single-session-user
```

LongMemEval 当前输出官方可评分文件：

```text
official_hypotheses.jsonl
```

格式：

```json
{"question_id": "...", "hypothesis": "模型输出"}
```

官方评分示例：

```powershell
Push-Location ../LongMemEval/src/evaluation
python evaluate_qa.py `
  gpt-4o-mini `
  ../../../Memoli-agent/workspace/benchmark/results/longmemeval/s/<run_id>/official_hypotheses.jsonl `
  ../../data/longmemeval_s_cleaned.json
Pop-Location
```

## 8. 输出文件

每次运行输出到：

```text
workspace/benchmark/results/<dataset>/<split>/<run_id>/
```

主要文件：

| 文件 | 含义 |
|---|---|
| `predictions.jsonl` | 每个 QA 的统一预测记录。 |
| `metrics.json` | 聚合指标、配置快照、官方指标来源。 |
| `report.md` | 可读报告。 |
| `interface_schema.md` | 当前接口格式说明。 |
| `official_hypotheses.jsonl` | LongMemEval 官方评分输入。 |

`predictions.jsonl` 每行示例：

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
  "retrieval_recall": 1.0,
  "evidence": ["D1:3"],
  "retrieved_context": ["..."],
  "agent_type": "memoli",
  "agent_metadata": {},
  "metadata": {}
}
```

## 9. 常见问题

### 9.1 benchmark 会评价 Agent 如何记忆吗？

不会。benchmark 只评价最终 QA 输出。历史如何学习、如何压缩、如何检索，是 Agent 自己的内部策略。

### 9.2 如何避免样本串记忆？

开启：

```toml
reset_per_sample = true
```

Memoli adapter 还会使用：

```toml
reset_memory_per_sample = true
```

并为每个 sample 创建独立 workspace。

### 9.3 EchoProvider 能作为真实分数吗？

不能。EchoProvider 只能验证流程是否跑通，不能代表模型长期记忆能力。报告中如果检测到 Echo、error provider 或 fallback，会提示结果不能作为真实分数。

### 9.4 LongMemEval_M 为什么先跑小样本？

`longmemeval_m_cleaned.json` 很大，每个样本包含大量历史 sessions。建议先用 `sample_size=1` 验证流程，再扩大规模。

## 10. 验收清单

- [ ] 切换 `[agent].type` 后，数据集读取和输出格式不变。
- [ ] Memoli adapter 能继续跑通 LoCoMo / LongMemEval 小样本。
- [ ] HTTP adapter 能通过 mock 服务完成 reset / ingest / answer。
- [ ] CLI adapter 能通过 stdin/stdout JSON 完成 answer。
- [ ] Python adapter 能动态加载自定义类。
- [ ] LoCoMo 分数来自官方 `evaluation.py`。
- [ ] LongMemEval 生成官方 `official_hypotheses.jsonl`。
