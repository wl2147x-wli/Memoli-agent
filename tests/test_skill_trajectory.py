from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.provider import LLMResponse, ToolCall
from memoli_agent.agent.skills.admin import SkillAdminService
from memoli_agent.agent.skills.manifest import SkillPackageValidator
from memoli_agent.agent.skills.repository import SQLiteSkillRepository
from memoli_agent.agent.skills.requirements import RequirementEvaluator
from memoli_agent.agent.skills.runtime import SkillRuntime
from memoli_agent.agent.skills.tool import SkillLoadTool
from memoli_agent.agent.tools.builtin import TimeTool
from memoli_agent.agent.tools.control import (
    UpdateWorkingCheckpointTool,
    WorkingStateStore,
)
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import InMemoryTrajectoryStore, SQLiteTrajectoryStore
from memoli_agent.agent.types import ChatMessage


@dataclass
class CaptureProvider:
    responses: list[LLMResponse]
    calls: list[list[ChatMessage]] = field(default_factory=list)
    name: str = "capture"

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        del tools
        self.calls.append(list(messages))
        return self.responses.pop(0)


def _skill(root: Path) -> Path:
    root.mkdir()
    (root / "SKILL.md").write_text(
        """---
name: trace-method
version: 1.0.0
description: Use when demonstrating a traced Skill workflow.
---
Call the existing time tool, then explain the result.
""",
        encoding="utf-8",
    )
    return root


def test_catalog_load_generic_tool_and_domain_events_share_trace(
    tmp_path: Path,
) -> None:
    asyncio.run(_trajectory_case(tmp_path))


async def _trajectory_case(tmp_path: Path) -> None:
    skill_repository = SQLiteSkillRepository(tmp_path / "skills.db")
    validator = SkillPackageValidator()
    admin = SkillAdminService(skill_repository, tmp_path / "artifacts", validator)
    runtime = SkillRuntime(
        skill_repository, validator, RequirementEvaluator(environment={})
    )
    installed = admin.install(_skill(tmp_path / "source"))
    admin.activate(installed.name, installed.version, actor="tester", reason="release")

    trajectory_database = tmp_path / "trajectory.db"
    trajectory = SQLiteTrajectoryStore(
        trajectory_database,
        payload_directory=tmp_path / "payloads",
        capture_content="full-local",
    )
    await trajectory.start()
    registry = ToolRegistry()
    registry.register(TimeTool())
    registry.register(
        SkillLoadTool(
            runtime,
            tool_names_provider=lambda: {
                tool.name for tool in registry.list_tools()
            },
            trajectory_store=trajectory,
        )
    )
    catalog = runtime.build_catalog(
        session_instance_id="session-instance",
        session_key="cli:trace",
        tools={tool.name for tool in registry.list_tools()},
        mcp_servers=set(),
    )
    provider = CaptureProvider(
        [
            LLMResponse(
                "",
                [ToolCall("skill_load", {"name": "trace-method"}, id="load")],
                provider="capture",
            ),
            LLMResponse(
                "",
                [ToolCall("time", {}, id="time")],
                provider="capture",
            ),
            LLMResponse("done", provider="capture"),
        ]
    )
    reasoner = Reasoner(
        provider=provider,
        tool_registry=registry,
        trajectory_store=trajectory,
        max_iterations=4,
    )
    result = await reasoner.run_turn(
        [
            ChatMessage(role="system", content=catalog.content),
            ChatMessage(role="user", content="run traced method"),
        ],
        session_key="cli:trace",
        session_instance_id="session-instance",
    )
    await trajectory.close()
    skill_repository.close()

    assert result.response.content == "done"
    assert any(
        message.role == "tool" and "<skill_instruction" in message.content
        for message in provider.calls[1]
    )
    connection = sqlite3.connect(trajectory_database)
    rows = connection.execute(
        "SELECT event_type, trace_id, span_id FROM events ORDER BY sequence"
    ).fetchall()
    connection.close()
    event_types = [row[0] for row in rows]
    assert "skill_load_requested" in event_types
    assert "skill_loaded" in event_types
    assert event_types.count("tool_intent_recorded") == 2
    loaded = next(row for row in rows if row[0] == "skill_loaded")
    assert loaded[1] == result.trace_id
    assert loaded[2]


def test_related_sop_hint_alone_is_not_recorded_as_skill_use() -> None:
    trajectory = InMemoryTrajectoryStore()
    working = WorkingStateStore()
    registry = ToolRegistry()
    registry.register(UpdateWorkingCheckpointTool(working))
    provider = CaptureProvider(
        [
            LLMResponse(
                "",
                [
                    ToolCall(
                        "update_working_checkpoint",
                        {
                            "key_info": "collect evidence",
                            "objective": "research",
                            "current_step": "collect",
                            "related_sop": "trace-method",
                        },
                    )
                ],
                provider="capture",
            ),
            LLMResponse("done", provider="capture"),
        ]
    )
    reasoner = Reasoner(
        provider=provider,
        tool_registry=registry,
        trajectory_store=trajectory,
        working_state=working,
    )
    result = asyncio.run(
        reasoner.run_turn(
            [ChatMessage(role="user", content="remember the SOP hint")],
            session_key="cli:hint",
        )
    )
    assert result.response.content == "done"
    assert not any(event.event_type.startswith("skill_") for event in trajectory.events)
    checkpoint = working.get_checkpoint("cli:hint")
    assert checkpoint is not None and checkpoint.related_sop == "trace-method"
    working.close()
