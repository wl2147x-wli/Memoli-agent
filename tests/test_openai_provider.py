from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Coroutine
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.llm.contracts import (
    ModelEvent,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ReasoningMode,
    ReasoningPolicy,
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
from memoli_agent.agent.plugins.events import HookKind, HookName, ModelAfterEvent
from memoli_agent.agent.plugins.hooks import HookBus, HookRegistration
from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import InMemoryTrajectoryStore
from memoli_agent.agent.types import ChatMessage
from memoli_agent.presentation.events import PresentationEventHub


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


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (ReasoningPolicy(), False),
        (ReasoningPolicy(mode=ReasoningMode.ADAPTIVE), True),
    ],
)
def test_qwen_vllm_sends_explicit_thinking_switch(
    policy: ReasoningPolicy, expected: bool
) -> None:
    seen: dict[str, Any] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "qwen-switch",
                "object": "chat.completion",
                "created": 1,
                "model": "qwen3",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "最终回答"},
                    }
                ],
            },
        )

    client = AsyncOpenAI(
        api_key="unit-test-secret",
        base_url="https://qwen.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    provider = OpenAIProvider(
        model="qwen3", api_key="unused", dialect="qwen-vllm", client=client
    )
    response = _run(
        provider.complete(
            ModelRequest(
                (ModelMessage("user", (TextBlock("问题"),)),),
                reasoning_policy=policy,
                max_output_tokens=256,
            )
        )
    )
    _run(client.close())

    assert seen["max_tokens"] == 256
    assert "max_completion_tokens" not in seen
    assert seen["chat_template_kwargs"]["enable_thinking"] is expected
    assert response.content == "最终回答"


def test_qwen_vllm_nonstream_keeps_only_final_content() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "qwen-final",
                "object": "chat.completion",
                "created": 1,
                "model": "qwen3",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "reasoning_content": "结构化秘密推理",
                            "content": "<think>标签秘密推理</think>\n最终回答",
                        },
                    }
                ],
            },
        )

    client = AsyncOpenAI(
        api_key="unit-test-secret",
        base_url="https://qwen.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    provider = OpenAIProvider(
        model="qwen3", api_key="unused", dialect="qwen-vllm", client=client
    )
    events: list[ModelEvent] = []

    async def on_event(event: ModelEvent) -> None:
        events.append(event)

    response = _run(
        provider.complete(
            ModelRequest((ModelMessage("user", (TextBlock("问题"),)),)), on_event
        )
    )
    _run(client.close())

    assert response.content == "最终回答"
    assert response.message.text == "最终回答"
    assert events[-1].text == "最终回答"
    public = repr((response, events))
    assert "秘密推理" not in public
    assert "<think>" not in public


def test_qwen_vllm_stream_buffers_cross_chunk_think_block() -> None:
    chunks = [
        {"content": "<thi", "reasoning_content": "结构化秘密"},
        {"content": "nk>标签秘密"},
        {"content": "推理</thi"},
        {"content": "nk>\n最终回答"},
    ]
    payloads = []
    for index, delta in enumerate(chunks):
        payloads.append(
            {
                "id": "qwen-stream",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "qwen3",
                "choices": [
                    {
                        "index": 0,
                        "delta": delta,
                        "finish_reason": "stop" if index == len(chunks) - 1 else None,
                    }
                ],
            }
        )
    body = "".join(f"data: {json.dumps(item)}\n\n" for item in payloads)
    body += "data: [DONE]\n\n"

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        )

    client = AsyncOpenAI(
        api_key="unit-test-secret",
        base_url="https://qwen.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    provider = OpenAIProvider(
        model="qwen3", api_key="unused", dialect="qwen-vllm", client=client
    )
    events: list[ModelEvent] = []

    async def on_event(event: ModelEvent) -> None:
        events.append(event)

    response = _run(
        provider.complete(
            ModelRequest(
                (ModelMessage("user", (TextBlock("问题"),)),), stream=True
            ),
            on_event,
        )
    )
    _run(client.close())

    deltas = [event.text for event in events if event.kind is ModelEventKind.TEXT_DELTA]
    assert response.content == "最终回答"
    assert deltas == ["最终回答"]
    public = repr((response, events))
    assert "秘密" not in public
    assert "<thi" not in public


def test_qwen_vllm_reasoner_boundaries_keep_only_final_answer_and_tools() -> None:
    requests: list[dict[str, Any]] = []

    def sse(deltas: list[dict[str, Any]], finish_reason: str) -> str:
        chunks = []
        for index, delta in enumerate(deltas):
            chunks.append(
                {
                    "id": f"qwen-e2e-{len(requests)}",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "qwen3",
                    "choices": [
                        {
                            "index": 0,
                            "delta": delta,
                            "finish_reason": (
                                finish_reason if index == len(deltas) - 1 else None
                            ),
                        }
                    ],
                }
            )
        return (
            "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            + "data: [DONE]\n\n"
        )

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            body = sse(
                [
                    {"reasoning_content": "结构化绝密推理", "content": "<think>"},
                    {
                        "content": "标签绝密推理</think>",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-memory",
                                "type": "function",
                                "function": {
                                    "name": "memory_probe",
                                    "arguments": '{"query":"记忆"}',
                                },
                            }
                        ],
                    },
                ],
                "tool_calls",
            )
        else:
            body = sse(
                [
                    {"content": "<think>最终前绝密"},
                    {"content": "推理</think>\n我有记忆管理工具。"},
                ],
                "stop",
            )
        return httpx.Response(
            200, text=body, headers={"content-type": "text/event-stream"}
        )

    class MemoryProbe:
        name = "memory_probe"
        description = "检查记忆工具"
        parameters = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }

        async def run(self, arguments: dict[str, Any]) -> ToolResult:
            return ToolResult(f"已检查：{arguments['query']}")

    client = AsyncOpenAI(
        api_key="unit-test-secret",
        base_url="https://qwen.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    provider = OpenAIProvider(
        model="qwen3", api_key="unused", dialect="qwen-vllm", client=client
    )
    registry = ToolRegistry()
    registry.register(MemoryProbe())
    trajectory = InMemoryTrajectoryStore()
    hook_events: list[ModelAfterEvent] = []
    hook_bus = HookBus(trajectory)
    hook_bus.register(
        HookRegistration(
            "qwen-boundary-test",
            "1.0.0",
            "in_process",
            HookName.MODEL_AFTER,
            HookKind.OBSERVER,
            lambda event: hook_events.append(event),
            handler_name="capture-model-after",
        )
    )
    presentation = PresentationEventHub()

    result = _run(
        Reasoner(
            provider,
            tool_registry=registry,
            trajectory_store=trajectory,
            hook_bus=hook_bus,
            presentation_events=presentation,
            stream_model=True,
            reasoning_policy=ReasoningPolicy(mode=ReasoningMode.ADAPTIVE),
        ).run_turn(
            [ChatMessage("user", "你有没有记忆管理相关的工具？")],
            session_key="qwen-e2e",
        )
    )
    _run(client.close())

    presentation_events = []
    while not presentation._queue.empty():
        presentation_events.append(_run(presentation.consume()))
    public_boundaries = repr(
        (
            result,
            hook_events,
            trajectory.event_payloads,
            trajectory.traces,
            trajectory.spans,
            presentation_events,
            requests[1]["messages"],
        )
    )
    assert result.response.content == "我有记忆管理工具。"
    assert requests[0]["chat_template_kwargs"]["enable_thinking"] is True
    assert requests[1]["messages"][-1]["role"] == "tool"
    assert [event.content for event in hook_events] == ["", "我有记忆管理工具。"]
    assert "我有记忆管理工具。" in public_boundaries
    assert "绝密推理" not in public_boundaries
    assert "<think>" not in public_boundaries
    assert "</think>" not in public_boundaries


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
