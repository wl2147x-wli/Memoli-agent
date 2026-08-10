from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from memoli_agent.agent.context import ContextBuilder
from memoli_agent.agent.core.passive_turn import PassiveTurnPipeline
from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.loop import AgentLoop
from memoli_agent.agent.memory.models import MemoryItem, MemoryQueryResult
from memoli_agent.agent.provider import LLMResponse, ToolCall
from memoli_agent.agent.runner import AgentRunner
from memoli_agent.agent.session import SessionManager
from memoli_agent.agent.skills.models import SkillCatalog
from memoli_agent.agent.tools.builtin import TimeTool
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import InMemoryTrajectoryStore
from memoli_agent.agent.types import ContextRequest, TurnState
from memoli_agent.bus.events import InboundMessage, OutboundMessage
from memoli_agent.bus.queue import MessageBus


def test_session_isolation_history_window_and_context_block_order() -> None:
    manager = SessionManager(history_window=2)
    first = manager.get_or_create("cli:first")
    second = manager.get_or_create("cli:second")
    first.add_user_message("old")
    first.add_assistant_message("recent answer")
    first.add_user_message("recent question")

    assert [item.content for item in first.get_history()] == [
        "recent answer",
        "recent question",
    ]
    assert second.get_history() == []

    inbound = InboundMessage("cli", "first", "user", "current")
    rendered = ContextBuilder("Memoli", "system").render(
        ContextRequest(
            TurnState(inbound.session_key, inbound, first),
            "Memoli",
            "system",
            skill_catalog_prompt_block="skill-budgeted",
            memory_prompt_block="memory-budgeted",
            working_prompt_block="working-budgeted",
        )
    )
    assert [message.content for message in rendered.messages] == [
        "system",
        "skill-budgeted",
        "memory-budgeted",
        "working-budgeted",
        "recent answer",
        "recent question",
        "current",
    ]


@dataclass
class ScriptedProvider:
    responses: list[LLMResponse]
    calls: list[list[Any]] = field(default_factory=list)

    async def chat(
        self, messages: list[Any], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        self.calls.append(list(messages))
        return self.responses.pop(0)


@dataclass
class FakeMemoryRuntime:
    async def pre_recall(self, **_: Any) -> MemoryQueryResult:
        return MemoryQueryResult(
            [
                MemoryItem(
                    "用户偏好简洁回答",
                    "test",
                    datetime.now(UTC),
                    item_id="claim-1",
                )
            ],
            candidate_count=1,
            injected_chars=8,
            reason="test",
        )

    def render_prompt_block(self, result: MemoryQueryResult) -> str:
        return f"<memory>{result.items[0].content}</memory>"

    async def project_completed_trace(self, *_: Any, **__: Any) -> dict[str, str]:
        return {"status": "disabled"}


@dataclass
class FakeSkillRuntime:
    def build_catalog(self, **_: Any) -> SkillCatalog:
        content = "<available_skills><skill name='research'/></available_skills>"
        return SkillCatalog(content, 1, 1, len(content))


def test_deterministic_inbound_to_outbound_e2e() -> None:
    provider = ScriptedProvider(
        [
            LLMResponse("", [ToolCall("time", {}, "time-1")]),
            LLMResponse("已结合记忆、Skill 和工具完成。"),
        ]
    )
    trajectory = InMemoryTrajectoryStore()
    registry = ToolRegistry()
    registry.register(TimeTool())
    sessions = SessionManager(history_window=4)
    pipeline = PassiveTurnPipeline(
        session_manager=sessions,
        context_builder=ContextBuilder("Memoli", "system"),
        reasoner=Reasoner(
            provider,
            tool_registry=registry,
            trajectory_store=trajectory,
        ),
        memory_runtime=FakeMemoryRuntime(),  # type: ignore[arg-type]
        trajectory_store=trajectory,
        skill_runtime=FakeSkillRuntime(),  # type: ignore[arg-type]
        tool_registry=registry,
    )
    bus = MessageBus()
    loop = AgentLoop(bus, AgentRunner(passive_turn_pipeline=pipeline))

    async def scenario() -> OutboundMessage:
        await trajectory.start()
        await loop.start()
        await bus.publish_inbound(InboundMessage("cli", "e2e", "user", "几点了"))
        outbound = await asyncio.wait_for(bus.consume_outbound(), 1)
        await loop.stop()
        return outbound

    outbound = asyncio.run(scenario())
    assert outbound.content == "已结合记忆、Skill 和工具完成。"
    assert outbound.metadata["trace_id"]
    assert [item.role for item in sessions.get_or_create("cli:e2e").get_history()] == [
        "user",
        "assistant",
    ]
    assert any(event.event_type == "tool_finished" for event in trajectory.events)
    first_context = [message.content for message in provider.calls[0]]
    assert any("available_skills" in content for content in first_context)
    assert any("用户偏好简洁回答" in content for content in first_context)
