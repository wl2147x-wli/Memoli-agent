from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

import pytest

from memoli_agent.agent.context_management import (
    ContextArchive,
    ContextSnapshot,
    InMemoryContextStateRepository,
)
from memoli_agent.agent.plugins.hooks import HookBus
from memoli_agent.agent.provider import LLMResponse, ToolCall
from memoli_agent.agent.subagent.context import ContextCompiler, parse_structured_result
from memoli_agent.agent.subagent.events import SubAgentResult, SubAgentTask
from memoli_agent.agent.subagent.manager import SubAgentManager
from memoli_agent.agent.subagent.models import (
    AgentTask,
    ContextPackage,
    DelegationRequest,
    StructuredSubAgentResult,
    TaskStatus,
)
from memoli_agent.agent.subagent.profiles import (
    ProfileToolRegistryFactory,
    default_subagent_profiles,
)
from memoli_agent.agent.subagent.repository import (
    CyclicDependencyError,
    InvalidTaskTransitionError,
    TaskGraphRepository,
)
from memoli_agent.agent.subagent.runtime import SubAgentRuntime, SubAgentRuntimeFactory
from memoli_agent.agent.tools.builtin import SpawnSubAgentTool, TimeTool
from memoli_agent.agent.tools.execution import ToolExecutionContext, tool_context
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import (
    InMemoryTrajectoryStore,
    NullTrajectoryStore,
)
from memoli_agent.agent.types import ChatMessage
from memoli_agent.bus.queue import MessageBus


@dataclass
class FakeRuntime:
    delay: float = 0
    active: int = 0
    max_active: int = 0

    async def run(self, task: SubAgentTask) -> SubAgentResult:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            artifact = task.task_dir / "answer.txt"
            artifact.write_text("artifact", encoding="utf-8")
            structured = StructuredSubAgentResult(
                status="completed",
                conclusion=f"done:{task.instruction}",
                artifacts=({"path": "answer.txt", "kind": "text"},),
                completed_criteria=("done",),
            )
            return SubAgentResult(
                task_id=task.task_id,
                content=structured.conclusion,
                success=True,
                profile_name=task.profile_name,
                task_dir=task.task_dir,
                agent_id=task.agent_id,
                trace_id=task.trace_id,
                attempt_id=task.attempt_id,
                status="completed",
                structured=structured,
            )
        finally:
            self.active -= 1


@dataclass
class ScriptedProvider:
    responses: list[LLMResponse]
    name: str = "scripted"

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        del messages, tools
        return self.responses.pop(0)


def _agent_task(root: Path, task_id: str, status: TaskStatus) -> AgentTask:
    return AgentTask(
        task_id=task_id,
        agent_id=f"agent_{task_id}",
        root_agent_id="main",
        parent_agent_id="main",
        parent_task_id="",
        root_session_key="session-a",
        profile_name="research",
        objective=task_id,
        context_package=ContextPackage(objective=task_id),
        status=status,
        depth=1,
        task_dir=root / task_id,
        max_iterations=4,
        max_elapsed_seconds=30,
    )


def _manager(tmp_path: Path, runtime: FakeRuntime | None = None) -> SubAgentManager:
    return SubAgentManager(
        runtime=cast(SubAgentRuntime, runtime or FakeRuntime()),
        repository=TaskGraphRepository(tmp_path / "task-graph.db"),
        bus=MessageBus(),
        root=tmp_path / "tasks",
        profiles=default_subagent_profiles(),
        max_concurrent=1,
        max_depth=1,
    )


def test_repository_persists_graph_and_rejects_cycle_and_duplicate_claim(
    tmp_path: Path,
) -> None:
    repository = TaskGraphRepository(tmp_path / "graph.db")
    first = _agent_task(tmp_path, "first", TaskStatus.PENDING)
    second = _agent_task(tmp_path, "second", TaskStatus.PENDING)
    repository.create_task(first)
    repository.create_task(second, ["first"])
    assert repository.refresh_task_readiness("first") is TaskStatus.RUNNABLE
    assert repository.refresh_task_readiness("second") is TaskStatus.BLOCKED
    assert repository.transition(
        "first", TaskStatus.RUNNING, expected=TaskStatus.RUNNABLE
    )
    assert not repository.transition(
        "first", TaskStatus.RUNNING, expected=TaskStatus.RUNNABLE
    )
    with pytest.raises(CyclicDependencyError):
        repository.add_dependency("second", "first")
    assert repository.dependencies("first") == []
    with pytest.raises(InvalidTaskTransitionError):
        repository.transition("first", TaskStatus.RUNNABLE)
    assert repository.transition(
        "first", TaskStatus.FAILED, expected=TaskStatus.RUNNING
    )
    assert repository.refresh_task_readiness("second") is TaskStatus.BLOCKED
    blocked = repository.get_task("second")
    assert blocked is not None and blocked.blocked_reason == "dependency_failed"
    repository.close_sync()


def test_repository_migration_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "migration.db"
    repository = TaskGraphRepository(database)
    repository.close_sync()
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA user_version = 1")
    connection.commit()
    connection.close()
    migrated = TaskGraphRepository(database)
    migrated.close_sync()
    connection = sqlite3.connect(database)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    connection.close()


def test_context_package_is_bounded_and_unstructured_result_keeps_truth() -> None:
    compiler = ContextCompiler(max_dependency_chars=32)
    context = compiler.compile(
        DelegationRequest(
            objective="inspect",
            acceptance_criteria=("evidence",),
            confirmed_facts=("known",),
        ),
        dependency_results=("x" * 100,),
    )
    assert context.objective == "inspect"
    assert "TRUNCATED" in context.dependency_results[0]
    assert "unrelated chat" not in ContextCompiler.render(context)
    result = parse_structured_result("plain conclusion", default_status="completed")
    assert result.conclusion == "plain conclusion"
    assert result.unstructured_fallback
    assert result.evidence == ()


def test_profile_registry_enforces_visible_tools_and_task_write_root(
    tmp_path: Path,
) -> None:
    source = ToolRegistry()
    source.register(TimeTool())
    factory = ProfileToolRegistryFactory(source, tmp_path)
    profiles = default_subagent_profiles()
    research = factory.build(profiles["research"], tmp_path / "research")
    coding_root = tmp_path / "coding"
    coding_root.mkdir()
    coding = factory.build(profiles["coding"], coding_root)
    assert [tool.name for tool in research.list_tools()] == ["time", "file_read"]
    coding_names = [tool.name for tool in coding.list_tools()]
    assert coding_names == ["time", "file_read", "file_patch", "file_write", "code_run"]
    outside = asyncio.run(
        coding.execute("file_write", {"path": "../outside.txt", "content": "x"})
    )
    assert not outside.success
    network = asyncio.run(
        coding.execute(
            "code_run",
            {"type": "python", "script": "import requests; requests.get('x')"},
        )
    )
    assert not network.success


def test_subagent_runtime_uses_full_tool_loop_and_records_lineage(
    tmp_path: Path,
) -> None:
    source = ToolRegistry()
    source.register(TimeTool())
    profiles = default_subagent_profiles()
    trajectory = InMemoryTrajectoryStore()
    provider = ScriptedProvider(
        [
            LLMResponse("", [ToolCall("time", {})], provider="scripted"),
            LLMResponse(
                json.dumps(
                    {
                        "status": "completed",
                        "conclusion": "finished",
                        "evidence": [],
                        "artifacts": [],
                    }
                ),
                provider="scripted",
            ),
        ]
    )
    runtime = SubAgentRuntime(
        SubAgentRuntimeFactory(
            provider=provider,
            fallback_provider=None,
            tool_registry_factory=ProfileToolRegistryFactory(source, tmp_path),
            trajectory_store=trajectory,
        ),
        profiles,
    )
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    task = SubAgentTask(
        task_id="task-1",
        instruction="get time",
        profile_name="research",
        parent_session_key="session-a",
        task_dir=task_dir,
        agent_id="agent-1",
        parent_agent_id="main",
        attempt_id="attempt-1",
        trace_id="trace-1",
    )
    result = asyncio.run(runtime.run(task))
    assert result.success and result.content == "finished"
    assert "tool_intent_recorded" in [event.event_type for event in trajectory.events]
    root = next(
        span for span in trajectory.spans.values() if span.parent_span_id is None
    )
    assert root.attributes["agent_id"] == "agent-1"
    assert root.attributes["attempt_id"] == "attempt-1"


def test_memory_governor_uses_null_trajectory_store(tmp_path: Path) -> None:
    trajectory = InMemoryTrajectoryStore()
    hook_bus = HookBus(trajectory)
    tool_factory = ProfileToolRegistryFactory(
        ToolRegistry(), tmp_path, hook_bus=hook_bus
    )
    factory = SubAgentRuntimeFactory(
        provider=ScriptedProvider([]),
        fallback_provider=None,
        tool_registry_factory=tool_factory,
        trajectory_store=trajectory,
        hook_bus=hook_bus,
    )

    profiles = default_subagent_profiles()
    assert isinstance(
        factory.trajectory_store_for(profiles["memory-governor"]),
        NullTrajectoryStore,
    )
    assert factory.trajectory_store_for(profiles["research"]) is trajectory
    assert factory.hook_bus_for(profiles["memory-governor"]) is None
    assert factory.hook_bus_for(profiles["research"]) is hook_bus
    governor_registry = tool_factory.build(
        profiles["memory-governor"], tmp_path, inherit_hook_bus=False
    )
    research_registry = tool_factory.build(profiles["research"], tmp_path)
    assert governor_registry.hook_bus is None
    assert research_registry.hook_bus is hook_bus


def _main_snapshot(session_key: str) -> ContextSnapshot:
    """§7.6 主 Agent 会话的最小冻结快照（SubAgent 隔离测试的对照基线）。"""
    return ContextSnapshot(
        session_key=session_key,
        session_instance_id="main-instance",
        layout_version=1,
        system_prompt="main-system",
        skill_catalog="main-skills",
        tool_schemas_json="[]",
        system_prompt_hash="ms",
        skill_catalog_hash="mk",
        tool_schema_hash="mt",
        stable_prefix_hash="mp",
        created_at="now",
    )


def _main_archive(session_key: str) -> ContextArchive:
    """§7.6 主 Agent 会话的活动 frontier archive（隔离测试对照）。"""
    return ContextArchive(
        archive_id="main-arc",
        session_key=session_key,
        generation=1,
        content="main summary",
        content_hash="main-chash",
        source_refs=("source:main-1",),
        epoch=0,
        status="active",
    )


def test_subagent_does_not_read_or_modify_main_agent_context_state(
    tmp_path: Path,
) -> None:
    """§7.6/§7.5：普通 SubAgent 未装配 durable ContextSource，不读不改主 Agent
    的 conversation epoch、snapshot 或 archive frontier。

    SubAgentRuntimeFactory 不接受 context_repository（无 snapshot/frontier 句柄），
    且 SubAgent 全部 trajectory 写入在 ``subagent:`` 命名空间下；主 Agent 会话的
    epoch/snapshot/frontier 在 SubAgent 运行前后保持不变（design line 58/107）。
    """
    trajectory = InMemoryTrajectoryStore()
    # 主 Agent 会话 "c:1" 的派生状态：epoch=2、冻结快照、活动 frontier
    main_session = "c:1"
    assert trajectory.advance_epoch(main_session) == 2
    repo = InMemoryContextStateRepository()
    repo.save_snapshot(_main_snapshot(main_session))
    repo.append_archive(_main_archive(main_session))
    snapshot_before = repo.get_snapshot(main_session)
    frontier_before = repo.list_frontier(main_session)
    epoch_before = asyncio.run(trajectory.current_epoch(main_session))

    # 普通 SubAgent（research）共享 trajectory store；factory 不装配
    # context_source/context_repository（默认隔离，§7.5）
    source = ToolRegistry()
    source.register(TimeTool())
    profiles = default_subagent_profiles()
    provider = ScriptedProvider(
        [
            LLMResponse(
                json.dumps(
                    {
                        "status": "completed",
                        "conclusion": "done",
                        "evidence": [],
                        "artifacts": [],
                    }
                ),
                provider="scripted",
            )
        ]
    )
    runtime = SubAgentRuntime(
        SubAgentRuntimeFactory(
            provider=provider,
            fallback_provider=None,
            tool_registry_factory=ProfileToolRegistryFactory(source, tmp_path),
            trajectory_store=trajectory,
        ),
        profiles,
    )
    task_dir = tmp_path / "task-iso"
    task_dir.mkdir()
    task = SubAgentTask(
        task_id="task-iso",
        instruction="summarize",
        profile_name="research",
        parent_session_key=main_session,
        task_dir=task_dir,
        agent_id="agent-iso",
        parent_agent_id="main",
        attempt_id="attempt-iso",
        trace_id="trace-iso",
    )
    result = asyncio.run(runtime.run(task))
    assert result.success

    # 主 Agent 会话派生状态未被 SubAgent 触及（隔离）
    assert asyncio.run(trajectory.current_epoch(main_session)) == epoch_before
    assert repo.get_snapshot(main_session) == snapshot_before
    assert repo.list_frontier(main_session) == frontier_before
    # SubAgent 在自己的 ``subagent:`` 命名空间写轨迹，未污染主会话
    subagent_session = f"subagent:{task.agent_id}"
    trace = trajectory.traces.get(task.trace_id)
    assert trace is not None
    assert trace.session_id == subagent_session
    assert not any(
        trace.session_id == main_session for trace in trajectory.traces.values()
    )



async def _case_spawn_tool_compatibility_and_boundaries(tmp_path: Path) -> None:
    disabled = await SpawnSubAgentTool(None).run({"instruction": "x"})
    assert not disabled.success
    manager = _manager(tmp_path)
    await manager.start()
    tool = SpawnSubAgentTool(manager)
    empty = await tool.run({"instruction": "  "})
    assert not empty.success
    unknown = await tool.run({"instruction": "x", "profile": "missing"})
    assert not unknown.success
    context = ToolExecutionContext("parent-trace", "session-a", "call-1")
    with tool_context(context):
        result = await tool.run({"instruction": "sync", "profile": "research"})
    assert result.success
    assert result.metadata["task_id"].startswith("sub_")
    assert result.metadata["profile"] == "research"
    assert Path(str(result.metadata["task_dir"])).is_dir()
    with tool_context(context):
        background = await tool.run(
            {"instruction": "background", "profile": "research", "background": True}
        )
    assert background.success and background.metadata["background"]
    event = await asyncio.wait_for(manager.bus.consume_inbound(), 2)
    assert event.chat_id == "session-a"
    await manager.stop()


def test_spawn_tool_compatibility_and_boundaries(tmp_path: Path) -> None:
    asyncio.run(_case_spawn_tool_compatibility_and_boundaries(tmp_path))


async def _case_manager_sync_background_exports_artifacts_and_session_isolation(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    await manager.start()
    result = await manager.run_task("sync", "research", "session-a")
    persisted = manager.get_task(result.task_id, "session-a")
    assert persisted is not None and persisted.status is TaskStatus.COMPLETED
    assert persisted.agent_id and persisted.trace_id
    assert manager.repository.attempts(result.task_id)[0].trace_id == persisted.trace_id
    assert manager.repository.artifacts(result.task_id)[0].sha256
    task_json = json.loads((persisted.task_dir / "task.json").read_text("utf-8"))
    assert task_json["task_id"] == result.task_id
    assert "done:sync" in (persisted.task_dir / "result.md").read_text("utf-8")
    assert manager.get_task(result.task_id, "session-b") is None

    background_id = manager.spawn_background("background", "research", "session-a")
    event = await asyncio.wait_for(manager.bus.consume_inbound(), timeout=2)
    assert event.metadata["task_id"] == background_id
    assert event.metadata["agent_id"]
    assert event.metadata["status"] == "completed"
    await manager.stop()


async def _case_manager_dependency_depth_capacity_cancel_and_recovery(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime(delay=0.05)
    manager = _manager(tmp_path, runtime)
    await manager.start()
    first_id = manager.spawn_background("first", "research", "session-a")
    second_id = manager.spawn_background(
        "second",
        "research",
        "session-a",
        dependency_ids=(first_id,),
    )
    waiting = manager.get_task(second_id, "session-a")
    assert waiting is not None and waiting.status is TaskStatus.BLOCKED
    await asyncio.gather(
        asyncio.wait_for(manager.bus.consume_inbound(), 2),
        asyncio.wait_for(manager.bus.consume_inbound(), 2),
    )
    assert runtime.max_active == 1
    assert manager.get_task(first_id, "session-a") is not None
    second = manager.get_task(second_id, "session-a")
    assert second is not None and second.status is TaskStatus.COMPLETED
    assert second.context_package.dependency_results == ("done:first",)

    with pytest.raises(ValueError, match="深度"):
        manager.create_task(DelegationRequest(objective="deep", depth=2))
    assert len(manager.list_tasks()) == 2

    slow_id = manager.spawn_background("cancel", "research", "session-a")
    await asyncio.sleep(0)
    cancelled = await manager.cancel_task(slow_id, root_session_key="session-a")
    assert cancelled.status is TaskStatus.CANCELLED

    interrupted = _agent_task(tmp_path, "orphan", TaskStatus.RUNNING)
    manager.repository.create_task(interrupted)
    assert manager.repository.recover_interrupted() == ["orphan"]
    resumed = manager.resume_task("orphan", root_session_key="session-a")
    assert resumed.status is TaskStatus.RUNNABLE
    risky = replace(
        _agent_task(tmp_path, "risky", TaskStatus.RUNNING),
        side_effecting=True,
    )
    manager.repository.create_task(risky)
    manager.repository.recover_interrupted()
    with pytest.raises(ValueError, match="显式确认"):
        manager.resume_task("risky", root_session_key="session-a")
    assert (
        manager.resume_task(
            "risky", root_session_key="session-a", confirm_side_effects=True
        ).status
        is TaskStatus.RUNNABLE
    )
    for _ in range(40):
        orphan_poll = manager.get_task("orphan", "session-a")
        risky_poll = manager.get_task("risky", "session-a")
        if (
            orphan_poll is not None
            and orphan_poll.status is TaskStatus.COMPLETED
            and risky_poll is not None
            and risky_poll.status is TaskStatus.COMPLETED
        ):
            break
        await asyncio.sleep(0.05)
    orphan_done = manager.get_task("orphan", "session-a")
    risky_done = manager.get_task("risky", "session-a")
    assert orphan_done is not None and orphan_done.status is TaskStatus.COMPLETED
    assert risky_done is not None and risky_done.status is TaskStatus.COMPLETED
    assert len(manager.repository.attempts("orphan")) == 1
    assert len(manager.repository.attempts("risky")) == 1
    await manager.stop()


def test_manager_sync_background_exports_artifacts_and_session_isolation(
    tmp_path: Path,
) -> None:
    asyncio.run(
        _case_manager_sync_background_exports_artifacts_and_session_isolation(tmp_path)
    )


def test_manager_dependency_depth_capacity_cancel_and_recovery(
    tmp_path: Path,
) -> None:
    asyncio.run(_case_manager_dependency_depth_capacity_cancel_and_recovery(tmp_path))


def test_invalid_subagent_configuration_is_rejected() -> None:
    from memoli_agent.bootstrap.config import SubAgentConfig

    with pytest.raises(ValueError):
        SubAgentConfig(max_concurrent=0)
    with pytest.raises(ValueError):
        SubAgentConfig(max_depth=0)
    with pytest.raises(ValueError):
        SubAgentConfig(recovery_policy="replay")
