"""可替换的 GenericAgent 风格浏览器工具集。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.execution import WorkspacePathResolver, bound_text


class BrowserAdapter(Protocol):
    """浏览器后端只需实现两个稳定动作。"""

    async def scan(
        self, *, tabs_only: bool, switch_tab_id: str | None, text_only: bool
    ) -> dict[str, Any]: ...

    async def execute_js(
        self,
        script: str,
        *,
        switch_tab_id: str | None,
        no_monitor: bool,
    ) -> dict[str, Any]: ...


@dataclass(slots=True)
class WebScanTool:
    adapter: BrowserAdapter
    max_output_chars: int = 35_000
    name: str = "web_scan"
    description: str = (
        "获取简化页面内容和标签页列表；页面切换或操作后调用以重新感知页面。"
    )
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "tabs_only": {"type": "boolean", "default": False},
                "switch_tab_id": {"type": "string"},
                "text_only": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            result = await self.adapter.scan(
                tabs_only=bool(arguments.get("tabs_only", False)),
                switch_tab_id=_optional_text(arguments.get("switch_tab_id")),
                text_only=bool(arguments.get("text_only", False)),
            )
        except Exception as exc:
            return _browser_error(self.name, exc)
        raw = json.dumps(result, ensure_ascii=False)
        visible, truncated = bound_text(raw, self.max_output_chars)
        return ToolResult(
            visible,
            raw_content=raw,
            metadata={"tool": self.name, "truncated": truncated},
        )


@dataclass(slots=True)
class WebExecuteJSTool:
    adapter: BrowserAdapter
    workspace: Path
    max_output_chars: int = 8_000
    name: str = "web_execute_js"
    description: str = (
        "执行 JavaScript 精确读取或操作当前页面；不要猜测元素，"
        "长结果可保存到 workspace。"
    )
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "script": {"type": "string"},
                "save_to_file": {"type": "string"},
                "no_monitor": {"type": "boolean", "default": False},
                "switch_tab_id": {"type": "string"},
            },
            "required": ["script"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        script = arguments.get("script")
        if not isinstance(script, str) or not script:
            return _browser_error(self.name, ValueError("script 必须显式提供。"))
        try:
            result = await self.adapter.execute_js(
                script,
                switch_tab_id=_optional_text(arguments.get("switch_tab_id")),
                no_monitor=bool(arguments.get("no_monitor", False)),
            )
            raw = json.dumps(result, ensure_ascii=False)
            model_result = dict(result)
            save_to_file = _optional_text(arguments.get("save_to_file"))
            if save_to_file and isinstance(result.get("js_return"), str):
                target = WorkspacePathResolver(self.workspace).writable_file(
                    save_to_file
                )
                full_result = str(result["js_return"])
                target.write_text(full_result, encoding="utf-8", newline="")
                model_result["js_return"] = full_result[:170]
                model_result["saved_to"] = str(target)
            model_text = json.dumps(model_result, ensure_ascii=False)
        except Exception as exc:
            return _browser_error(self.name, exc)
        visible, truncated = bound_text(model_text, self.max_output_chars)
        return ToolResult(
            visible,
            raw_content=raw,
            metadata={"tool": self.name, "truncated": truncated},
        )


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _browser_error(tool: str, exc: Exception) -> ToolResult:
    raw = json.dumps(
        {"status": "error", "error": type(exc).__name__, "message": str(exc)},
        ensure_ascii=False,
    )
    return ToolResult(
        raw,
        success=False,
        raw_content=raw,
        status="error",
        metadata={"tool": tool, "error": type(exc).__name__},
    )
