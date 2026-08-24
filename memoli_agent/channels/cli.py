"""Memoli CLI 通道装配；交互语义由共享 controller 统一。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress

from memoli_agent.agent.context_management import ContextStateRepository
from memoli_agent.agent.memory.governance import MemoryGovernanceService
from memoli_agent.agent.session import SessionManager
from memoli_agent.agent.trajectory import TrajectoryStore
from memoli_agent.bootstrap.config import CLIChannelConfig
from memoli_agent.bootstrap.inspection import RuntimeInspector
from memoli_agent.bus.queue import MessageBus
from memoli_agent.channels.adapters import CLIAdapter, PlainCLIAdapter
from memoli_agent.channels.capabilities import (
    detect_terminal_capabilities,
    initialize_utf8_terminal,
)
from memoli_agent.channels.commands import TurnController
from memoli_agent.channels.controller import CLIController, CLIState, InputOutcome
from memoli_agent.channels.interactive import InteractiveCLIAdapter
from memoli_agent.presentation.events import PresentationEventHub
from memoli_agent.presentation.renderer import TerminalRenderer


async def run_cli(
    bus: MessageBus,
    *,
    chat_id: str = "local",
    inspector: RuntimeInspector | None = None,
    session_manager: SessionManager | None = None,
    presentation_events: PresentationEventHub | None = None,
    turn_controller: TurnController | None = None,
    cli_config: CLIChannelConfig | None = None,
    input_reader: Callable[[str], str] = input,
    writer: Callable[..., None] = print,
    memory_governance: MemoryGovernanceService | None = None,
    trajectory_store: TrajectoryStore | None = None,
    context_repository: ContextStateRepository | None = None,
) -> None:
    """选择一次终端 adapter，再运行唯一 controller/renderer 生命周期。"""

    initialize_utf8_terminal()
    config = cli_config or CLIChannelConfig(interactive=False)
    controller = CLIController(
        bus,
        chat_id=chat_id,
        inspector=inspector,
        session_manager=session_manager,
        turn_controller=turn_controller,
        queue_limit=config.queue_limit,
        memory_governance=memory_governance,
        trajectory_store=trajectory_store,
        context_repository=context_repository,
    )
    adapter, color, diagnostic = _select_adapter(
        controller,
        config,
        input_reader,
        writer,
    )
    try:
        await adapter.start()
    except (ImportError, OSError, RuntimeError) as exc:
        with suppress(Exception):
            await adapter.close()
        diagnostic = _fallback_diagnostic(exc)
        adapter = PlainCLIAdapter(input_reader, writer)
        color = False
        await adapter.start()

    renderer = TerminalRenderer(
        controller.state.session_key,
        adapter.write,
        refresh_hz=config.refresh_hz,
        max_tool_rows=config.max_tool_rows,
        color=color,
        markdown=isinstance(adapter, InteractiveCLIAdapter),
    )
    await renderer.start()
    if diagnostic:
        renderer.notice(diagnostic)
    renderer.notice(controller.startup_info())

    output_task = asyncio.create_task(
        _consume_outbound(bus, controller, renderer),
        name="cli_output",
    )
    event_task = (
        asyncio.create_task(
            _consume_presentation(presentation_events, renderer),
            name="cli_presentation",
        )
        if presentation_events is not None
        else None
    )
    try:
        await _input_loop(adapter, controller, renderer)
    finally:
        tasks = [output_task, *([event_task] if event_task else [])]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        await renderer.close()
        await adapter.close()


def _select_adapter(
    controller: CLIController,
    config: CLIChannelConfig,
    input_reader: Callable[[str], str],
    writer: Callable[..., None],
) -> tuple[CLIAdapter, bool, str]:
    if input_reader is not input or writer is not print:
        return PlainCLIAdapter(input_reader, writer), False, ""
    capabilities = detect_terminal_capabilities(config)
    if not capabilities.interactive:
        return PlainCLIAdapter(input_reader, writer), False, ""
    try:
        if not initialize_utf8_terminal():
            raise OSError("utf8-terminal-unavailable")
        adapter: CLIAdapter = InteractiveCLIAdapter(
            controller.registry,
            lambda: controller.context,
            controller.turn_controller,
            controller.status_line,
        )
        return adapter, capabilities.color, ""
    except (ImportError, OSError, RuntimeError) as exc:
        return PlainCLIAdapter(input_reader, writer), False, _fallback_diagnostic(exc)


async def _input_loop(
    adapter: CLIAdapter,
    controller: CLIController,
    renderer: TerminalRenderer,
) -> None:
    while True:
        try:
            text = await adapter.read()
        except EOFError:
            renderer.notice("再见。")
            return
        if isinstance(adapter, InteractiveCLIAdapter) and text.strip():
            renderer.submit_input(text)
        outcome = await controller.handle_input(text)
        _present_outcome(outcome, renderer)
        if outcome.stop:
            return


def _present_outcome(outcome: InputOutcome, renderer: TerminalRenderer) -> None:
    if outcome.notice:
        renderer.notice(outcome.notice)


async def _consume_outbound(
    bus: MessageBus,
    controller: CLIController,
    renderer: TerminalRenderer,
) -> None:
    while True:
        outbound = await bus.consume_outbound()
        controller.observe_outbound(outbound)
        renderer.submit_outbound(outbound)


async def _consume_presentation(
    events: PresentationEventHub,
    renderer: TerminalRenderer,
) -> None:
    while True:
        renderer.submit_event(await events.consume())


def _fallback_diagnostic(exc: BaseException) -> str:
    return f"增强终端初始化失败（{type(exc).__name__}），已降级到 plain CLI。"


__all__ = ["CLIController", "CLIState", "PlainCLIAdapter", "run_cli"]
