import pytest

from memoli_agent.agent.skills.manifest import SkillPackageValidator
from memoli_agent.agent.skills.models import (
    SkillBinding,
    SkillRequirements,
    SkillVersion,
)
from memoli_agent.agent.skills.requirements import RequirementEvaluator
from memoli_agent.agent.skills.runtime import SkillRuntime


def test_requirement_evaluator_covers_tools_mcp_bin_env_and_platform(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "memoli_agent.agent.skills.requirements.shutil.which",
        lambda name: "C:/bin/git" if name == "git" else None,
    )
    monkeypatch.setattr(
        "memoli_agent.agent.skills.requirements.platform.system",
        lambda: "Windows",
    )
    evaluator = RequirementEvaluator(environment={"TOKEN": "secret-value"})
    requirements = SkillRequirements(
        tools=("file_read",),
        mcp=("docs",),
        bins=("git",),
        env=("TOKEN",),
        platforms=("windows",),
    )
    assert evaluator.evaluate(
        requirements,
        tools={"file_read"},
        mcp_servers={"docs"},
    ).available

    missing = evaluator.evaluate(
        SkillRequirements(
            tools=("write",),
            mcp=("search",),
            bins=("missing-bin",),
            env=("MISSING_TOKEN",),
            platforms=("linux",),
        ),
        tools=set(),
        mcp_servers=set(),
    )
    assert missing.missing == (
        "tool:write",
        "mcp:search",
        "bin:missing-bin",
        "env:MISSING_TOKEN",
        "platform:windows",
    )
    assert "secret-value" not in repr(missing)


class BrokenRuntimeRepository:
    def list_active(self) -> list[SkillVersion]:
        raise RuntimeError("database unavailable")

    def create_snapshot(
        self,
        session_instance_id: str,
        session_key: str,
        versions: list[SkillVersion],
    ) -> list[SkillBinding]:
        del session_instance_id, session_key, versions
        return []

    def get_bound_version(
        self, session_instance_id: str, name: str
    ) -> None:
        del session_instance_id, name
        return None


def test_catalog_failure_is_isolated_without_injecting_fallback_text() -> None:
    runtime = SkillRuntime(
        BrokenRuntimeRepository(),
        SkillPackageValidator(),
        RequirementEvaluator(environment={}),
    )
    catalog = runtime.build_catalog(
        session_instance_id="session",
        session_key="chat",
        tools=set(),
        mcp_servers=set(),
    )
    assert catalog.content == ""
    assert catalog.error == "RuntimeError"
