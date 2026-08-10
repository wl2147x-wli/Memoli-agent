"""主动循环决策器。

当前决策规则非常保守：只在 cooldown 到期后发送配置中的固定主动消息。
"""

from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from memoli_agent.agent.proactive.state import (
    ProactiveDecisionResult,
    ProactiveSignal,
    ProactiveState,
)


@dataclass(frozen=True, slots=True)
class ProactiveDecision:
    """最小主动决策器。"""

    cooldown_seconds: int
    message: str
    quiet_hours_start: int | None = None
    quiet_hours_end: int | None = None
    quiet_hours_timezone: str = "UTC"

    async def decide(
        self,
        signal: ProactiveSignal,
        state: ProactiveState,
    ) -> ProactiveDecisionResult:
        """判断本次 tick 是否需要主动发送消息。"""

        if self._in_quiet_hours(signal):
            return ProactiveDecisionResult(
                should_send=False,
                metadata={"reason": "quiet-hours"},
            )

        if state.last_triggered_at is not None:
            elapsed = (signal.now - state.last_triggered_at).total_seconds()
            if elapsed < self.cooldown_seconds:
                return ProactiveDecisionResult(
                    should_send=False,
                    metadata={
                        "reason": "cooldown",
                        "elapsed_seconds": elapsed,
                    },
                )

        return ProactiveDecisionResult(
            should_send=True,
            content=self.message,
            metadata={
                "reason": "cooldown_ready",
                "tick_count": signal.tick_count,
                **signal.metadata,
            },
        )

    def _in_quiet_hours(self, signal: ProactiveSignal) -> bool:
        """按配置时区判断当前小时是否处于免打扰时段。"""

        start = self.quiet_hours_start
        end = self.quiet_hours_end
        if start is None or end is None:
            return False
        try:
            local_hour = signal.now.astimezone(ZoneInfo(self.quiet_hours_timezone)).hour
        except ZoneInfoNotFoundError as exc:
            raise ValueError("proactive quiet-hours 时区无效。") from exc
        if start == end:
            return True
        if start < end:
            return start <= local_hour < end
        return local_hour >= start or local_hour < end
