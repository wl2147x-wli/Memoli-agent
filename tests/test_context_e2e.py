from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memoli_agent.agent.context_management import (
    ConservativeTokenEstimator,
    ContextCompiler,
    ContextCompilerSettings,
    InMemoryContextStateRepository,
    SQLiteContextStateRepository,
    ToolResultPreviewer,
)
from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.provider import LLMResponse, ToolCall
from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import InMemoryTrajectoryStore
from memoli_agent.agent.types import ChatMessage


@dataclass
class LongProvider:
    rounds: int
    calls: list[list[ChatMessage]] = field(default_factory=list)

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.calls.append(list(messages))
        index = len(self.calls) - 1
        if index < self.rounds:
            return LLMResponse(
                "",
                [ToolCall("evidence", {"index": index}, f"call-{index}")],
            )
        return LLMResponse("verified complete")


@dataclass
class EvidenceTool:
    name: str = "evidence"
    description: str = "return long evidence"
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
        return ToolResult(
            content=f"verification={index}; TODO=preserve; " + "x" * 400,
            raw_content=f"decision={index}; constraint=no-delete; " + "x" * 2_000,
        )


def test_long_tool_loop_stays_bounded_and_never_repeats_side_effects() -> None:
    repository = InMemoryContextStateRepository()
    estimator = ConservativeTokenEstimator()
    compiler = ContextCompiler(
        repository,
        estimator,
        ContextCompilerSettings(
            context_window_tokens=4_000,
            max_output_tokens=100,
            safety_margin_tokens=100,
            recent_tail_tokens=500,
            archive_tokens=250,
        ),
    )
    registry = ToolRegistry()
    tool = EvidenceTool()
    registry.register(tool)
    provider = LongProvider(rounds=6)
    result = asyncio.run(
        Reasoner(
            provider,
            tool_registry=registry,
            trajectory_store=InMemoryTrajectoryStore(),
            context_compiler=compiler,
            tool_result_previewer=ToolResultPreviewer(repository, estimator, 80),
            max_iterations=8,
        ).run_turn(
            [
                ChatMessage("system", "Never delete evidence."),
                ChatMessage("user", "Complete report; verify it; keep TODO evidence."),
            ],
            session_key="long",
        )
    )
    assert result.response.content == "verified complete"
    assert tool.calls == list(range(6))
    for call in provider.calls:
        estimated = estimator.count_request(call, registry.get_schemas())
        assert estimated <= 3_800
        assert call[0].content == "Never delete evidence."


def test_context_rot_fixture_reduces_tokens_and_plans_compaction() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/context/context_rot.json").read_text(
            encoding="utf-8"
        )
    )
    messages = [ChatMessage("system", "security")]
    messages.extend(ChatMessage(**item) for item in fixture["turns"])
    messages = [
        ChatMessage(
            item.role,
            item.content + (" evidence-detail" * 30 if index < 4 else ""),
        )
        for index, item in enumerate(messages)
    ]
    estimator = ConservativeTokenEstimator()
    baseline = estimator.count_request(messages, [])
    repository = InMemoryContextStateRepository()
    compiler = ContextCompiler(
        repository,
        estimator,
        ContextCompilerSettings(
            context_window_tokens=650,
            max_output_tokens=50,
            safety_margin_tokens=20,
            recent_tail_tokens=60,
            archive_tokens=300,
        ),
    )
    compiled = compiler.compile(
        session_key="rot",
        session_instance_id="i",
        messages=messages,
        tools=[],
        emergency=True,
    )
    # §5.1/§5.5：emergency compile 确定性 shed 降载并产出 compaction_plan（最旧
    # 未覆盖完整 turn 批次），不提交 archive；archive 固定字段保存由异步协调器
    # execute/commit 阶段保证（见 test_context_compaction）。
    assert compiled.budget.estimated_input_tokens < baseline
    assert compiled.compaction_plan is not None
    assert compiled.compaction_plan.mode == "emergency"
    assert compiled.compaction_plan.batch
    assert not repository.list_archives("rot")


def test_mixed_language_large_schema_dynamic_tail_and_restart(tmp_path: Path) -> None:
    database = tmp_path / "context.db"
    repository = SQLiteContextStateRepository(database)
    estimator = ConservativeTokenEstimator()
    settings = ContextCompilerSettings(3_000, 100, 100)
    compiler = ContextCompiler(repository, estimator, settings)
    schema = {
        "type": "function",
        "function": {
            "name": "search_records",
            "description": "检索 records and verify evidence",
            "parameters": {
                "type": "object",
                "properties": {
                    f"field_{index}": {
                        "type": "string",
                        "description": "中文 English JSON field",
                    }
                    for index in range(40)
                },
            },
        },
    }
    first = compiler.compile(
        session_key="mixed",
        session_instance_id="i",
        messages=[
            ChatMessage("system", "安全规则 security"),
            ChatMessage("user", "分析 mixed 中英文 context"),
            ChatMessage(
                "system", '<memory_context trust="data">旧记忆</memory_context>'
            ),
            ChatMessage("system", '<agent_status revision="1">one</agent_status>'),
        ],
        tools=[schema],
    )
    second = compiler.compile(
        session_key="mixed",
        session_instance_id="i",
        messages=[
            ChatMessage("system", "安全规则 security"),
            ChatMessage("user", "分析 mixed 中英文 context"),
            ChatMessage(
                "system", '<memory_context trust="data">新记忆</memory_context>'
            ),
            ChatMessage("system", '<agent_status revision="2">two</agent_status>'),
        ],
        tools=[schema],
    )
    assert first.stable_prefix_hash == second.stable_prefix_hash
    assert first.tool_schema_hash == second.tool_schema_hash
    assert first.context_hash != second.context_hash
    repository.close()

    reopened = SQLiteContextStateRepository(database)
    restored = ContextCompiler(reopened, estimator, settings).compile(
        session_key="mixed",
        session_instance_id="new-process",
        messages=[
            ChatMessage("system", "changed system must remain frozen"),
            ChatMessage("user", "continue"),
        ],
        tools=[schema],
    )
    assert restored.capability_revision == first.capability_revision + 1
    assert restored.stable_prefix_hash != first.stable_prefix_hash
    assert restored.tool_schema_hash == first.tool_schema_hash
    reopened.close()
