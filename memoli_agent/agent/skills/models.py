"""Skill Runtime 的领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class SkillRequirements:
    """Skill 在当前执行环境中可见和可加载所需的依赖。"""

    tools: tuple[str, ...] = ()
    mcp: tuple[str, ...] = ()
    bins: tuple[str, ...] = ()
    env: tuple[str, ...] = ()
    platforms: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "tools": list(self.tools),
            "mcp": list(self.mcp),
            "bins": list(self.bins),
            "env": list(self.env),
            "platforms": list(self.platforms),
        }


@dataclass(frozen=True, slots=True)
class SkillManifest:
    """从 ``SKILL.md`` frontmatter 读取的声明式元数据。"""

    name: str
    version: str
    description: str
    requirements: SkillRequirements = field(default_factory=SkillRequirements)
    requested_permissions: dict[str, Any] = field(default_factory=dict)
    risk: str = "low"


@dataclass(frozen=True, slots=True)
class SkillPackage:
    """通过静态校验、尚未安装的 Skill 包。"""

    manifest: SkillManifest
    source_root: Path
    body: str
    files: tuple[str, ...]
    content_hash: str
    total_bytes: int


@dataclass(frozen=True, slots=True)
class SkillVersion:
    """SQLite 注册表中的不可变 Skill 版本。"""

    version_id: int
    skill_id: int
    name: str
    owner: str
    source_type: str
    version: str
    description: str
    state: str
    artifact_path: str
    content_hash: str
    manifest_json: str
    created_at: str


@dataclass(frozen=True, slots=True)
class SkillBinding:
    """一个运行时会话固定到的 Skill 版本。"""

    session_instance_id: str
    session_key: str
    version_id: int
    name: str
    version: str
    bound_at: str


@dataclass(frozen=True, slots=True)
class RequirementResult:
    """依赖检查结果；缺失项只保存名称，不暴露环境变量值。"""

    available: bool
    missing: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SkillCatalog:
    """可注入系统上下文的稳定 Skill Catalog。"""

    content: str = ""
    candidate_count: int = 0
    disclosed_count: int = 0
    char_count: int = 0
    omitted_count: int = 0
    omitted: bool = False
    error: str = ""
