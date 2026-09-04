from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Coroutine
from typing import Any

import httpx
import pytest
from anthropic import AsyncAnthropic

from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.llm.anthropic_provider import AnthropicProvider
from memoli_agent.agent.llm.contracts import (
    ModelEvent,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    OpaqueContinuation,
    ReasoningMode,
    ReasoningPolicy,
    ReasoningSummaryBlock,
    ReasoningVisibility,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from memoli_agent.agent.llm.errors import (
    AuthenticationProviderError,
    ContentSafetyProviderError,
    ContextLengthProviderError,
    InvalidRequestProviderError,
    PermissionProviderError,
    UnsupportedReasoningPolicyError,
)
from memoli_agent.agent.llm.retry import RetryPolicy
from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.types import ChatMessage


def _run(coroutine: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coroutine)


def _provider(handler: httpx.MockTransport) -> tuple[AnthropicProvider, AsyncAnthropic]:
    client = AsyncAnthropic(
        api_key="unit-test-secret",
        base_url="https://anthropic.test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=handler),
    )
    return AnthropicProvider(
        model="claude-test", api_key="unused", client=client
    ), client


def test_anthropic_native_round_trip_preserves_thinking_and_tool_links() -> None:
    seen: dict[str, Any] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "msg-1",
                "type": "message",
                "role": "assistant",
                "model": "claude-actual",
                "stop_reason": "tool_use",
                "stop_sequence": None,
                "content": [
                    {
                        "type": "thinking",
                        "thinking": "need data",
                        "signature": "signed-continuation",
                    },
                    {"type": "text", "text": "checking"},
                    {
                        "type": "tool_use",
                        "id": "toolu-2",
                        "name": "lookup",
                        "input": {"q": "memoli"},
                    },
                ],
                "usage": {
                    "input_tokens": 20,
                    "output_tokens": 7,
                    "cache_read_input_tokens": 4,
                },
            },
        )

    provider, client = _provider(httpx.MockTransport(handle))
    request = ModelRequest(
        messages=(
            ModelMessage("system", (TextBlock("system one"),)),
            ModelMessage("system", (TextBlock("system two"),)),
            ModelMessage("user", (TextBlock("continue"),)),
            ModelMessage(
                "assistant",
                (
                    ThinkingBlock("prior thought", signature="prior-signature"),
                    ToolUseBlock("toolu-1", "lookup", {"q": "old"}),
                ),
            ),
            ModelMessage("user", (ToolResultBlock("toolu-1", "old result"),)),
        ),
        tools=(
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "lookup",
                    "parameters": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                    },
                },
            },
        ),
        reasoning=True,
    )

    response = _run(provider.complete(request))
    _run(client.close())

    assert seen["path"] == "/v1/messages"
    assert seen["body"]["system"] == "system one\n\nsystem two"
    assert seen["body"]["tools"][0]["input_schema"]["properties"]["q"]
    assert seen["body"]["messages"][-1]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "toolu-1",
        "content": "old result",
    }
    assert seen["body"]["messages"][-2]["content"][0]["signature"] == (
        "prior-signature"
    )
    assert all(
        not isinstance(block, ThinkingBlock) for block in response.message.blocks
    )
    assert response.continuation is not None
    assert response.continuation.items[0]["signature"] == "signed-continuation"
    assert response.tool_calls[0].id == "toolu-2"
    assert response.usage == {
        "input_tokens": 20,
        "output_tokens": 7,
        "total_tokens": 27,
        "cached_input_tokens": 4,
    }


def test_anthropic_opaque_continuation_replays_original_order() -> None:
    bodies: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(
                200,
                json={
                    "id": "msg-1",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-test",
                    "stop_reason": "tool_use",
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": "summary",
                            "signature": "private-signature",
                        },
                        {"type": "text", "text": "checking"},
                        {
                            "type": "tool_use",
                            "id": "toolu-1",
                            "name": "lookup",
                            "input": {"q": "memoli"},
                        },
                    ],
                    "usage": {"input_tokens": 3, "output_tokens": 2},
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "msg-2",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "done"}],
                "usage": {"input_tokens": 5, "output_tokens": 1},
            },
        )

    provider, client = _provider(httpx.MockTransport(handle))
    policy = ReasoningPolicy(ReasoningMode.ADAPTIVE)
    first = _run(
        provider.complete(
            ModelRequest(
                (ModelMessage("user", (TextBlock("go"),)),),
                reasoning_policy=policy,
            )
        )
    )
    assert first.message is not None
    assert first.continuation is not None
    completed = _run(
        provider.complete(
            ModelRequest(
                (
                    ModelMessage("user", (TextBlock("go"),)),
                    first.message,
                    ModelMessage(
                        "user", (ToolResultBlock("toolu-1", "result"),)
                    ),
                ),
                reasoning_policy=policy,
                continuation=first.continuation,
            )
        )
    )
    _run(client.close())

    assert completed.content == "done"
    assert [
        block["type"] for block in bodies[1]["messages"][-2]["content"]
    ] == ["thinking", "text", "tool_use"]
    assert (
        bodies[1]["messages"][-2]["content"][0]["signature"]
        == "private-signature"
    )


def test_anthropic_rejects_disabling_reasoning_during_continuation() -> None:
    called = False

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    provider, client = _provider(httpx.MockTransport(handle))
    continuation = OpaqueContinuation(
        "anthropic",
        items=(
            {
                "type": "thinking",
                "thinking": "",
                "signature": "private-signature",
            },
        ),
        reasoning_policy=ReasoningPolicy(ReasoningMode.ADAPTIVE),
    )

    with pytest.raises(UnsupportedReasoningPolicyError):
        _run(
            provider.complete(
                ModelRequest(
                    (ModelMessage("user", (TextBlock("continue"),)),),
                    continuation=continuation,
                )
            )
        )
    _run(client.close())
    assert called is False


def test_anthropic_reasoner_multi_tool_exchange_replays_all_private_blocks() -> None:
    bodies: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(
                200,
                json={
                    "id": "msg-tools",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-test",
                    "stop_reason": "tool_use",
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": "safe summary",
                            "signature": "private-signature",
                        },
                        {"type": "redacted_thinking", "data": "private-data"},
                        {
                            "type": "tool_use",
                            "id": "toolu-a",
                            "name": "first",
                            "input": {"value": 1},
                        },
                        {
                            "type": "tool_use",
                            "id": "toolu-b",
                            "name": "second",
                            "input": {"value": 2},
                        },
                    ],
                    "usage": {"input_tokens": 4, "output_tokens": 3},
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "msg-final",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "完成"}],
                "usage": {"input_tokens": 8, "output_tokens": 1},
            },
        )

    class RecordingTool:
        description = "测试工具"
        parameters = {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
        }

        def __init__(self, name: str) -> None:
            self.name = name
            self.calls: list[dict[str, Any]] = []

        async def run(self, arguments: dict[str, Any]) -> ToolResult:
            self.calls.append(arguments)
            return ToolResult(f"{self.name}-result")

    provider, client = _provider(httpx.MockTransport(handle))
    first = RecordingTool("first")
    second = RecordingTool("second")
    registry = ToolRegistry()
    registry.register(first)
    registry.register(second)
    result = _run(
        Reasoner(
            provider,
            tool_registry=registry,
            reasoning_policy=ReasoningPolicy(
                ReasoningMode.ADAPTIVE,
                visibility=ReasoningVisibility.HIDDEN,
            ),
        ).run_turn([ChatMessage("user", "执行两个工具")], session_key="anthropic-e2e")
    )
    _run(client.close())

    assert result.response.content == "完成"
    assert first.calls == [{"value": 1}]
    assert second.calls == [{"value": 2}]
    replay = bodies[1]["messages"][-2]["content"]
    assert [block["type"] for block in replay] == [
        "thinking",
        "redacted_thinking",
        "tool_use",
        "tool_use",
    ]
    assert replay[0]["signature"] == "private-signature"
    assert replay[1]["data"] == "private-data"
    assert [block["tool_use_id"] for block in bodies[1]["messages"][-1]["content"]] == [
        "toolu-a",
        "toolu-b",
    ]
    assert "private-signature" not in repr(result)


def test_anthropic_sse_assembles_thinking_tool_input_and_usage() -> None:
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg-stream",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-stream",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 9, "output_tokens": 0},
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "thinking",
                    "thinking": "",
                    "signature": "",
                },
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "think"},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "sig"},
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {
                    "type": "tool_use",
                    "id": "toolu-stream",
                    "name": "lookup",
                    "input": {},
                },
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "input_json_delta", "partial_json": '{"q":'},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": '"memoli"}',
                },
            },
        ),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 6},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    body = "".join(
        f"event: {name}\ndata: {json.dumps(payload)}\n\n" for name, payload in events
    )

    def handle(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200,
            text=body,
            headers={"content-type": "text/event-stream"},
        )

    provider, client = _provider(httpx.MockTransport(handle))
    emitted: list[ModelEvent] = []

    async def on_event(event: ModelEvent) -> None:
        emitted.append(event)

    response = _run(
        provider.complete(
            ModelRequest(
                (ModelMessage("user", (TextBlock("go"),)),),
                stream=True,
                reasoning=True,
            ),
            on_event,
        )
    )
    _run(client.close())

    assert isinstance(response.message.blocks[0], ToolUseBlock)
    assert response.continuation is not None
    assert response.continuation.items[0]["signature"] == "sig"
    assert response.tool_calls[0].arguments == {"q": "memoli"}
    assert response.usage["total_tokens"] == 15
    assert ModelEventKind.THINKING_DELTA not in [event.kind for event in emitted]
    assert ModelEventKind.TOOL_CALL_DELTA in [event.kind for event in emitted]


def test_anthropic_visible_updates_do_not_emit_private_signature() -> None:
    events = [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg-stream",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-stream",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 1, "output_tokens": 0},
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "thinking", "thinking": "", "signature": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "摘要"},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "private-signature"},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    body = "".join(
        f"event: {name}\ndata: {json.dumps(payload)}\n\n" for name, payload in events
    )

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        )

    provider, client = _provider(httpx.MockTransport(handle))
    emitted: list[ModelEvent] = []

    async def on_event(event: ModelEvent) -> None:
        emitted.append(event)

    response = _run(
        provider.complete(
            ModelRequest(
                (ModelMessage("user", (TextBlock("go"),)),),
                stream=True,
                reasoning_policy=ReasoningPolicy(
                    ReasoningMode.ADAPTIVE,
                    visibility=ReasoningVisibility.UPDATES,
                ),
            ),
            on_event,
        )
    )
    _run(client.close())

    assert response.message is not None
    assert isinstance(response.message.blocks[0], ReasoningSummaryBlock)
    summary_events = [
        event for event in emitted
        if event.kind is ModelEventKind.REASONING_SUMMARY_DELTA
    ]
    assert [event.text for event in summary_events] == ["摘要"]
    assert "private-signature" not in repr(emitted)


@pytest.mark.parametrize("transient_status", [408, 429, 500, 529])
def test_anthropic_retries_transient_status_but_not_authentication_failure(
    transient_status: int,
) -> None:
    attempts = 0

    def retry_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                transient_status,
                headers={"retry-after": "0"},
                json={
                    "type": "error",
                    "error": {"type": "overloaded_error", "message": "busy"},
                },
            )
        return httpx.Response(
            200,
            json={
                "id": "msg-ok",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    provider, client = _provider(httpx.MockTransport(retry_handler))
    response = _run(
        provider.complete(ModelRequest((ModelMessage("user", (TextBlock("x"),)),)))
    )
    _run(client.close())
    assert attempts == 2
    assert response.attempt_count == 2
    assert [attempt.outcome for attempt in response.attempts] == [
        "failed",
        "completed",
    ]
    assert response.attempts[0].status_code == transient_status

    auth_attempts = 0

    def auth_handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_attempts
        auth_attempts += 1
        return httpx.Response(
            401,
            json={
                "type": "error",
                "error": {"type": "authentication_error", "message": "bad key"},
            },
        )

    provider, client = _provider(httpx.MockTransport(auth_handler))
    with pytest.raises(AuthenticationProviderError):
        _run(
            provider.complete(ModelRequest((ModelMessage("user", (TextBlock("x"),)),)))
        )
    _run(client.close())
    assert auth_attempts == 1


@pytest.mark.parametrize("failure_kind", ["network", "timeout"])
def test_anthropic_retries_transient_transport_failures(failure_kind: str) -> None:
    attempts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            error_type = (
                httpx.ConnectError if failure_kind == "network" else httpx.ReadTimeout
            )
            raise error_type("temporary", request=request)
        return httpx.Response(
            200,
            json={
                "id": "msg-ok",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    provider, client = _provider(httpx.MockTransport(handle))
    provider.retry_policy = RetryPolicy(max_retries=1, base_delay_seconds=0)
    response = _run(
        provider.complete(ModelRequest((ModelMessage("user", (TextBlock("x"),)),)))
    )
    _run(client.close())
    assert attempts == 2
    assert response.attempt_count == 2


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (403, "permission_error", PermissionProviderError),
        (400, "context_length_exceeded", ContextLengthProviderError),
        (400, "content_policy_violation", ContentSafetyProviderError),
        (400, "invalid_request_error", InvalidRequestProviderError),
    ],
)
def test_anthropic_permanent_errors_are_classified_without_retry(
    status: int, code: str, expected: type[Exception]
) -> None:
    attempts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            status,
            json={"type": "error", "error": {"type": code, "message": "rejected"}},
        )

    provider, client = _provider(httpx.MockTransport(handle))
    with pytest.raises(expected):
        _run(
            provider.complete(ModelRequest((ModelMessage("user", (TextBlock("x"),)),)))
        )
    _run(client.close())
    assert attempts == 1


@pytest.mark.provider_live
def test_anthropic_live_smoke_is_opt_in() -> None:
    if os.getenv("MEMOLI_RUN_PROVIDER_LIVE") != "1":
        pytest.skip("设置 MEMOLI_RUN_PROVIDER_LIVE=1 后才运行真实 Provider smoke")
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("未配置 ANTHROPIC_API_KEY")
    model = os.getenv("ANTHROPIC_MODEL")
    if not model:
        pytest.skip("未配置 ANTHROPIC_MODEL")

    async def scenario() -> None:
        provider = AnthropicProvider(
            model=model,
            api_key=os.environ["ANTHROPIC_API_KEY"],
            base_url=os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            max_retries=0,
        )
        try:
            response = await provider.complete(
                ModelRequest(
                    (ModelMessage("user", (TextBlock("Reply with OK."),)),),
                    max_output_tokens=16,
                )
            )
            assert response.model
            assert response.error_type is None
        finally:
            await provider.aclose()

    asyncio.run(scenario())
