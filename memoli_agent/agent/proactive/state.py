"""主动循环状态类型。

这里的类型只描述一次本地 tick 所需的最小状态，不引入复杂任务计划器。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ProactiveState:
    """主动循环的内存状态。"""

    tick_count: int = 0
    last_triggered_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProactiveSignal:
    """一次感知阶段得到的信号。"""

    now: datetime
    tick_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProactiveDecisionResult:
    """一次主动决策结果。"""

    should_send: bool
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
