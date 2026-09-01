from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memoli_agent.agent.context_management import (
    ConservativeTokenEstimator,
    ContextCompiler,
    ContextCompilerSettings,
)
from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.execution import ToolExecutionContext
from memoli_agent.agent.types import ChatMessage
from memoli_agent.bootstrap.config import AppConfig, RuntimeConfig, ToolsConfig
from memoli_agent.bootstrap.tools import build_tool_registry


@dataclass
class DeferredTool:
    name: str
    description: str = "MCP weather lookup"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult("sunny")


def _schema_names(registry, **kwargs: object) -> list[str]:  # type: ignore[no-untyped-def]
    return [item["function"]["name"] for item in registry.get_schemas(**kwargs)]


def test_disabled_search_preserves_complete_default_contract(tmp_path: Path) -> None:
    registry = build_tool_registry(
        AppConfig(runtime=RuntimeConfig(workspace=str(tmp_path)))
    )
    registry.register(DeferredTool("mcp_weather"))
    assert "mcp_weather" in _schema_names(registry)
    assert "tool_search" not in _schema_names(registry)


def test_enabled_search_freezes_base_and_discloses_deferred_schema(
    tmp_path: Path,
) -> None:
    registry = build_tool_registry(
        AppConfig(
            runtime=RuntimeConfig(workspace=str(tmp_path)),
            tools=ToolsConfig(tool_search_enabled=True),
        )
    )
    base = registry.get_schemas()
    registry.register(DeferredTool("z_weather"))
    registry.register(DeferredTool("a_weather"))
    assert registry.get_schemas() == base

    assert registry.disclosure_repository is not None
    compiler = ContextCompiler(
        registry.disclosure_repository,
        ConservativeTokenEstimator(),
        ContextCompilerSettings(32_000, 2_000, 1_000),
    )
    first = compiler.compile(
        session_key="session-a",
        session_instance_id="instance-a",
        messages=[ChatMessage("system", "system"), ChatMessage("user", "weather")],
        tools=base,
        epoch=3,
    )

    hidden = asyncio.run(registry.execute("a_weather", {}))
    assert hidden.success is False
    base_names = frozenset(_schema_names(registry))
    search_context = ToolExecutionContext(
        "trace-a",
        "session-a",
        "search-1",
        conversation_epoch=3,
        allowed_tool_names=base_names,
    )
    result = asyncio.run(
        registry.execute(
            "tool_search", {"query": "weather"}, context=search_context
        )
    )
    assert result.success is True
    assert result.metadata["disclosed"] == ["a_weather", "z_weather"]
    assert set(_schema_names(registry)) == set(base_names)
    names = _schema_names(
        registry, session_key="session-a", conversation_epoch=3
    )
    assert names[-2:] == ["a_weather", "z_weather"]
    restored = compiler.compile(
        session_key="session-a",
        session_instance_id="instance-a",
        messages=[ChatMessage("system", "system"), ChatMessage("user", "weather")],
        tools=base,
        epoch=3,
    )
    assert restored.stable_prefix_hash == first.stable_prefix_hash
    assert restored.tool_schema_hash != first.tool_schema_hash
    assert [item["function"]["name"] for item in restored.tools][-2:] == [
        "a_weather",
        "z_weather",
    ]
    assert _schema_names(
        registry, session_key="session-b", conversation_epoch=3
    ) == _schema_names(registry)

    repeated_context = ToolExecutionContext(
        "trace-a",
        "session-a",
        "search-2",
        conversation_epoch=3,
        allowed_tool_names=frozenset(names),
    )
    repeated = asyncio.run(
        registry.execute(
            "tool_search", {"query": "weather"}, context=repeated_context
        )
    )
    assert repeated.metadata["disclosed"] == []
    allowed = asyncio.run(
        registry.execute("a_weather", {}, context=repeated_context)
    )
    assert allowed.success is True
