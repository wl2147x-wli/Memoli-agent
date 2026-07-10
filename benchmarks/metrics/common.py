"""Common metric aggregation helpers."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean


def aggregate(records: list[dict]) -> dict:
    scores = [record["score"] for record in records if record.get("score") is not None]
    recalls = [
        record["retrieval_recall"]
        for record in records
        if record.get("retrieval_recall") is not None
    ]
    by_type: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_type[record["question_type"]].append(record)

    return {
        "total_questions": len(records),
        "overall": {
            "score": mean(scores) if scores else None,
            "retrieval_recall": mean(recalls) if recalls else None,
        },
        "by_question_type": {
            qtype: {
                "count": len(items),
                "score": mean([i["score"] for i in items if i.get("score") is not None])
                if any(i.get("score") is not None for i in items)
                else None,
                "retrieval_recall": mean(
                    [
                        i["retrieval_recall"]
                        for i in items
                        if i.get("retrieval_recall") is not None
                    ]
                )
                if any(i.get("retrieval_recall") is not None for i in items)
                else None,
            }
            for qtype, items in sorted(by_type.items())
        },
    }
