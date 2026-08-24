from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from memoli_agent.agent.context_management import (
    ConservativeTokenEstimator,
    ContextCompiler,
    ContextCompilerSettings,
    ContextStateError,
    InMemoryContextStateRepository,
    TaskAwareCompactor,
)
from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.core.results import TerminationReason, TurnResult
from memoli_agent.agent.llm.contracts import ModelCapabilities, ModelRequest
from memoli_agent.agent.provider import (
    LLMResponse,
    ProviderError,
    ResponseProtocolError,
    ToolCall,
)
from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import (
    InMemoryTrajectoryStore,
    NewTrajectoryEvent,
    SpanKind,
    SQLiteTrajectoryStore,
    TrajectoryError,
)
from memoli_agent.agent.types import ChatMessage


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


@dataclass
class ScriptedProvider:
    responses: list[LLMResponse]
    name: str = "scripted"
    calls: list[list[ChatMessage]] = field(default_factory=list)

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        if not self.responses:
            raise ProviderError("没有更多脚本响应")
        return self.responses.pop(0)


@dataclass
class FailingProvider:
    name: str = "failing"

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        raise ProviderError("provider failed")


def _archive_json(refs: list[str]) -> str:
    """构造通过 §5.4 校验的合法 archive（固定字段非空 + 给定 source_refs）。"""
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


@dataclass
class ValidArchiveProvider:
    """回填请求中 source_refs 的合法 archive，供 soft/hard 成功路径压缩。"""

    name: str = "valid-archive"
    received: list[list[ChatMessage]] = field(default_factory=list)

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.received.append(list(messages))
        payload = json.loads(messages[1].content)
        refs = payload["schema"]["source_refs"]
        return LLMResponse(_archive_json(refs), provider=self.name)

    async def aclose(self) -> None:
        return None


def _four_pair_messages() -> list[ChatMessage]:
    """4 个 ~100 字符 user/assistant 对，候选 token ≈ 403（available=430 时 hard）。"""
    messages = [ChatMessage("system", "security")]
    for index in range(4):
        messages.extend(
            [
                ChatMessage("user", f"old {index} " + "x" * 100),
                ChatMessage("assistant", "done " + "y" * 100),
            ]
        )
    return messages



@dataclass
class StreamProtocolProvider:
    name: str = "stream-protocol"
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    request_stream_values: list[bool] = field(default_factory=list)

    async def complete(
        self,
        request: ModelRequest,
        on_event: Any = None,
    ) -> LLMResponse:
        self.request_stream_values.append(request.stream)
        if request.stream:
            raise ResponseProtocolError(
                "invalid streamed tool arguments",
                provider=self.name,
                partial_stream=True,
            )
        return LLMResponse("recovered", provider=self.name)

    async def aclose(self) -> None:
        return None


@dataclass
class SlowToolProvider:
    name: str = "slow"
    calls: int = 0

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls += 1
        await asyncio.sleep(0.01)
        return LLMResponse("", [ToolCall("work", {})], provider=self.name)


@dataclass
class RecordingTool:
    name: str
    success: bool = True
    needs_user: bool = False
    calls: list[dict[str, Any]] = field(default_factory=list)
    description: str = "测试工具"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(arguments)
        return ToolResult(
            content=f"{self.name}-result",
            success=self.success,
            metadata={
                "error": None if self.success else "ExpectedFailure",
                "needs_user": self.needs_user,
            },
        )


@dataclass
class FailAfterStore(InMemoryTrajectoryStore):
    fail_at: int = 1

    async def record(self, item: NewTrajectoryEvent):  # type: ignore[no-untyped-def]
        if len(self.events) + 1 == self.fail_at:
            raise TrajectoryError("expected write failure")
        return await super().record(item)


class ConflictOnceRepository(InMemoryContextStateRepository):
    """§6.3：首次 ``commit_archive`` 注入 ``ContextStateError``（模拟并发 archive
    已提交撞 coverage/generation），其后正常委托。验证协调器把冲突作为 fresh
    re-compile 处理：不计熔断、无孤立 archive、本轮不再压缩。"""

    def __init__(self) -> None:
        super().__init__()
        self.conflicted: bool = False

    def commit_archive(  # type: ignore[no-untyped-def]
        self, archive, *, outbox=None, reset_failures=True
    ):
        if not self.conflicted:
            self.conflicted = True
            raise ContextStateError("injected concurrent coverage overlap")
        return super().commit_archive(
            archive, outbox=outbox, reset_failures=reset_failures
        )



def make_registry(*tools: RecordingTool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def test_two_tool_rounds_complete_and_preserve_model_context() -> None:
    first_tool = RecordingTool("first")
    second_tool = RecordingTool("second")
    provider = ScriptedProvider(
        [
            LLMResponse(
                "", [ToolCall("first", {"value": 1}, "call-1")], provider="scripted"
            ),
            LLMResponse(
                "", [ToolCall("second", {"value": 2}, "call-2")], provider="scripted"
            ),
            LLMResponse("最终完成", provider="scripted", usage={"total_tokens": 9}),
        ]
    )
    store = InMemoryTrajectoryStore()
    reasoner = Reasoner(
        provider,
        tool_registry=make_registry(first_tool, second_tool),
        trajectory_store=store,
    )

    result = run(reasoner.run_turn([ChatMessage("user", "执行任务")], session_key="s1"))

    assert result.termination_reason is TerminationReason.COMPLETED
    assert result.response.content == "最终完成"
    assert result.iterations == 3
    assert first_tool.calls == [{"value": 1}]
    assert second_tool.calls == [{"value": 2}]
    assert any(message.content == "first-result" for message in provider.calls[1])
    assert any(message.content == "second-result" for message in provider.calls[2])
    assert [event.event_type for event in store.events].count("model_requested") == 3
    assert store.events[-1].event_type == "trace_finished"


def test_two_tool_rounds_persist_complete_sqlite_hierarchy(tmp_path: Path) -> None:
    async def scenario() -> tuple[TurnResult, dict[str, Any]]:
        provider = ScriptedProvider(
            [
                LLMResponse("", [ToolCall("first", {}, "call-1")]),
                LLMResponse("", [ToolCall("second", {}, "call-2")]),
                LLMResponse("最终完成", usage={"total_tokens": 9}),
            ]
        )
        store = SQLiteTrajectoryStore(
            tmp_path / "trace.db",
            payload_directory=tmp_path / "payloads",
        )
        await store.start()
        result = await Reasoner(
            provider,
            tool_registry=make_registry(
                RecordingTool("first"), RecordingTool("second")
            ),
            trajectory_store=store,
        ).run_turn([ChatMessage("user", "执行任务")], session_key="sqlite-session")
        bundle = await store.get_trace(result.trace_id)
        await store.close()
        assert bundle is not None
        return result, bundle

    result, bundle = run(scenario())
    assert result.termination_reason is TerminationReason.COMPLETED
    events = bundle["events"]
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    event_types = [event["event_type"] for event in events]
    assert event_types.count("model_requested") == 3
    assert event_types.count("tool_intent_recorded") == 2
    assert event_types[-1] == "trace_finished"
    span_kinds = [span["kind"] for span in bundle["spans"]]
    assert span_kinds.count(SpanKind.LLM.value) == 3
    assert span_kinds.count(SpanKind.TOOL.value) == 2


def test_multiple_tools_execute_in_declared_order() -> None:
    order: list[str] = []

    @dataclass
    class OrderedTool(RecordingTool):
        async def run(self, arguments: dict[str, Any]) -> ToolResult:
            order.append(self.name)
            return await super().run(arguments)

    first = OrderedTool("first")
    second = OrderedTool("second")
    provider = ScriptedProvider(
        [
            LLMResponse(
                "",
                [ToolCall("first", {}), ToolCall("second", {})],
                provider="scripted",
            ),
            LLMResponse("完成", provider="scripted"),
        ]
    )
    reasoner = Reasoner(provider, tool_registry=make_registry(first, second))

    result = run(reasoner.run_turn([ChatMessage("user", "go")], session_key="s"))

    assert result.termination_reason is TerminationReason.COMPLETED
    assert order == ["first", "second"]


def test_missing_tool_call_ids_are_normalized_once() -> None:
    first = RecordingTool("first")
    second = RecordingTool("second")
    provider = ScriptedProvider(
        [
            LLMResponse(
                "",
                [ToolCall("first", {}), ToolCall("second", {})],
                provider="scripted",
            ),
            LLMResponse("完成", provider="scripted"),
        ]
    )
    store = InMemoryTrajectoryStore()
    result = run(
        Reasoner(
            provider,
            tool_registry=make_registry(first, second),
            trajectory_store=store,
        ).run_turn([ChatMessage("user", "go")], session_key="s")
    )

    assert result.termination_reason is TerminationReason.COMPLETED
    assistant = next(
        message for message in provider.calls[1] if message.role == "assistant"
    )
    tool_messages = [message for message in provider.calls[1] if message.role == "tool"]
    assistant_ids = [call["id"] for call in assistant.tool_calls or []]
    assert assistant_ids == ["call_1_0", "call_1_1"]
    assert [message.tool_call_id for message in tool_messages] == assistant_ids
    intent_payloads = [
        payload
        for event, payload in zip(store.events, store.event_payloads, strict=True)
        if event.event_type == "tool_intent_recorded"
    ]
    assert [payload["tool_call_id"] for payload in intent_payloads] == assistant_ids


def test_needs_user_and_provider_fallback_are_explicit() -> None:
    needs_user = RecordingTool("approval", needs_user=True)
    provider = ScriptedProvider(
        [LLMResponse("", [ToolCall("approval", {})], provider="scripted")]
    )
    result = run(
        Reasoner(provider, tool_registry=make_registry(needs_user)).run_turn(
            [ChatMessage("user", "go")], session_key="s"
        )
    )
    assert result.termination_reason is TerminationReason.NEEDS_USER

    fallback = ScriptedProvider([LLMResponse("fallback ok", provider="echo")])
    fallback_result = run(
        Reasoner(FailingProvider(), fallback_provider=fallback).run_turn(
            [ChatMessage("user", "hello")], session_key="s"
        )
    )
    assert fallback_result.termination_reason is TerminationReason.COMPLETED
    assert fallback_result.fallback_used is True
    assert fallback_result.response.provider == "echo"


def test_stream_protocol_error_recovers_once_with_non_stream_request() -> None:
    provider = StreamProtocolProvider()
    result = run(
        Reasoner(provider, stream_model=True).run_turn(
            [ChatMessage(role="user", content="remember this")],
            session_key="cli:local",
        )
    )

    assert result.termination_reason is TerminationReason.COMPLETED
    assert result.response.content == "recovered"
    assert provider.request_stream_values == [True, False]


def test_context_length_error_recompiles_once_without_repeating_tools() -> None:
    provider = ScriptedProvider(
        [
            LLMResponse(
                "too long",
                provider="scripted",
                error_type="provider-context-length",
            ),
            LLMResponse("recovered", provider="scripted"),
        ]
    )
    repository = InMemoryContextStateRepository()
    compiler = ContextCompiler(
        repository,
        ConservativeTokenEstimator(),
        ContextCompilerSettings(
            context_window_tokens=500,
            max_output_tokens=50,
            safety_margin_tokens=20,
            recent_tail_tokens=1_000,
            archive_tokens=60,
        ),
    )
    messages = [ChatMessage("system", "security")]
    for index in range(4):
        messages.extend(
            [
                ChatMessage("user", f"old {index} " + "x" * 100),
                ChatMessage("assistant", "done " + "y" * 100),
            ]
        )
    result = run(
        Reasoner(provider, context_compiler=compiler).run_turn(
            messages,
            session_key="s",
            session_instance_id="instance",
        )
    )
    assert result.termination_reason is TerminationReason.COMPLETED
    assert len(provider.calls) == 2
    assert provider.calls[0] != provider.calls[1]
    # §5.5：无 compactor 时 emergency 仅确定性 shed 重编译，不提交 archive。
    assert not repository.list_archives("s")


def test_model_trajectory_records_compilation_and_cache_usage() -> None:
    provider = ScriptedProvider(
        [
            LLMResponse(
                "done",
                provider="scripted",
                usage={"input_tokens": 20, "cached_input_tokens": 5},
            )
        ]
    )
    repository = InMemoryContextStateRepository()
    compiler = ContextCompiler(
        repository,
        ConservativeTokenEstimator(),
        ContextCompilerSettings(1_000, 50, 20),
    )
    store = InMemoryTrajectoryStore()
    result = run(
        Reasoner(provider, trajectory_store=store, context_compiler=compiler).run_turn(
            [ChatMessage("system", "security"), ChatMessage("user", "hello")],
            session_key="s",
        )
    )
    assert result.termination_reason is TerminationReason.COMPLETED
    payload = next(
        item
        for event, item in zip(store.events, store.event_payloads, strict=True)
        if event.event_type == "model_responded"
    )
    assert payload["context_compilation"]["layout_version"] == 1
    assert payload["cache_usage"]["cache_hit_ratio"] == 0.25


def test_required_context_over_budget_never_calls_provider() -> None:
    provider = ScriptedProvider([LLMResponse("must not run")])
    compiler = ContextCompiler(
        InMemoryContextStateRepository(),
        ConservativeTokenEstimator(),
        ContextCompilerSettings(100, 50, 20),
    )
    result = run(
        Reasoner(provider, context_compiler=compiler).run_turn(
            [
                ChatMessage("system", "security " + "s" * 100),
                ChatMessage("user", "required " + "u" * 100),
            ],
            session_key="s",
        )
    )
    assert result.error_type == "context-budget-exhausted"
    assert provider.calls == []


def test_open_compaction_circuit_prevents_emergency_retry() -> None:
    provider = ScriptedProvider(
        [LLMResponse("too long", error_type="provider-context-length")]
    )
    repository = InMemoryContextStateRepository()
    compiler = ContextCompiler(
        repository,
        ConservativeTokenEstimator(),
        ContextCompilerSettings(
            500, 50, 20, recent_tail_tokens=1_000, archive_tokens=60
        ),
    )
    compiler.record_compaction_failure("s")
    compiler.record_compaction_failure("s")
    messages = [ChatMessage("system", "security")]
    for index in range(4):
        messages.extend(
            [
                ChatMessage("user", f"old {index} " + "x" * 100),
                ChatMessage("assistant", "done " + "y" * 100),
            ]
        )
    result = run(
        Reasoner(provider, context_compiler=compiler).run_turn(
            messages, session_key="s"
        )
    )
    assert result.error_type == "provider-context-length"
    assert len(provider.calls) == 1


def test_failed_task_compactor_keeps_deterministic_emergency_recovery() -> None:
    primary = ScriptedProvider(
        [
            LLMResponse("too long", error_type="provider-context-length"),
            LLMResponse("recovered"),
        ]
    )
    compaction_provider = ScriptedProvider([LLMResponse("invalid-json")])
    repository = InMemoryContextStateRepository()
    compiler = ContextCompiler(
        repository,
        ConservativeTokenEstimator(),
        ContextCompilerSettings(
            500, 50, 20, recent_tail_tokens=1_000, archive_tokens=60
        ),
    )
    compactor = TaskAwareCompactor(
        compaction_provider,
        repository,
        ConservativeTokenEstimator(),
        100,
    )
    messages = [ChatMessage("system", "security")]
    for index in range(4):
        messages.extend(
            [
                ChatMessage("user", f"old {index} " + "x" * 100),
                ChatMessage("assistant", "done " + "y" * 100),
            ]
        )
    result = run(
        Reasoner(
            primary,
            context_compiler=compiler,
            task_compactor=compactor,
        ).run_turn(messages, session_key="s")
    )
    assert result.termination_reason is TerminationReason.COMPLETED
    assert repository.get_compaction_failures("s") == 1
    assert len(primary.calls) == 2


def test_soft_compaction_commits_archive_and_recompiles() -> None:
    """§5.2 soft：候选达 soft 阈值时主动压缩最旧未覆盖 turn 并在提交后重编译。"""
    primary = ScriptedProvider([LLMResponse("done", provider="scripted")])
    repository = InMemoryContextStateRepository()
    compiler = ContextCompiler(
        repository,
        ConservativeTokenEstimator(),
        ContextCompilerSettings(
            500, 50, 20, recent_tail_tokens=1_000, archive_tokens=1_000,
            hard_threshold_ratio=0.95,  # 399/430≈0.928 落 soft 区间
        ),
    )
    compactor = TaskAwareCompactor(
        ValidArchiveProvider(), repository, ConservativeTokenEstimator(), 1_000
    )
    result = run(
        Reasoner(
            primary, context_compiler=compiler, task_compactor=compactor
        ).run_turn(_four_pair_messages(), session_key="s")
    )
    assert result.termination_reason is TerminationReason.COMPLETED
    archives = repository.list_archives("s")
    assert len(archives) == 1
    # archive_tokens 较大时投影不提前收敛，soft 选全部可压缩 turn（3 个完整对）
    assert len(archives[0].source_refs) == 6
    assert repository.get_compaction_failures("s") == 0
    assert len(primary.calls) == 1


def test_soft_compaction_failure_keeps_view_and_records_failure() -> None:
    """§5.2/§5.6 soft 失败：保原可发送视图、计数失败、不提交 archive。"""
    primary = ScriptedProvider([LLMResponse("done", provider="scripted")])
    repository = InMemoryContextStateRepository()
    compiler = ContextCompiler(
        repository,
        ConservativeTokenEstimator(),
        ContextCompilerSettings(
            500, 50, 20, recent_tail_tokens=1_000, archive_tokens=1_000,
            hard_threshold_ratio=0.95,
        ),
    )
    compactor = TaskAwareCompactor(
        ScriptedProvider([LLMResponse("invalid-json")]),
        repository,
        ConservativeTokenEstimator(),
        1_000,
    )
    result = run(
        Reasoner(
            primary, context_compiler=compiler, task_compactor=compactor
        ).run_turn(_four_pair_messages(), session_key="s")
    )
    assert result.termination_reason is TerminationReason.COMPLETED
    assert not repository.list_archives("s")
    assert repository.get_compaction_failures("s") == 1
    assert len(primary.calls) == 1


def test_soft_compaction_conflict_fresh_recompiles_without_failure() -> None:
    """§6.3 冲突幂等：commit_archive 撞并发 coverage（ContextStateError）时，
    协调器 fresh re-compile——不计熔断失败、不留孤立 archive、本轮不再压缩
    （compacted_this_turn loop-guard）。冲突意味着 Provider 已产出合法 archive
    （仅提交撞并发），故视同成功路径清熔断。"""
    primary = ScriptedProvider([LLMResponse("done", provider="scripted")])
    repository = ConflictOnceRepository()
    compiler = ContextCompiler(
        repository,
        ConservativeTokenEstimator(),
        ContextCompilerSettings(
            500, 50, 20, recent_tail_tokens=1_000, archive_tokens=1_000,
            hard_threshold_ratio=0.95,  # 399/430≈0.928 落 soft 区间
        ),
    )
    compactor = TaskAwareCompactor(
        ValidArchiveProvider(), repository, ConservativeTokenEstimator(), 1_000
    )
    result = run(
        Reasoner(
            primary, context_compiler=compiler, task_compactor=compactor
        ).run_turn(_four_pair_messages(), session_key="s")
    )
    assert result.termination_reason is TerminationReason.COMPLETED
    # 冲突回滚：无 archive 提交（注入的冲突模拟并发 archive，本协调器未成功提交）
    assert not repository.list_archives("s")
    # 冲突非 Provider/校验故障，不计熔断（fresh re-compile 的有界重试）
    assert repository.get_compaction_failures("s") == 0
    assert repository.conflicted is True  # 确实走了冲突分支
    assert len(primary.calls) == 1  # 重编译后正常完成，不重试压缩


def test_hard_compaction_commits_archive_and_recompiles() -> None:
    """§5.6 hard：候选达 hard 阈值时压缩最旧未覆盖 turn 并重编译。"""
    primary = ScriptedProvider([LLMResponse("done", provider="scripted")])
    repository = InMemoryContextStateRepository()
    compiler = ContextCompiler(
        repository,
        ConservativeTokenEstimator(),
        ContextCompilerSettings(
            500, 50, 20, recent_tail_tokens=1_000, archive_tokens=1_000
        ),
    )
    compactor = TaskAwareCompactor(
        ValidArchiveProvider(), repository, ConservativeTokenEstimator(), 1_000
    )
    result = run(
        Reasoner(
            primary, context_compiler=compiler, task_compactor=compactor
        ).run_turn(_four_pair_messages(), session_key="s")
    )
    assert result.termination_reason is TerminationReason.COMPLETED
    archives = repository.list_archives("s")
    assert len(archives) == 1
    # archive_tokens 较大时投影不提前收敛，hard 选全部可压缩 turn（3 个完整对）
    assert len(archives[0].source_refs) == 6
    assert repository.get_compaction_failures("s") == 0
    assert len(primary.calls) == 1


def test_hard_reject_when_minimum_exceeds_budget_commits_no_archive() -> None:
    """§5.6 hard 拒绝：最小必需仍超限时显式失败，不压缩、不提交 archive。"""
    primary = ScriptedProvider([LLMResponse("must not run")])
    repository = InMemoryContextStateRepository()
    compiler = ContextCompiler(
        repository,
        ConservativeTokenEstimator(),
        ContextCompilerSettings(
            200, 50, 20, recent_tail_tokens=1_000, archive_tokens=60
        ),
    )
    compactor = TaskAwareCompactor(
        ValidArchiveProvider(), repository, ConservativeTokenEstimator(), 100
    )
    messages = [
        ChatMessage("system", "security"),
        ChatMessage("user", "required " + "u" * 400),
    ]
    result = run(
        Reasoner(
            primary, context_compiler=compiler, task_compactor=compactor
        ).run_turn(messages, session_key="s")
    )
    assert result.error_type == "context-budget-exhausted"
    assert primary.calls == []
    assert not repository.list_archives("s")
    assert repository.get_compaction_failures("s") == 0


def test_emergency_recovers_at_most_once_per_trace() -> None:
    """§5.7：同 trace 最多一次 emergency 恢复，第二次 context-length 不再重试。"""
    primary = ScriptedProvider(
        [
            LLMResponse(
                "too long",
                provider="scripted",
                error_type="provider-context-length",
            ),
            LLMResponse(
                "still too long",
                provider="scripted",
                error_type="provider-context-length",
            ),
        ]
    )
    compiler = ContextCompiler(
        InMemoryContextStateRepository(),
        ConservativeTokenEstimator(),
        ContextCompilerSettings(
            500, 50, 20, recent_tail_tokens=1_000, archive_tokens=60
        ),
    )
    result = run(
        Reasoner(primary, context_compiler=compiler).run_turn(
            _four_pair_messages(), session_key="s"
        )
    )
    assert result.termination_reason is TerminationReason.FAILED
    assert result.error_type == "provider-context-length"
    assert len(primary.calls) == 2


def test_context_length_recovery_does_not_repeat_committed_tool_side_effects() -> None:
    """§5.7：emergency 重试使用相同 trace 且不重复已提交的工具副作用。"""
    tool = RecordingTool("work")
    primary = ScriptedProvider(
        [
            LLMResponse("", [ToolCall("work", {})], provider="scripted"),
            LLMResponse(
                "too long",
                provider="scripted",
                error_type="provider-context-length",
            ),
            LLMResponse("recovered", provider="scripted"),
        ]
    )
    compiler = ContextCompiler(
        InMemoryContextStateRepository(),
        ConservativeTokenEstimator(),
        ContextCompilerSettings(
            500, 50, 20, recent_tail_tokens=1_000, archive_tokens=60
        ),
    )
    # 24 个小对使 call2 候选远超 available，normal 降到 (387,430]、emergency
    # 再降一层，保证 emergency 确实改善（不同 hash + 更少 token）以触发重试。
    messages = [ChatMessage("system", "security")]
    for index in range(24):
        messages.extend(
            [ChatMessage("user", f"u{index}"), ChatMessage("assistant", f"a{index}")]
        )
    messages.append(ChatMessage("user", "go"))
    result = run(
        Reasoner(
            primary,
            tool_registry=make_registry(tool),
            context_compiler=compiler,
        ).run_turn(messages, session_key="s")
    )
    assert result.termination_reason is TerminationReason.COMPLETED
    assert len(tool.calls) == 1  # 工具仅执行一次，emergency 重试不重复副作用
    assert len(primary.calls) == 3


def test_completion_retries_and_iteration_budget() -> None:
    provider = ScriptedProvider(
        [
            LLMResponse("", provider="scripted"),
            LLMResponse("被截断", provider="scripted", finish_reason="length"),
            LLMResponse("完整回复", provider="scripted"),
        ]
    )
    result = run(
        Reasoner(provider, max_iterations=3).run_turn(
            [ChatMessage("user", "hello")], session_key="s"
        )
    )
    assert result.termination_reason is TerminationReason.COMPLETED
    assert result.iterations == 3

    tool = RecordingTool("work")
    budget_provider = ScriptedProvider(
        [LLMResponse("", [ToolCall("work", {})], provider="scripted")]
    )
    exhausted = run(
        Reasoner(
            budget_provider,
            tool_registry=make_registry(tool),
            max_iterations=1,
        ).run_turn([ChatMessage("user", "go")], session_key="s")
    )
    assert exhausted.termination_reason is TerminationReason.BUDGET_EXHAUSTED
    assert exhausted.response.content == "任务未在迭代预算内完成。"


def test_repeated_failure_stops_with_no_progress() -> None:
    tool = RecordingTool("broken", success=False)
    provider = ScriptedProvider(
        [
            LLMResponse("", [ToolCall("broken", {"x": 2})], provider="scripted"),
            LLMResponse("", [ToolCall("broken", {"x": 1})], provider="scripted"),
        ]
    )
    result = run(
        Reasoner(
            provider,
            tool_registry=make_registry(tool),
            max_iterations=4,
            no_progress_limit=2,
        ).run_turn([ChatMessage("user", "go")], session_key="s")
    )
    assert result.termination_reason is TerminationReason.FAILED
    assert result.error_type == "no-progress"
    assert len(tool.calls) == 2


def test_partial_prepared_trace_identifiers_are_rejected() -> None:
    provider = ScriptedProvider([LLMResponse("完成")])
    with pytest.raises(ValueError, match="必须同时提供"):
        run(
            Reasoner(provider).run_turn(
                [ChatMessage("user", "go")],
                session_key="s",
                trace_id="0" * 32,
            )
        )


def test_trace_write_failure_prevents_tool_side_effect() -> None:
    tool = RecordingTool("side_effect")
    provider = ScriptedProvider(
        [LLMResponse("", [ToolCall("side_effect", {})], provider="scripted")]
    )
    store = FailAfterStore(fail_at=4)
    result = run(
        Reasoner(
            provider,
            tool_registry=make_registry(tool),
            trajectory_store=store,
        ).run_turn([ChatMessage("user", "go")], session_key="s")
    )
    assert result.termination_reason is TerminationReason.FAILED
    assert result.error_type == "trace-write-failed"
    assert tool.calls == []
    assert len(provider.calls) == 1


def test_elapsed_budget_stops_before_tool_execution() -> None:
    tool = RecordingTool("work")
    provider = SlowToolProvider()
    started = time.monotonic()
    result = run(
        Reasoner(
            provider,
            tool_registry=make_registry(tool),
            # 使用远小于一次事件循环调度的预算，避免 Windows 计时器粒度导致偶发失败。
            max_elapsed_seconds=1e-9,
        ).run_turn([ChatMessage("user", "go")], session_key="s")
    )
    assert time.monotonic() - started < 1
    assert result.termination_reason is TerminationReason.BUDGET_EXHAUSTED
    assert tool.calls == []
