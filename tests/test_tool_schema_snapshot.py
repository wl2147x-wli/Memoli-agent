from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.registry import ToolRegistry


@dataclass
class SchemaTool:
    name: str
    description: str = "test"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult("ok")


def test_schema_order_is_stable_without_changing_registry_compatibility() -> None:
    first = ToolRegistry()
    second = ToolRegistry()
    for name in ("plugin_z", "mcp_a", "builtin_m"):
        first.register(SchemaTool(name))
    for name in ("builtin_m", "plugin_z", "mcp_a"):
        second.register(SchemaTool(name))

    assert [tool.name for tool in first.list_tools()] == [
        "plugin_z",
        "mcp_a",
        "builtin_m",
    ]
    assert first.get_schemas() == second.get_schemas()
    assert [item["function"]["name"] for item in first.get_schemas()] == [
        "builtin_m",
        "mcp_a",
        "plugin_z",
    ]


def test_schema_snapshot_is_independent_of_nested_mapping_insertion_order() -> None:
    first = ToolRegistry()
    second = ToolRegistry()
    first.register(
        SchemaTool(
            "read",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "p"}},
            },
        )
    )
    second.register(
        SchemaTool(
            "read",
            parameters={
                "properties": {"path": {"description": "p", "type": "string"}},
                "type": "object",
            },
        )
    )
    # The compiler's canonical JSON uses sort_keys=True, so semantically equal nested
    # mappings produce the same byte-level snapshot even if dict insertion differs.
    import json

    def canonical(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    assert canonical(first.get_schemas()) == canonical(second.get_schemas())
