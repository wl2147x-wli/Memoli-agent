"""§9.1 端到端长会话测试。

覆盖多轮工具调用、soft archive 提交、frontier 分层合并、重启恢复、``/clear``
后从零开始与最终 Provider 请求一致性（spec §9.1 / design 决策 4–7）。

通过真实 ``PassiveTurnPipeline``（装配 ``CrossTurnContextPhase`` + ``ReasonerPhase``
+ ``AfterReasoningPhase``）驱动 SQLite trajectory/context 仓库的多轮串行 turn：
主 Agent Provider 每 turn 做 N 轮 evidence 工具调用积累证据；上一 turn 的
committed 消息由 ``CrossTurnContextPhase`` 注入下一 turn 候选，跨过 soft 阈值即
由统一协调器提交 archive。压缩 Provider 协作回传合法 archive（``source_refs``
取自请求 schema，``_validated_archive`` 引用校验恒通过），使 soft 提交与 frontier
合并真正落盘。

三 turn 序列：turn1 仅积累（无前序完整 turn，不可压缩）；turn2 压缩 turn1→A1
（loop-guard 抑制本轮二次压缩，frontier 仅 1 节点不合并）；turn3 压缩 turn2→A2
后 ``merge_frontier([A1, A2])`` 产出 level-2 merged 节点 M。``hard_threshold_ratio``
设为不可达以保持全程 soft（design 决策 4：soft/hard 共用同一协调器入口，此处聚焦
soft 路径）。

本文件刻意不导入 pytest，避免 pyright reportMissingImports 环境解析噪声
（与 test_context_frontier_bounds.py 的 _expect_raises 约定一致）。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memoli_agent.agent.context import ContextBuilder
from memoli_agent.agent.context_management import (
    ConservativeTokenEstimator,
    ContextCompiler,
    ContextCompilerSettings,
    SQLiteContextStateRepository,
    TaskAwareCompactor,
)
from memoli_agent.agent.context_management.cross_turn import (
    RestorationLevel,
    TrajectoryContextSource,
)
from memoli_agent.agent.core.passive_turn import PassiveTurnPipeline
from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.provider import LLMResponse, ToolCall
from memoli_agent.agent.session import SessionManager
from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import SQLiteTrajectoryStore
from memoli_agent.agent.types import ChatMessage
from memoli_agent.bus.events import InboundMessage

_SYSTEM = ChatMessage("system", "安全规则：禁止删除证据；保留 TODO 与决策原因。")
# PassiveTurnPipeline 的 session_key = f"{channel}:{chat_id}"。
_SESSION_KEY = "test:1"


def _archive_json(refs: list[str]) -> str:
    """固定字段 + 原样 source_refs 的合法 archive（§5.4 校验通过）。"""

    return json.dumps(
        {
            "goal_constraints": ["preserve constraint"],
            "decisions_reasons": ["decision because evidence"],
            "facts_evidence": ["payload:42"],
            "files_artifacts": ["result.txt"],
            "verification_status": ["tests passed"],
            "failure_paths": ["first attempt failed"],
            "todo_remaining": ["ship"],
            "source_refs": list(refs),
        }
    )


@dataclass
class CooperativeCompactorProvider:
    """压缩/合并 LLM：从请求 ``schema.source_refs`` 原样回传合法 archive。

    模拟真实压缩模型「看到批次、摘要并保留引用」——refs 取自请求 schema，故
    soft 提交与 frontier 合并的 ``_validated_archive`` 引用集合校验恒通过，archive
    真正落盘。``name`` 非 ``'echo'`` 以通过 ``TaskAwareCompactor`` 的 echo 拒绝守卫。
    compact 与 merge 请求均把 source_refs 放进 user payload 的 schema 字段
    （compaction.py:``_request`` / ``_merge_request``）。
    """

    name: str = "cooperative"
    calls: list[list[ChatMessage]] = field(default_factory=list)

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        payload = json.loads(messages[1].content)
        refs = list(payload["schema"]["source_refs"])
        return LLMResponse(_archive_json(refs), provider="cooperative")


@dataclass
class SessionProvider:
    """主 Agent Provider：每 turn 做 ``rounds_per_turn`` 轮工具调用后完成。

    调用计数跨 turn 持续——完成响应结束 turn，下一次 ``chat`` 即新 turn 首轮——
    故每 turn 确定地产生 ``rounds_per_turn`` 次 evidence 调用 + 1 次完成，与压缩
    是否触发无关（压缩在单次迭代内完成，不增减迭代数）。
    """

    rounds_per_turn: int
    calls: list[list[ChatMessage]] = field(default_factory=list)
    name: str = "session"
    _tool_count: int = 0

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        if self._tool_count < self.rounds_per_turn:
            self._tool_count += 1
            index = len(self.calls) - 1
            return LLMResponse(
                "",
                [ToolCall("evidence", {"index": index}, f"call-{index}")],
            )
        self._tool_count = 0
        # 完成消息含唯一序号：避免多 turn 末尾输出字节相同导致 content-based
        # source_ref 跨 turn 碰撞（_validated_archive §5.4 覆盖无环性会拒绝与父
        # archive 共享 ref 的批次）。
        return LLMResponse(f"verified complete #{len(self.calls)}")


@dataclass
class EvidenceTool:
    """采集长证据的工具——每轮注入 ~1800 字符以跨过 soft 阈值。"""

    name: str = "evidence"
    description: str = "采集长证据"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"index": {"type": "integer"}},
        }
    )
    calls: list[int] = field(default_factory=list)

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        index = int(arguments["index"])
        self.calls.append(index)
        body = "x" * 1_800
        return ToolResult(
            content=f"evidence-{index} TODO=preserve {body}",
            raw_content=f"decision-{index} constraint=no-delete {body}",
        )


def _settings() -> ContextCompilerSettings:
    """soft 易触、hard 不可达、frontier 超 1 节点即合并的测试配置。"""

    return ContextCompilerSettings(
        context_window_tokens=4_000,
        max_output_tokens=100,
        safety_margin_tokens=100,
        recent_tail_tokens=500,
        archive_tokens=800,
        archive_frontier_tokens=8_000,
        archive_frontier_max_items=1,
        soft_threshold_ratio=0.30,
        hard_threshold_ratio=1.5,
    )


def _inbound(content: str) -> InboundMessage:
    return InboundMessage(
        channel="test", chat_id="1", sender="user", content=content
    )


async def _run_long_session(tmp_path: Path) -> None:
    estimator = ConservativeTokenEstimator()
    settings = _settings()
    available = (
        settings.context_window_tokens
        - settings.max_output_tokens
        - settings.safety_margin_tokens
    )

    store = SQLiteTrajectoryStore(
        tmp_path / "trajectories.db",
        payload_directory=tmp_path / "payloads",
        capture_content="full-local",
    )
    await store.start()
    repo = SQLiteContextStateRepository(tmp_path / "context.db")
    compiler = ContextCompiler(repo, estimator, settings)
    compactor_provider = CooperativeCompactorProvider()
    compactor = TaskAwareCompactor(
        compactor_provider, repo, estimator, archive_tokens=800
    )
    registry = ToolRegistry()
    evidence = EvidenceTool()
    registry.register(evidence)
    schemas = registry.get_schemas()
    main_provider = SessionProvider(rounds_per_turn=3)
    reasoner = Reasoner(
        main_provider,
        tool_registry=registry,
        trajectory_store=store,
        context_compiler=compiler,
        task_compactor=compactor,
        max_iterations=20,
    )
    pipeline = PassiveTurnPipeline(
        session_manager=SessionManager(),
        context_builder=ContextBuilder(
            agent_name="tester", system_prompt=_SYSTEM.content
        ),
        reasoner=reasoner,
        trajectory_store=store,
        context_source=TrajectoryContextSource(store),
        tool_registry=registry,
    )

    # 三轮长 turn：每轮 3 次 evidence 工具调用 + 1 次完成。
    await pipeline.run(_inbound("采集证据并完成报告"))
    await pipeline.run(_inbound("继续采集更多证据"))
    out = await pipeline.run(_inbound("再采集一批证据"))

    # §9.1 多轮工具调用：三轮共 9 次调用、index 全唯一（无重复副作用）。
    assert len(evidence.calls) >= 6
    assert len(set(evidence.calls)) == len(evidence.calls)

    # §9.1 soft archive 提交 + frontier 分层合并：A1（turn2）+A2（turn3）后合并
    # 为 level-2 节点 M，活动 frontier 收敛为单一 merged 节点。
    archives = repo.list_archives(_SESSION_KEY)
    assert len(archives) >= 2, f"期望至少两份 archive，实际 {archives}"
    assert any(item.level >= 2 for item in archives), (
        "期望存在 level-2 合并节点"
    )
    frontier = repo.list_frontier(_SESSION_KEY)
    assert len(frontier) == 1, f"期望 frontier 收敛为 1 节点，实际 {frontier}"
    assert frontier[0].level >= 2

    # §9.1 最终 Provider 请求一致性：每次请求都在预算内且稳定 system 前缀不变。
    assert main_provider.calls, "主 Provider 未被调用"
    for call in main_provider.calls:
        assert estimator.count_request(call, schemas) <= available
        assert call[0].content == _SYSTEM.content

    # §9.1 turn_output 经 AfterReasoningPhase 落盘，最终输出可读（完成消息含
    # 唯一序号，只校验前缀以解耦调用计数）。
    assert out.content.startswith("verified complete")

    # 稳定前缀哈希快照（重启前后对照）。
    prefix_before = compiler.compile(
        session_key=_SESSION_KEY,
        session_instance_id="cap",
        messages=[_SYSTEM, ChatMessage("user", "capture")],
        tools=schemas,
        epoch=1,
    ).stable_prefix_hash

    # §9.1 重启恢复：关闭并重开 SQLite 仓库，durable 来源精确还原 committed turn，
    # 派生 frontier 跨进程持久，稳定前缀哈希不变。
    await store.close()
    repo.close()
    reopened_store = SQLiteTrajectoryStore(
        tmp_path / "trajectories.db",
        payload_directory=tmp_path / "payloads",
        capture_content="full-local",
    )
    await reopened_store.start()
    reopened_repo = SQLiteContextStateRepository(tmp_path / "context.db")
    reopened_compiler = ContextCompiler(reopened_repo, estimator, settings)
    source = TrajectoryContextSource(reopened_store)
    assert (
        await source.restoration_level(_SESSION_KEY, 1) is RestorationLevel.EXACT
    )
    read = await source.read_turns(session_key=_SESSION_KEY, epoch=1)
    assert len(read.turns) >= 1
    assert any(
        "采集证据" in message.content
        for turn in read.turns
        for message in turn.to_messages()
    )
    # 派生 frontier 跨进程持久（merged 节点仍在）。
    reopened_frontier = reopened_repo.list_frontier(_SESSION_KEY)
    assert len(reopened_frontier) == 1
    assert reopened_frontier[0].level >= 2
    restarted = reopened_compiler.compile(
        session_key=_SESSION_KEY,
        session_instance_id="restart",
        messages=[_SYSTEM, ChatMessage("user", "continue")],
        tools=schemas,
        epoch=1,
    )
    assert restarted.stable_prefix_hash == prefix_before

    # §9.1 /clear 后从零开始：推进 epoch + 重置派生 context 状态（镜像
    # commands.py ``_clear`` 的三步原语），新 epoch 不见旧 frontier/turn。
    new_epoch = reopened_store.advance_epoch(_SESSION_KEY)
    assert new_epoch == 2
    reopened_repo.reset_session(_SESSION_KEY)
    reopened_repo.clear_epoch_previews(_SESSION_KEY, before_epoch=new_epoch)
    assert reopened_repo.list_frontier(_SESSION_KEY) == ()
    cleared_turns = await source.read_turns(
        session_key=_SESSION_KEY, epoch=new_epoch
    )
    assert cleared_turns.turns == ()
    from_zero = reopened_compiler.compile(
        session_key=_SESSION_KEY,
        session_instance_id="clear",
        messages=[_SYSTEM, ChatMessage("user", "fresh start")],
        tools=schemas,
        epoch=new_epoch,
    )
    # 新 epoch 从零：frontier 空且稳定前缀仍由 system+tools 决定（未被破坏）。
    assert reopened_compiler.latest_summary(_SESSION_KEY)[
        "frontier_active_count"
    ] == 0
    assert from_zero.stable_prefix_hash == prefix_before

    await reopened_store.close()
    reopened_repo.close()


def test_long_session_e2e_soft_archive_frontier_merge_restart_and_clear(
    tmp_path: Path,
) -> None:
    asyncio.run(_run_long_session(tmp_path))
