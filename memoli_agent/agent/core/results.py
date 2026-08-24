"""Agent Loop 的纯结果合同。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from memoli_agent.agent.provider import LLMResponse


class LoopOutcome(StrEnum):
    """单步循环的控制结果。"""

    CONTINUE = "continue"
    COMPLETED = "completed"
    NEEDS_USER = "needs-user"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget-exhausted"


class TerminationReason(StrEnum):
    """一次 turn 的最终状态。"""

    COMPLETED = "completed"
    NEEDS_USER = "needs-user"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget-exhausted"


@dataclass(frozen=True, slots=True)
class StepSummary:
    """供调用方和测试读取的精简步骤摘要。"""

    iteration: int
    provider: str
    outcome: LoopOutcome
    tool_names: tuple[str, ...] = ()
    duration_seconds: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TurnResult:
    """Agent Loop 的结构化结果。"""

    trace_id: str
    response: LLMResponse
    termination_reason: TerminationReason
    iterations: int
    steps: tuple[StepSummary, ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)
    fallback_used: bool = False
    error_type: str | None = None
    # 跨轮 committed turn 状态：0 表示未记录（轨迹关闭/不支持 committed turn）。
    # phases 层据此续写 turn_output_committed（§2.3）。
    committed_epoch: int = 0
    committed_turn_seq: int = 0
    committed_output_seq: int = 0

    def __post_init__(self) -> None:
        if self.iterations < 0:
            raise ValueError("iterations 不能为负数。")
        if (
            self.termination_reason is TerminationReason.COMPLETED
            and not self.response.content.strip()
        ):
            raise ValueError("completed 结果必须包含最终回复。")
        if self.termination_reason is TerminationReason.FAILED and not self.error_type:
            raise ValueError("failed 结果必须包含 error_type。")
