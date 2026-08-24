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
            [
                ChatMessage("system", "system"),
                ChatMessage(
                    "system", "<working_checkpoint>旧状态</working_checkpoint>"
                ),
                ChatMessage("system", '<agent_status revision="99">旧</agent_status>'),
                ChatMessage("user", "开始"),
            ],
            session_key="task",
        )
    )
    status_blocks = [
        [message.content for message in call if "<agent_status" in message.content]
        for call in provider.calls
    ]
    assert all(len(blocks) == 1 for blocks in status_blocks)
    assert all(
        not any("<working_checkpoint>旧状态" in message.content for message in call)
        for call in provider.calls
    )
    assert 'revision="0"' in status_blocks[0][0]
    assert 'revision="1"' in status_blocks[1][0]
    assert "last_tool: update_working_checkpoint" in status_blocks[1][0]


def test_status_renders_complete_agent_fields_separate_from_runtime() -> None:
    state = WorkingStateStore(max_chars=4_000)
    state.update_checkpoint(
        "task",
        "关键发现",
        "openspec-apply-change",
        objective="统一上下文",
        current_step="移除旧块",
        next_action="运行验证",
        constraints=("不得重复注入", "保持 schema"),
        decisions=("调用前重建",),
        artifacts=("agent-plan.md",),
    )
    state.project_iteration(
        "task",
        iteration=2,
        elapsed_seconds=1.5,
        last_tool="file_patch",
        last_tool_status="completed",
        artifacts=("verified-output.txt",),
    )

    rendered = state.render_status("task")

    assert rendered.revision == 1
    assert rendered.truncated is False
    assert rendered.content.count("<agent_status") == 1
    assert '<working_checkpoint trust="agent">' in rendered.content
    assert "objective: 统一上下文" in rendered.content
    assert "current_step: 移除旧块" in rendered.content
    assert "next_action: 运行验证" in rendered.content
    assert "key_info: 关键发现" in rendered.content
    assert "related_sop: openspec-apply-change" in rendered.content
    assert "constraints: 不得重复注入; 保持 schema" in rendered.content
    assert "decisions: 调用前重建" in rendered.content
    assert "agent_artifacts: agent-plan.md" in rendered.content
    assert "runtime_artifacts: verified-output.txt" in rendered.content
    assert rendered.content.index("runtime_artifacts:") < rendered.content.index(
        "agent_artifacts:"
    )


def test_status_without_checkpoint_is_explicit_and_bounded() -> None:
    state = WorkingStateStore(max_chars=4_000)

    rendered = state.render_status("missing")

    assert rendered.revision == 0
    assert '<agent_status revision="0" trust="runtime">' in rendered.content
    assert '<working_checkpoint trust="agent">\nunavailable' in rendered.content

    bounded = WorkingStateStore(max_chars=160).render_status("missing")
    assert bounded.truncated is True
    assert bounded.content.endswith("...[TRUNCATED]")
    assert len(bounded.content) <= 160


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
