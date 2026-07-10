from __future__ import annotations

from benchmarks.metrics.locomo import build_official_qa, extract_prediction_context


def test_extract_prediction_context_finds_turn_ids() -> None:
    record = {
        "retrieved_context": [
            "[sample=x][session=session_1][message=D1:3] Alice: tea",
            "[sample=x][session=session_2][message=D2:4] Bob: coffee D1:3",
        ]
    }

    assert extract_prediction_context(record) == ["D1:3", "D2:4"]


def test_build_official_qa_prefers_raw_question_metadata() -> None:
    record = {
        "question": "Fallback question?",
        "prediction": "tea",
        "gold_answers": ["tea"],
        "question_type": "single-hop",
        "evidence": ["D1:1"],
        "retrieved_context": ["[message=D1:1] Alice likes tea."],
        "metadata": {
            "question_metadata": {
                "category": 4,
                "raw": {
                    "question": "What does Alice like?",
                    "answer": "tea",
                    "evidence": ["D1:1"],
                    "category": 4,
                },
            }
        },
    }

    qa = build_official_qa(record)

    assert qa == {
        "question": "What does Alice like?",
        "answer": "tea",
        "evidence": ["D1:1"],
        "category": 4,
        "prediction": "tea",
        "prediction_context": ["D1:1"],
    }
