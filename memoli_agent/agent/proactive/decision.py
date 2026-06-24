"""主动循环决策器。

当前决策规则非常保守：只在 cooldown 到期后发送配置中的固定主动消息。
"""

from __future__ import annotations

from dataclasses import dataclass

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

    async def decide(
        self,
        signal: ProactiveSignal,
        state: ProactiveState,
    ) -> ProactiveDecisionResult:
        """判断本次 tick 是否需要主动发送消息。"""

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
