"""LoCoMo official metrics adapter."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

DEFAULT_LOCOMO_EVAL_SCRIPT = "D:/wli/project1/locomo/task_eval/evaluation.py"


def evaluate_locomo_official(
    records: list[dict[str, Any]],
    eval_script_path: str = DEFAULT_LOCOMO_EVAL_SCRIPT,
) -> list[dict[str, Any]]:
    """Score LoCoMo predictions with the original repository evaluator."""

    evaluation = _load_official_evaluation(eval_script_path)
    qas = [_to_official_qa(record) for record in records]
    scores, _lengths, recalls = evaluation.eval_question_answering(
        qas,
        eval_key="prediction",
        metric="f1",
    )
    if len(scores) != len(records) or len(recalls) != len(records):
        raise RuntimeError(
            "LoCoMo official evaluator returned a different number of scores "
            f"({len(scores)}) or recalls ({len(recalls)}) than records "
            f"({len(records)})."
        )

    for record, qa, score, recall in zip(records, qas, scores, recalls, strict=True):
        record["score"] = float(score)
        record["retrieval_recall"] = float(recall)
        record["metric_source"] = str(Path(eval_script_path))
        record["official_qa"] = qa
    return records


def build_official_qa(record: dict[str, Any]) -> dict[str, Any]:
    """Expose LoCoMo official QA conversion for tests and schema docs."""

    return _to_official_qa(record)


def extract_prediction_context(record: dict[str, Any]) -> list[str]:
    """Extract LoCoMo turn IDs such as D1:3 from retrieved context strings."""

    contexts = record.get("retrieved_context") or []
    extracted: list[str] = []
    seen = set()
    for context in contexts:
        for match in re.finditer(r"\bD\d+:\d+\b", str(context)):
            value = match.group(0)
            if value not in seen:
                seen.add(value)
                extracted.append(value)
    return extracted


def _to_official_qa(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") or {}
    question_metadata = metadata.get("question_metadata") or {}
    raw_qa = dict(question_metadata.get("raw") or {})
    category = raw_qa.get("category", question_metadata.get("category"))
    if category is None:
        category = _category_from_question_type(record.get("question_type"))

    qa = {
        "question": raw_qa.get("question", record.get("question", "")),
        "answer": raw_qa.get("answer", _first_gold(record)),
        "evidence": raw_qa.get("evidence", record.get("evidence") or []),
        "category": int(category),
        "prediction": record.get("prediction", ""),
        "prediction_context": extract_prediction_context(record),
    }
    return qa


def _load_official_evaluation(eval_script_path: str):
    path = Path(eval_script_path)
    if not path.exists():
        raise FileNotFoundError(f"LoCoMo official evaluator not found: {path}")

    spec = importlib.util.spec_from_file_location("locomo_official_evaluation", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load LoCoMo official evaluator: {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "LoCoMo official evaluator dependency is missing. "
            f"Install the missing package and retry. Original error: {exc}"
        ) from exc

    if not hasattr(module, "eval_question_answering"):
        raise AttributeError(
            f"LoCoMo official evaluator has no eval_question_answering(): {path}"
        )
    return module


def _first_gold(record: dict[str, Any]) -> str:
    answers = record.get("gold_answers") or []
    return str(answers[0]) if answers else ""


def _category_from_question_type(question_type: str | None) -> int:
    mapping = {
        "multi-hop": 1,
        "temporal": 2,
        "open-domain": 3,
        "single-hop": 4,
        "adversarial": 5,
    }
    if question_type not in mapping:
        raise ValueError(
            f"Cannot infer LoCoMo category from question_type={question_type!r}"
        )
    return mapping[question_type]
