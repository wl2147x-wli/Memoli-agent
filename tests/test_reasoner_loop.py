from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.core.results import TerminationReason, TurnResult
from memoli_agent.agent.provider import LLMResponse, ProviderError, ToolCall
from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import (
    InMemoryTrajectoryStore,
    NewTrajectoryEvent,
    SpanKind,
    SQLiteTrajectoryStore,
    TrajectoryError,
)
from memoli_agent.agent.types import ChatMessage


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


@dataclass
class ScriptedProvider:
    responses: list[LLMResponse]
    name: str = "scripted"
    calls: list[list[ChatMessage]] = field(default_factory=list)

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        if not self.responses:
            raise ProviderError("没有更多脚本响应")
        return self.responses.pop(0)


@dataclass
class FailingProvider:
    name: str = "failing"

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        raise ProviderError("provider failed")


@dataclass
class SlowToolProvider:
    name: str = "slow"
    calls: int = 0

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls += 1
        await asyncio.sleep(0.01)
        return LLMResponse("", [ToolCall("work", {})], provider=self.name)


@dataclass
class RecordingTool:
    name: str
    success: bool = True
    needs_user: bool = False
    calls: list[dict[str, Any]] = field(default_factory=list)
    description: str = "测试工具"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(arguments)
        return ToolResult(
            content=f"{self.name}-result",
            success=self.success,
            metadata={
                "error": None if self.success else "ExpectedFailure",
                "needs_user": self.needs_user,
            },
        )


@dataclass
class FailAfterStore(InMemoryTrajectoryStore):
    fail_at: int = 1

    async def record(self, item: NewTrajectoryEvent):  # type: ignore[no-untyped-def]
        if len(self.events) + 1 == self.fail_at:
            raise TrajectoryError("expected write failure")
        return await super().record(item)


def make_registry(*tools: RecordingTool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def test_two_tool_rounds_complete_and_preserve_model_context() -> None:
    first_tool = RecordingTool("first")
    second_tool = RecordingTool("second")
    provider = ScriptedProvider(
        [
            LLMResponse(
                "", [ToolCall("first", {"value": 1}, "call-1")], provider="scripted"
            ),
            LLMResponse(
                "", [ToolCall("second", {"value": 2}, "call-2")], provider="scripted"
            ),
            LLMResponse("最终完成", provider="scripted", usage={"total_tokens": 9}),
        ]
    )
    store = InMemoryTrajectoryStore()
    reasoner = Reasoner(
        provider,
        tool_registry=make_registry(first_tool, second_tool),
        trajectory_store=store,
    )

    result = run(reasoner.run_turn([ChatMessage("user", "执行任务")], session_key="s1"))

    assert result.termination_reason is TerminationReason.COMPLETED
    assert result.response.content == "最终完成"
    assert result.iterations == 3
    assert first_tool.calls == [{"value": 1}]
    assert second_tool.calls == [{"value": 2}]
    assert any(message.content == "first-result" for message in provider.calls[1])
    assert any(message.content == "second-result" for message in provider.calls[2])
    assert [event.event_type for event in store.events].count("model_requested") == 3
    assert store.events[-1].event_type == "trace_finished"


def test_two_tool_rounds_persist_complete_sqlite_hierarchy(tmp_path: Path) -> None:
    async def scenario() -> tuple[TurnResult, dict[str, Any]]:
        provider = ScriptedProvider(
            [
                LLMResponse("", [ToolCall("first", {}, "call-1")]),
                LLMResponse("", [ToolCall("second", {}, "call-2")]),
                LLMResponse("最终完成", usage={"total_tokens": 9}),
            ]
        )
        store = SQLiteTrajectoryStore(
            tmp_path / "trace.db",
            payload_directory=tmp_path / "payloads",
        )
        await store.start()
        result = await Reasoner(
            provider,
            tool_registry=make_registry(
                RecordingTool("first"), RecordingTool("second")
            ),
            trajectory_store=store,
        ).run_turn([ChatMessage("user", "执行任务")], session_key="sqlite-session")
        bundle = await store.get_trace(result.trace_id)
        await store.close()
        assert bundle is not None
        return result, bundle

    result, bundle = run(scenario())
    assert result.termination_reason is TerminationReason.COMPLETED
    events = bundle["events"]
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    event_types = [event["event_type"] for event in events]
    assert event_types.count("model_requested") == 3
    assert event_types.count("tool_intent_recorded") == 2
    assert event_types[-1] == "trace_finished"
    span_kinds = [span["kind"] for span in bundle["spans"]]
    assert span_kinds.count(SpanKind.LLM.value) == 3
    assert span_kinds.count(SpanKind.TOOL.value) == 2


def test_multiple_tools_execute_in_declared_order() -> None:
    order: list[str] = []

    @dataclass
    class OrderedTool(RecordingTool):
        async def run(self, arguments: dict[str, Any]) -> ToolResult:
            order.append(self.name)
            return await super().run(arguments)

    first = OrderedTool("first")
    second = OrderedTool("second")
    provider = ScriptedProvider(
        [
            LLMResponse(
                "",
                [ToolCall("first", {}), ToolCall("second", {})],
                provider="scripted",
            ),
            LLMResponse("完成", provider="scripted"),
        ]
    )
    reasoner = Reasoner(provider, tool_registry=make_registry(first, second))

    result = run(reasoner.run_turn([ChatMessage("user", "go")], session_key="s"))

    assert result.termination_reason is TerminationReason.COMPLETED
    assert order == ["first", "second"]


def test_missing_tool_call_ids_are_normalized_once() -> None:
    first = RecordingTool("first")
    second = RecordingTool("second")
    provider = ScriptedProvider(
        [
            LLMResponse(
                "",
                [ToolCall("first", {}), ToolCall("second", {})],
                provider="scripted",
            ),
            LLMResponse("完成", provider="scripted"),
        ]
    )
    store = InMemoryTrajectoryStore()
    result = run(
        Reasoner(
            provider,
            tool_registry=make_registry(first, second),
            trajectory_store=store,
        ).run_turn([ChatMessage("user", "go")], session_key="s")
    )

    assert result.termination_reason is TerminationReason.COMPLETED
    assistant = next(
        message for message in provider.calls[1] if message.role == "assistant"
    )
    tool_messages = [message for message in provider.calls[1] if message.role == "tool"]
    assistant_ids = [call["id"] for call in assistant.tool_calls or []]
    assert assistant_ids == ["call_1_0", "call_1_1"]
    assert [message.tool_call_id for message in tool_messages] == assistant_ids
    intent_payloads = [
        payload
        for event, payload in zip(store.events, store.event_payloads, strict=True)
        if event.event_type == "tool_intent_recorded"
    ]
    assert [payload["tool_call_id"] for payload in intent_payloads] == assistant_ids


def test_needs_user_and_provider_fallback_are_explicit() -> None:
    needs_user = RecordingTool("approval", needs_user=True)
    provider = ScriptedProvider(
        [LLMResponse("", [ToolCall("approval", {})], provider="scripted")]
    )
    result = run(
        Reasoner(provider, tool_registry=make_registry(needs_user)).run_turn(
            [ChatMessage("user", "go")], session_key="s"
        )
    )
    assert result.termination_reason is TerminationReason.NEEDS_USER

    fallback = ScriptedProvider([LLMResponse("fallback ok", provider="echo")])
    fallback_result = run(
        Reasoner(FailingProvider(), fallback_provider=fallback).run_turn(
            [ChatMessage("user", "hello")], session_key="s"
        )
    )
    assert fallback_result.termination_reason is TerminationReason.COMPLETED
    assert fallback_result.fallback_used is True
    assert fallback_result.response.provider == "echo"


def test_completion_retries_and_iteration_budget() -> None:
    provider = ScriptedProvider(
        [
            LLMResponse("", provider="scripted"),
            LLMResponse("被截断", provider="scripted", finish_reason="length"),
            LLMResponse("完整回复", provider="scripted"),
        ]
    )
    result = run(
        Reasoner(provider, max_iterations=3).run_turn(
            [ChatMessage("user", "hello")], session_key="s"
        )
    )
    assert result.termination_reason is TerminationReason.COMPLETED
    assert result.iterations == 3

    tool = RecordingTool("work")
    budget_provider = ScriptedProvider(
        [LLMResponse("", [ToolCall("work", {})], provider="scripted")]
    )
    exhausted = run(
        Reasoner(
            budget_provider,
            tool_registry=make_registry(tool),
            max_iterations=1,
        ).run_turn([ChatMessage("user", "go")], session_key="s")
    )
    assert exhausted.termination_reason is TerminationReason.BUDGET_EXHAUSTED
    assert exhausted.response.content == "任务未在迭代预算内完成。"


def test_repeated_failure_stops_with_no_progress() -> None:
    tool = RecordingTool("broken", success=False)
    provider = ScriptedProvider(
        [
            LLMResponse("", [ToolCall("broken", {"x": 2})], provider="scripted"),
            LLMResponse("", [ToolCall("broken", {"x": 1})], provider="scripted"),
        ]
    )
    result = run(
        Reasoner(
            provider,
            tool_registry=make_registry(tool),
            max_iterations=4,
            no_progress_limit=2,
        ).run_turn([ChatMessage("user", "go")], session_key="s")
    )
    assert result.termination_reason is TerminationReason.FAILED
    assert result.error_type == "no-progress"
    assert len(tool.calls) == 2


def test_partial_prepared_trace_identifiers_are_rejected() -> None:
    provider = ScriptedProvider([LLMResponse("完成")])
    with pytest.raises(ValueError, match="必须同时提供"):
        run(
            Reasoner(provider).run_turn(
                [ChatMessage("user", "go")],
                session_key="s",
                trace_id="0" * 32,
            )
        )


def test_trace_write_failure_prevents_tool_side_effect() -> None:
    tool = RecordingTool("side_effect")
    provider = ScriptedProvider(
        [LLMResponse("", [ToolCall("side_effect", {})], provider="scripted")]
    )
    store = FailAfterStore(fail_at=4)
    result = run(
        Reasoner(
            provider,
            tool_registry=make_registry(tool),
            trajectory_store=store,
        ).run_turn([ChatMessage("user", "go")], session_key="s")
    )
    assert result.termination_reason is TerminationReason.FAILED
    assert result.error_type == "trace-write-failed"
    assert tool.calls == []
    assert len(provider.calls) == 1


def test_elapsed_budget_stops_before_tool_execution() -> None:
    tool = RecordingTool("work")
    provider = SlowToolProvider()
    started = time.monotonic()
    result = run(
        Reasoner(
            provider,
            tool_registry=make_registry(tool),
            # 使用远小于一次事件循环调度的预算，避免 Windows 计时器粒度导致偶发失败。
            max_elapsed_seconds=1e-9,
        ).run_turn([ChatMessage("user", "go")], session_key="s")
    )
    assert time.monotonic() - started < 1
    assert result.termination_reason is TerminationReason.BUDGET_EXHAUSTED
    assert tool.calls == []
