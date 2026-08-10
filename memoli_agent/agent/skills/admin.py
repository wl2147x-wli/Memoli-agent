"""宿主侧 Skill 校验、安装和版本治理服务。"""

from __future__ import annotations

import json
import shutil
import stat
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from memoli_agent.agent.skills.manifest import (
    SkillPackageValidator,
    SkillValidationError,
)
from memoli_agent.agent.skills.models import (
    SkillPackage,
    SkillRequirements,
    SkillVersion,
)
from memoli_agent.agent.skills.ports import SkillAdminRepository
from memoli_agent.agent.skills.requirements import RequirementEvaluator


class SkillAdminService:
    """仅供宿主/CLI 调用；不会注册成模型工具。"""

    def __init__(
        self,
        repository: SkillAdminRepository,
        artifact_root: str | Path,
        validator: SkillPackageValidator,
    ) -> None:
        self.repository = repository
        self.artifact_root = Path(artifact_root).resolve()
        self.validator = validator

    def validate(self, source: str | Path) -> SkillPackage:
        return self.validator.validate(source)

    def install(
        self,
        source: str | Path,
        *,
        actor: str = "host",
        reason: str = "install",
        source_type: str = "local",
    ) -> SkillVersion:
        """先完整校验，再暂存、原子发布并写入注册表。"""

        package = self.validate(source)
        destination = (
            self.artifact_root / package.manifest.name / package.manifest.version
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            installed = self.validator.validate(destination)
            if installed.content_hash != package.content_hash:
                raise SkillValidationError("目标版本已存在但内容哈希不同。")
            return self.repository.register_package(
                package,
                destination,
                actor=actor,
                reason=reason,
                source_type=source_type,
            )

        self.artifact_root.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(prefix=".skill-staging-", dir=self.artifact_root)
        )
        published = False
        try:
            staged_package = staging / "package"
            shutil.copytree(package.source_root, staged_package)
            verified = self.validator.validate(staged_package)
            if verified.content_hash != package.content_hash:
                raise SkillValidationError("Skill 暂存复制后的哈希不一致。")
            staged_package.replace(destination)
            published = True
            _make_read_only(destination)
            return self.repository.register_package(
                package,
                destination,
                actor=actor,
                reason=reason,
                source_type=source_type,
            )
        except Exception:
            if published and destination.exists():
                _make_writable(destination)
                shutil.rmtree(destination)
            raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def list(self, name: str | None = None) -> list[SkillVersion]:
        return self.repository.list_versions(name)

    def show(self, name: str, version: str | None = None) -> SkillVersion | None:
        return self.repository.get_version(name, version)

    def inspect(
        self,
        version: SkillVersion,
        *,
        tools: set[str] | None = None,
        mcp_servers: set[str] | None = None,
    ) -> dict[str, Any]:
        """展开依赖、权限声明与宿主批准事实，供 CLI 稳定展示。"""

        manifest = json.loads(version.manifest_json)
        raw_requirements = manifest.get("requires", {})
        requirements = SkillRequirements(
            tools=tuple(raw_requirements.get("tools", ())),
            mcp=tuple(raw_requirements.get("mcp", ())),
            bins=tuple(raw_requirements.get("bins", ())),
            env=tuple(raw_requirements.get("env", ())),
            platforms=tuple(raw_requirements.get("platforms", ())),
        )
        availability = RequirementEvaluator().evaluate(
            requirements,
            tools=tools or set(),
            mcp_servers=mcp_servers or set(),
        )
        return {
            **asdict(version),
            "requirements": manifest.get("requires", {}),
            "available": availability.available,
            "missing_requirements": list(availability.missing),
            "requested_permissions": manifest.get("requested_permissions", {}),
            "risk": manifest.get("risk", "low"),
            "governance": self.repository.governance(
                version.name, version.version
            ),
        }

    def activate(
        self, name: str, version: str, *, actor: str, reason: str
    ) -> SkillVersion:
        return self.repository.activate(name, version, actor=actor, reason=reason)

    def deprecate(
        self, name: str, version: str, *, actor: str, reason: str
    ) -> SkillVersion:
        return self.repository.deprecate(name, version, actor=actor, reason=reason)

    def revoke(
        self, name: str, version: str, *, actor: str, reason: str
    ) -> SkillVersion:
        return self.repository.revoke(name, version, actor=actor, reason=reason)

    def rollback(self, name: str, *, actor: str, reason: str) -> SkillVersion:
        return self.repository.rollback(name, actor=actor, reason=reason)


def _make_read_only(root: Path) -> None:
    """设置平台可表达的只读权限；加载时仍以哈希作为最终权威。"""

    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file():
            path.chmod(stat.S_IREAD)
        elif path.is_dir():
            path.chmod(stat.S_IREAD | stat.S_IEXEC)
    root.chmod(stat.S_IREAD | stat.S_IEXEC)


def _make_writable(root: Path) -> None:
    """只用于安装事务回滚，使暂存制品可以被安全清理。"""

    root.chmod(stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
    for path in root.rglob("*"):
        if path.is_dir():
            path.chmod(stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
        else:
            path.chmod(stat.S_IREAD | stat.S_IWRITE)
