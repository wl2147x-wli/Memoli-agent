from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memoli_agent.agent.context import ContextBuilder
from memoli_agent.agent.core.passive_turn import PassiveTurnPipeline
from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.provider import LLMResponse, ToolCall
from memoli_agent.agent.session import SessionManager
from memoli_agent.agent.tools.control import WorkingStateStore
from memoli_agent.agent.types import ChatMessage
from memoli_agent.bootstrap.config import AppConfig, RuntimeConfig
from memoli_agent.bootstrap.tools import build_tool_registry
from memoli_agent.bus.events import InboundMessage


@dataclass
class CapturingProvider:
    responses: list[LLMResponse]
    calls: list[list[ChatMessage]] = field(default_factory=list)

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        return self.responses.pop(0)


def test_checkpoint_is_injected_into_next_user_turn(tmp_path: Path) -> None:
    state = WorkingStateStore()
    registry = build_tool_registry(
        AppConfig(runtime=RuntimeConfig(workspace=str(tmp_path))),
        working_state=state,
    )
    provider = CapturingProvider(
        [
            LLMResponse(
                "",
                [
                    ToolCall(
                        "update_working_checkpoint",
                        {"key_info": "必须先读文件", "related_sop": "coding"},
                        "checkpoint-1",
                    )
                ],
            ),
            LLMResponse("第一轮完成"),
            LLMResponse("第二轮完成"),
        ]
    )
    pipeline = PassiveTurnPipeline(
        session_manager=SessionManager(),
        context_builder=ContextBuilder("Memoli", "system"),
        reasoner=Reasoner(
            provider,
            tool_registry=registry,
            working_state=state,
        ),
        working_state=state,
    )

    async def scenario() -> None:
        await pipeline.run(InboundMessage("cli", "local", "tester", "开始任务"))
        await pipeline.run(InboundMessage("cli", "local", "tester", "继续任务"))

    asyncio.run(scenario())

    second_turn_messages = provider.calls[2]
    checkpoint_messages = [
        message.content
        for message in second_turn_messages
        if message.role == "system" and "<agent_status" in message.content
    ]
    assert len(checkpoint_messages) == 1
    assert 'revision="1"' in checkpoint_messages[0]
    assert "key_info: 必须先读文件" in checkpoint_messages[0]
    assert "related_sop: coding" in checkpoint_messages[0]
    assert not any(
        message.content.startswith("<working_checkpoint>")
        for message in second_turn_messages
    )
