"""工具搜索和按需解锁模块。

第六阶段只做最小关键词搜索，不做 deferred tool 解锁。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from memoli_agent.agent.context_management.models import ToolDisclosure
from memoli_agent.agent.tools.base import Tool, ToolResult
from memoli_agent.agent.tools.execution import current_tool_context
from memoli_agent.agent.tools.registry import ToolRegistry


@dataclass(frozen=True, slots=True)
class ToolSearch:
    """按关键词搜索已注册工具。"""

    registry: ToolRegistry

    def search(self, query: str) -> list[Tool]:
        """根据工具名和描述进行简单匹配。"""

        keyword = query.strip().lower()
        if not keyword:
            return self.registry.list_tools()

        return [
            tool
            for tool in self.registry.list_tools()
            if keyword in tool.name.lower() or keyword in tool.description.lower()
        ]


@dataclass(frozen=True, slots=True)
class ToolSearchTool:
    """Model-facing deterministic entry point for deferred tool schemas."""

    registry: ToolRegistry
    limit: int = 8
    name: str = "tool_search"
    description: str = "按关键词搜索并披露当前会话尚未加载的插件或 MCP 工具。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "描述当前缺少的能力或工具关键词。",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or "").strip()
        context = current_tool_context()
        repository = self.registry.disclosure_repository
        if context is None or not context.session_key or repository is None:
            return ToolResult(
                json.dumps(
                    {
                        "status": "error",
                        "error": "ToolDisclosureContextUnavailable",
                    },
                    ensure_ascii=False,
                ),
                success=False,
                status="error",
                metadata={"error": "ToolDisclosureContextUnavailable"},
            )
        selected = self.registry.search_deferred(
            query,
            limit=self.limit,
            exclude=context.allowed_tool_names,
        )
        disclosed_schemas: list[dict[str, Any]] = []
        disclosed_names: list[str] = []
        for tool in selected:
            schema = self.registry.schema_for(tool)
            schema_json = json.dumps(
                schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            disclosure = repository.save_tool_disclosure(
                ToolDisclosure(
                    session_key=context.session_key,
                    conversation_epoch=context.conversation_epoch,
                    tool_name=tool.name,
                    schema_json=schema_json,
                    schema_hash=hashlib.sha256(schema_json.encode()).hexdigest(),
                    tool_call_id=context.tool_call_id,
                    created_at=datetime.now(UTC).isoformat(),
                )
            )
            disclosed_schemas.append(json.loads(disclosure.schema_json))
            disclosed_names.append(disclosure.tool_name)
        payload = {
            "status": "success",
            "query": query,
            "disclosed": disclosed_names,
            "disclosed_tools": disclosed_schemas,
        }
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return ToolResult(
            content=content,
            raw_content=content,
            metadata={
                "query": query,
                "disclosed": disclosed_names,
            },
        )
