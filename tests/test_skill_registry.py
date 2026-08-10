import sqlite3
import stat
from pathlib import Path

import pytest

from memoli_agent.agent.skills.admin import SkillAdminService
from memoli_agent.agent.skills.manifest import SkillPackageValidator
from memoli_agent.agent.skills.repository import (
    SkillRegistryError,
    SkillRevisionConflict,
    SQLiteSkillRepository,
)


def _source(root: Path, version: str, body: str) -> Path:
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "\n".join(
            (
                "---",
                "name: report",
                f"version: {version}",
                "description: Build a report.",
                "---",
                body,
            )
        ),
        encoding="utf-8",
    )
    return root


def _admin(tmp_path: Path) -> tuple[SkillAdminService, SQLiteSkillRepository]:
    repository = SQLiteSkillRepository(tmp_path / "skills.db")
    return (
        SkillAdminService(
            repository,
            tmp_path / "artifacts",
            SkillPackageValidator(),
        ),
        repository,
    )


def test_install_is_immutable_idempotent_and_governed(tmp_path: Path) -> None:
    admin, repository = _admin(tmp_path)
    try:
        source = _source(tmp_path / "v1", "1.0.0", "version one")
        installed = admin.install(source, actor="tester", reason="fixture")
        repeated = admin.install(source, actor="tester", reason="repeat")
        assert installed.version_id == repeated.version_id
        assert installed.state == "draft"
        artifact_file = Path(installed.artifact_path) / "SKILL.md"
        assert not artifact_file.stat().st_mode & stat.S_IWUSR

        conflict = _source(tmp_path / "conflict", "1.0.0", "different")
        with pytest.raises(ValueError):
            admin.install(conflict, actor="tester", reason="conflict")

        active = admin.activate(
            "report", "1.0.0", actor="tester", reason="release"
        )
        assert active.state == "active"
        assert repository.list_active()[0].version == "1.0.0"
    finally:
        repository.close()


def test_failed_copy_cleans_staging_and_does_not_register(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, repository = _admin(tmp_path)
    source = _source(tmp_path / "v1", "1.0.0", "one")

    def fail_copy(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("copy failed")

    monkeypatch.setattr("memoli_agent.agent.skills.admin.shutil.copytree", fail_copy)
    try:
        with pytest.raises(OSError):
            admin.install(source)
        assert repository.list_versions() == []
        artifact_root = tmp_path / "artifacts"
        assert not list(artifact_root.glob(".skill-staging-*"))
    finally:
        repository.close()


def test_snapshot_is_stable_and_rollback_uses_previous_active(tmp_path: Path) -> None:
    admin, repository = _admin(tmp_path)
    try:
        v1 = admin.install(_source(tmp_path / "v1", "1.0.0", "one"))
        admin.activate(v1.name, v1.version, actor="tester", reason="v1")
        repository.create_snapshot("session-1", "chat", repository.list_active())

        v2 = admin.install(_source(tmp_path / "v2", "2.0.0", "two"))
        admin.activate(v2.name, v2.version, actor="tester", reason="v2")
        repository.create_snapshot("session-1", "chat", repository.list_active())
        first_binding = repository.get_bound_version("session-1", "report")
        assert first_binding is not None and first_binding.version == "1.0.0"

        repository.create_snapshot("session-2", "chat", repository.list_active())
        second_binding = repository.get_bound_version("session-2", "report")
        assert second_binding is not None and second_binding.version == "2.0.0"
        rolled_back = admin.rollback("report", actor="tester", reason="regression")
        assert rolled_back.version == "1.0.0"
    finally:
        repository.close()


def test_future_schema_fails_closed_without_creating_tables(tmp_path: Path) -> None:
    database = tmp_path / "future.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE skill_meta(key TEXT PRIMARY KEY, value TEXT)")
    connection.execute("INSERT INTO skill_meta VALUES ('schema_version', '99')")
    connection.commit()
    connection.close()

    with pytest.raises(SkillRegistryError):
        SQLiteSkillRepository(database)

    connection = sqlite3.connect(database)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    connection.close()
    assert tables == {"skill_meta"}


def test_stale_management_revision_rolls_back_without_partial_state(
    tmp_path: Path,
) -> None:
    admin, repository = _admin(tmp_path)
    try:
        installed = admin.install(_source(tmp_path / "v1", "1.0.0", "one"))
        install_revision = repository.revision
        repository.activate(
            installed.name,
            installed.version,
            actor="first",
            reason="release",
            expected_revision=install_revision,
        )
        with pytest.raises(SkillRevisionConflict):
            repository.deprecate(
                installed.name,
                installed.version,
                actor="stale",
                reason="outdated request",
                expected_revision=install_revision,
            )
        active = repository.list_active()[0]
        current = repository.get_version("report", "1.0.0")
        assert active.version == "1.0.0"
        assert current is not None and current.state == "active"
    finally:
        repository.close()
