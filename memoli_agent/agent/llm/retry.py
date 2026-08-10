"""Provider 共享的有界异步重试策略。"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from memoli_agent.agent.llm.contracts import ProviderAttempt
from memoli_agent.agent.llm.errors import ProviderError

T = TypeVar("T")
RetryObserver = Callable[[ProviderError, int, float], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """只重试被 Adapter 明确标记为 transient 的错误。"""

    max_retries: int = 1
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    jitter_ratio: float = 0.1

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries 不能小于 0。")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("重试等待时间不能小于 0。")

    async def call(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        observer: RetryObserver | None = None,
    ) -> tuple[T, tuple[ProviderAttempt, ...]]:
        history: list[ProviderAttempt] = []
        for attempt in range(1, self.max_retries + 2):
            started = time.monotonic()
            try:
                result = await operation()
                history.append(
                    ProviderAttempt(
                        attempt=attempt,
                        outcome="completed",
                        duration_seconds=max(0.0, time.monotonic() - started),
                    )
                )
                return result, tuple(history)
            except asyncio.CancelledError:
                raise
            except ProviderError as exc:
                exc.attempt = attempt
                will_retry = exc.retryable and attempt <= self.max_retries
                delay = self._delay(exc, attempt) if will_retry else None
                history.append(
                    ProviderAttempt(
                        attempt=attempt,
                        outcome="failed",
                        duration_seconds=max(0.0, time.monotonic() - started),
                        error_type=exc.error_type,
                        status_code=exc.status_code,
                        retryable=will_retry,
                        retry_wait_seconds=delay,
                    )
                )
                exc.attempts = tuple(history)
                if not will_retry:
                    raise
                if observer is not None:
                    await observer(exc, attempt, delay or 0.0)
                await asyncio.sleep(delay or 0.0)
        raise RuntimeError("unreachable retry state")

    def _delay(self, error: ProviderError, attempt: int) -> float:
        if error.retry_after is not None:
            return min(self.max_delay_seconds, max(0.0, error.retry_after))
        base = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** max(0, attempt - 1)),
        )
        if not base or not self.jitter_ratio:
            return base
        jitter = random.uniform(-self.jitter_ratio, self.jitter_ratio)
        return min(self.max_delay_seconds, max(0.0, base * (1 + jitter)))
