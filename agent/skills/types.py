"""
Type definitions for skills system.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class SkillInstallSpec:
    """Specification for installing skill dependencies."""
    kind: str  # 安装方式：homebrew、pip、npm、下载等
    id: Optional[str] = None
    label: Optional[str] = None
    bins: List[str] = field(default_factory=list)
    os: List[str] = field(default_factory=list)
    formula: Optional[str] = None  # Homebrew 的 formula 名
    package: Optional[str] = None  # pip/npm 的包名
    module: Optional[str] = None
    url: Optional[str] = None  # 下载地址
    archive: Optional[str] = None
    extract: bool = False
    strip_components: Optional[int] = None
    target_dir: Optional[str] = None


@dataclass
class SkillMetadata:
    """Metadata for a skill from frontmatter."""
    always: bool = False  # 始终包含此技能
    default_enabled: bool = True  # 首次发现时的初始启用状态
    skill_key: Optional[str] = None  # 覆盖默认的技能键名
    primary_env: Optional[str] = None  # 主要环境变量
    emoji: Optional[str] = None
    homepage: Optional[str] = None
    os: List[str] = field(default_factory=list)  # 支持的操作系统平台
    requires: Dict[str, List[str]] = field(default_factory=dict)  # 依赖要求
    install: List[SkillInstallSpec] = field(default_factory=list)


@dataclass
class Skill:
    """Represents a skill loaded from a markdown file."""
    name: str
    description: str
    file_path: str
    base_dir: str
    source: str  # 来源：内置或自定义
    content: str  # 完整的 Markdown 正文
    disable_model_invocation: bool = False
    frontmatter: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillEntry:
    """A skill with parsed metadata."""
    skill: Skill
    metadata: Optional[SkillMetadata] = None
    user_invocable: bool = True  # 用户是否可以直接调用该技能


@dataclass
class LoadSkillsResult:
    """Result of loading skills from a directory."""
    skills: List[Skill]
    diagnostics: List[str] = field(default_factory=list)


@dataclass
class SkillSnapshot:
    """Snapshot of skills for a specific run."""
    prompt: str  # 格式化后的提示文本
    skills: List[Dict[str, str]]  # 技能信息列表（名称、primary_env 等）
    resolved_skills: List[Skill] = field(default_factory=list)
    version: Optional[int] = None
