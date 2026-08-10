"""CLI benchmark agent adapter."""

from __future__ import annotations

import asyncio
import json
import subprocess
from typing import Any

from benchmarks.config import AgentBenchmarkConfig
from benchmarks.datasets.base import (
    BenchmarkPrediction,
    BenchmarkQuestion,
    BenchmarkSample,
)

from .base import prediction_from_payload, question_to_payload, sample_to_payload


class CliAgentAdapter:
    def __init__(self, config: AgentBenchmarkConfig) -> None:
        if not config.command:
            raise ValueError("agent.command is required when agent.type = 'cli'.")
        if config.input_format.lower() != "json":
            raise ValueError("Only agent.input_format = 'json' is supported.")
        self.config = config

    async def reset(self, sample_id: str) -> None:
        if not self.config.reset_per_sample:
            return
        await self._invoke({"action": "reset", "sample_id": sample_id})

    async def ingest(self, sample: BenchmarkSample) -> None:
        await self._invoke({"action": "ingest", **sample_to_payload(sample)})

    async def answer(
        self, sample: BenchmarkSample, question: BenchmarkQuestion
    ) -> BenchmarkPrediction:
        payload = await self._invoke(
            {"action": "answer", **question_to_payload(sample, question)}
        )
        return prediction_from_payload(sample, question, payload)

    async def close(self) -> None:
        return None

    async def _invoke(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._invoke_sync, payload)

    def _invoke_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        completed = subprocess.run(
            self.config.command,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            encoding="utf-8",
            shell=True,
            timeout=self.config.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "CLI agent command failed "
                f"with exit code {completed.returncode}: {completed.stderr.strip()}"
            )
        stdout = completed.stdout.strip()
        if not stdout:
            return {}
        data = json.loads(stdout)
        if not isinstance(data, dict):
            raise TypeError("CLI agent returned non-object JSON.")
        return data
