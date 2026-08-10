"""LongMemEval dataset adapter."""

from __future__ import annotations

import json
import random
import re
from collections.abc import Iterator
from pathlib import Path

from benchmarks.config import DatasetConfig
from benchmarks.datasets.base import (
    BenchmarkMessage,
    BenchmarkQuestion,
    BenchmarkSample,
    BenchmarkSession,
)


class LongMemEvalDatasetAdapter:
    def __init__(self, config: DatasetConfig) -> None:
        self.config = config

    def load(self) -> list[BenchmarkSample]:
        path = Path(self.config.path)
        if path.stat().st_size > 400_000_000:
            raw_items = self._load_streaming(path)
        else:
            with path.open(encoding="utf-8") as file:
                raw_items = json.load(file)

        samples = [self._convert_sample(item) for item in raw_items]
        samples = _filter_questions(samples, set(self.config.question_types))
        return _sample(samples, self.config.sample_size, self.config.seed)

    def _load_streaming(self, path: Path) -> list[dict]:
        limit = self.config.sample_size if self.config.sample_size > 0 else 0
        items = []
        for item in iter_json_array(path):
            if _matches_types(item, set(self.config.question_types)):
                items.append(item)
            if limit and len(items) >= limit:
                break
        return items

    def _convert_sample(self, item: dict) -> BenchmarkSample:
        session_ids = item.get("haystack_session_ids") or []
        dates = item.get("haystack_dates") or []
        raw_sessions = item.get("haystack_sessions") or []
        if self.config.max_sessions > 0:
            session_ids = session_ids[-self.config.max_sessions :]
            dates = dates[-self.config.max_sessions :]
            raw_sessions = raw_sessions[-self.config.max_sessions :]

        sessions = []
        for s_index, turns in enumerate(raw_sessions):
            session_id = (
                str(session_ids[s_index])
                if s_index < len(session_ids)
                else f"session_{s_index}"
            )
            timestamp = str(dates[s_index]) if s_index < len(dates) else ""
            messages = []
            for t_index, turn in enumerate(turns):
                messages.append(
                    BenchmarkMessage(
                        id=f"{session_id}:turn_{t_index}",
                        role=str(turn.get("role") or "user"),
                        speaker=str(turn.get("role") or ""),
                        content=str(turn.get("content") or ""),
                        timestamp=timestamp,
                        metadata={
                            "has_answer": bool(turn.get("has_answer")),
                            "session_id": session_id,
                            "turn_index": t_index,
                        },
                    )
                )
            sessions.append(
                BenchmarkSession(
                    id=session_id,
                    messages=messages,
                    timestamp=timestamp,
                    metadata={"session_index": s_index},
                )
            )

        qtype = _question_type(item)
        question = BenchmarkQuestion(
            id=str(item.get("question_id") or ""),
            question=str(item.get("question") or ""),
            gold_answers=[str(item.get("answer") or "")],
            timestamp=str(item.get("question_date") or ""),
            question_type=qtype,
            evidence=[str(e) for e in item.get("answer_session_ids") or []],
            metadata={
                "raw_question_type": item.get("question_type"),
                "answer_session_ids": item.get("answer_session_ids") or [],
            },
        )
        return BenchmarkSample(
            id=question.id,
            sessions=sessions,
            questions=[question],
            metadata={"dataset": "longmemeval", "split": self.config.split},
        )


def iter_json_array(path: Path, chunk_size: int = 1024 * 1024) -> Iterator[dict]:
    decoder = json.JSONDecoder()
    buffer = ""
    started = False
    with path.open(encoding="utf-8") as file:
        while True:
            chunk = file.read(chunk_size)
            if not chunk and not buffer:
                break
            buffer += chunk
            while True:
                if not started:
                    match = re.search(r"\S", buffer)
                    if not match:
                        break
                    if buffer[match.start()] != "[":
                        raise ValueError("Expected JSON array.")
                    buffer = buffer[match.start() + 1 :]
                    started = True
                match = re.search(r"\S", buffer)
                if not match:
                    break
                if buffer[match.start()] == "]":
                    return
                if buffer[match.start()] == ",":
                    buffer = buffer[match.start() + 1 :]
                    continue
                try:
                    item, end = decoder.raw_decode(buffer[match.start() :])
                except json.JSONDecodeError:
                    if len(buffer) > chunk_size * 4:
                        buffer = buffer[match.start() :]
                    break
                yield item
                buffer = buffer[match.start() + end :]
            if not chunk:
                break


def _question_type(item: dict) -> str:
    question_id = str(item.get("question_id") or "")
    if question_id.endswith("_abs"):
        return "abstention"
    return str(item.get("question_type") or "unknown")


def _matches_types(item: dict, question_types: set[str]) -> bool:
    return not question_types or _question_type(item) in question_types


def _filter_questions(
    samples: list[BenchmarkSample], question_types: set[str]
) -> list[BenchmarkSample]:
    if not question_types:
        return samples
    return [
        sample
        for sample in samples
        if sample.questions and sample.questions[0].question_type in question_types
    ]


def _sample(
    samples: list[BenchmarkSample], sample_size: int, seed: int
) -> list[BenchmarkSample]:
    if sample_size <= 0 or sample_size >= len(samples):
        return samples
    rng = random.Random(seed)
    return rng.sample(samples, sample_size)
