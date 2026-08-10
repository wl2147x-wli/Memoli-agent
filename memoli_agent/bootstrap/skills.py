"""Skill Runtime 的集中装配。"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from memoli_agent.agent.skills.admin import SkillAdminService
from memoli_agent.agent.skills.manifest import SkillPackageValidator
from memoli_agent.agent.skills.repository import (
    SkillRegistryError,
    SQLiteSkillRepository,
)
from memoli_agent.agent.skills.requirements import RequirementEvaluator
from memoli_agent.agent.skills.runtime import SkillRuntime
from memoli_agent.bootstrap.config import AppConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SkillComponents:
    repository: SQLiteSkillRepository
    admin: SkillAdminService
    runtime: SkillRuntime

    def close(self) -> None:
        self.repository.close()


def build_skill_components(
    config: AppConfig, *, force: bool = False
) -> SkillComponents | None:
    """仅在启用时创建数据库；CLI 可用 ``force`` 进入宿主管理面。"""

    if not config.skills.enabled and not force:
        return None
    repository: SQLiteSkillRepository | None = None
    try:
        validator = SkillPackageValidator(
            max_skill_file_bytes=config.skills.max_skill_file_bytes,
            max_package_bytes=config.skills.max_package_bytes,
        )
        repository = SQLiteSkillRepository(config.skills.database)
        admin = SkillAdminService(repository, config.skills.artifact_root, validator)
        runtime = SkillRuntime(
            repository,
            validator,
            RequirementEvaluator(),
            max_catalog_chars=config.skills.catalog_max_chars,
            max_skill_chars=config.skills.skill_max_chars,
            max_reference_chars=config.skills.reference_max_chars,
            verify_integrity_on_load=config.skills.verify_integrity_on_load,
        )
        _install_builtin_example(admin)
        return SkillComponents(repository=repository, admin=admin, runtime=runtime)
    except (OSError, sqlite3.Error, ValueError, SkillRegistryError) as exc:
        if repository is not None:
            repository.close()
        if force:
            raise
        logger.error("Skill Runtime 初始化失败，已降级为普通 Agent Loop：%s", exc)
        return None


def _install_builtin_example(admin: SkillAdminService) -> None:
    """首次启用时安装并显式激活只读示例；不覆盖后续宿主治理。"""

    source = Path(__file__).parents[1] / "skills" / "research-report"
    existing = admin.show("research-report", "1.0.0")
    if existing is not None:
        return
    installed = admin.install(
        source,
        actor="runtime-bootstrap",
        reason="install builtin example",
        source_type="builtin",
    )
    admin.activate(
        installed.name,
        installed.version,
        actor="runtime-bootstrap",
        reason="activate builtin example",
    )
