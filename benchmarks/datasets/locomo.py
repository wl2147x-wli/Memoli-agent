"""LoCoMo dataset adapter."""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from benchmarks.config import DatasetConfig
from benchmarks.datasets.base import (
    BenchmarkMessage,
    BenchmarkQuestion,
    BenchmarkSample,
    BenchmarkSession,
)

CATEGORY_TO_TYPE = {
    1: "multi-hop",
    2: "temporal",
    3: "open-domain",
    4: "single-hop",
    5: "adversarial",
}


class LocomoDatasetAdapter:
    def __init__(self, config: DatasetConfig) -> None:
        self.config = config

    def load(self) -> list[BenchmarkSample]:
        with Path(self.config.path).open(encoding="utf-8") as file:
            raw_samples = json.load(file)

        samples = [self._convert_sample(item) for item in raw_samples]
        samples = _filter_questions(samples, set(self.config.question_types))
        return _sample(samples, self.config.sample_size, self.config.seed)

    def _convert_sample(self, item: dict) -> BenchmarkSample:
        conversation = item.get("conversation", {})
        sessions = []
        for key in sorted(conversation, key=_session_sort_key):
            if not re.fullmatch(r"session_\d+", key):
                continue
            session_index = key.split("_", 1)[1]
            timestamp = str(conversation.get(f"session_{session_index}_date_time", ""))
            messages = []
            for index, turn in enumerate(conversation.get(key) or []):
                dia_id = str(turn.get("dia_id") or f"{key}:{index}")
                content = str(turn.get("text") or "")
                if turn.get("blip_caption"):
                    content = f"{content}\n[image_caption] {turn['blip_caption']}"
                messages.append(
                    BenchmarkMessage(
                        id=dia_id,
                        role=_role_for_speaker(turn.get("speaker"), conversation),
                        speaker=str(turn.get("speaker") or ""),
                        content=content,
                        timestamp=timestamp,
                        metadata={"raw": turn, "session_id": key, "turn_index": index},
                    )
                )
            sessions.append(
                BenchmarkSession(
                    id=key,
                    messages=messages,
                    timestamp=timestamp,
                    metadata={"session_index": int(session_index)},
                )
            )

        questions = []
        for index, qa in enumerate(item.get("qa") or []):
            category = int(qa.get("category", 0))
            qtype = CATEGORY_TO_TYPE.get(category, "unknown")
            questions.append(
                BenchmarkQuestion(
                    id=f"{item.get('sample_id', 'locomo')}:qa_{index}",
                    question=str(qa.get("question") or ""),
                    gold_answers=[str(qa.get("answer") or "")],
                    question_type=qtype,
                    evidence=[str(e) for e in qa.get("evidence") or []],
                    metadata={"category": category, "raw": qa},
                )
            )

        return BenchmarkSample(
            id=str(item.get("sample_id") or "locomo-sample"),
            sessions=sessions,
            questions=questions,
            metadata={
                "dataset": "locomo",
                "event_summary": item.get("event_summary"),
                "observation": item.get("observation"),
                "session_summary": item.get("session_summary"),
            },
        )


def _role_for_speaker(speaker: str | None, conversation: dict) -> str:
    if speaker == conversation.get("speaker_b"):
        return "assistant"
    return "user"


def _session_sort_key(key: str) -> tuple[int, str]:
    match = re.fullmatch(r"session_(\d+)", key)
    return (int(match.group(1)) if match else 999999, key)


def _filter_questions(
    samples: list[BenchmarkSample], question_types: set[str]
) -> list[BenchmarkSample]:
    if not question_types:
        return samples
    filtered = []
    for sample in samples:
        questions = [q for q in sample.questions if q.question_type in question_types]
        if questions:
            sample.questions = questions
            filtered.append(sample)
    return filtered


def _sample(
    samples: list[BenchmarkSample], sample_size: int, seed: int
) -> list[BenchmarkSample]:
    if sample_size <= 0 or sample_size >= len(samples):
        return samples
    rng = random.Random(seed)
    return rng.sample(samples, sample_size)
