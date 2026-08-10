"""Dynamic Python benchmark agent adapter."""

from __future__ import annotations

import importlib
from typing import Any

from benchmarks.config import AgentBenchmarkConfig
from benchmarks.datasets.base import (
    BenchmarkPrediction,
    BenchmarkQuestion,
    BenchmarkSample,
)

from .base import maybe_await


class PythonAgentAdapter:
    def __init__(
        self,
        config: AgentBenchmarkConfig,
        dataset_name: str,
        split: str,
    ) -> None:
        if not config.module or not config.class_name:
            raise ValueError(
                "agent.module and agent.class_name are required when "
                "agent.type = 'python'."
            )
        module = importlib.import_module(config.module)
        adapter_class = getattr(module, config.class_name)
        self.inner = _instantiate(adapter_class, config, dataset_name, split)

    async def reset(self, sample_id: str) -> None:
        await maybe_await(self.inner.reset(sample_id))

    async def ingest(self, sample: BenchmarkSample) -> None:
        await maybe_await(self.inner.ingest(sample))

    async def answer(
        self, sample: BenchmarkSample, question: BenchmarkQuestion
    ) -> BenchmarkPrediction:
        result = await maybe_await(self.inner.answer(sample, question))
        if not isinstance(result, BenchmarkPrediction):
            raise TypeError("Python agent answer() must return BenchmarkPrediction.")
        return result

    async def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if close is not None:
            await maybe_await(close())


def _instantiate(
    adapter_class: type,
    config: AgentBenchmarkConfig,
    dataset_name: str,
    split: str,
) -> Any:
    attempts = (
        lambda: adapter_class(config=config, dataset_name=dataset_name, split=split),
        lambda: adapter_class(config, dataset_name, split),
        lambda: adapter_class(config=config),
        lambda: adapter_class(config),
        lambda: adapter_class(),
    )
    last_error: TypeError | None = None
    for attempt in attempts:
        try:
            return attempt()
        except TypeError as error:
            last_error = error
    raise TypeError(f"Could not instantiate Python agent adapter: {last_error}")
