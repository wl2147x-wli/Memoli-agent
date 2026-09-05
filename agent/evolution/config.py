"""Configuration for the self-evolution subsystem.

Reads flat ``self_evolution_*`` keys from config.json. All fields have safe
defaults so the feature degrades gracefully when keys are absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# 兜底默认值——取值保守（参见执行器模块的文档字符串）。
# 它们仅在 config.json 完全无法读取时才会用到；真正的默认值位于 config.py。
DEFAULT_ENABLED = True
DEFAULT_IDLE_MINUTES = 10
DEFAULT_MIN_TURNS = 6
# 沙箱内演化代理的最大审查步数。刻意保持较小（不对外暴露为
# 配置项）：审查应当廉价且聚焦，而不是长时间的自主运行。
DEFAULT_MAX_STEPS = 12


@dataclass
class EvolutionConfig:
    """Resolved self-evolution settings."""

    enabled: bool = DEFAULT_ENABLED
    idle_minutes: int = DEFAULT_IDLE_MINUTES
    min_turns: int = DEFAULT_MIN_TURNS
    max_steps: int = DEFAULT_MAX_STEPS

    @property
    def idle_seconds(self) -> int:
        return max(60, self.idle_minutes * 60)


def _as_bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "on"):
            return True
        if v in ("false", "0", "no", "off"):
            return False
    return fallback


def _as_pos_int(value: Any, fallback: int) -> int:
    try:
        n = int(value)
        return n if n > 0 else fallback
    except (TypeError, ValueError):
        return fallback


def get_evolution_config() -> EvolutionConfig:
    """Build EvolutionConfig from the live config.json ``self_evolution_*`` keys."""
    try:
        from config import conf
        c = conf()
    except Exception:
        c = {}

    def _get(key, default):
        try:
            return c.get(key, default)
        except Exception:
            return default

    return EvolutionConfig(
        enabled=_as_bool(_get("self_evolution_enabled", None), DEFAULT_ENABLED),
        idle_minutes=_as_pos_int(_get("self_evolution_idle_minutes", None), DEFAULT_IDLE_MINUTES),
        min_turns=_as_pos_int(_get("self_evolution_min_turns", None), DEFAULT_MIN_TURNS),
        max_steps=DEFAULT_MAX_STEPS,
    )
