"""Agent adapter registry."""

from __future__ import annotations

from benchmarks.config import AgentBenchmarkConfig

from .base import BenchmarkAgentAdapter
from .cli import CliAgentAdapter
from .http import HttpAgentAdapter
from .memoli import MemoliAgentAdapter
from .python import PythonAgentAdapter


def create_agent_adapter(
    config: AgentBenchmarkConfig,
    dataset_name: str,
    split: str,
) -> BenchmarkAgentAdapter:
    agent_type = config.type.lower()
    if agent_type == "memoli":
        return MemoliAgentAdapter(config=config, dataset_name=dataset_name, split=split)
    if agent_type == "http":
        return HttpAgentAdapter(config=config)
    if agent_type == "cli":
        return CliAgentAdapter(config=config)
    if agent_type in {"python", "custom"}:
        return PythonAgentAdapter(config=config, dataset_name=dataset_name, split=split)
    raise ValueError(f"Unsupported agent.type: {config.type}")
