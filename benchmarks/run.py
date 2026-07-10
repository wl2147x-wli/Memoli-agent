"""Command line entrypoint for memory-agent benchmarks."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from benchmarks.agents import create_agent_adapter
from benchmarks.config import apply_overrides, load_benchmark_config
from benchmarks.datasets.base import BenchmarkPrediction, BenchmarkQuestion
from benchmarks.datasets.locomo import LocomoDatasetAdapter
from benchmarks.datasets.longmemeval import LongMemEvalDatasetAdapter
from benchmarks.metrics.common import aggregate
from benchmarks.metrics.locomo import DEFAULT_LOCOMO_EVAL_SCRIPT, evaluate_locomo_official
from benchmarks.reports.writer import ReportWriter


async def main() -> None:
    args = _parse_args()
    config = load_benchmark_config(args.config)
    apply_overrides(config, args.overrides)
    result = await run_benchmark(config)
    print(f"Saved benchmark outputs to {result}")


async def run_benchmark(config) -> Path:
    samples = _build_dataset_adapter(config).load()
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = (
        Path(config.output.dir)
        / config.dataset.name
        / config.dataset.split
        / run_id
    )
    writer = ReportWriter(output_dir)
    agent = create_agent_adapter(
        config=config.agent,
        dataset_name=config.dataset.name,
        split=config.dataset.split,
    )

    records: list[dict[str, Any]] = []
    provider_warning = False
    try:
        for sample in samples:
            await agent.reset(sample.id)
            await agent.ingest(sample)
            for question in sample.questions:
                prediction = await agent.answer(sample, question)
                record = _record(config, sample.id, question, prediction)
                records.append(record)
                provider_warning = provider_warning or _has_provider_warning(record)
    finally:
        await agent.close()

    metric_source = None
    if config.dataset.name == "locomo":
        metric_source = DEFAULT_LOCOMO_EVAL_SCRIPT
        evaluate_locomo_official(records, metric_source)

    metrics = {
        "dataset": config.dataset.name,
        "split": config.dataset.split,
        "total_samples": len(samples),
        "metric_source": metric_source,
        **aggregate(records),
        "config": asdict(config),
    }

    if config.output.save_predictions:
        writer.write_predictions(records)
        if config.dataset.name == "longmemeval":
            writer.write_official_hypotheses(records)
    if config.output.save_metrics:
        writer.write_metrics(metrics)
    writer.write_interface_schema()
    if config.output.save_report:
        writer.write_report(config, metrics, records, provider_warning)
    return output_dir


def _build_dataset_adapter(config):
    name = config.dataset.name.lower()
    if name == "locomo":
        return LocomoDatasetAdapter(config.dataset)
    if name == "longmemeval":
        return LongMemEvalDatasetAdapter(config.dataset)
    raise ValueError(f"Unsupported dataset.name: {config.dataset.name}")


def _record(
    config,
    sample_id: str,
    question: BenchmarkQuestion,
    prediction: BenchmarkPrediction,
) -> dict[str, Any]:
    score = None
    recall = None
    return {
        "dataset": config.dataset.name,
        "split": config.dataset.split,
        "sample_id": sample_id,
        "question_id": question.id,
        "question_type": question.question_type,
        "question": question.question,
        "prediction": prediction.prediction,
        "gold_answers": question.gold_answers,
        "score": score,
        "retrieval_recall": recall,
        "evidence": question.evidence,
        "retrieved_context": prediction.retrieved_context,
        "agent_type": config.agent.type,
        "agent_metadata": prediction.metadata.get("agent_metadata", {}),
        "metadata": {
            **prediction.metadata,
            "question_metadata": question.metadata,
        },
    }


def _has_provider_warning(record: dict[str, Any]) -> bool:
    metadata = record.get("metadata", {})
    provider = str(metadata.get("provider", "")).lower()
    return provider in {"echo", "error"} or bool(metadata.get("fallback_used"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Memoli benchmarks.")
    parser.add_argument("--config", required=True, help="Path to benchmark TOML config.")
    args, overrides = parser.parse_known_args()
    args.overrides = overrides
    return args


if __name__ == "__main__":
    asyncio.run(main())
