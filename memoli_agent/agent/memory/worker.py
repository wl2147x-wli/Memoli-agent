"""独立于在线 turn 的有界离线记忆 Worker。"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from memoli_agent.agent.memory.consolidator import MemoryConsolidator
from memoli_agent.agent.memory.extraction import ExtractorPermanentError
from memoli_agent.agent.memory.models import MemoryScope
from memoli_agent.agent.memory.source import (
    EvidenceVerificationError,
    TrajectorySourceError,
)
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore

_AUTO_SCAN_USER_SESSION_PREFIXES = ("cli:",)


def _auto_scan_session_allowed(session_id: str) -> bool:
    """Only user-facing channel traces may become automatic memory sources."""

    return session_id.startswith(_AUTO_SCAN_USER_SESSION_PREFIXES)


@dataclass(slots=True)
class OfflineMemoryWorker:
    store: SQLiteMemoryStore
    consolidator: MemoryConsolidator
    poll_seconds: float = 2.0
    batch_size: int = 4
    lease_seconds: int = 120
    retry_max_seconds: int = 300
    auto_scan_enabled: bool = False
    trigger_coordinator: Any = None
    card_builder: Any = None
    index_worker: Any = None
    episode_projector: Any = None
    governance_dispatcher: Any = None
    governance_batch_size: int = 8
    governance_lease_seconds: int = 120
    dead_letter_stale_after_seconds: int = 86_400
    chat_turn_threshold: int = 20
    worker_id: str = field(default_factory=lambda: f"memory-worker-{uuid.uuid4().hex}")
    _wake: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _stop: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)
    _last_error_type: str = field(default="", init=False)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self.store.recover_expired_long_term_update_leases()
        self.store.recover_expired_governance_leases()
        self.store.recover_expired_derived_leases()
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(), name=f"offline-memory:{self.worker_id}"
        )

    async def stop(self, timeout_seconds: float = 10.0) -> None:
        task = self._task
        if task is None:
            return
        self._stop.set()
        self._wake.set()
        try:
            await asyncio.wait_for(task, timeout=max(0.1, timeout_seconds))
        except TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        finally:
            self._task = None

    def wake(self) -> None:
        self._wake.set()

    async def maintenance_tick(self) -> dict[str, Any]:
        trigger_diagnostics: dict[str, Any] = {}
        if self.auto_scan_enabled and self.trigger_coordinator is not None:
            trigger_diagnostics = await self.trigger_coordinator.tick()
            auto_scan_enqueued = int(
                trigger_diagnostics.get("long_task_enqueued", 0)
            ) + int(trigger_diagnostics.get("chat_windows_enqueued", 0))
        else:
            auto_scan_enqueued = 0
        processed = succeeded = failed = skipped = 0
        requests = self.store.claim_long_term_update_requests(
            worker_id=self.worker_id,
            limit=self.batch_size,
            lease_seconds=self.lease_seconds,
        )
        for request in requests:
            processed += 1
            if request.source_type == "auto-scan" and not _auto_scan_session_allowed(
                request.session_id
            ):
                self.store.complete_long_term_update_request(
                    request.request_id,
                    worker_id=self.worker_id,
                    candidate_count=0,
                )
                skipped += 1
                continue
            try:
                await self.consolidator.run_request(request, worker_id=self.worker_id)
                succeeded += 1
            except Exception as exc:
                error_type = type(exc).__name__
                self._last_error_type = error_type
                permanent = isinstance(
                    exc,
                    ExtractorPermanentError
                    | EvidenceVerificationError
                    | TrajectorySourceError
                    | PermissionError
                    | TypeError
                    | ValueError,
                )
                delay = min(
                    self.retry_max_seconds,
                    2 ** min(max(request.attempts, 1), 8),
                )
                self.store.fail_long_term_update_request(
                    request.request_id,
                    worker_id=self.worker_id,
                    error_type=error_type,
                    permanent=permanent,
                    retry_seconds=delay,
                )
                failed += 1
        episodes = await self._project_episodes()
        governance = await self._govern_candidates()
        cards = len(self.card_builder.tick()) if self.card_builder is not None else 0
        semantic: dict[str, int] = {}
        if self.index_worker is not None:
            result = await self.index_worker.tick()
            semantic = {
                "processed": result.processed,
                "succeeded": result.succeeded,
                "failed": result.failed,
                "stale": result.stale,
                "policy_filtered": result.policy_filtered,
            }
        return {
            "auto_scan_enqueued": auto_scan_enqueued,
            "triggers": trigger_diagnostics,
            "requests": {
                "processed": processed,
                "succeeded": succeeded,
                "failed": failed,
                "skipped": skipped,
            },
            "episode_projections": episodes,
            "governance": governance,
            "card_projections": cards,
            "semantic_index": semantic,
        }

    async def _govern_candidates(self) -> dict[str, int]:
        if self.governance_dispatcher is None:
            return {"processed": 0, "succeeded": 0, "failed": 0}
        processed = succeeded = failed = 0
        jobs = self.store.claim_governance_jobs(
            worker_id=self.worker_id,
            limit=self.governance_batch_size,
            lease_seconds=self.governance_lease_seconds,
        )
        for job in jobs:
            processed += 1
            try:
                await self.governance_dispatcher.review(job, worker_id=self.worker_id)
                succeeded += 1
            except Exception as exc:
                self._last_error_type = type(exc).__name__
                self.store.fail_governance_job(
                    job.job_id,
                    worker_id=self.worker_id,
                    error_type=type(exc).__name__,
                    retry_seconds=min(
                        self.retry_max_seconds,
                        2 ** min(max(job.attempts, 1), 8),
                    ),
                )
                failed += 1
        return {"processed": processed, "succeeded": succeeded, "failed": failed}

    async def _project_episodes(self) -> int:
        if self.episode_projector is None:
            return 0
        count = 0
        for job in self.store.claim_projection_jobs(
            "episode", self.batch_size, worker_id=self.worker_id
        ):
            key = str(job["projection_key"])
            try:
                payload = json.loads(str(job["payload_json"]))
                await self.episode_projector.project_trace(
                    str(payload["trace_id"]),
                    MemoryScope(str(payload["scope_kind"]), str(payload["scope_id"])),
                    objective=str(payload.get("objective") or ""),
                    current_step=str(payload.get("current_step") or ""),
                )
                self.store.finish_projection_job(
                    "episode", key, worker_id=self.worker_id
                )
                count += 1
            except Exception as exc:
                self.store.fail_projection_job(
                    "episode", key, type(exc).__name__, worker_id=self.worker_id
                )
                self._last_error_type = type(exc).__name__
        return count

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                diagnostics = await self.maintenance_tick()
                pending = (
                    diagnostics["requests"]["processed"] > 0
                    or diagnostics["governance"]["processed"] > 0
                )
                if pending:
                    await asyncio.sleep(0)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error_type = type(exc).__name__
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass

    def diagnostics(self) -> dict[str, Any]:
        offline = self.store.offline_diagnostics(
            dead_letter_stale_after_seconds=self.dead_letter_stale_after_seconds
        )
        return {
            "enabled": True,
            "running": self._task is not None and not self._task.done(),
            "worker_id": self.worker_id,
            "last_error_type": self._last_error_type,
            "chat_turn_threshold": self.chat_turn_threshold,
            **offline,
        }
