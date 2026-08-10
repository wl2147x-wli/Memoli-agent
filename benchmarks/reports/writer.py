"""Benchmark output writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from benchmarks.config import BenchmarkConfig


class ReportWriter:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_predictions(self, records: list[dict[str, Any]]) -> Path:
        path = self.output_dir / "predictions.jsonl"
        _write_jsonl(path, records)
        return path

    def write_official_hypotheses(self, records: list[dict[str, Any]]) -> Path:
        path = self.output_dir / "official_hypotheses.jsonl"
        official = [
            {"question_id": record["question_id"], "hypothesis": record["prediction"]}
            for record in records
        ]
        _write_jsonl(path, official)
        return path

    def write_metrics(self, metrics: dict[str, Any]) -> Path:
        path = self.output_dir / "metrics.json"
        content = json.dumps(metrics, ensure_ascii=False, indent=2)
        path.write_text(content, encoding="utf-8")
        return path

    def write_interface_schema(self) -> Path:
        path = self.output_dir / "interface_schema.md"
        path.write_text(_interface_schema_text(), encoding="utf-8")
        return path

    def write_report(
        self,
        config: BenchmarkConfig,
        metrics: dict[str, Any],
        records: list[dict[str, Any]],
        provider_warning: bool,
    ) -> Path:
        path = self.output_dir / "report.md"
        lines = [
            f"# Benchmark Report: {config.dataset.name} / {config.dataset.split}",
            "",
            "## 配置摘要",
            "",
            f"- dataset.path: `{config.dataset.path}`",
            f"- sample_size: `{config.dataset.sample_size}`",
            f"- question_types: `{config.dataset.question_types}`",
            f"- agent.type: `{config.agent.type}`",
            f"- ingest_mode: `{config.agent.ingest_mode}`",
            f"- answer_mode: `{config.agent.answer_mode}`",
            "",
            "## 总体指标",
            "",
            f"- total_questions: `{metrics.get('total_questions')}`",
            f"- overall score: `{metrics.get('overall', {}).get('score')}`",
            "- retrieval recall: "
            f"`{metrics.get('overall', {}).get('retrieval_recall')}`",
            "",
        ]
        if provider_warning:
            lines += [
                "> 警告：本次运行出现 EchoProvider、error provider 或 fallback，"
                "结果不能作为真实测评分数。",
                "",
            ]

        if metrics.get("metric_source"):
            lines += [
                "## 指标来源",
                "",
                f"- metric_source: `{metrics['metric_source']}`",
                "",
            ]

        lines += [
            "## 输出文件",
            "",
            "- `predictions.jsonl`：统一预测明细。",
            "- `metrics.json`：聚合指标。",
            "- `report.md`：当前可读报告。",
            "- `interface_schema.md`：当前测评接口主要格式架构。",
            "",
            "## 按问题类型",
            "",
        ]
        for qtype, item in metrics.get("by_question_type", {}).items():
            lines.append(
                f"- `{qtype}`: count={item['count']}, "
                f"score={item['score']}, recall={item['retrieval_recall']}"
            )

        lines += ["", "## 低分样例", ""]
        low_records = [
            record
            for record in records
            if record.get("score") is not None and record.get("score", 1.0) < 0.5
        ][:5]
        if not low_records:
            lines.append("- 无低分样例，或当前数据集未在本地计算 QA score。")
        for record in low_records:
            lines += [
                f"### {record['question_id']}",
                "",
                f"- 类型：`{record['question_type']}`",
                f"- 问题：{record['question']}",
                f"- 预测：{record['prediction']}",
                f"- 标准答案：{record['gold_answers']}",
                f"- 分数：{record['score']}",
                "",
            ]

        path.write_text("\n".join(lines), encoding="utf-8")
        return path


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def _interface_schema_text() -> str:
    return """# Benchmark Interface Schema

## 统一 Agent 接口

benchmark 只依赖下面四个方法，不关心具体 Agent 如何记忆、检索、压缩或写文件：

```python
class BenchmarkAgentAdapter:
    async def reset(self, sample_id: str) -> None: ...
    async def ingest(self, sample: BenchmarkSample) -> None: ...
    async def answer(
        self, sample: BenchmarkSample, question: BenchmarkQuestion
    ) -> BenchmarkPrediction: ...
    async def close(self) -> None: ...
```

支持的 `agent.type`：

- `memoli`：调用本地 Memoli Python API。
- `http`：通过 HTTP POST 调用任意远程 Agent 服务。
- `cli`：通过标准输入/输出 JSON 调用命令行 Agent。
- `python` / `custom`：动态加载本地 Python adapter 类。

## 统一数据对象

```python
BenchmarkMessage(id, role, speaker, content, timestamp, metadata)
BenchmarkSession(id, messages, timestamp, metadata)
BenchmarkQuestion(
    id, question, gold_answers, timestamp, question_type, evidence, metadata
)
BenchmarkSample(id, sessions, questions, metadata)
BenchmarkPrediction(
    sample_id, question_id, prediction, gold_answers, retrieved_context, metadata
)
```

## ingest 输入格式

HTTP / CLI adapter 会把样本转成如下 JSON：

```json
{
  "sample_id": "conv-30",
  "metadata": {},
  "sessions": [
    {
      "session_id": "session_1",
      "timestamp": "2023-01-01",
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

CLI adapter 会额外加入 `"action": "ingest"`。

## answer 输入格式

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

CLI adapter 会额外加入 `"action": "answer"`。

## answer 输出格式

HTTP / CLI adapter 期望 Agent 返回 JSON object：

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

`prediction` 也可以用兼容字段 `answer` 表示。

## predictions.jsonl

每行一个 QA 预测：

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

## metrics.json

包含 `dataset`、`split`、`metric_source`、`total_samples`、
`total_questions`、`overall`、`by_question_type` 和 `config`。

## LoCoMo official qa 重组格式

LoCoMo 官方脚本接收的每个 QA：

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

`score` 和 `retrieval_recall` 来自
`D:/wli/project1/locomo/task_eval/evaluation.py` 的
`eval_question_answering()`。

## LongMemEval official_hypotheses.jsonl

LongMemEval 官方 judge 输入：

```json
{"question_id": "...", "hypothesis": "模型输出"}
```
"""
