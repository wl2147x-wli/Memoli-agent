"""记忆 runtime。

MemoryRuntime 是长期记忆系统的对外入口：

- query：按关键词检索长期记忆。
- mutate：写入长期事实记忆。
- render_prompt_block：把检索结果渲染为可注入 prompt 的中文块。
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from memoli_agent.agent.memory.models import (
    MemoryItem,
    MemoryMutation,
    MemoryQuery,
    MemoryQueryResult,
    MemoryScope,
)


@dataclass(frozen=True, slots=True)
class MemoryRuntime:
    """长期记忆运行时。"""

    store: Any
    retriever: Any
    auto_recall: bool = True
    core_card_limit: int = 8
    core_card_chars: int = 4_000
    recall_chars: int = 8_000
    recall_limit: int = 8
    card_limit: int = 2
    claim_limit: int = 5
    episode_limit: int = 2
    spillover_order: tuple[str, ...] = ("claim", "card", "episode")
    index_worker: Any = None
    card_builder: Any = None
    episode_projector: Any = None
    offline_worker: Any = None
    offline_enabled: bool = False
    extractor_fingerprint: str = ""
    governance_service: Any = None
    retrieval_mode: str = "auto"
    detail_level: str = "summary"
    card_statement_limit: int = 6
    claim_expansion_limit: int = 6
    evidence_expansion_limit: int = 3
    direct_claim_fallback: bool = True

    async def start(self) -> None:
        if self.offline_worker is not None:
            await self.offline_worker.start()

    async def stop(self) -> None:
        if self.offline_worker is not None:
            await self.offline_worker.stop()

    async def query(self, request: MemoryQuery) -> MemoryQueryResult:
        """按关键词查询长期记忆。"""

        pending = self.retriever.query(request)
        result = await pending if inspect.isawaitable(pending) else pending
        items = []
        used = 0
        omitted_chars = 0
        for item in result.items:
            if used + len(item.content) > self.recall_chars:
                omitted_chars += len(item.content)
                continue
            items.append(item)
            used += len(item.content)
        return MemoryQueryResult(
            items,
            candidate_count=result.candidate_count,
            filtered_count=result.filtered_count,
            degraded=result.degraded,
            injected_chars=used,
            reason=result.reason,
            active_lanes=result.active_lanes,
            degraded_lanes=result.degraded_lanes,
            lane_candidate_counts=dict(result.lane_candidate_counts),
            query_context_fields=result.query_context_fields,
            truncated=len(items) < len(result.items) or result.truncated,
            omitted_items=(len(result.items) - len(items)) + result.omitted_items,
            omitted_chars=omitted_chars + result.omitted_chars,
            requested_route=result.requested_route,
            actual_route=result.actual_route,
            detail_level=result.detail_level,
            degraded_reasons=result.degraded_reasons,
            query_plan_summary=dict(result.query_plan_summary),
            filter_counts=dict(result.filter_counts),
        )

    async def pre_recall(
        self,
        *,
        user_message: str,
        objective: str = "",
        current_step: str = "",
        session_id: str = "",
        scope: MemoryScope | None = None,
    ) -> MemoryQueryResult:
        """用当前交互和 checkpoint 做轻量预检索，并优先保留核心卡片。"""

        if not self.auto_recall:
            return MemoryQueryResult([], reason="auto-recall-disabled")
        request = MemoryQuery(
            query=user_message,
            objective=objective,
            current_step=current_step,
            session_id=session_id,
            scope=scope or MemoryScope(),
            limit=self.recall_limit,
            card_limit=self.card_limit,
            claim_limit=self.claim_limit,
            episode_limit=self.episode_limit,
            max_chars=self.recall_chars,
            spillover_order=self.spillover_order,
            retrieval_mode=self.retrieval_mode,  # type: ignore[arg-type]
            detail_level=self.detail_level,  # type: ignore[arg-type]
            card_statement_limit=self.card_statement_limit,
            claim_expansion_limit=self.claim_expansion_limit,
            evidence_expansion_limit=self.evidence_expansion_limit,
            direct_claim_fallback=self.direct_claim_fallback,
        )
        recalled = await self.query(request)
        core = (
            self.store.select_core_cards(
                request.scope,
                limit=self.core_card_limit,
                max_chars=self.core_card_chars,
            )
            if hasattr(self.store, "select_core_cards")
            else []
        )
        seen = {item.item_id for item in core}
        items = [*core, *(item for item in recalled.items if item.item_id not in seen)]
        return MemoryQueryResult(
            items,
            candidate_count=recalled.candidate_count + len(core),
            filtered_count=recalled.filtered_count,
            degraded=recalled.degraded,
            injected_chars=sum(len(item.content) for item in items),
            reason=f"core+{recalled.reason}",
            active_lanes=recalled.active_lanes,
            degraded_lanes=recalled.degraded_lanes,
            lane_candidate_counts=dict(recalled.lane_candidate_counts),
            query_context_fields=recalled.query_context_fields,
            truncated=recalled.truncated,
            omitted_items=recalled.omitted_items,
            omitted_chars=recalled.omitted_chars,
            requested_route=recalled.requested_route,
            actual_route=recalled.actual_route,
            detail_level=recalled.detail_level,
            degraded_reasons=recalled.degraded_reasons,
            query_plan_summary=dict(recalled.query_plan_summary),
            filter_counts=dict(recalled.filter_counts),
        )

    async def mutate(self, request: MemoryMutation) -> MemoryItem:
        """写入一条长期事实记忆。"""

        if hasattr(self.store, "append_claim"):
            return self.store.append_claim(request)
        return self.store.append_memory(
            content=request.content,
            source=request.source,
            metadata=request.metadata,
        )

    async def project_completed_trace(
        self,
        trace_id: str,
        *,
        objective: str = "",
        current_step: str = "",
    ) -> dict[str, Any]:
        """在 trace 已提交后生成 Episode；失败由调用方降级处理。"""

        if self.episode_projector is None or not trace_id:
            return {"status": "disabled"}
        segments = await self.episode_projector.project_trace(
            trace_id,
            MemoryScope(),
            objective=objective,
            current_step=current_step,
        )
        return {"status": "ready", "segments": len(segments)}

    def schedule_completed_trace(
        self,
        trace_id: str,
        *,
        objective: str = "",
        current_step: str = "",
        scope: MemoryScope | None = None,
    ) -> dict[str, Any]:
        if self.episode_projector is None or not trace_id:
            return {"status": "disabled"}
        self.store.enqueue_episode_projection(
            trace_id,
            scope or MemoryScope(),
            objective=objective,
            current_step=current_step,
        )
        if self.offline_worker is not None:
            self.offline_worker.wake()
        return {"status": "scheduled", "trace_id": trace_id}

    async def request_long_term_update(
        self,
        *,
        trace_id: str,
        session_id: str,
        idempotency_key: str,
        scope: MemoryScope | None = None,
    ) -> Any:
        selected_scope = scope or MemoryScope()
        coordinator_enabled = bool(
            self.offline_worker is not None
            and self.offline_worker.auto_scan_enabled
            and self.offline_worker.trigger_coordinator is not None
        )
        if (
            not self.offline_enabled
            or not coordinator_enabled
            or not hasattr(self.store, "create_update_intent")
        ):
            return {
                "status": "disabled",
                "reason": (
                    "trigger-coordinator-disabled"
                    if self.offline_enabled
                    else "offline-consolidation-disabled"
                ),
                "pending_chat_count": 0,
            }
        pending = self.store.pending_chat_consumptions(selected_scope, session_id)
        boundary_key = (
            f"{pending[0].trace_id}:{pending[-1].trace_id}:{len(pending)}"
            if pending
            else "empty"
        )
        intent = self.store.create_update_intent(
            selected_scope, session_id, boundary_key
        )
        if self.offline_worker is not None:
            self.offline_worker.wake()
        return {
            "status": "waiting-for-trigger",
            "hint_id": intent.hint_id,
            "scope": selected_scope,
            "pending_chat_count": len(pending),
        }

    async def maintenance_tick(self) -> dict[str, Any]:
        """串行执行一个有界维护批次，不创建并发 agent turn。"""

        if self.offline_worker is not None:
            return await self.offline_worker.maintenance_tick()

        diagnostics: dict[str, Any] = {}
        if self.card_builder is not None:
            card_results = self.card_builder.tick()
            diagnostics["card_projections"] = len(card_results)
        if self.index_worker is not None:
            result = await self.index_worker.tick()
            diagnostics["semantic_index"] = {
                "processed": result.processed,
                "succeeded": result.succeeded,
                "failed": result.failed,
                "stale": result.stale,
                "policy_filtered": result.policy_filtered,
            }
        return diagnostics

    def diagnostics(self) -> dict[str, Any]:
        if self.offline_worker is not None:
            return {
                **dict(self.store.index_diagnostics()),
                "offline": self.offline_worker.diagnostics(),
            }
        if hasattr(self.store, "index_diagnostics"):
            return {
                **dict(self.store.index_diagnostics()),
                "offline": {
                    "enabled": self.offline_enabled,
                    "running": False,
                    **(
                        self.store.offline_diagnostics()
                        if hasattr(self.store, "offline_diagnostics")
                        else {}
                    ),
                },
            }
        return {"engine": "markdown", "semantic_entries": 0}

    def render_prompt_block(self, result: MemoryQueryResult) -> str:
        """把检索结果渲染成 prompt block。"""

        if not result.items:
            return ""

        lines = ['<memory_context trust="data">']
        for item in result.items:
            evidence = (
                ", ".join(f"{ref.kind}:{ref.ref_id}" for ref in item.evidence)
                or "unavailable"
            )
            lines.append(
                f"- [{item.item_type}:{item.item_id or 'legacy'}] {item.content} "
                f"(evidence={evidence}; reason={item.recall_reason or 'keyword'})"
            )
        lines.append("</memory_context>")
        return "\n".join(lines)

    def close(self) -> None:
        if hasattr(self.store, "close"):
            self.store.close()


__all__ = [
    "MemoryItem",
    "MemoryMutation",
    "MemoryQuery",
    "MemoryQueryResult",
    "MemoryRuntime",
]
