from __future__ import annotations

import json
import asyncio
from pathlib import Path

from benchmarks.config import load_benchmark_config
from benchmarks.run import run_benchmark


def test_echo_dry_run_writes_outputs(tmp_path: Path) -> None:
    dataset_path = tmp_path / "longmemeval.json"
    dataset_path.write_text(
        json.dumps(
            [
                {
                    "question_id": "q1",
                    "question_type": "single-session-user",
                    "question": "What does Alice like?",
                    "answer": "tea",
                    "question_date": "2023/01/02 10:00",
                    "haystack_dates": ["2023/01/01 10:00"],
                    "haystack_session_ids": ["s1"],
                    "haystack_sessions": [
                        [{"role": "user", "content": "Alice likes tea.", "has_answer": True}]
                    ],
                    "answer_session_ids": ["s1"],
                }
            ]
        ),
        encoding="utf-8",
    )
    app_config = tmp_path / "config.benchmark.toml"
    app_config.write_text(
        """
[runtime]
workspace = "workspace"
[llm]
provider = "echo"
model = "echo"
api_key = ""
base_url = ""
[memory]
enabled = true
path = "workspace/memory"
[channels.cli]
enabled = false
[plugins]
enabled = []
[subagent]
enabled = false
[proactive]
enabled = false
[mcp]
enabled = false
""".strip(),
        encoding="utf-8",
    )
    bench_config = tmp_path / "bench.toml"
    output_dir = tmp_path / "results"
    workspace_root = tmp_path / "workspace"
    bench_config.write_text(
        f"""
[dataset]
name = "longmemeval"
path = "{dataset_path.as_posix()}"
split = "test"
sample_size = 1
seed = 1
question_types = ["single-session-user"]
max_sessions = 0
[agent]
config_path = "{app_config.as_posix()}"
workspace_root = "{workspace_root.as_posix()}"
reset_memory_per_sample = true
ingest_mode = "memory_write"
answer_mode = "agent_turn"
capture_retrieved_context = true
[metrics]
primary = "f1"
include_retrieval_recall = true
judge_enabled = false
judge_model = "gpt-4o-mini"
[output]
dir = "{output_dir.as_posix()}"
save_predictions = true
save_metrics = true
save_report = true
""",
        encoding="utf-8",
    )

    result_dir = asyncio.run(run_benchmark(load_benchmark_config(bench_config)))

    assert (result_dir / "predictions.jsonl").exists()
    assert (result_dir / "metrics.json").exists()
    assert (result_dir / "report.md").exists()
    assert (result_dir / "interface_schema.md").exists()
    assert (result_dir / "official_hypotheses.jsonl").exists()
    assert (workspace_root / "longmemeval" / "test" / "q1" / "memory" / "MEMORY.md").exists()
