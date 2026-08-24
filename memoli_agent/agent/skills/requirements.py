"""Skill 声明依赖的确定性检查。"""

from __future__ import annotations

import os
import platform
import shutil
from collections.abc import Mapping

from memoli_agent.agent.skills.models import RequirementResult, SkillRequirements


class RequirementEvaluator:
    """只报告缺失依赖名称，不读取或返回环境变量值。"""

    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self.environment = environment if environment is not None else os.environ

    def evaluate(
        self,
        requirements: SkillRequirements,
        *,
        tools: set[str],
        mcp_servers: set[str],
    ) -> RequirementResult:
        missing: list[str] = []
        missing.extend(
            f"tool:{name}" for name in requirements.tools if name not in tools
        )
        missing.extend(
            f"mcp:{name}" for name in requirements.mcp if name not in mcp_servers
        )
        missing.extend(
            f"bin:{name}" for name in requirements.bins if shutil.which(name) is None
        )
        missing.extend(
            f"env:{name}" for name in requirements.env if not self.environment.get(name)
        )
        current_platform = _platform_name()
        if requirements.platforms and current_platform not in {
            item.lower() for item in requirements.platforms
        }:
            missing.append("platform:" + current_platform)
        return RequirementResult(available=not missing, missing=tuple(missing))


def _platform_name() -> str:
    name = platform.system().lower()
    return {"darwin": "macos", "windows": "windows", "linux": "linux"}.get(name, name)
