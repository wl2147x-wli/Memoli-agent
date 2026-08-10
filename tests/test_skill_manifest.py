import os
from pathlib import Path

import pytest

from memoli_agent.agent.skills.manifest import (
    SkillPackageValidator,
    SkillValidationError,
)


def _write_skill(
    root: Path, frontmatter: str, body: str = "# Procedure\nDo work."
) -> Path:
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        f"---\n{frontmatter}\n---\n{body}\n", encoding="utf-8"
    )
    return root


def test_valid_manifest_is_normalized_without_installing(tmp_path: Path) -> None:
    source = _write_skill(
        tmp_path / "skill",
        """
name: sample-skill
version: 1.2.3
description: Use when a sample procedure is needed.
requires:
  tools: [file_read]
  mcp: [docs]
  bins: [git]
  env: [SAMPLE_TOKEN]
  platforms: [windows]
requested_permissions:
  network: false
risk: medium
""".strip(),
    )
    reference = source / "references"
    reference.mkdir()
    (reference / "guide.md").write_text("guide", encoding="utf-8")

    package = SkillPackageValidator().validate(source)

    assert package.manifest.name == "sample-skill"
    assert package.manifest.version == "1.2.3"
    assert package.manifest.requirements.tools == ("file_read",)
    assert package.files == ("SKILL.md", "references/guide.md")
    assert len(package.content_hash) == 64


@pytest.mark.parametrize(
    "frontmatter",
    [
        "name: Bad_Name\nversion: 1.0.0\ndescription: bad",
        "name: good\nversion: latest\ndescription: bad",
        "name: good\nversion: 1.0.0\ndescription: ok\nunknown: true",
        "name: good\nversion: 1.0.0\ndescription: ok\nactive: true",
        "name: good\nversion: 1.0.0\ndescription: ok\nrequires:\n  tools: file_read",
        "name: good\nname: forged\nversion: 1.0.0\ndescription: duplicate",
        (
            "name: !!python/object/apply:os.system ['echo unsafe']\n"
            "version: 1.0.0\ndescription: bad"
        ),
    ],
)
def test_invalid_or_untrusted_manifest_is_rejected(
    tmp_path: Path, frontmatter: str
) -> None:
    source = _write_skill(tmp_path / "skill", frontmatter)
    with pytest.raises(SkillValidationError):
        SkillPackageValidator().validate(source)


def test_package_limits_and_directory_allowlist_are_enforced(tmp_path: Path) -> None:
    source = _write_skill(
        tmp_path / "skill",
        "name: sample\nversion: 1.0.0\ndescription: sample",
        "x" * 100,
    )
    with pytest.raises(SkillValidationError):
        SkillPackageValidator(max_skill_file_bytes=50).validate(source)

    (source / "unexpected.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SkillValidationError):
        SkillPackageValidator().validate(source)


def test_hard_link_into_package_is_rejected(tmp_path: Path) -> None:
    source = _write_skill(
        tmp_path / "skill",
        "name: sample\nversion: 1.0.0\ndescription: sample",
    )
    references = source / "references"
    references.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    try:
        os.link(outside, references / "linked.txt")
    except OSError:
        pytest.skip("当前文件系统不支持测试硬链接。")
    with pytest.raises(SkillValidationError):
        SkillPackageValidator().validate(source)


def test_symbolic_link_source_is_rejected(tmp_path: Path) -> None:
    source = _write_skill(
        tmp_path / "skill",
        "name: sample\nversion: 1.0.0\ndescription: sample",
    )
    linked = tmp_path / "linked-skill"
    try:
        linked.symlink_to(source, target_is_directory=True)
    except OSError:
        pytest.skip("当前系统未允许创建符号链接。")
    with pytest.raises(SkillValidationError):
        SkillPackageValidator().validate(linked)
