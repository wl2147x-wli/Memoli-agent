"""Common benchmark agent adapter protocol and payload helpers."""

from __future__ import annotations

import inspect
from typing import Any, Protocol

from benchmarks.datasets.base import (
    BenchmarkPrediction,
    BenchmarkQuestion,
    BenchmarkSample,
)


class BenchmarkAgentAdapter(Protocol):
    """Minimal interface required by the benchmark runner."""

    async def reset(self, sample_id: str) -> None:
        ...

    async def ingest(self, sample: BenchmarkSample) -> None:
        ...

    async def answer(
        self, sample: BenchmarkSample, question: BenchmarkQuestion
    ) -> BenchmarkPrediction:
        ...

    async def close(self) -> None:
        ...


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def sample_to_payload(sample: BenchmarkSample) -> dict[str, Any]:
    return {
        "sample_id": sample.id,
        "metadata": sample.metadata,
        "sessions": [
            {
                "session_id": session.id,
                "timestamp": session.timestamp,
                "metadata": session.metadata,
                "messages": [
                    {
                        "id": message.id,
                        "role": message.role,
                        "speaker": message.speaker,
                        "content": message.content,
                        "timestamp": message.timestamp,
                        "metadata": message.metadata,
                    }
                    for message in session.messages
                ],
            }
            for session in sample.sessions
        ],
    }


def question_to_payload(
    sample: BenchmarkSample, question: BenchmarkQuestion
) -> dict[str, Any]:
    return {
        "sample_id": sample.id,
        "question_id": question.id,
        "question": question.question,
        "question_type": question.question_type,
        "timestamp": question.timestamp,
        "gold_answers": question.gold_answers,
        "evidence": question.evidence,
        "metadata": question.metadata,
    }


def prediction_from_payload(
    sample: BenchmarkSample,
    question: BenchmarkQuestion,
    payload: dict[str, Any],
) -> BenchmarkPrediction:
    prediction = payload.get("prediction", payload.get("answer", ""))
    retrieved_context = payload.get("retrieved_context", [])
    if retrieved_context is None:
        retrieved_context = []
    if not isinstance(retrieved_context, list):
        retrieved_context = [str(retrieved_context)]

    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {"raw_metadata": metadata}

    return BenchmarkPrediction(
        sample_id=sample.id,
        question_id=question.id,
        prediction=str(prediction),
        gold_answers=question.gold_answers,
        retrieved_context=[str(item) for item in retrieved_context],
        metadata=metadata,
    )
