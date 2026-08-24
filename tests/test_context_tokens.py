import json

from memoli_agent.agent.context_management.tokens import ConservativeTokenEstimator
from memoli_agent.agent.types import ChatMessage


def test_conservative_estimator_counts_cjk_english_and_json() -> None:
    estimator = ConservativeTokenEstimator()
    assert estimator.count_text("上下文工程") >= 5
    assert estimator.count_text("context engineering") >= 6
    assert estimator.count_text(json.dumps({"name": "工具"}, ensure_ascii=False)) >= 6


def test_request_estimate_includes_message_tool_and_protocol_overhead() -> None:
    estimator = ConservativeTokenEstimator()
    message_only = estimator.count_request([ChatMessage("user", "hello")], [])
    with_tool = estimator.count_request(
        [ChatMessage("user", "hello")],
        [
            {
                "type": "function",
                "function": {
                    "name": "read",
                    "description": "read a file",
                    "parameters": {"type": "object"},
                },
            }
        ],
    )
    assert message_only > estimator.count_text("hello")
    assert with_tool > message_only
