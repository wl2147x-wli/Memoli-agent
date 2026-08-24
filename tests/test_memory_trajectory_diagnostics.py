"""检索诊断 trajectory 接入与写入失败安全测试 (task 7.3)。

验证：
- 新的诊断摘要 (query_plan_summary / filter_counts) 经 MemoryRuntime 透传不丢失；
- memory_retrieved trajectory 事件 payload 携带这些摘要；
- trajectory 写入失败不改变候选排序或主回合结果（排序在写入前完成）。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memoli_agent.agent.lifecycle.phases import BeforeReasoningPhase
from memoli_agent.agent.lifecycle.types import PassiveTurnContext
from memoli_agent.agent.memory.hybrid import (
    FtsSearchLane,
    HybridMemoryRetriever,
    MetadataSearchLane,
    PatternSearchLane,
)
from memoli_agent.agent.memory.layered import LayeredMemoryRetriever
from memoli_agent.agent.memory.models import EvidenceRef, MemoryMutation
from memoli_agent.agent.memory.runtime import MemoryRuntime
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore
from memoli_agent.agent.trajectory import (
    InMemoryTrajectoryStore,
    NewTrajectoryEvent,
    TrajectoryError,
    TrajectoryEvent,
)
from memoli_agent.bus.events import InboundMessage


def _claim(content: str) -> MemoryMutation:
    return MemoryMutation(
        content,
        evidence=(EvidenceRef("message", f"msg-{content}", content),),
    )


def _runtime(store: SQLiteMemoryStore) -> MemoryRuntime:
    hybrid = HybridMemoryRetriever(
        store=store,
        fts_lane=FtsSearchLane(store),
        pattern_lane=PatternSearchLane(store),
        metadata_lane=MetadataSearchLane(store),
        semantic_lane=None,
    )
    return MemoryRuntime(
        store=store,
        retriever=LayeredMemoryRetriever(store, hybrid),
        auto_recall=True,
        recall_chars=8_000,
        recall_limit=8,
        card_limit=2,
        claim_limit=5,
        episode_limit=2,
    )


def _ctx(content: str, *, trace_id: str = "trace-1") -> PassiveTurnContext:
    return PassiveTurnContext(
        inbound=InboundMessage("cli", "session-1", "user", content),
        trace_id=trace_id,
        root_span_id="span-1",
    )


def test_runtime_passes_query_plan_summary_and_filter_counts(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    store.append_claim(_claim("项目使用清华源下载依赖"))
    runtime = _runtime(store)

    async def scenario() -> None:
        result = await runtime.pre_recall(user_message="清华源", session_id="session-1")
        # 诊断摘要在 runtime 透传后仍存在。
        assert result.query_plan_summary.get("fts_term_count") == 1
        assert "pattern_term_count" in result.query_plan_summary
        assert "hard_filter" in result.filter_counts
        assert "relative_threshold" in result.filter_counts

    asyncio.run(scenario())


@dataclass
class FailingTrajectoryStore:
    """record 永远抛 TrajectoryError，用于证明写入失败不影响排序。"""

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def record(self, item: NewTrajectoryEvent) -> TrajectoryEvent:
        raise TrajectoryError("injected trajectory write failure")

    def sanitize_for_capture(self, value: Any) -> Any:
        return value


def test_trajectory_records_retrieval_diagnostics(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    store.append_claim(_claim("项目使用清华源下载依赖"))
    runtime = _runtime(store)
    trajectory = InMemoryTrajectoryStore()
    phase = BeforeReasoningPhase(
        memory_runtime=runtime,
        trajectory_store=trajectory,
    )

    async def scenario() -> None:
        await trajectory.start()
        ctx = _ctx("清华源")
        await phase.run(ctx)
        # 成功写入：payload 携带新诊断摘要与聚合过滤计数。
        memory_events = [
            payload
            for payload in trajectory.event_payloads
            if isinstance(payload, dict)
        ]
        assert memory_events, "expected a memory_retrieved trajectory event"
        payload = memory_events[0]
        assert "query_plan_summary" in payload
        assert "filter_counts" in payload
        assert "omitted_items" in payload
        assert "omitted_chars" in payload
        assert payload["query_plan_summary"]["fts_term_count"] == 1
        # 排序结果同步落回 context。
        assert ctx.memory_query_result is not None
        assert ctx.memory_query_result.items
        assert ctx.metadata.get("memory_status") == "ready"

    asyncio.run(scenario())


def test_trajectory_write_failure_does_not_change_ranking(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "mem.db")
    claim = store.append_claim(_claim("项目使用清华源下载依赖"))
    runtime = _runtime(store)
    phase = BeforeReasoningPhase(
        memory_runtime=runtime,
        trajectory_store=FailingTrajectoryStore(),
    )

    async def scenario() -> None:
        ctx = _ctx("清华源")
        await phase.run(ctx)
        # 写入失败：排序已在写入前完成，结果不变。
        assert ctx.memory_query_result is not None
        assert [item.item_id for item in ctx.memory_query_result.items] == [
            claim.item_id
        ]
        assert ctx.metadata.get("memory_trace_diagnostic") == "write-failed"
        assert ctx.metadata.get("memory_status") == "ready"
        assert ctx.memory_prompt_block  # 主回合 prompt 块照常渲染

    asyncio.run(scenario())
