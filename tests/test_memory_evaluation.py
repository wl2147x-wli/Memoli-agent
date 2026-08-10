from benchmarks.memory_evaluation import DEFAULT_CASES, retrieval_metrics


def test_three_layer_benchmark_contract_and_metrics() -> None:
    assert {case.layer for case in DEFAULT_CASES} == {
        "generation",
        "retrieval",
        "usage",
    }
    assert {case.category for case in DEFAULT_CASES} >= {
        "basic",
        "conflict-temporal",
        "proactive",
    }
    metrics = retrieval_metrics(
        {"a", "b"},
        ["a", "x"],
        current_flags=[True, False],
        evidence_flags=[True, True],
        status_correct=[True, True],
        injected_chars=20,
        latency_ms=1.5,
    )
    assert metrics.recall_at_k == 0.5
    assert metrics.precision_at_k == 0.5
    assert metrics.evidence_coverage == 1.0
