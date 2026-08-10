"""Skill Registry 的最小分权端口。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from memoli_agent.agent.skills.models import SkillBinding, SkillPackage, SkillVersion


class SkillRegistryReader(Protocol):
    """在线 Runtime 可读取的版本解析边界。"""

    def list_active(self) -> list[SkillVersion]: ...

    def get_bound_version(
        self, session_instance_id: str, name: str
    ) -> SkillVersion | None: ...


class SkillSessionBinder(Protocol):
    """在线 Runtime 唯一允许的持久化写边界。"""

    def create_snapshot(
        self,
        session_instance_id: str,
        session_key: str,
        versions: list[SkillVersion],
    ) -> list[SkillBinding]: ...


class SkillRuntimeRepository(SkillRegistryReader, SkillSessionBinder, Protocol):
    """Catalog/Loader 使用的组合端口，不包含发布管理方法。"""


class SkillAdminRepository(Protocol):
    """宿主管理面使用的发布端口。"""

    def register_package(
        self,
        package: SkillPackage,
        artifact_path: Path,
        *,
        source_type: str = "local",
        owner: str = "host",
        actor: str = "host",
        reason: str = "install",
    ) -> SkillVersion: ...

    def list_versions(self, name: str | None = None) -> list[SkillVersion]: ...

    def get_version(
        self, name: str, version: str | None = None
    ) -> SkillVersion | None: ...

    def activate(
        self,
        name: str,
        version: str,
        *,
        actor: str = "host",
        reason: str = "activate",
        event_type: str = "activated",
    ) -> SkillVersion: ...

    def deprecate(
        self, name: str, version: str, *, actor: str = "host", reason: str
    ) -> SkillVersion: ...

    def revoke(
        self, name: str, version: str, *, actor: str = "host", reason: str
    ) -> SkillVersion: ...

    def rollback(
        self, name: str, *, actor: str = "host", reason: str
    ) -> SkillVersion: ...

    def governance(self, name: str, version: str) -> dict[str, Any]: ...
