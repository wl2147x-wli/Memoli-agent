from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.provider import LLMResponse, ProviderError, ToolCall
from memoli_agent.agent.tools.control import (
    UpdateWorkingCheckpointTool,
    WorkingStateStore,
)
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.types import ChatMessage
from memoli_agent.agent.working.repository import WorkingStateRepository


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


def test_every_model_call_sees_one_latest_status() -> None:
    state = WorkingStateStore()
    registry = ToolRegistry()
    registry.register(UpdateWorkingCheckpointTool(state))
    provider = Provider(
        [
            LLMResponse(
                "",
                [ToolCall("update_working_checkpoint", {"key_info": "已读配置"}, "c1")],
            ),
            LLMResponse("完成"),
        ]
    )
    reasoner = Reasoner(provider, tool_registry=registry, working_state=state)
    asyncio.run(
        reasoner.run_turn(
            [ChatMessage("system", "system"), ChatMessage("user", "开始")],
            session_key="task",
        )
    )
    status_blocks = [
        [message.content for message in call if "<agent_status" in message.content]
        for call in provider.calls
    ]
    assert all(len(blocks) == 1 for blocks in status_blocks)
    assert 'revision="0"' in status_blocks[0][0]
    assert 'revision="1"' in status_blocks[1][0]
    assert "last_tool: update_working_checkpoint" in status_blocks[1][0]


def test_retry_and_fallback_share_unique_status_path() -> None:
    state = WorkingStateStore()
    primary = Provider([LLMResponse(""), LLMResponse("完成")])
    reasoner = Reasoner(primary, working_state=state)
    asyncio.run(
        reasoner.run_turn([ChatMessage("user", "开始")], session_key="retry-task")
    )
    assert len(primary.calls) == 2
    assert all(
        sum("<agent_status" in message.content for message in call) == 1
        for call in primary.calls
    )

    @dataclass
    class FailingProvider:
        async def chat(
            self,
            messages: list[ChatMessage],
            tools: list[dict[str, Any]] | None = None,
        ) -> LLMResponse:
            raise ProviderError("失败")

    fallback = Provider([LLMResponse("fallback")])
    asyncio.run(
        Reasoner(
            FailingProvider(),
            fallback_provider=fallback,
            working_state=state,
        ).run_turn([ChatMessage("user", "继续")], session_key="fallback-task")
    )
    assert sum("<agent_status" in message.content for message in fallback.calls[0]) == 1


def test_restart_restores_checkpoint_without_leaking_new_task(tmp_path: Path) -> None:
    database = tmp_path / "working.db"
    first_state = WorkingStateStore(repository=WorkingStateRepository(database))
    first_state.update_checkpoint("old-task", "持久化状态", "")
    first_state.close()

    restored_state = WorkingStateStore(repository=WorkingStateRepository(database))
    provider = Provider([LLMResponse("恢复"), LLMResponse("新任务")])
    reasoner = Reasoner(provider, working_state=restored_state)

    async def scenario() -> None:
        await reasoner.run_turn([ChatMessage("user", "继续")], session_key="old-task")
        await reasoner.run_turn([ChatMessage("user", "开始")], session_key="new-task")

    asyncio.run(scenario())
    old_status = next(
        message.content
        for message in provider.calls[0]
        if "<agent_status" in message.content
    )
    new_status = next(
        message.content
        for message in provider.calls[1]
        if "<agent_status" in message.content
    )
    assert "持久化状态" in old_status
    assert "持久化状态" not in new_status
