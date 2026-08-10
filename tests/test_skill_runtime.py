import stat
from pathlib import Path

from memoli_agent.agent.skills.admin import SkillAdminService
from memoli_agent.agent.skills.manifest import SkillPackageValidator
from memoli_agent.agent.skills.repository import SQLiteSkillRepository
from memoli_agent.agent.skills.requirements import RequirementEvaluator
from memoli_agent.agent.skills.runtime import SkillRuntime


def _source(
    root: Path,
    version: str,
    body: str,
    requirements: str = "",
) -> Path:
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "\n".join(
            (
                "---",
                "name: report",
                f"version: {version}",
                "description: Use when an evidence report is required.",
                requirements,
                "---",
                body,
            )
        ),
        encoding="utf-8",
    )
    references = root / "references"
    references.mkdir()
    (references / "guide.md").write_text("reference guide", encoding="utf-8")
    return root


def _runtime(
    tmp_path: Path, *, skill_chars: int = 1_000
) -> tuple[SkillAdminService, SQLiteSkillRepository, SkillRuntime]:
    repository = SQLiteSkillRepository(tmp_path / "skills.db")
    validator = SkillPackageValidator()
    admin = SkillAdminService(repository, tmp_path / "artifacts", validator)
    runtime = SkillRuntime(
        repository,
        validator,
        RequirementEvaluator(environment={}),
        max_skill_chars=skill_chars,
        max_reference_chars=1_000,
    )
    return admin, repository, runtime


def test_catalog_and_progressive_load_use_session_binding(tmp_path: Path) -> None:
    admin, repository, runtime = _runtime(tmp_path)
    try:
        installed = admin.install(_source(tmp_path / "v1", "1.0.0", "procedure"))
        admin.activate(
            installed.name, installed.version, actor="tester", reason="release"
        )
        catalog = runtime.build_catalog(
            session_instance_id="s1",
            session_key="chat",
            tools={"file_read"},
            mcp_servers=set(),
        )
        assert "report@1.0.0" in catalog.content

        body = runtime.load(
            session_instance_id="s1",
            name="report",
            reference=None,
            tools={"file_read"},
            mcp_servers=set(),
        )
        assert body.success is True
        assert '<skill_instruction name="report" version="1.0.0"' in body.content
        assert "procedure" in body.content
        assert "artifact" not in body.metadata

        reference = runtime.load(
            session_instance_id="s1",
            name="report",
            reference="references/guide.md",
            tools={"file_read"},
            mcp_servers=set(),
        )
        assert reference.success is True
        assert "reference guide" in reference.content
        escaped = runtime.load(
            session_instance_id="s1",
            name="report",
            reference="../secret.txt",
            tools={"file_read"},
            mcp_servers=set(),
        )
        assert escaped.metadata["rejection_reason"] == "invalid-reference"
        missing_reference = runtime.load(
            session_instance_id="s1",
            name="report",
            reference="references/missing.md",
            tools={"file_read"},
            mcp_servers=set(),
        )
        assert missing_reference.metadata["rejection_reason"] == "invalid-reference"
        unbound = runtime.load(
            session_instance_id="other-session",
            name="report",
            reference=None,
            tools={"file_read"},
            mcp_servers=set(),
        )
        assert unbound.metadata["rejection_reason"] == "not-visible"
    finally:
        repository.close()


def test_out_of_band_artifact_tampering_is_rejected(tmp_path: Path) -> None:
    admin, repository, runtime = _runtime(tmp_path)
    try:
        installed = admin.install(_source(tmp_path / "v1", "1.0.0", "procedure"))
        admin.activate(
            installed.name, installed.version, actor="tester", reason="release"
        )
        runtime.build_catalog(
            session_instance_id="s1",
            session_key="chat",
            tools={"file_read"},
            mcp_servers=set(),
        )
        skill_file = Path(installed.artifact_path) / "SKILL.md"
        skill_file.chmod(stat.S_IREAD | stat.S_IWRITE)
        skill_file.write_text(skill_file.read_text(encoding="utf-8") + "tamper")
        outcome = runtime.load(
            session_instance_id="s1",
            name="report",
            reference=None,
            tools={"file_read"},
            mcp_servers=set(),
        )
        assert outcome.metadata["rejection_reason"] == "integrity-mismatch"
    finally:
        repository.close()


def test_empty_snapshot_catalog_budget_and_version_changes_are_stable(
    tmp_path: Path,
) -> None:
    admin, repository, runtime = _runtime(tmp_path)
    try:
        empty = runtime.build_catalog(
            session_instance_id="empty-session",
            session_key="chat",
            tools={"file_read"},
            mcp_servers=set(),
        )
        assert empty.content == ""
        v1 = admin.install(_source(tmp_path / "v1", "1.0.0", "one"))
        admin.activate(v1.name, v1.version, actor="tester", reason="v1")
        still_empty = runtime.build_catalog(
            session_instance_id="empty-session",
            session_key="chat",
            tools={"file_read"},
            mcp_servers=set(),
        )
        assert still_empty.content == ""

        first = runtime.build_catalog(
            session_instance_id="stable-session",
            session_key="chat",
            tools={"file_read"},
            mcp_servers=set(),
        )
        v2 = admin.install(_source(tmp_path / "v2", "2.0.0", "two"))
        admin.activate(v2.name, v2.version, actor="tester", reason="v2")
        second = runtime.build_catalog(
            session_instance_id="stable-session",
            session_key="chat",
            tools={"file_read"},
            mcp_servers=set(),
        )
        assert first.content == second.content
        assert "report@1.0.0" in second.content

        tiny_runtime = SkillRuntime(
            repository,
            SkillPackageValidator(),
            RequirementEvaluator(environment={}),
            max_catalog_chars=10,
        )
        tiny = tiny_runtime.build_catalog(
            session_instance_id="tiny-session",
            session_key="chat",
            tools={"file_read"},
            mcp_servers=set(),
        )
        assert tiny.content == ""
        assert tiny.omitted and tiny.omitted_count == 1
    finally:
        repository.close()


def test_deprecated_binding_continues_but_new_session_cannot_bind(
    tmp_path: Path,
) -> None:
    admin, repository, runtime = _runtime(tmp_path)
    try:
        installed = admin.install(_source(tmp_path / "v1", "1.0.0", "one"))
        admin.activate(
            installed.name, installed.version, actor="tester", reason="release"
        )
        runtime.build_catalog(
            session_instance_id="old",
            session_key="chat",
            tools={"file_read"},
            mcp_servers=set(),
        )
        admin.deprecate(
            installed.name, installed.version, actor="tester", reason="old"
        )
        old_load = runtime.load(
            session_instance_id="old",
            name="report",
            reference=None,
            tools={"file_read"},
            mcp_servers=set(),
        )
        new_catalog = runtime.build_catalog(
            session_instance_id="new",
            session_key="chat",
            tools={"file_read"},
            mcp_servers=set(),
        )
        assert old_load.success
        assert new_catalog.content == ""
    finally:
        repository.close()


def test_unavailable_environment_filters_catalog_without_secret_value(
    tmp_path: Path,
) -> None:
    repository = SQLiteSkillRepository(tmp_path / "skills.db")
    validator = SkillPackageValidator()
    admin = SkillAdminService(repository, tmp_path / "artifacts", validator)
    runtime = SkillRuntime(
        repository,
        validator,
        RequirementEvaluator(environment={"API_SECRET": "super-secret-value"}),
    )
    try:
        source = _source(
            tmp_path / "v1",
            "1.0.0",
            "one",
            "requires:\n  env: [MISSING_SECRET]",
        )
        installed = admin.install(source)
        admin.activate(
            installed.name, installed.version, actor="tester", reason="release"
        )
        catalog = runtime.build_catalog(
            session_instance_id="secret-session",
            session_key="chat",
            tools={"file_read"},
            mcp_servers=set(),
        )
        assert catalog.content == ""
        assert "super-secret-value" not in repr(catalog)
    finally:
        repository.close()


def test_load_rechecks_dependency_revocation_integrity_and_budget(
    tmp_path: Path,
) -> None:
    admin, repository, runtime = _runtime(tmp_path, skill_chars=5)
    try:
        installed = admin.install(
            _source(
                tmp_path / "v1",
                "1.0.0",
                "long procedure",
                "requires:\n  tools: [file_read]",
            )
        )
        admin.activate(
            installed.name, installed.version, actor="tester", reason="release"
        )
        runtime.build_catalog(
            session_instance_id="s1",
            session_key="chat",
            tools={"file_read"},
            mcp_servers=set(),
        )
        over_budget = runtime.load(
            session_instance_id="s1",
            name="report",
            reference=None,
            tools={"file_read"},
            mcp_servers=set(),
        )
        assert over_budget.success is False
        assert over_budget.metadata["rejection_reason"] == "content-budget-exceeded"

        missing = runtime.load(
            session_instance_id="s1",
            name="report",
            reference=None,
            tools=set(),
            mcp_servers=set(),
        )
        assert missing.metadata["rejection_reason"] == "requirements-unavailable"

        admin.revoke("report", "1.0.0", actor="tester", reason="unsafe")
        revoked = runtime.load(
            session_instance_id="s1",
            name="report",
            reference=None,
            tools={"file_read"},
            mcp_servers=set(),
        )
        assert revoked.metadata["rejection_reason"] == "revoked"
    finally:
        repository.close()
