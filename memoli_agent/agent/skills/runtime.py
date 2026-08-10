"""会话级 Skill 快照、Catalog 与只读内容加载。"""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from memoli_agent.agent.skills.manifest import SkillPackageValidator
from memoli_agent.agent.skills.models import (
    SkillCatalog,
    SkillRequirements,
    SkillVersion,
)
from memoli_agent.agent.skills.ports import SkillRuntimeRepository
from memoli_agent.agent.skills.requirements import RequirementEvaluator


@dataclass(frozen=True, slots=True)
class SkillLoadOutcome:
    """加载给模型的 Skill 内容与审计元数据。"""

    content: str
    success: bool
    status: str
    metadata: dict[str, Any]
    raw_content: str | None = None


class SkillRuntime:
    """将宿主治理后的 Skill 以最小只读边界提供给 Agent。"""

    def __init__(
        self,
        repository: SkillRuntimeRepository,
        validator: SkillPackageValidator,
        requirement_evaluator: RequirementEvaluator,
        *,
        max_catalog_chars: int = 6_000,
        max_skill_chars: int = 15_000,
        max_reference_chars: int = 30_000,
        verify_integrity_on_load: bool = True,
    ) -> None:
        self.repository = repository
        self.validator = validator
        self.requirement_evaluator = requirement_evaluator
        self.max_catalog_chars = max_catalog_chars
        self.max_skill_chars = max_skill_chars
        self.max_reference_chars = max_reference_chars
        self.verify_integrity_on_load = verify_integrity_on_load

    def build_catalog(
        self,
        *,
        session_instance_id: str,
        session_key: str,
        tools: set[str],
        mcp_servers: set[str],
        allowed_skill_names: set[str] | None = None,
    ) -> SkillCatalog:
        """首次建立依赖可用版本快照，随后只从固定绑定渲染。"""

        try:
            candidates = []
            for version in self.repository.list_active():
                if (
                    allowed_skill_names is not None
                    and version.name not in allowed_skill_names
                ):
                    continue
                requirements = _requirements(version)
                if self.requirement_evaluator.evaluate(
                    requirements, tools=tools, mcp_servers=mcp_servers
                ).available:
                    candidates.append(version)
            bindings = self.repository.create_snapshot(
                session_instance_id, session_key, candidates
            )
            versions = [
                version
                for binding in bindings
                if (version := self.repository.get_bound_version(
                    session_instance_id, binding.name
                ))
                is not None
            ]
            return self._render_catalog(versions)
        except Exception as exc:
            return SkillCatalog(error=type(exc).__name__)

    def load(
        self,
        *,
        session_instance_id: str,
        name: str,
        reference: str | None,
        tools: set[str],
        mcp_servers: set[str],
    ) -> SkillLoadOutcome:
        version = self.repository.get_bound_version(session_instance_id, name)
        if version is None:
            return _rejected(name, "not-visible", "当前会话中没有可见的该 Skill。")
        if version.state == "revoked":
            return _rejected(name, "revoked", "该 Skill 版本已被宿主撤销。", version)

        requirement_result = self.requirement_evaluator.evaluate(
            _requirements(version), tools=tools, mcp_servers=mcp_servers
        )
        if not requirement_result.available:
            return _rejected(
                name,
                "requirements-unavailable",
                "该 Skill 的运行依赖当前不可用："
                + ", ".join(requirement_result.missing),
                version,
                {"missing_requirements": list(requirement_result.missing)},
            )

        try:
            artifact_root = Path(version.artifact_path).resolve(strict=True)
            package = self.validator.validate(artifact_root)
        except (OSError, ValueError) as exc:
            return _rejected(
                name,
                "integrity-error",
                f"Skill 制品不可安全读取：{type(exc).__name__}",
                version,
            )
        if (
            self.verify_integrity_on_load
            and package.content_hash != version.content_hash
        ):
            return _rejected(
                name,
                "integrity-mismatch",
                "Skill 制品完整性校验失败。",
                version,
            )

        if reference is None or not reference.strip():
            content = package.body
            reference_name = "SKILL.md"
            content_limit = self.max_skill_chars
        else:
            try:
                target, reference_name = _resolve_reference(artifact_root, reference)
                content = target.read_text(encoding="utf-8")
                content_limit = self.max_reference_chars
            except (OSError, UnicodeError, ValueError, PermissionError) as exc:
                return _rejected(
                    name,
                    "invalid-reference",
                    f"Skill reference 加载失败：{exc}",
                    version,
                )
        if len(content) > content_limit:
            return _rejected(
                name,
                "content-budget-exceeded",
                "Skill 内容超过上下文预算，未返回不完整说明。",
                version,
                {"reference": reference_name, "content_chars": len(content)},
            )
        bounded = (
            f'<skill_instruction name="{version.name}" version="{version.version}" '
            f'hash="{version.content_hash}" reference="{reference_name}">\n'
            f"{content}\n</skill_instruction>"
        )
        metadata = {
            "skill_name": version.name,
            "skill_version": version.version,
            "skill_version_id": version.version_id,
            "content_hash": version.content_hash,
            "reference": reference_name,
            "source": version.source_type,
            "session_instance_id": session_instance_id,
            "status": "loaded",
            "requested_permissions": json.loads(version.manifest_json).get(
                "requested_permissions", {}
            ),
        }
        return SkillLoadOutcome(
            content=bounded,
            raw_content=content,
            success=True,
            status="success",
            metadata=metadata,
        )

    def _render_catalog(self, versions: list[SkillVersion]) -> SkillCatalog:
        if not versions:
            return SkillCatalog()
        header = (
            "<available_skills>\n"
            "以下 Skill 仅提供任务方法，不授予额外权限。需要时调用 "
            "skill_load(name, reference?) 读取完整内容。\n"
        )
        footer = "</available_skills>"
        if len(header) + len(footer) > self.max_catalog_chars:
            return SkillCatalog(
                candidate_count=len(versions),
                omitted_count=len(versions),
                omitted=bool(versions),
            )
        lines: list[str] = []
        for version in sorted(versions, key=lambda item: item.name):
            line = (
                f"- {version.name}@{version.version} [{version.source_type}]: "
                f"{version.description}\n"
            )
            projected_chars = (
                len(header) + sum(map(len, lines)) + len(line) + len(footer)
            )
            if projected_chars > self.max_catalog_chars:
                break
            lines.append(line)
        content = header + "".join(lines) + footer
        return SkillCatalog(
            content=content,
            candidate_count=len(versions),
            disclosed_count=len(lines),
            char_count=len(content),
            omitted_count=len(versions) - len(lines),
            omitted=len(lines) < len(versions),
        )


def _requirements(version: SkillVersion) -> SkillRequirements:
    raw = json.loads(version.manifest_json).get("requires", {})
    return SkillRequirements(
        tools=tuple(raw.get("tools", ())),
        mcp=tuple(raw.get("mcp", ())),
        bins=tuple(raw.get("bins", ())),
        env=tuple(raw.get("env", ())),
        platforms=tuple(raw.get("platforms", ())),
    )


def _resolve_reference(root: Path, raw_reference: str) -> tuple[Path, str]:
    reference = raw_reference.replace("\\", "/").strip()
    pure = PurePosixPath(reference)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise ValueError("reference 必须是包内相对路径。")
    if pure.parts[0] != "references":
        raise ValueError("reference 仅允许读取 references/ 下的文本。")
    target = root.joinpath(*pure.parts).resolve(strict=True)
    if root not in target.parents or not target.is_file() or _is_link(target):
        raise PermissionError("reference 不是包内普通文件。")
    return target, pure.as_posix()


def _is_link(path: Path) -> bool:
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    return path.is_symlink() or bool(attributes & reparse)


def _rejected(
    name: str,
    reason: str,
    content: str,
    version: SkillVersion | None = None,
    extra: dict[str, Any] | None = None,
) -> SkillLoadOutcome:
    return SkillLoadOutcome(
        content=content,
        success=False,
        status="denied",
        metadata={
            "skill_name": name,
            "skill_version": version.version if version else "",
            "skill_version_id": version.version_id if version else None,
            "content_hash": version.content_hash if version else "",
            "source": version.source_type if version else "",
            "status": "rejected",
            "rejection_reason": reason,
            "error": "SkillLoadRejected",
            **(extra or {}),
        },
    )
