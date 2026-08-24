"""§3.6 /clear、重启延续、epoch store 失败、并发 clear 与旧配置迁移测试。

覆盖 §3.3/§3.4 的清理边界：
- /clear 在活动 turn 期间被拒绝；
- /clear 成功后推进 conversation epoch 并重置派生 context 状态；
- 未装配持久 epoch 存储、或 advance_epoch 失败时保持旧 epoch；
- 连续 /clear 使 epoch 单调递增（并发 clear 由 SQLite BEGIN IMMEDIATE 串行化）；
- conversation epoch 持久于 trajectory store，重启（新实例）后保持。
旧配置迁移测试见 test_context_baseline_regressions.test_post_change_config_baseline。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memoli_agent.agent.context_management import (
    FrozenToolPreview,
    InMemoryContextStateRepository,
)
from memoli_agent.agent.session import SessionManager
from memoli_agent.agent.trajectory import (
    InMemoryTrajectoryStore,
    NewTrajectoryEvent,
    SQLiteTrajectoryStore,
)
from memoli_agent.channels.cli import CLIState
from memoli_agent.channels.commands import (
    CommandContext,
    CommandRegistry,
    build_command_registry,
)


@dataclass
class _BusyTurnController:
    """活动 turn 控制器替身：busy 恒为真，验证 /clear 在活动 turn 期间被拒绝。"""

    busy: bool = True
    queue_depth: int = 0

    def cancel_current_turn(self) -> bool:
        return False


class _FailingEpochStore:
    """advance_epoch 总是失败，验证 /clear 失败时保持旧 epoch（§3.3）。"""

    def advance_epoch(self, session_id: str) -> int:
        raise RuntimeError("epoch store unavailable")


def _clear_context(
    state: CLIState,
    manager: SessionManager,
    *,
    # stub（_BusyTurnController/_FailingEpochStore）只实现被测子集，不满足完整
    # protocol，故用 Any 透传给 CommandContext 的强类型字段（§3.6 测试替身约定）。
    trajectory_store: Any = None,
    turn_controller: Any = None,
    context_repository: Any = None,
) -> tuple[CommandRegistry, CommandContext]:
    registry = build_command_registry()
    ctx_cmd = CommandContext(
        state, None, manager, turn_controller, None, trajectory_store,
        context_repository,
    )
    return registry, ctx_cmd


def test_clear_rejected_during_active_turn() -> None:
    """§3.6：/clear 在活动 turn 期间不可用，且不推进 epoch。"""

    store = InMemoryTrajectoryStore()
    manager = SessionManager()
    state = CLIState("s")
    registry, ctx_cmd = _clear_context(
        state, manager, trajectory_store=store,
        turn_controller=_BusyTurnController(),
    )
    result = registry.route("/clear", ctx_cmd)
    assert result.handled
    assert "unavailable" in result.message
    assert "活动 turn" in result.message
    # 拒绝时未推进 epoch
    assert asyncio.run(store.current_epoch("cli:s")) == 1


def test_clear_without_trajectory_store_keeps_old_epoch() -> None:
    """§3.6：未装配持久 epoch 存储时 /clear 保持旧 epoch（不谎称已清理）。"""

    manager = SessionManager()
    session = manager.get_or_create("cli:s")
    session.conversation_epoch = 5
    state = CLIState("s")
    registry, ctx_cmd = _clear_context(state, manager, trajectory_store=None)
    result = registry.route("/clear", ctx_cmd)
    assert result.handled
    assert "未装配持久 epoch 存储" in result.message
    assert "未删除" in result.message
    assert manager.get_or_create("cli:s").conversation_epoch == 5


def test_clear_keeps_old_epoch_when_advance_fails() -> None:
    """§3.6：advance_epoch 抛错时 /clear 报失败并保持旧 epoch。"""

    store = _FailingEpochStore()
    manager = SessionManager()
    session = manager.get_or_create("cli:s")
    session.conversation_epoch = 5
    state = CLIState("s")
    registry, ctx_cmd = _clear_context(state, manager, trajectory_store=store)
    result = registry.route("/clear", ctx_cmd)
    assert result.handled
    assert "无法持久创建新 conversation epoch" in result.message
    assert "未删除" in result.message
    assert manager.get_or_create("cli:s").conversation_epoch == 5


def test_sequential_clears_advance_epoch_monotonically() -> None:
    """§3.6：连续 /clear 使 epoch 单调递增（并发 clear 由 SQLite 串行化）。"""

    store = InMemoryTrajectoryStore()
    manager = SessionManager()
    state = CLIState("s")
    registry, ctx_cmd = _clear_context(state, manager, trajectory_store=store)
    first = registry.route("/clear", ctx_cmd)
    second = registry.route("/clear", ctx_cmd)
    assert "已创建新 conversation epoch" in first.message
    assert "已创建新 conversation epoch" in second.message
    assert asyncio.run(store.current_epoch("cli:s")) == 3
    assert manager.get_or_create("cli:s").conversation_epoch == 3


def test_clear_epoch_survives_restart(tmp_path: Path) -> None:
    """§3.6：conversation epoch 持久于 trajectory store，重启后保持。"""

    db = tmp_path / "traj.db"
    payloads = tmp_path / "payloads"

    async def first() -> None:
        store = SQLiteTrajectoryStore(db, payload_directory=payloads)
        await store.start()
        assert store.advance_epoch("cli:s") == 2
        await store.close()

    asyncio.run(first())

    async def second() -> None:
        store = SQLiteTrajectoryStore(db, payload_directory=payloads)
        await store.start()
        # 重启（新实例）后 epoch 仍为推进后的值，未被重置或回退。
        assert await store.current_epoch("cli:s") == 2
        await store.close()

    asyncio.run(second())


def test_clear_marks_old_epoch_previews_invisible_not_deleted() -> None:
    """§7.4：/clear 把旧 epoch 的派生预览索引标记不可见，不删行，payload 保留。

    - /clear 推进 epoch（1→2）后，旧 epoch（1）预览经 get_preview_by_ref 不再返回；
    - 预览仍可按 id 取回（审计/可重建派生索引，未删行）；
    - 原始 trajectory payload 独立保留（/clear 不隐式删 payload，design line 91）。
    """

    store = InMemoryTrajectoryStore()
    repo = InMemoryContextStateRepository()
    manager = SessionManager()
    state = CLIState("s")
    session_key = state.session_key  # "cli:s"
    # 旧 epoch（1）冻结一个预览 + 记录一个 trajectory payload（受管事实）
    preview = FrozenToolPreview(
        "p1", session_key, "call", "tool", "hash", 99, 10, "x", "ref", epoch=1
    )
    repo.save_preview(preview)
    payload = {"content": "tool result payload"}
    asyncio.run(
        store.record(
            NewTrajectoryEvent(
                trace_id="t", event_type="tool_message_committed", payload=payload
            )
        )
    )
    assert len(store.events) == 1 and len(store.event_payloads) == 1
    # 直接构造 CommandContext（显式类型，不经 object 类型 helper）
    registry = build_command_registry()
    ctx_cmd = CommandContext(state, None, manager, None, None, store, repo)
    result = registry.route("/clear", ctx_cmd)
    assert result.handled
    assert "已创建新 conversation epoch" in result.message
    # epoch 推进到 2
    assert asyncio.run(store.current_epoch(session_key)) == 2
    # 旧 epoch 预览不可见 → ref 查不到（不注入新 epoch 上下文）
    assert repo.get_preview_by_ref(session_key, 1, "call") is None
    # 预览行未删：仍可按 id 取回（审计/可重建派生索引）
    assert repo.get_preview("p1") == preview
    # 原始 trajectory payload 独立保留（/clear 不隐式删 payload）
    assert store.events and store.event_payloads == [payload]


def test_current_epoch_sync_is_pure_read_in_memory() -> None:
    """§8.2：current_epoch_sync 是纯只读诊断，不初始化 epoch 1（与异步
    current_epoch 的「无记录写 1」区分）；/context 据此显示而不改写状态。"""

    store = InMemoryTrajectoryStore()
    # 全新 store：无 epoch 记录，同步读返回默认 1，但不写入 epochs。
    assert store.current_epoch_sync("cli:s") == 1
    assert store.epochs == {}  # 纯读：未像异步 current_epoch 那样初始化 epoch 1
    # advance_epoch 后同步读反映推进值。
    assert store.advance_epoch("cli:s") == 2
    assert store.current_epoch_sync("cli:s") == 2
    # 另一未触碰 session 同步读仍为 1，且不写入。
    assert store.current_epoch_sync("cli:other") == 1
    assert "cli:other" not in store.epochs


def test_current_epoch_sync_is_pure_read_sqlite(tmp_path: Path) -> None:
    """§8.2：SQLite current_epoch_sync 纯 SELECT，不 INSERT OR IGNORE epoch 1。"""

    db = tmp_path / "traj.db"
    payloads = tmp_path / "payloads"

    async def scenario() -> None:
        store = SQLiteTrajectoryStore(db, payload_directory=payloads)
        await store.start()
        try:
            # 全新 session：同步读返回 1，但不创建 session_epochs 行。
            assert store.current_epoch_sync("cli:s") == 1
            connection = store._require_connection()
            count = connection.execute(
                "SELECT COUNT(*) FROM session_epochs WHERE session_id=?",
                ("cli:s",),
            ).fetchone()
            assert int(count[0]) == 0  # 纯读：未插入 epoch 1
            # advance_epoch 后同步读反映推进值。
            assert store.advance_epoch("cli:s") == 2
            assert store.current_epoch_sync("cli:s") == 2
        finally:
            await store.close()

    asyncio.run(scenario())

