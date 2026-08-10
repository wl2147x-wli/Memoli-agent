from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Coroutine
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

from memoli_agent.agent.llm.contracts import (
    ModelEvent,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    TextBlock,
    ToolResultBlock,
)
from memoli_agent.agent.llm.errors import (
    AuthenticationProviderError,
    ContentSafetyProviderError,
    ContextLengthProviderError,
    InvalidRequestProviderError,
    PermissionProviderError,
    ResponseProtocolError,
)
from memoli_agent.agent.llm.openai_provider import OpenAIProvider
from memoli_agent.agent.llm.retry import RetryPolicy


def _run(coroutine: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coroutine)


def _provider(handler: httpx.MockTransport) -> tuple[OpenAIProvider, AsyncOpenAI]:
    client = AsyncOpenAI(
        api_key="unit-test-secret",
        base_url="https://openai.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=handler),
    )
    return OpenAIProvider(model="gpt-test", api_key="unused", client=client), client


def test_openai_http_wire_shape_and_multiple_tool_calls() -> None:
    seen: dict[str, Any] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-actual",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": "checking",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path":"a.txt"}',
                                    },
                                },
                                {
                                    "id": "call-2",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path":"b.txt"}',
                                    },
                                },
                            ],
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "total_tokens": 14,
                },
            },
        )

    provider, client = _provider(httpx.MockTransport(handle))
    request = ModelRequest(
        messages=(
            ModelMessage("system", (TextBlock("be precise"),)),
            ModelMessage("user", (TextBlock("read both"),)),
            ModelMessage("user", (ToolResultBlock("old-call", "old result"),)),
        ),
        tools=(
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "read",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                },
            },
        ),
        max_output_tokens=321,
    )

    response = _run(provider.complete(request))
    _run(client.close())

    assert seen["path"] == "/v1/chat/completions"
    assert seen["body"]["max_completion_tokens"] == 321
    assert seen["body"]["messages"][2] == {
        "role": "tool",
        "tool_call_id": "old-call",
        "content": "old result",
    }
    assert [call.id for call in response.tool_calls] == ["call-1", "call-2"]
    assert response.tool_calls[1].arguments == {"path": "b.txt"}
    assert response.model == "gpt-actual"
    assert response.request_id == "chatcmpl-1"
    assert response.usage == {
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
    }


def test_openai_sse_assembles_text_tools_usage_and_events() -> None:
    chunks = [
        {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-stream",
            "choices": [{"index": 0, "delta": {"content": "hel"}}],
        },
        {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-stream",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "content": "lo",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": '{"q":'},
                            }
                        ],
                    },
                }
            ],
        },
        {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-stream",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": '"memoli"}'}}
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        },
        {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "gpt-stream",
            "choices": [],
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "total_tokens": 8,
            },
        },
    ]
    body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
    body += "data: [DONE]\n\n"

    def handle(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream_options"] == {"include_usage": True}
        return httpx.Response(
            200,
            text=body,
            headers={"content-type": "text/event-stream"},
        )

    provider, client = _provider(httpx.MockTransport(handle))
    events: list[ModelEvent] = []

    async def on_event(event: ModelEvent) -> None:
        events.append(event)

    response = _run(
        provider.complete(
            ModelRequest((ModelMessage("user", (TextBlock("go"),)),), stream=True),
            on_event,
        )
    )
    _run(client.close())

    assert response.content == "hello"
    assert response.tool_calls[0].arguments == {"q": "memoli"}
    assert response.finish_reason == "tool_calls"
    assert response.usage["total_tokens"] == 8
    assert [event.kind for event in events].count(ModelEventKind.TEXT_DELTA) == 2
    assert events[-1].kind == ModelEventKind.COMPLETED


@pytest.mark.parametrize("transient_status", [408, 429, 500])
def test_openai_retries_transient_status_but_not_authentication_failure(
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
                json={"error": {"message": "slow", "type": "rate_limit"}},
            )
        return httpx.Response(
            200,
            json={
                "id": "ok",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-test",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "ok"},
                    }
                ],
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
    assert response.attempts[0].retry_wait_seconds == 0

    auth_attempts = 0

    def auth_handler(request: httpx.Request) -> httpx.Response:
        nonlocal auth_attempts
        auth_attempts += 1
        return httpx.Response(
            401,
            json={"error": {"message": "bad key", "type": "authentication_error"}},
        )

    provider, client = _provider(httpx.MockTransport(auth_handler))
    with pytest.raises(AuthenticationProviderError):
        _run(
            provider.complete(ModelRequest((ModelMessage("user", (TextBlock("x"),)),)))
        )
    _run(client.close())
    assert auth_attempts == 1


def test_openai_rejects_malformed_tool_arguments() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "bad",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-test",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "bad-call",
                                    "type": "function",
                                    "function": {"name": "x", "arguments": "[1]"},
                                }
                            ],
                        },
                    }
                ],
            },
        )

    provider, client = _provider(httpx.MockTransport(handle))
    with pytest.raises(ResponseProtocolError):
        _run(
            provider.complete(ModelRequest((ModelMessage("user", (TextBlock("x"),)),)))
        )
    _run(client.close())


def test_deepseek_dialect_uses_explicit_compatible_fields() -> None:
    seen: dict[str, Any] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "ok",
                "object": "chat.completion",
                "created": 1,
                "model": "deepseek-test",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "ok"},
                    }
                ],
            },
        )

    client = AsyncOpenAI(
        api_key="unit-test-secret",
        base_url="https://deepseek.test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    provider = OpenAIProvider(
        model="deepseek-test",
        api_key="unused",
        dialect="deepseek",
        client=client,
    )
    _run(
        provider.complete(
            ModelRequest(
                (ModelMessage("user", (TextBlock("x"),)),),
                max_output_tokens=123,
            )
        )
    )
    _run(client.close())

    assert seen["max_tokens"] == 123
    assert "max_completion_tokens" not in seen


@pytest.mark.parametrize("failure_kind", ["network", "timeout"])
def test_openai_retries_transient_transport_failures(failure_kind: str) -> None:
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
                "id": "ok",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-test",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "ok"},
                    }
                ],
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
        (403, "permission_denied", PermissionProviderError),
        (400, "context_length_exceeded", ContextLengthProviderError),
        (400, "content_filter", ContentSafetyProviderError),
        (400, "invalid_request_error", InvalidRequestProviderError),
    ],
)
def test_openai_permanent_errors_are_classified_without_retry(
    status: int, code: str, expected: type[Exception]
) -> None:
    attempts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            status,
            json={"error": {"message": "rejected", "type": code, "code": code}},
        )

    provider, client = _provider(httpx.MockTransport(handle))
    with pytest.raises(expected):
        _run(
            provider.complete(ModelRequest((ModelMessage("user", (TextBlock("x"),)),)))
        )
    _run(client.close())
    assert attempts == 1


def test_openai_sdk_error_never_exposes_api_key_or_remote_secret_text() -> None:
    secret = "memoli-secret-sentinel"

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {secret}"
        return httpx.Response(
            401,
            json={
                "error": {
                    "message": f"rejected credential {secret}",
                    "type": "authentication_error",
                }
            },
        )

    client = AsyncOpenAI(
        api_key=secret,
        base_url="https://openai.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    provider = OpenAIProvider(model="gpt-test", api_key=secret, client=client)
    with pytest.raises(AuthenticationProviderError) as captured:
        _run(
            provider.complete(
                ModelRequest((ModelMessage("user", (TextBlock("x"),)),))
            )
        )
    _run(client.close())

    assert secret not in str(captured.value)
    assert secret not in repr(provider)


@pytest.mark.provider_live
def test_openai_live_smoke_is_opt_in() -> None:
    if os.getenv("MEMOLI_RUN_PROVIDER_LIVE") != "1":
        pytest.skip("设置 MEMOLI_RUN_PROVIDER_LIVE=1 后才运行真实 Provider smoke")
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("未配置 OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL")
    if not model:
        pytest.skip("未配置 OPENAI_MODEL")

    async def scenario() -> None:
        provider = OpenAIProvider(
            model=model,
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
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
