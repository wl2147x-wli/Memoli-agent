from pathlib import Path

import pytest

from memoli_agent.skills_cli import main


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f"""
[skills]
enabled = true
database = "{(tmp_path / 'skills.db').as_posix()}"
artifact_root = "{(tmp_path / 'artifacts').as_posix()}"
""",
        encoding="utf-8",
    )
    return path


def _skill(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text(
        """---
name: cli-skill
version: 1.0.0
description: Use when testing the host CLI.
---
Follow the CLI test procedure.
""",
        encoding="utf-8",
    )
    return source


def test_host_cli_validates_installs_activates_and_lists(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _config(tmp_path)
    source = _skill(tmp_path)
    assert main(["--config", str(config), "validate", str(source)]) == 0
    assert main(["--config", str(config), "install", str(source)]) == 0
    assert (
        main(
            [
                "--config",
                str(config),
                "activate",
                "cli-skill",
                "1.0.0",
                "--actor",
                "pytest",
                "--reason",
                "reviewed",
            ]
        )
        == 0
    )
    assert main(["--config", str(config), "list", "--name", "cli-skill"]) == 0
    output = capsys.readouterr().out
    assert '"state": "active"' in output
    assert '"name": "cli-skill"' in output

    assert '"source_type": "local"' in output
