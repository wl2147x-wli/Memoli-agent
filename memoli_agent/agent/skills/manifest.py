"""安全解析并静态校验 ``SKILL.md`` 包。"""

from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Any

import yaml

from memoli_agent.agent.skills.models import (
    SkillManifest,
    SkillPackage,
    SkillRequirements,
)

_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_ALLOWED_FIELDS = {
    "name",
    "version",
    "description",
    "requires",
    "requested_permissions",
    "risk",
}
_GOVERNANCE_FIELDS = {
    "active",
    "approved",
    "validated",
    "status",
    "state",
    "deprecated",
    "revoked",
}
_REQUIREMENT_FIELDS = {"tools", "mcp", "bins", "env", "platforms"}
_RISK_LEVELS = {"low", "medium", "high"}
_ALLOWED_PACKAGE_DIRECTORIES = {"references", "templates", "scripts", "tests"}


class SkillValidationError(ValueError):
    """Skill 包不满足静态契约。"""


class SkillPackageValidator:
    """使用 ``yaml.safe_load`` 校验本地 Skill 目录。"""

    def __init__(
        self,
        *,
        max_skill_file_bytes: int = 262_144,
        max_package_bytes: int = 2_097_152,
    ) -> None:
        self.max_skill_file_bytes = max_skill_file_bytes
        self.max_package_bytes = max_package_bytes

    def validate(self, source: str | Path) -> SkillPackage:
        requested_root = Path(source)
        if _is_link(requested_root):
            raise SkillValidationError("Skill 来源不能是链接或重解析点。")
        root = requested_root.resolve(strict=True)
        if not root.is_dir() or _is_link(root):
            raise SkillValidationError(
                "Skill 来源必须是普通目录，不能是链接或重解析点。"
            )
        skill_file = root / "SKILL.md"
        if not skill_file.is_file() or _is_link(skill_file):
            raise SkillValidationError("Skill 包根目录必须包含普通文件 SKILL.md。")

        files = self._collect_files(root)
        for path in files:
            relative = path.relative_to(root)
            if len(relative.parts) == 1 and relative.name != "SKILL.md":
                raise SkillValidationError(
                    "Skill 根目录只允许 SKILL.md 和标准附属目录。"
                )
            if len(relative.parts) > 1 and relative.parts[0] not in (
                _ALLOWED_PACKAGE_DIRECTORIES
            ):
                raise SkillValidationError(
                    f"Skill 包含不允许的附属目录：{relative.parts[0]}"
                )
        total_bytes = sum(path.stat().st_size for path in files)
        if total_bytes > self.max_package_bytes:
            raise SkillValidationError("Skill 包超过大小上限。")
        if skill_file.stat().st_size > self.max_skill_file_bytes:
            raise SkillValidationError("SKILL.md 超过单文件大小上限。")

        try:
            raw_skill = skill_file.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise SkillValidationError("SKILL.md 必须使用 UTF-8 编码。") from exc
        frontmatter, body = _split_frontmatter(raw_skill)
        manifest = _parse_manifest(frontmatter)
        relative_files = tuple(
            sorted(path.relative_to(root).as_posix() for path in files)
        )
        digest = _hash_files(root, relative_files)
        return SkillPackage(
            manifest=manifest,
            source_root=root,
            body=body,
            files=relative_files,
            content_hash=digest,
            total_bytes=total_bytes,
        )

    def _collect_files(self, root: Path) -> list[Path]:
        files: list[Path] = []
        for current_root, directory_names, file_names in os.walk(
            root, topdown=True, followlinks=False
        ):
            current = Path(current_root)
            if _is_link(current):
                raise SkillValidationError("Skill 包不能包含链接或重解析目录。")
            for name in list(directory_names):
                directory = current / name
                if _is_link(directory):
                    raise SkillValidationError("Skill 包不能包含链接或重解析目录。")
            for name in file_names:
                path = current / name
                if _is_link(path) or not path.is_file():
                    raise SkillValidationError("Skill 包只能包含普通文件。")
                if path.stat().st_nlink > 1:
                    raise SkillValidationError("Skill 包不能包含硬链接文件。")
                resolved = path.resolve(strict=True)
                if root != resolved and root not in resolved.parents:
                    raise SkillValidationError("Skill 文件不能逃逸包根目录。")
                if path.stat().st_size > self.max_skill_file_bytes:
                    raise SkillValidationError(f"Skill 文件超过上限：{path.name}")
                files.append(path)
        return files


def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillValidationError("SKILL.md 必须以 YAML frontmatter 开始。")
    try:
        end = next(
            index for index in range(1, len(lines)) if lines[index].strip() == "---"
        )
    except StopIteration as exc:
        raise SkillValidationError("SKILL.md 缺少 frontmatter 结束标记。") from exc
    yaml_text = "\n".join(lines[1:end])
    try:
        _reject_duplicate_keys(yaml_text)
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise SkillValidationError("SKILL.md frontmatter 不是合法 YAML。") from exc
    if not isinstance(parsed, dict):
        raise SkillValidationError("SKILL.md frontmatter 必须是映射。")
    body = "\n".join(lines[end + 1 :]).strip()
    if not body:
        raise SkillValidationError("Skill 正文不能为空。")
    return parsed, body


def _parse_manifest(data: dict[str, Any]) -> SkillManifest:
    keys = {str(key) for key in data}
    governance = sorted(keys & _GOVERNANCE_FIELDS)
    if governance:
        raise SkillValidationError(
            "Skill 清单不能声明宿主治理状态：" + ", ".join(governance)
        )
    unknown = sorted(keys - _ALLOWED_FIELDS)
    if unknown:
        raise SkillValidationError("Skill 清单包含未知字段：" + ", ".join(unknown))

    name = _required_string(data, "name")
    version = _required_string(data, "version")
    description = _required_string(data, "description")
    if not _NAME_PATTERN.fullmatch(name):
        raise SkillValidationError("Skill name 必须是小写 kebab-case。")
    if not _SEMVER_PATTERN.fullmatch(version):
        raise SkillValidationError("Skill version 必须是合法 SemVer。")
    if len(description) > 500:
        raise SkillValidationError("Skill description 不能超过 500 个字符。")

    raw_requires = data.get("requires", {})
    if raw_requires is None:
        raw_requires = {}
    if not isinstance(raw_requires, dict):
        raise SkillValidationError("requires 必须是映射。")
    unknown_requirements = sorted(set(raw_requires) - _REQUIREMENT_FIELDS)
    if unknown_requirements:
        raise SkillValidationError(
            "requires 包含未知字段：" + ", ".join(unknown_requirements)
        )
    requirements = SkillRequirements(
        **{
            field: _string_tuple(raw_requires.get(field, ()), f"requires.{field}")
            for field in _REQUIREMENT_FIELDS
        }
    )

    permissions = data.get("requested_permissions", {})
    if permissions is None:
        permissions = {}
    if not isinstance(permissions, dict):
        raise SkillValidationError("requested_permissions 必须是映射。")
    _validate_json_value(permissions, "requested_permissions")
    risk = str(data.get("risk", "low")).strip().lower()
    if risk not in _RISK_LEVELS:
        raise SkillValidationError("risk 仅支持 low、medium 或 high。")
    return SkillManifest(
        name=name,
        version=version,
        description=description,
        requirements=requirements,
        requested_permissions=dict(permissions),
        risk=risk,
    )


def _required_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SkillValidationError(f"Skill 清单缺少非空字符串字段 {key}。")
    return value.strip()


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise SkillValidationError(f"{field} 必须是非空字符串数组。")
    return tuple(dict.fromkeys(item.strip() for item in value))


def _is_link(path: Path) -> bool:
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    return path.is_symlink() or bool(attributes & reparse)


def _hash_files(root: Path, relative_files: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for relative in relative_files:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update((root / relative).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _reject_duplicate_keys(yaml_text: str) -> None:
    """在 safe_load 前检查所有 YAML mapping 的重复 key。"""

    node = yaml.compose(yaml_text, Loader=yaml.SafeLoader)
    if node is None:
        return

    def visit(current: yaml.Node) -> None:
        if isinstance(current, yaml.MappingNode):
            keys: set[str] = set()
            for key_node, value_node in current.value:
                key = str(getattr(key_node, "value", ""))
                if key in keys:
                    raise SkillValidationError(f"YAML 字段重复：{key}")
                keys.add(key)
                visit(value_node)
        elif isinstance(current, yaml.SequenceNode):
            for child in current.value:
                visit(child)

    visit(node)


def _validate_json_value(value: Any, field: str) -> None:
    if value is None or isinstance(value, str | int | float | bool):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, field)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _validate_json_value(item, field)
        return
    raise SkillValidationError(f"{field} 只能包含 JSON 兼容值。")
