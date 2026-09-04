from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.llm.contracts import (
    ModelEvent,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ReasoningMode,
    ReasoningPolicy,
    ReasoningVisibility,
    TextBlock,
    ToolResultBlock,
)
from memoli_agent.agent.llm.errors import ResponseProtocolError
from memoli_agent.agent.llm.openai_responses_provider import OpenAIResponsesProvider
from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.types import ChatMessage


class _ResponsesEndpoint:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.result


class _Client:
    def __init__(self, result: Any) -> None:
        self.responses = _ResponsesEndpoint(result)


class _SequentialEndpoint(_ResponsesEndpoint):
    def __init__(self, results: list[Any]) -> None:
        super().__init__(None)
        self.results = results

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.results.pop(0)


class _SequentialClient:
    def __init__(self, results: list[Any]) -> None:
        self.responses = _SequentialEndpoint(results)


@dataclass
class _RecordingTool:
    name: str
    calls: list[dict[str, Any]] = field(default_factory=list)
    description: str = "测试工具"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(arguments)
        return ToolResult(f"{self.name}-result")


class _Stream:
    def __init__(self, events: list[Any]) -> None:
        self.events = events
        self.closed = False

    def __aiter__(self) -> _Stream:
        self._iterator = iter(self.events)
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._iterator)
        except StopIteration:
            raise StopAsyncIteration from None

    async def close(self) -> None:
        self.closed = True


class _BlockingStream:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.closed = False

    def __aiter__(self) -> _BlockingStream:
        return self

    async def __anext__(self) -> Any:
        self.started.set()
        await asyncio.Event().wait()
        raise StopAsyncIteration

    async def close(self) -> None:
        self.closed = True


def _policy(
    visibility: ReasoningVisibility = ReasoningVisibility.HIDDEN,
) -> ReasoningPolicy:
    return ReasoningPolicy(ReasoningMode.ADAPTIVE, "high", visibility)


def _tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "lookup",
            "description": "lookup",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def test_responses_stateless_tool_continuation_replays_ordered_items() -> None:
    first = {
        "id": "resp-1",
        "model": "gpt-test",
        "status": "completed",
        "output": [
            {
                "id": "rs-1",
                "type": "reasoning",
                "encrypted_content": "encrypted-private-state",
                "summary": [],
            },
            {
                "id": "fc-1",
                "type": "function_call",
                "call_id": "call-1",
                "name": "lookup",
                "arguments": '{"q":"memoli"}',
                "phase": "analysis",
            },
        ],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "output_tokens_details": {"reasoning_tokens": 3},
        },
    }
    client = _Client(first)
    provider = OpenAIResponsesProvider(
        model="gpt-test", api_key="unused", client=client
    )
    request = ModelRequest(
        (ModelMessage("user", (TextBlock("find"),)),),
        tools=(_tool(),),
        reasoning_policy=_policy(),
    )

    response = asyncio.run(provider.complete(request))

    assert response.tool_calls[0].id == "call-1"
    assert response.message is not None
    assert response.continuation is not None
    assert [item["type"] for item in response.continuation.items] == [
        "reasoning",
        "function_call",
    ]
    assert response.usage["reasoning_tokens"] == 3
    assert client.responses.calls[0]["store"] is False
    assert client.responses.calls[0]["include"] == [
        "reasoning.encrypted_content"
    ]

    final = {
        "id": "resp-2",
        "model": "gpt-test",
        "status": "completed",
        "output": [
            {
                "id": "msg-2",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "done"}],
            }
        ],
        "usage": {"input_tokens": 20, "output_tokens": 2, "total_tokens": 22},
    }
    client.responses.result = final
    continued = ModelRequest(
        (
            ModelMessage("user", (TextBlock("find"),)),
            response.message,
            ModelMessage("user", (ToolResultBlock("call-1", "result"),)),
        ),
        tools=(_tool(),),
        reasoning_policy=_policy(),
        continuation=response.continuation,
    )
    completed = asyncio.run(provider.complete(continued))

    sent = client.responses.calls[1]["input"]
    assert [item.get("type") for item in sent[1:]] == [
        "reasoning",
        "function_call",
        "function_call_output",
    ]
    assert sent[-1]["call_id"] == "call-1"
    assert completed.content == "done"
    assert completed.continuation is None


def test_responses_parses_all_message_items_and_visible_summaries() -> None:
    result = {
        "id": "resp",
        "model": "gpt-test",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "A"}],
            },
            {
                "type": "reasoning",
                "encrypted_content": "private",
                "summary": [{"type": "summary_text", "text": "safe"}],
            },
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "B"}],
            },
        ],
        "usage": {},
    }
    provider = OpenAIResponsesProvider(
        model="gpt-test", api_key="unused", client=_Client(result)
    )

    response = asyncio.run(
        provider.complete(
            ModelRequest(
                (ModelMessage("user", (TextBlock("go"),)),),
                reasoning_policy=_policy(ReasoningVisibility.SUMMARY),
            )
        )
    )

    assert response.content == "AB"
    assert "private" not in repr(response.message)
    assert response.message is not None
    assert any(
        getattr(block, "text", "") == "safe" for block in response.message.blocks
    )


def test_responses_unknown_output_item_fails_closed() -> None:
    provider = OpenAIResponsesProvider(
        model="gpt-test",
        api_key="unused",
        client=_Client({"output": [{"type": "future_required_item"}]}),
    )

    with pytest.raises(ResponseProtocolError):
        asyncio.run(
            provider.complete(
                ModelRequest((ModelMessage("user", (TextBlock("go"),)),))
            )
        )


def test_responses_stream_emits_safe_events_and_closes() -> None:
    completed = {
        "id": "resp",
        "model": "gpt-test",
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "done"}],
            },
            {
                "type": "function_call",
                "call_id": "call-a",
                "name": "lookup",
                "arguments": '{"q":"a"}',
            },
            {
                "type": "function_call",
                "call_id": "call-b",
                "name": "lookup",
                "arguments": '{"q":"b"}',
            },
        ],
        "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
    }
    stream = _Stream(
        [
            SimpleNamespace(type="response.output_text.delta", delta="done"),
            SimpleNamespace(
                type="response.reasoning_summary_text.delta", delta="safe update"
            ),
            SimpleNamespace(type="response.completed", response=completed),
        ]
    )
    provider = OpenAIResponsesProvider(
        model="gpt-test", api_key="unused", client=_Client(stream)
    )
    events: list[ModelEvent] = []

    async def on_event(event: ModelEvent) -> None:
        events.append(event)

    response = asyncio.run(
        provider.complete(
            ModelRequest(
                (ModelMessage("user", (TextBlock("go"),)),),
                reasoning_policy=_policy(ReasoningVisibility.UPDATES),
                tools=(_tool(),),
                stream=True,
            ),
            on_event,
        )
    )

    assert response.content == "done"
    assert stream.closed is True
    assert [call.id for call in response.tool_calls] == ["call-a", "call-b"]
    assert [event.kind for event in events] == [
        ModelEventKind.TEXT_DELTA,
        ModelEventKind.REASONING_SUMMARY_DELTA,
        ModelEventKind.USAGE,
        ModelEventKind.COMPLETED,
    ]


def test_responses_stream_cancellation_closes_stream() -> None:
    stream = _BlockingStream()
    provider = OpenAIResponsesProvider(
        model="gpt-test", api_key="unused", client=_Client(stream)
    )

    async def scenario() -> None:
        task = asyncio.create_task(
            provider.complete(
                ModelRequest(
                    (ModelMessage("user", (TextBlock("go"),)),), stream=True
                )
            )
        )
        await stream.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert stream.closed is True


def test_responses_reasoner_multi_tool_exchange_replays_private_state() -> None:
    client = _SequentialClient(
        [
            {
                "id": "resp-tools",
                "model": "gpt-test",
                "status": "completed",
                "output": [
                    {
                        "type": "reasoning",
                        "encrypted_content": "private-state",
                        "summary": [],
                    },
                    {
                        "type": "function_call",
                        "call_id": "call-a",
                        "name": "first",
                        "arguments": '{"value":1}',
                    },
                    {
                        "type": "function_call",
                        "call_id": "call-b",
                        "name": "second",
                        "arguments": '{"value":2}',
                    },
                ],
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
            {
                "id": "resp-final",
                "model": "gpt-test",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "完成"}],
                    }
                ],
                "usage": {"input_tokens": 7, "output_tokens": 1},
            },
        ]
    )
    provider = OpenAIResponsesProvider(
        model="gpt-test", api_key="unused", client=client
    )
    first = _RecordingTool("first")
    second = _RecordingTool("second")
    registry = ToolRegistry()
    registry.register(first)
    registry.register(second)

    result = asyncio.run(
        Reasoner(
            provider,
            tool_registry=registry,
            reasoning_policy=_policy(),
        ).run_turn([ChatMessage("user", "执行两个工具")], session_key="responses-e2e")
    )

    assert result.response.content == "完成"
    assert first.calls == [{"value": 1}]
    assert second.calls == [{"value": 2}]
    replay = client.responses.calls[1]["input"]
    assert [item.get("type") for item in replay[-5:]] == [
        "reasoning",
        "function_call",
        "function_call",
        "function_call_output",
        "function_call_output",
    ]
    assert "private-state" not in repr(result)
