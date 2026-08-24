from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memoli_agent.agent.context_management import (
    ConservativeTokenEstimator,
    FrozenToolPreview,
    InMemoryContextStateRepository,
    ToolResultPreviewer,
)
from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.core.results import TerminationReason
from memoli_agent.agent.provider import LLMResponse, ToolCall
from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.control import AskUserTool
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import (
    InMemoryTrajectoryStore,
    SpanKind,
    SQLiteTrajectoryStore,
    TrajectoryError,
)
from memoli_agent.agent.types import ChatMessage
from memoli_agent.bootstrap.config import AppConfig, RuntimeConfig
from memoli_agent.bootstrap.tools import build_tool_registry


@dataclass
class Provider:
    responses: list[LLMResponse]
    calls: list[list[ChatMessage]] = field(default_factory=list)

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        return self.responses.pop(0)


@dataclass
class RawTool:
    name: str = "raw_tool"
    description: str = "测试原始与模型输出分离"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            "bounded",
            raw_content="complete-raw-output",
            metadata={"truncated": True},
        )


def test_raw_trajectory_keeps_schema_original_and_executed_arguments() -> None:
    registry = ToolRegistry()
    registry.register(RawTool())
    store = InMemoryTrajectoryStore()
    provider = Provider(
        [
            LLMResponse("", [ToolCall("raw_tool", {"value": 1}, "call-1")]),
            LLMResponse("完成"),
        ]
    )

    result = asyncio.run(
        Reasoner(provider, tool_registry=registry, trajectory_store=store).run_turn(
            [ChatMessage("user", "go")], session_key="session-1"
        )
    )

    assert result.response.content == "完成"
    model_request = next(
        payload
        for event, payload in zip(store.events, store.event_payloads, strict=True)
        if event.event_type == "model_requested"
    )
    tool_result = next(
        payload
        for event, payload in zip(store.events, store.event_payloads, strict=True)
        if event.event_type == "tool_finished"
    )
    assert model_request["tools"][0]["function"]["name"] == "raw_tool"
    assert tool_result["original_arguments"] == {"value": 1}
    assert tool_result["executed_arguments"] == {"value": 1}
    assert tool_result["raw_content"] == "complete-raw-output"
    assert tool_result["model_content"] == "bounded"
    root = next(span for span in store.spans.values() if span.kind is SpanKind.AGENT)
    assert root.input_data["session_id"] == "session-1"
    assert root.input_data["current_user_message_index"] == 0
    assert root.input_data["current_user_message_id"]
    forbidden = {"reward", "rubric", "correct_tool", "sft", "rl"}
    assert forbidden.isdisjoint(key.lower() for key in tool_result)


def test_real_ask_user_tool_ends_turn_with_structured_question() -> None:
    registry = ToolRegistry()
    registry.register(AskUserTool())
    provider = Provider(
        [
            LLMResponse(
                "",
                [
                    ToolCall(
                        "ask_user",
                        {"question": "继续吗？", "candidates": ["继续", "暂停"]},
                        "call-ask",
                    )
                ],
            )
        ]
    )

    result = asyncio.run(
        Reasoner(provider, tool_registry=registry).run_turn(
            [ChatMessage("user", "go")], session_key="session-1"
        )
    )

    assert result.termination_reason is TerminationReason.NEEDS_USER
    assert "继续吗？" in result.response.content
    assert "1. 继续" in result.response.content


def test_real_file_tools_complete_a_multi_round_task(tmp_path: Path) -> None:
    registry = build_tool_registry(
        AppConfig(runtime=RuntimeConfig(workspace=str(tmp_path)))
    )
    provider = Provider(
        [
            LLMResponse(
                "",
                [
                    ToolCall(
                        "file_write",
                        {"path": "result.txt", "content": "完成\n"},
                        "call-write",
                    )
                ],
            ),
            LLMResponse(
                "",
                [
                    ToolCall(
                        "file_read",
                        {"path": "result.txt", "show_linenos": False},
                        "call-read",
                    )
                ],
            ),
            LLMResponse("任务完成"),
        ]
    )

    result = asyncio.run(
        Reasoner(provider, tool_registry=registry).run_turn(
            [ChatMessage("user", "写入并检查")], session_key="session-1"
        )
    )

    assert result.response.content == "任务完成"
    assert (tmp_path / "result.txt").read_text(encoding="utf-8") == "完成\n"
    assert any(message.content == "完成\n" for message in provider.calls[2])


def test_large_result_uses_redacted_payload_and_frozen_preview(tmp_path: Path) -> None:
    async def scenario() -> tuple[
        str, list[list[ChatMessage]], object, FrozenToolPreview
    ]:
        registry = ToolRegistry()
        registry.register(RawTool())
        store = SQLiteTrajectoryStore(
            tmp_path / "trace.db",
            payload_directory=tmp_path / "payloads",
            capture_content="redacted",
        )
        await store.start()
        provider = Provider(
            [
                LLMResponse("", [ToolCall("raw_tool", {}, "call-large")]),
                LLMResponse("done"),
            ]
        )
        context_repo = InMemoryContextStateRepository()
        previewer = ToolResultPreviewer(
            context_repo, ConservativeTokenEstimator(), preview_tokens=8
        )
        # Exercise trajectory sanitization with a secret-like raw result.
        registry._tools["raw_tool"] = SensitiveRawTool()
        result = await Reasoner(
            provider,
            tool_registry=registry,
            trajectory_store=store,
            tool_result_previewer=previewer,
        ).run_turn([ChatMessage("user", "go")], session_key="session-large")
        bundle = await store.get_trace(result.trace_id)
        assert bundle is not None
        raw_event = next(
            item
            for item in bundle["events"]
            if item["event_type"] == "tool_result_payload_stored"
        )
        payload = await store.read_payload_json(raw_event["payload_id"])
        preview = next(iter(context_repo.previews.values()))
        await store.close()
        return result.response.content, provider.calls, payload, preview

    content, calls, payload, preview = asyncio.run(scenario())
    assert content == "done"
    assert "secret-value" not in str(payload)
    assert "[REDACTED]" in str(payload)
    tool_message = next(item for item in calls[1] if item.role == "tool")
    assert tool_message.content == preview.preview
    assert preview.payload_ref.startswith("trajectory-payload:")
    assert preview.transformed is True


@dataclass
class SensitiveRawTool(RawTool):
    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            "short fallback",
            raw_content="authorization: Bearer secret-value\n" + "x" * 500,
        )


def test_short_result_stays_verbatim_with_previewer_enabled() -> None:
    registry = ToolRegistry()
    registry.register(RawTool())
    provider = Provider(
        [
            LLMResponse("", [ToolCall("raw_tool", {}, "call-short")]),
            LLMResponse("done"),
        ]
    )
    previewer = ToolResultPreviewer(
        InMemoryContextStateRepository(),
        ConservativeTokenEstimator(),
        preview_tokens=1_000,
    )
    asyncio.run(
        Reasoner(
            provider,
            tool_registry=registry,
            trajectory_store=InMemoryTrajectoryStore(),
            tool_result_previewer=previewer,
        ).run_turn([ChatMessage("user", "go")], session_key="short")
    )
    tool_message = next(item for item in provider.calls[1] if item.role == "tool")
    assert tool_message.content == "bounded"


@dataclass
class FailOnPayloadStore(InMemoryTrajectoryStore):
    async def record(self, item):  # type: ignore[no-untyped-def]
        if item.event_type == "tool_result_payload_stored":
            raise TrajectoryError("expected payload failure")
        return await super().record(item)


def test_payload_write_failure_stops_before_preview_is_committed() -> None:
    registry = ToolRegistry()
    tool = RawTool()
    registry.register(tool)
    provider = Provider([LLMResponse("", [ToolCall("raw_tool", {}, "call-failure")])])
    context_repo = InMemoryContextStateRepository()
    result = asyncio.run(
        Reasoner(
            provider,
            tool_registry=registry,
            trajectory_store=FailOnPayloadStore(),
            tool_result_previewer=ToolResultPreviewer(
                context_repo, ConservativeTokenEstimator(), 8
            ),
        ).run_turn([ChatMessage("user", "go")], session_key="failure")
    )
    assert result.error_type == "trace-write-failed"
    assert context_repo.previews == {}


def test_payload_reference_is_not_an_ambient_read_capability() -> None:
    registry = ToolRegistry()
    result = asyncio.run(
        registry.execute(
            "trajectory-payload:42",
            {"workspace": "outside", "scope": "admin"},
        )
    )
    assert result.success is False
    assert result.metadata["tool"] == "trajectory-payload:42"
    assert "不存在" in result.content
