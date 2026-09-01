import asyncio
from pathlib import Path

from memoli_agent.agent.skills.admin import SkillAdminService
from memoli_agent.agent.skills.manifest import SkillPackageValidator
from memoli_agent.agent.skills.repository import SQLiteSkillRepository
from memoli_agent.agent.skills.requirements import RequirementEvaluator
from memoli_agent.agent.skills.runtime import SkillRuntime
from memoli_agent.agent.skills.tool import SkillLoadTool
from memoli_agent.agent.subagent.profiles import (
    ProfileToolRegistryFactory,
    default_subagent_profiles,
)
from memoli_agent.agent.tools.builtin import TimeTool
from memoli_agent.agent.tools.execution import ToolExecutionContext
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import InMemoryTrajectoryStore


def _skill(root: Path) -> Path:
    root.mkdir()
    (root / "SKILL.md").write_text(
        """---
name: coding-method
version: 1.0.0
description: Use when a coding task can write files.
requires:
  tools: [file_write]
---
Write only through the current profile's existing file tool.
""",
        encoding="utf-8",
    )
    return root


def test_subagent_catalog_uses_actual_profile_tools_and_independent_snapshot(
    tmp_path: Path,
) -> None:
    repository = SQLiteSkillRepository(tmp_path / "skills.db")
    validator = SkillPackageValidator()
    admin = SkillAdminService(repository, tmp_path / "artifacts", validator)
    runtime = SkillRuntime(repository, validator, RequirementEvaluator(environment={}))
    trajectory = InMemoryTrajectoryStore()
    try:
        installed = admin.install(_skill(tmp_path / "source"))
        admin.activate(
            installed.name, installed.version, actor="tester", reason="release"
        )

        source = ToolRegistry()
        source.register(TimeTool())
        source.register(
            SkillLoadTool(
                runtime,
                tool_names_provider=lambda: {"time", "file_write", "skill_load"},
                trajectory_store=trajectory,
            )
        )
        factory = ProfileToolRegistryFactory(source, tmp_path)
        profiles = default_subagent_profiles()
        research = factory.build(profiles["research"], tmp_path / "research")
        coding_root = tmp_path / "coding"
        coding_root.mkdir()
        coding = factory.build(profiles["coding"], coding_root)

        research_catalog = runtime.build_catalog(
            session_instance_id="research-attempt",
            session_key="subagent:research",
            tools={tool.name for tool in research.list_tools()},
            mcp_servers=set(),
        )
        coding_catalog = runtime.build_catalog(
            session_instance_id="coding-attempt",
            session_key="subagent:coding",
            tools={tool.name for tool in coding.list_tools()},
            mcp_servers=set(),
        )
        assert research_catalog.content == ""
        assert "coding-method@1.0.0" in coding_catalog.content

        result = asyncio.run(
            coding.execute(
                "skill_load",
                {"name": "coding-method"},
                context=ToolExecutionContext(
                    trace_id="child-trace",
                    span_id="child-tool-span",
                    session_key="subagent:coding",
                    session_instance_id="coding-attempt",
                    tool_call_id="child-call",
                ),
            )
        )
        assert result.success
        assert result.metadata["session_instance_id"] == "coding-attempt"
        loaded = [
            event
            for event in trajectory.events
            if event.event_type == "skill_loaded"
        ]
        assert loaded[0].trace_id == "child-trace"
        assert loaded[0].span_id == "child-tool-span"
        assert loaded[0].payload_id is not None
        payload = trajectory.event_payloads[loaded[0].payload_id - 1]
        assert payload["tool_call_id"] == "child-call"
        invalid = asyncio.run(
            coding.execute(
                "skill_load",
                {"name": "coding-method", "artifact_path": "secret"},
                context=ToolExecutionContext(
                    trace_id="child-trace",
                    span_id="invalid-span",
                    session_key="subagent:coding",
                    session_instance_id="coding-attempt",
                    tool_call_id="invalid-call",
                ),
            )
        )
        assert not invalid.success
        assert invalid.metadata["error"] == "ToolArgumentsInvalid"
        assert invalid.metadata["validator"] == "additionalProperties"
    finally:
        repository.close()
