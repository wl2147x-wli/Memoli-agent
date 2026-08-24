from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from memoli_agent.agent.plugins.events import (
    HookKind,
    HookName,
    ToolAfterEvent,
    ToolDecision,
)
from memoli_agent.agent.plugins.hooks import HookBus, HookRegistration
from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.execution import ToolExecutionContext
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import SQLiteTrajectoryStore
from memoli_agent.bootstrap.app import build_app_runtime
from memoli_agent.bootstrap.config import (
    AppConfig,
    LLMConfig,
    MemoryConfig,
    PluginsConfig,
    TrajectoryConfig,
    WorkingMemoryConfig,
)
from memoli_agent.bus.events import InboundMessage


@dataclass(frozen=True, slots=True)
class CaptureTool:
    name: str = "capture"
    description: str = "返回参数"
    parameters: dict[str, Any] = None  # type: ignore[assignment]

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(str(arguments["value"]))


def _hook(
    plugin_id: str,
    hook: HookName,
    kind: HookKind,
    callback: object,
    order: int = 0,
) -> HookRegistration:
    return HookRegistration(
        plugin_id,
        "1.0.0",
        "in_process",
        hook,
        kind,
        callback,  # type: ignore[arg-type]
        dependency_order=order,
        handler_name=f"{plugin_id}-{hook.value}",
    )


def test_tool_policy_rewrite_reaches_core_tool_and_after_observes() -> None:
    observed: list[ToolAfterEvent] = []
    bus = HookBus()
    bus.register(
        _hook(
            "rewrite",
            HookName.TOOL_BEFORE,
            HookKind.POLICY,
            lambda event: ToolDecision.rewrite({"value": "rewritten"}),
        )
    )
    bus.register(
        _hook(
            "observer",
            HookName.TOOL_AFTER,
            HookKind.OBSERVER,
            lambda event: observed.append(event),
        )
    )
    registry = ToolRegistry(hook_bus=bus)
    registry.register(CaptureTool(parameters={"type": "object"}))
    result = asyncio.run(
        registry.execute(
            "capture",
            {"value": "original"},
            context=ToolExecutionContext("", "session", "call"),
        )
    )
    assert result.content == "rewritten"
    assert result.metadata["executed_arguments"] == {"value": "rewritten"}
    assert observed[0].success is True


def test_policy_exception_denies_tool_and_tool_after_observes_rejection() -> None:
    observed: list[ToolAfterEvent] = []
    bus = HookBus()

    def fail(event: object) -> None:
        raise RuntimeError("boom")

    bus.register(_hook("fail", HookName.TOOL_BEFORE, HookKind.POLICY, fail))
    bus.register(
        _hook(
            "observer",
            HookName.TOOL_AFTER,
            HookKind.OBSERVER,
            lambda event: observed.append(event),
        )
    )
    registry = ToolRegistry(hook_bus=bus)
    registry.register(CaptureTool(parameters={"type": "object"}))
    result = asyncio.run(registry.execute("capture", {"value": "unsafe"}))
    assert result.success is False
    assert result.effective_status == "denied"
    assert observed[0].status == "denied"


def test_shared_tool_hook_reproduces_unknown_governor_trace_fk_failure(
    tmp_path: Path,
) -> None:
    async def scenario() -> tuple[bool, str, bool]:
        trajectory = SQLiteTrajectoryStore(
            tmp_path / "trajectory.db", payload_directory=tmp_path / "payloads"
        )
        await trajectory.start()
        try:
            bus = HookBus(trajectory)
            bus.register(
                _hook(
                    "shell_safety",
                    HookName.TOOL_BEFORE,
                    HookKind.POLICY,
                    lambda event: ToolDecision.allow(),
                )
            )
            shared = ToolRegistry(hook_bus=bus)
            shared.register(CaptureTool(parameters={"type": "object"}))
            failed = await shared.execute(
                "capture",
                {"value": "governor"},
                context=ToolExecutionContext(
                    "f" * 32, "subagent:memory-governor", "call-governor"
                ),
            )
            isolated = ToolRegistry(hook_bus=None)
            isolated.register(CaptureTool(parameters={"type": "object"}))
            succeeded = await isolated.execute(
                "capture",
                {"value": "governor"},
                context=ToolExecutionContext(
                    "f" * 32, "subagent:memory-governor", "call-isolated"
                ),
            )
            return failed.success, failed.content, succeeded.success
        finally:
            await trajectory.close()

    shared_success, error, isolated_success = asyncio.run(scenario())
    assert not shared_success
    assert "IntegrityError" in error
    assert isolated_success


def test_default_plugins_write_lifecycle_and_model_hooks_to_same_sqlite(
    tmp_path: Path,
) -> None:
    async def scenario() -> str:
        config = AppConfig(
            runtime=AppConfig().runtime,
            llm=LLMConfig(provider="echo", model="echo"),
            trajectory=TrajectoryConfig(
                database=str(tmp_path / "trace.db"),
                payload_directory=str(tmp_path / "payloads"),
            ),
            memory=MemoryConfig(enabled=False),
            working_memory=WorkingMemoryConfig(enabled=False),
            plugins=PluginsConfig(
                enabled=["memory_default", "shell_safety"],
                trusted=["memory_default", "shell_safety"],
                state_database=str(tmp_path / "plugin-state.db"),
            ),
        )
        config.runtime.workspace = str(tmp_path / "workspace")
        runtime = build_app_runtime(config)
        await runtime.start()
        outbound = await runtime.agent_loop.process(
            InboundMessage("cli", "local", "tester", "你好")
        )
        await runtime.shutdown()
        return str(outbound.metadata["trace_id"])

    trace_id = asyncio.run(scenario())
    connection = sqlite3.connect(tmp_path / "trace.db")
    event_types = {
        row[0]
        for row in connection.execute(
            "SELECT event_type FROM events WHERE trace_id=?", (trace_id,)
        )
    }
    runtime_events = {
        row[0]
        for row in connection.execute(
            "SELECT event_type FROM events WHERE event_type LIKE 'plugin_runtime_%' "
            "OR event_type LIKE 'plugin_backend_%'"
        )
    }
    connection.close()
    assert {
        "trace_started",
        "model_requested",
        "model_responded",
        "trace_finished",
    } <= event_types
    assert {"plugin_hook_started", "plugin_hook_completed"} <= event_types
    assert {"plugin_runtime_started", "plugin_runtime_stopped"} <= runtime_events
    assert (tmp_path / "plugin-state.db").is_file()
