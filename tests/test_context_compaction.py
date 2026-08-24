from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from memoli_agent.agent.context_management import (
    CompactionError,
    ConservativeTokenEstimator,
    ContextArchive,
    InMemoryContextStateRepository,
    TaskAwareCompactor,
)
from memoli_agent.agent.context_management.compaction import (
    ARCHIVE_FIELDS,
    _message_ref,
    _validated_archive,
)
from memoli_agent.agent.provider import EchoProvider, LLMResponse, ScriptedProvider
from memoli_agent.agent.trajectory import InMemoryTrajectoryStore
from memoli_agent.agent.types import ChatMessage


def _archive_json(refs: list[str]) -> str:
    return json.dumps(
        {
            "goal_constraints": ["preserve constraint"],
            "decisions_reasons": ["decision because evidence"],
            "facts_evidence": ["payload:42"],
            "files_artifacts": ["result.txt"],
            "verification_status": ["tests passed"],
            "failure_paths": ["first attempt failed"],
            "todo_remaining": ["ship"],
            "source_refs": refs,
        }
    )


def test_real_compactor_commits_fixed_schema_in_child_span() -> None:
    message = ChatMessage("user", "goal")
    import hashlib

    canonical = json.dumps(
        message.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    refs = ["message:" + hashlib.sha256(canonical.encode()).hexdigest()[:24]]
    provider = ScriptedProvider([LLMResponse(_archive_json(refs), provider="scripted")])
    repo = InMemoryContextStateRepository()
    store = InMemoryTrajectoryStore()
    archive = asyncio.run(
        TaskAwareCompactor(
            provider,
            repo,
            ConservativeTokenEstimator(),
            archive_tokens=1_000,
        ).compact(
            session_key="s",
            messages=[message],
            trace_id="trace",
            parent_span_id="parent",
            trajectory_store=store,
        )
    )
    assert repo.list_archives("s") == (archive,)
    assert json.loads(archive.content)["todo_remaining"] == ["ship"]
    assert [item.event_type for item in store.events] == [
        "context_compaction_requested",
        "context_compaction_committed",
    ]
    assert store.spans[next(iter(store.spans))].parent_span_id == "parent"


@pytest.mark.parametrize(
    "provider",
    [
        EchoProvider(),
        ScriptedProvider([LLMResponse("not-json", provider="scripted")]),
    ],
)
def test_echo_or_invalid_archive_never_changes_current_view(provider) -> None:  # type: ignore[no-untyped-def]
    repo = InMemoryContextStateRepository()
    store = InMemoryTrajectoryStore()
    with pytest.raises(CompactionError):
        asyncio.run(
            TaskAwareCompactor(
                provider,
                repo,
                ConservativeTokenEstimator(),
                archive_tokens=100,
            ).compact(
                session_key="s",
                messages=[ChatMessage("user", "goal")],
                trace_id="trace",
                parent_span_id="parent",
                trajectory_store=store,
            )
        )
    assert repo.list_archives("s") == ()


def test_validated_archive_rejects_overlap_with_parent_refs() -> None:
    """§5.4 覆盖无环性：新批次 source refs 不得与父归档已覆盖 refs 重叠。"""

    ref = _message_ref(ChatMessage("user", "goal"))
    with pytest.raises(CompactionError):
        _validated_archive(_archive_json([ref]), (ref,), parent_refs=(ref,))


def test_validated_archive_rejects_empty_task_information() -> None:
    """§5.4 最小任务信息：archive 不得全为空数组。"""

    ref = _message_ref(ChatMessage("user", "goal"))
    empty = json.dumps({**{key: [] for key in ARCHIVE_FIELDS}, "source_refs": [ref]})
    with pytest.raises(CompactionError):
        _validated_archive(empty, (ref,))


def test_validated_archive_rejects_extra_forbidden_fields() -> None:
    """§5.4 固定字段与禁止字段：键集合必须精确等于 schema。"""

    ref = _message_ref(ChatMessage("user", "goal"))
    payload = json.loads(_archive_json([ref]))
    payload["hidden_reasoning"] = ["must-not-leak"]  # 禁止字段
    with pytest.raises(CompactionError):
        _validated_archive(json.dumps(payload), (ref,))


def test_validated_archive_rejects_changed_source_refs() -> None:
    """§5.4 引用集合：source_refs 必须与提交批次完全一致。"""

    ref = _message_ref(ChatMessage("user", "goal"))
    other = _message_ref(ChatMessage("user", "other"))
    with pytest.raises(CompactionError):
        _validated_archive(_archive_json([other]), (ref,))


def test_compact_carries_epoch_target_and_parent_refs_to_request() -> None:
    """§5.3：压缩统一输入 schema 透传至请求与 archive。

    target_tokens/parent_archive_refs/epoch 既进入请求 user 消息，也记录到 archive。
    """

    @dataclass
    class CapturingProvider:
        response: LLMResponse
        received: list[list[ChatMessage]] = field(default_factory=list)
        name: str = "capturing"

        async def chat(
            self,
            messages: list[ChatMessage],
            tools: list[dict[str, Any]] | None = None,
        ) -> LLMResponse:
            self.received.append(list(messages))
            return self.response

        async def aclose(self) -> None:
            return None

    message = ChatMessage("user", "goal")
    ref = _message_ref(message)
    provider = CapturingProvider(
        LLMResponse(_archive_json([ref]), provider="capturing")
    )
    repo = InMemoryContextStateRepository()
    store = InMemoryTrajectoryStore()
    archive = asyncio.run(
        TaskAwareCompactor(
            provider,
            repo,
            ConservativeTokenEstimator(),
            archive_tokens=1_000,
        ).compact(
            session_key="s",
            messages=[message],
            trace_id="trace",
            parent_span_id="parent",
            trajectory_store=store,
            target_tokens=500,
            parent_archive_refs=("message:parent",),
            epoch=3,
        )
    )
    # archive 记录携带 epoch（§5.3 持久化）
    assert archive.epoch == 3
    # 请求 user 消息携带统一 schema 的目标/约束、父归档引用与 epoch（§5.3 输入 schema）
    user_payload = json.loads(provider.received[0][1].content)
    assert user_payload["target_tokens"] == 500
    assert user_payload["parent_archive_refs"] == ["message:parent"]
    assert user_payload["epoch"] == 3


def _seed_parent(
    repo: InMemoryContextStateRepository, archive_id: str, refs: list[str]
) -> None:
    """§6.5 测试夹具：直接 commit_archive 预置活动父 archive（generation 事务分配）。"""
    repo.commit_archive(
        ContextArchive(
            archive_id, "s", 0,
            _archive_json(refs),
            f"hash-{archive_id}",
            tuple(refs),
            epoch=0,
            coverage_hash=f"cov-{archive_id}",
        )
    )


def test_merge_frontier_merges_oldest_adjacent_when_over_max_items() -> None:
    """§6.5 merge_frontier：frontier 超 max_items 时取最旧相邻 2 个调 Provider
    再次摘要为高层 archive，原子合并（父 superseded、merged 活动、frontier
    缩减）。level=max(父)+1、source_refs=父并集、parent_archive_refs=父
    archive_id、generation 事务分配=max+1（correction 3 顺序 + correction 4）。"""
    repo = InMemoryContextStateRepository()
    store = InMemoryTrajectoryStore()
    _seed_parent(repo, "aid1", ["r1", "r2"])
    _seed_parent(repo, "aid2", ["r3", "r4"])

    # Provider 返回合并 archive（source_refs = 父并集 ["r1","r2","r3","r4"]）
    merged_json = _archive_json(["r1", "r2", "r3", "r4"])
    provider = ScriptedProvider([LLMResponse(merged_json, provider="scripted")])
    compactor = TaskAwareCompactor(
        provider, repo, ConservativeTokenEstimator(), archive_tokens=1_000,
    )
    result = asyncio.run(
        compactor.merge_frontier(
            session_key="s", trace_id="trace", parent_span_id="parent",
            trajectory_store=store, epoch=0,
            frontier_tokens=100_000, frontier_max_items=1,  # 2 个 > 1 → 触发
        )
    )
    assert result is not None
    assert result.level == 2  # max(父 level)+1
    assert set(result.source_refs) == {"r1", "r2", "r3", "r4"}  # 父并集
    assert result.parent_archive_refs == ("aid1", "aid2")
    assert result.generation == 3  # max(同 epoch generation)+1 = 3
    # 父 superseded、frontier 仅 merged 活动
    frontier = repo.list_frontier("s")
    assert len(frontier) == 1 and frontier[0].archive_id == result.archive_id
    # 轨迹：requested + committed（合并 span，与 compact 同事件类型不同 span）
    events = [item.event_type for item in store.events]
    assert events == [
        "context_compaction_requested",
        "context_compaction_committed",
    ]


def test_merge_frontier_returns_none_when_frontier_within_bounds() -> None:
    """§6.5 merge_frontier：frontier 未超 tokens/max_items 时不合并、
    Provider 不调用。"""
    repo = InMemoryContextStateRepository()
    store = InMemoryTrajectoryStore()
    _seed_parent(repo, "aid1", ["r1"])
    provider = ScriptedProvider([LLMResponse("must-not-be-used", provider="scripted")])
    compactor = TaskAwareCompactor(
        provider, repo, ConservativeTokenEstimator(), archive_tokens=1_000,
    )
    result = asyncio.run(
        compactor.merge_frontier(
            session_key="s", trace_id="trace", parent_span_id="parent",
            trajectory_store=store, epoch=0,
            frontier_tokens=100_000, frontier_max_items=8,  # 1 个 <= 8 → 不触发
        )
    )
    assert result is None
    assert len(store.events) == 0  # 未记录任何压缩事件


def test_merge_frontier_returns_none_on_provider_failure_leaving_frontier_intact(
) -> None:
    """§6.5 best-effort：合并 Provider/校验失败 → 返回 None，父节点保持活动
    （spec「原有 frontier、coverage、源 turn 与当前视图保持不变」+ correction 9
    失败不回滚已成立 context state）。"""
    repo = InMemoryContextStateRepository()
    store = InMemoryTrajectoryStore()
    _seed_parent(repo, "aid1", ["r1", "r2"])
    _seed_parent(repo, "aid2", ["r3", "r4"])
    # Provider 返回非 JSON → _validated_archive 抛 CompactionError → best-effort None
    provider = ScriptedProvider([LLMResponse("not-json", provider="scripted")])
    compactor = TaskAwareCompactor(
        provider, repo, ConservativeTokenEstimator(), archive_tokens=1_000,
    )
    result = asyncio.run(
        compactor.merge_frontier(
            session_key="s", trace_id="trace", parent_span_id="parent",
            trajectory_store=store, epoch=0,
            frontier_tokens=100_000, frontier_max_items=1,
        )
    )
    assert result is None
    # 父节点保持活动（未 superseded、无孤立 merged archive）
    frontier = repo.list_frontier("s")
    assert {a.archive_id for a in frontier} == {"aid1", "aid2"}
