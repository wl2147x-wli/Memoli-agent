"""Benchmark configuration loading."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class DatasetConfig:
    name: str
    path: str
    split: str = "default"
    sample_size: int = 0
    seed: int = 42
    question_types: list[str] = field(default_factory=list)
    max_sessions: int = 0


@dataclass(slots=True)
class AgentBenchmarkConfig:
    type: str = "memoli"
    # Memoli/Python adapter fields.
    config_path: str = "config.benchmark.toml"
    workspace_root: str = "workspace/benchmark"
    module: str = ""
    class_name: str = ""
    # Generic adapter behavior.
    reset_per_sample: bool = True
    reset_memory_per_sample: bool = True
    ingest_mode: str = "memory_write"
    answer_mode: str = "agent_turn"
    capture_retrieved_context: bool = True
    # HTTP adapter fields.
    base_url: str = ""
    reset_endpoint: str = "/reset"
    ingest_endpoint: str = "/ingest"
    answer_endpoint: str = "/answer"
    # CLI adapter fields.
    command: str = ""
    input_format: str = "json"
    timeout_seconds: int = 300


@dataclass(slots=True)
class MetricsConfig:
    primary: str = "f1"
    include_retrieval_recall: bool = True
    judge_enabled: bool = False
    judge_model: str = "gpt-4o-mini"
    # 可选：记忆学习分层评估（候选有效率/激活率/遵循率/留出增益）。
    # 未启用时不影响 LoCoMo/LongMemEval 官方评分。
    layered_memory: bool = False


@dataclass(slots=True)
class OutputConfig:
    dir: str = "workspace/benchmark/results"
    save_predictions: bool = True
    save_metrics: bool = True
    save_report: bool = True


@dataclass(slots=True)
class BenchmarkConfig:
    dataset: DatasetConfig
    agent: AgentBenchmarkConfig = field(default_factory=AgentBenchmarkConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    output: OutputConfig = field(default_factory=OutputConfig)


def load_benchmark_config(path: str | Path) -> BenchmarkConfig:
    config_path = Path(path)
    with config_path.open("rb") as file:
        raw = tomllib.load(file)

    if "dataset" not in raw:
        raise ValueError("benchmark config must include [dataset].")

    return BenchmarkConfig(
        dataset=DatasetConfig(**_table(raw, "dataset")),
        agent=AgentBenchmarkConfig(**_table(raw, "agent")),
        metrics=MetricsConfig(**_table(raw, "metrics")),
        output=OutputConfig(**_table(raw, "output")),
    )


def apply_overrides(config: BenchmarkConfig, overrides: list[str]) -> None:
    if len(overrides) % 2 != 0:
        raise ValueError("Overrides must be passed as --section.key value pairs.")

    for key, value in zip(overrides[0::2], overrides[1::2], strict=True):
        dotted = key.removeprefix("--")
        section_name, field_name = dotted.split(".", 1)
        section = getattr(config, section_name)
        current = getattr(section, field_name)
        setattr(section, field_name, _coerce_value(value, current))


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise TypeError(f"{key!r} must be a TOML table.")
    return value


def _coerce_value(raw: str, current: Any) -> Any:
    if isinstance(current, bool):
        return raw.lower() in {"1", "true", "yes", "on"}
    if isinstance(current, int):
        return int(raw)
    if isinstance(current, list):
        return [part.strip() for part in raw.split(",") if part.strip()]
    return raw
