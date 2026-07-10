"""Shared benchmark data objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class BenchmarkMessage:
    id: str
    role: str
    speaker: str
    content: str
    timestamp: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class BenchmarkSession:
    id: str
    messages: list[BenchmarkMessage]
    timestamp: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class BenchmarkQuestion:
    id: str
    question: str
    gold_answers: list[str]
    timestamp: str = ""
    question_type: str = ""
    evidence: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class BenchmarkSample:
    id: str
    sessions: list[BenchmarkSession]
    questions: list[BenchmarkQuestion]
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class BenchmarkPrediction:
    sample_id: str
    question_id: str
    prediction: str
    gold_answers: list[str]
    retrieved_context: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class DatasetAdapter(Protocol):
    def load(self) -> list[BenchmarkSample]:
        ...
