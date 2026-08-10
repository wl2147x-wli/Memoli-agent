from __future__ import annotations

import json
from pathlib import Path

from benchmarks.config import DatasetConfig
from benchmarks.datasets.locomo import LocomoDatasetAdapter
from benchmarks.datasets.longmemeval import LongMemEvalDatasetAdapter


def test_locomo_adapter_parses_sessions_and_questions(tmp_path: Path) -> None:
    data_path = tmp_path / "locomo.json"
    data_path.write_text(
        json.dumps(
            [
                {
                    "sample_id": "sample-1",
                    "conversation": {
                        "speaker_a": "Alice",
                        "speaker_b": "Bob",
                        "session_1_date_time": "1 pm",
                        "session_1": [
                            {
                                "speaker": "Alice",
                                "dia_id": "D1:1",
                                "text": "I like tea.",
                            },
                            {"speaker": "Bob", "dia_id": "D1:2", "text": "Nice."},
                        ],
                    },
                    "qa": [
                        {
                            "question": "What does Alice like?",
                            "answer": "tea",
                            "evidence": ["D1:1"],
                            "category": 4,
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    samples = LocomoDatasetAdapter(
        DatasetConfig(name="locomo", path=str(data_path))
    ).load()

    assert len(samples) == 1
    assert samples[0].id == "sample-1"
    assert samples[0].sessions[0].messages[0].id == "D1:1"
    assert samples[0].questions[0].question_type == "single-hop"
    assert samples[0].questions[0].evidence == ["D1:1"]


def test_longmemeval_adapter_maps_abstention(tmp_path: Path) -> None:
    data_path = tmp_path / "longmemeval.json"
    data_path.write_text(
        json.dumps(
            [
                {
                    "question_id": "q_abs",
                    "question_type": "single-session-user",
                    "question": "What is my hamster called?",
                    "answer": "Not mentioned.",
                    "question_date": "2023/01/02 10:00",
                    "haystack_dates": ["2023/01/01 10:00"],
                    "haystack_session_ids": ["s1"],
                    "haystack_sessions": [
                        [
                            {
                                "role": "user",
                                "content": "My cat is Luna.",
                                "has_answer": True,
                            }
                        ]
                    ],
                    "answer_session_ids": ["s1"],
                }
            ]
        ),
        encoding="utf-8",
    )

    samples = LongMemEvalDatasetAdapter(
        DatasetConfig(name="longmemeval", path=str(data_path))
    ).load()

    assert samples[0].questions[0].question_type == "abstention"
    assert samples[0].questions[0].evidence == ["s1"]
    assert samples[0].sessions[0].messages[0].metadata["has_answer"] is True
