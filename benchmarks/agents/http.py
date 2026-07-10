"""HTTP benchmark agent adapter."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib import request

from benchmarks.config import AgentBenchmarkConfig
from benchmarks.datasets.base import BenchmarkPrediction, BenchmarkQuestion, BenchmarkSample

from .base import prediction_from_payload, question_to_payload, sample_to_payload


class HttpAgentAdapter:
    def __init__(self, config: AgentBenchmarkConfig) -> None:
        if not config.base_url:
            raise ValueError("agent.base_url is required when agent.type = 'http'.")
        self.config = config
        self.base_url = config.base_url.rstrip("/")

    async def reset(self, sample_id: str) -> None:
        if not self.config.reset_per_sample:
            return
        await self._post(self.config.reset_endpoint, {"sample_id": sample_id})

    async def ingest(self, sample: BenchmarkSample) -> None:
        await self._post(self.config.ingest_endpoint, sample_to_payload(sample))

    async def answer(
        self, sample: BenchmarkSample, question: BenchmarkQuestion
    ) -> BenchmarkPrediction:
        payload = await self._post(
            self.config.answer_endpoint, question_to_payload(sample, question)
        )
        return prediction_from_payload(sample, question, payload)

    async def close(self) -> None:
        return None

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._post_sync, endpoint, payload)

    def _post_sync(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
            raw = response.read().decode("utf-8")
        if not raw.strip():
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError(f"HTTP agent endpoint returned non-object JSON: {url}")
        return data
