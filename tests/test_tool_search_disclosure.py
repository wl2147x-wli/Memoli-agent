from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memoli_agent.agent.tools.base import ToolResult
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


def _schema_names(registry) -> list[str]:  # type: ignore[no-untyped-def]
    return [item["function"]["name"] for item in registry.get_schemas()]


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

    hidden = asyncio.run(registry.execute("a_weather", {}))
    assert hidden.success is False
    result = asyncio.run(registry.execute("tool_search", {"query": "weather"}))
    assert result.success is True
    assert result.metadata["disclosed"] == ["a_weather", "z_weather"]
    names = _schema_names(registry)
    assert names == sorted(names)
    assert {"a_weather", "z_weather"} <= set(names)

    repeated = asyncio.run(registry.execute("tool_search", {"query": "weather"}))
    assert repeated.metadata["disclosed"] == []
    assert _schema_names(registry) == names
