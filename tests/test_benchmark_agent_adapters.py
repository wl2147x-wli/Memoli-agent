from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from benchmarks.agents import create_agent_adapter
from benchmarks.config import AgentBenchmarkConfig
from benchmarks.datasets.base import (
    BenchmarkMessage,
    BenchmarkPrediction,
    BenchmarkQuestion,
    BenchmarkSample,
    BenchmarkSession,
)


def _sample() -> BenchmarkSample:
    return BenchmarkSample(
        id="sample-1",
        sessions=[
            BenchmarkSession(
                id="session-1",
                messages=[
                    BenchmarkMessage(
                        id="m1",
                        role="user",
                        speaker="Alice",
                        content="Alice likes tea.",
                    )
                ],
            )
        ],
        questions=[
            BenchmarkQuestion(
                id="q1",
                question="What does Alice like?",
                gold_answers=["tea"],
                question_type="single-hop",
            )
        ],
    )


def test_python_agent_adapter_loads_custom_class(tmp_path: Path) -> None:
    module_path = tmp_path / "dummy_agent.py"
    module_path.write_text(
        """
from benchmarks.datasets.base import BenchmarkPrediction

class DummyAgent:
    def __init__(self, config, dataset_name, split):
        self.dataset_name = dataset_name
        self.split = split

    async def reset(self, sample_id):
        self.sample_id = sample_id

    async def ingest(self, sample):
        self.sample = sample

    async def answer(self, sample, question):
        return BenchmarkPrediction(
            sample_id=sample.id,
            question_id=question.id,
            prediction="tea",
            gold_answers=question.gold_answers,
            metadata={"agent_metadata": {"backend": "dummy-python"}},
        )
""".strip(),
        encoding="utf-8",
    )
    sys.path.insert(0, str(tmp_path))
    try:
        adapter = create_agent_adapter(
            AgentBenchmarkConfig(
                type="python", module="dummy_agent", class_name="DummyAgent"
            ),
            dataset_name="locomo",
            split="test",
        )
        sample = _sample()
        import asyncio

        asyncio.run(adapter.reset(sample.id))
        asyncio.run(adapter.ingest(sample))
        prediction = asyncio.run(adapter.answer(sample, sample.questions[0]))
    finally:
        sys.path.remove(str(tmp_path))

    assert isinstance(prediction, BenchmarkPrediction)
    assert prediction.prediction == "tea"
    assert prediction.metadata["agent_metadata"]["backend"] == "dummy-python"


def test_cli_agent_adapter_reads_json_and_returns_prediction(tmp_path: Path) -> None:
    script = tmp_path / "dummy_cli.py"
    script.write_text(
        """
import json
import sys

payload = json.loads(sys.stdin.read())
if payload["action"] == "answer":
    print(json.dumps({"prediction": "tea", "retrieved_context": ["m1"]}))
else:
    print("{}")
""".strip(),
        encoding="utf-8",
    )
    adapter = create_agent_adapter(
        AgentBenchmarkConfig(
            type="cli",
            command=f'"{sys.executable}" "{script}"',
            timeout_seconds=30,
        ),
        dataset_name="locomo",
        split="test",
    )
    sample = _sample()

    import asyncio

    asyncio.run(adapter.reset(sample.id))
    asyncio.run(adapter.ingest(sample))
    prediction = asyncio.run(adapter.answer(sample, sample.questions[0]))

    assert prediction.prediction == "tea"
    assert prediction.retrieved_context == ["m1"]


def test_http_agent_adapter_posts_reset_ingest_answer() -> None:
    calls: list[tuple[str, dict]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers["Content-Length"])
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            calls.append((self.path, payload))
            body = b"{}"
            if self.path == "/answer":
                body = json.dumps({"prediction": "tea"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return None

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        adapter = create_agent_adapter(
            AgentBenchmarkConfig(type="http", base_url=f"http://{host}:{port}"),
            dataset_name="locomo",
            split="test",
        )
        sample = _sample()

        import asyncio

        asyncio.run(adapter.reset(sample.id))
        asyncio.run(adapter.ingest(sample))
        prediction = asyncio.run(adapter.answer(sample, sample.questions[0]))
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert prediction.prediction == "tea"
    assert [path for path, _ in calls] == ["/reset", "/ingest", "/answer"]
    assert calls[1][1]["sessions"][0]["messages"][0]["content"] == "Alice likes tea."
