from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.data_structures import Size
from prompt_toolkit.document import Document
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

import memoli_agent.channels.cli as cli_channel
from memoli_agent.agent.loop import AgentLoop
from memoli_agent.bootstrap.config import AppConfig, CLIChannelConfig
from memoli_agent.bootstrap.inspection import RuntimeInspector
from memoli_agent.bus.events import InboundMessage, OutboundMessage
from memoli_agent.bus.queue import MessageBus
from memoli_agent.channels.adapters import PlainCLIAdapter
from memoli_agent.channels.capabilities import (
    TerminalCapabilities,
    detect_terminal_capabilities,
)
from memoli_agent.channels.commands import (
    CommandContext as CLICommandContext,
)
from memoli_agent.channels.commands import (
    CommandRegistry,
    CommandResult,
    CommandSpec,
    build_command_registry,
)
from memoli_agent.channels.controller import CLIController, CLIState, InputOutcome
from memoli_agent.channels.interactive import (
    FRAME_BOTTOM_LEFT,
    FRAME_BOTTOM_RIGHT,
    FRAME_HORIZONTAL,
    FRAME_MIN_WIDTH,
    FRAME_STYLE,
    FRAME_TITLE,
    FRAME_TITLE_WIDTH,
    FRAME_TOP_LEFT,
    FRAME_TOP_RIGHT,
    FRAME_VERTICAL,
    PROMPT_SHORTCUTS,
    InteractiveCLIAdapter,
    RegistryCompleter,
    SafePromptHistory,
    SlashAndHistorySuggest,
    frame_contract,
    frame_top_fragments,
)
from memoli_agent.presentation.events import (
    PresentationEvent,
    PresentationEventHub,
    PresentationEventKind,
)
from memoli_agent.presentation.renderer import (
    RenderState,
    TerminalRenderer,
    commit_outbound,
    reduce_event,
)


class _TTY(StringIO):
    def isatty(self) -> bool:
        return True


class _RecordingOutput(DummyOutput):
    def __init__(self, columns: int, rows: int = 24) -> None:
        self.columns = columns
        self.rows = rows
        self.fragments: list[str] = []

    def write(self, data: str) -> None:
        self.fragments.append(data)

    def write_raw(self, data: str) -> None:
        self.fragments.append(data)

    def get_size(self) -> Size:
        return Size(rows=self.rows, columns=self.columns)

    @property
    def text(self) -> str:
        return "".join(self.fragments)


def _handler(_: CLICommandContext, __: str) -> CommandResult:
    return CommandResult(True, "ok")


def test_cli_config_defaults_validation_and_terminal_capabilities() -> None:
    config = CLIChannelConfig()
    assert config.interactive is True
    assert config.refresh_hz == 12
    assert detect_terminal_capabilities(
        config,
        stdin=_TTY(),
        stdout=_TTY(),
        environ={},
    ).interactive
    no_color = detect_terminal_capabilities(
        config,
        stdin=_TTY(),
        stdout=_TTY(),
        environ={"NO_COLOR": "1"},
    )
    assert no_color.color is False
    assert (
        detect_terminal_capabilities(
            config, stdin=StringIO(), stdout=_TTY(), environ={}
        ).reason
        == "non-tty"
    )
    with pytest.raises(ValueError):
        CLIChannelConfig(refresh_hz=0)
    with pytest.raises(ValueError):
        CLIChannelConfig(color="sometimes")


def test_command_registry_drives_help_completion_aliases_and_conflicts() -> None:
    registry = build_command_registry()
    context = CLICommandContext(CLIState("local"))
    help_text = registry.route("/help", context).message
    candidates = registry.candidates("/st", context)

    assert "/workspace [新路径]" in help_text
    assert {item.name for item in candidates} == {"/status", "/stop"}
    assert registry.resolve("/quit") is registry.resolve("/exit")
    assert registry.route("//literal", context).forwarded_text == "/literal"
    assert "未知命令" in registry.route("/missing", context).message

    conflict = CommandRegistry(
        [CommandSpec("/one", "one", _handler, aliases=("/same",))]
    )
    with pytest.raises(ValueError, match="命令冲突"):
        conflict.register(CommandSpec("/same", "same", _handler))


def test_read_only_inspection_commands_and_stop_do_not_mutate_runtime() -> None:
    @dataclass
    class Controller:
        busy: bool = True
        queue_depth: int = 2
        calls: int = 0

        def cancel_current_turn(self) -> bool:
            self.calls += 1
            if not self.busy:
                return False
            self.busy = False
            return True

    controller = Controller()
    inspector = RuntimeInspector(AppConfig(), None, None, controller)
    context = CLICommandContext(CLIState("local"), inspector, None, controller)
    registry = build_command_registry()

    assert "stream:" in registry.route("/model", context).message
    assert "首版只读" in registry.route("/model other", context).message
    assert "embedding:" in registry.route("/memory", context).message
    assert registry.route("/stop", context).message.startswith("正在停止")
    assert registry.route("/stop", context).message == "当前没有可停止的任务。"
    assert controller.calls == 2


def test_safe_event_queue_filters_secrets_and_preserves_terminal_event() -> None:
    hub = PresentationEventHub(max_events=2, max_text_chars=80)
    sanitized = PresentationEvent(
        PresentationEventKind.TEXT_DELTA,
        "cli:local",
        "trace",
        "Bearer secret D:\\private\\token.txt\x1b[31m",
    ).sanitized(80)

    async def scenario() -> tuple[PresentationEvent, PresentationEvent]:
        await hub.publish(
            PresentationEvent(
                PresentationEventKind.TEXT_DELTA,
                "cli:local",
                "trace",
                "first",
            )
        )
        await hub.publish(
            PresentationEvent(
                PresentationEventKind.TEXT_DELTA,
                "cli:local",
                "trace",
                "second",
            )
        )
        await hub.publish(
            PresentationEvent(
                PresentationEventKind.TURN_FAILED,
                "cli:local",
                "trace",
                status="failed",
                error_type="provider-error",
            )
        )
        return await hub.consume(), await hub.consume()

    first, terminal = asyncio.run(scenario())
    assert "secret" not in sanitized.text
    assert "D:\\private" not in sanitized.text
    assert "\x1b" not in sanitized.text
    assert first.text == "second"
    assert terminal.kind == PresentationEventKind.TURN_FAILED


def test_render_reducer_is_session_isolated_and_deduplicates_final_prefix() -> None:
    state = RenderState("cli:local")
    state = reduce_event(
        state,
        PresentationEvent(
            PresentationEventKind.TURN_STARTED,
            "cli:local",
            "trace-1",
        ),
    )
    state = reduce_event(
        state,
        PresentationEvent(
            PresentationEventKind.TEXT_DELTA,
            "cli:local",
            "trace-1",
            "答案",
        ),
    )
    ignored = reduce_event(
        state,
        PresentationEvent(
            PresentationEventKind.TEXT_DELTA,
            "cli:other",
            "trace-2",
            "泄漏",
        ),
    )
    committed, visible = commit_outbound(
        ignored,
        OutboundMessage("cli", "local", "答案完成", {"trace_id": "trace-1"}),
    )
    assert ignored.streamed_text == "答案"
    assert visible == "完成"
    assert committed.committed == ("答案完成",)


def test_terminal_event_closes_streamed_tool_placeholder() -> None:
    state = reduce_event(
        RenderState("cli:local"),
        PresentationEvent(
            PresentationEventKind.TURN_STARTED,
            "cli:local",
            "trace-1",
        ),
    )
    state = reduce_event(
        state,
        PresentationEvent(
            PresentationEventKind.TOOL_STARTED,
            "cli:local",
            "trace-1",
            "start_long_term_update",
            step_id="streamed-tool-1",
            status="running",
        ),
    )
    state = reduce_event(
        state,
        PresentationEvent(
            PresentationEventKind.TURN_FAILED,
            "cli:local",
            "trace-1",
            status="failed",
            error_type="provider-response-protocol",
        ),
    )

    assert state.tools[0].status == "failed"
    assert state.error_type == "provider-response-protocol"


def test_registry_completer_suggest_and_history_are_session_local() -> None:
    registry = build_command_registry()
    context = CLICommandContext(CLIState("local"))
    completer = RegistryCompleter(registry, lambda: context)
    values = list(
        completer.get_completions(
            Document("/wor"), CompleteEvent(completion_requested=True)
        )
    )
    assert [item.text for item in values] == ["/working", "/workspace"]

    suggestion = SlashAndHistorySuggest(registry, lambda: context).get_suggestion(
        object(),  # type: ignore[arg-type]
        Document("/worksp"),
    )
    assert suggestion is not None and suggestion.text == "ace"

    history = SafePromptHistory()
    history.append_string("普通问题")
    history.append_string("/status")
    history.append_string("Bearer secret")
    assert list(history.get_strings()) == ["普通问题"]


def test_input_frame_contract_is_cyan_rounded_and_bounded() -> None:
    contract = frame_contract()
    assert contract == {
        "title": FRAME_TITLE,
        "title_width": FRAME_TITLE_WIDTH,
        "minimum_width": FRAME_MIN_WIDTH,
        "corners": (
            FRAME_TOP_LEFT,
            FRAME_TOP_RIGHT,
            FRAME_BOTTOM_LEFT,
            FRAME_BOTTOM_RIGHT,
        ),
        "horizontal": FRAME_HORIZONTAL,
        "vertical": FRAME_VERTICAL,
        "border_style": "ansicyan",
        "shortcuts": PROMPT_SHORTCUTS,
    }
    assert "".join(fragment[1] for fragment in frame_top_fragments()) == "╭─ 输入 ─"
    assert FRAME_MIN_WIDTH == 20
    assert PROMPT_SHORTCUTS == "Enter 发送 · Esc+Enter 换行 · / 命令"
    assert FRAME_STYLE is not None


def test_input_frame_toolbar_prioritizes_busy_queue_and_keeps_shortcuts() -> None:
    @dataclass
    class Controller:
        busy: bool = True
        queue_depth: int = 3

        def cancel_current_turn(self) -> bool:
            return False

    context = CLICommandContext(CLIState("local"))
    adapter = InteractiveCLIAdapter(
        build_command_registry(),
        lambda: context,
        Controller(),
        lambda: "Memoli | model-x | busy | queue=3",
        output=DummyOutput(),
    )
    toolbar = "".join(fragment[1] for fragment in adapter._bottom_toolbar())
    prompt = "".join(fragment[1] for fragment in adapter._prompt_message())
    assert "busy" in toolbar
    assert "queue=3" in toolbar
    assert toolbar.endswith(PROMPT_SHORTCUTS)
    assert "queue=3" in prompt


def test_prompt_toolkit_virtual_terminal_tab_completion_and_submit() -> None:
    registry = build_command_registry()
    context = CLICommandContext(CLIState("local"))

    async def scenario() -> str:
        with create_pipe_input() as pipe:
            adapter = InteractiveCLIAdapter(
                registry,
                lambda: context,
                input=pipe,
                output=DummyOutput(),
            )
            task = asyncio.create_task(adapter.read())
            await asyncio.sleep(0.05)
            pipe.send_text("/worksp")
            await asyncio.sleep(0.05)
            pipe.send_text("\t")
            await asyncio.sleep(0.05)
            pipe.send_text("\r")
            await asyncio.sleep(0.05)
            pipe.send_text("\r")
            return await asyncio.wait_for(task, 2)

    assert asyncio.run(scenario()) == "/workspace"


def test_submitted_input_is_persisted_before_async_turn_output() -> None:
    bus = MessageBus()
    controller = CLIController(bus)
    output: list[str] = []

    async def scenario() -> InboundMessage:
        with create_pipe_input() as pipe:
            adapter = InteractiveCLIAdapter(
                controller.registry,
                lambda: controller.context,
                input=pipe,
                output=DummyOutput(),
            )
            renderer = TerminalRenderer(
                controller.state.session_key,
                output.append,
                color=False,
            )
            await renderer.start()
            task = asyncio.create_task(
                cli_channel._input_loop(adapter, controller, renderer)
            )
            await asyncio.sleep(0.05)
            pipe.send_text("完整输入末字\r")
            inbound = await asyncio.wait_for(bus.consume_inbound(), 2)
            await asyncio.sleep(0.05)
            pipe.send_text("/exit\r")
            await asyncio.wait_for(task, 2)
            await renderer.close()
            return inbound

    inbound = asyncio.run(scenario())
    assert inbound.content == "完整输入末字"
    rendered = "".join(output)
    assert "╭─ 输入 " in rendered
    assert "你 ▸ 完整输入末字" in rendered
    assert "╰" in rendered and "╯" in rendered


def test_interactive_application_erases_temporary_frame_after_submit() -> None:
    registry = build_command_registry()
    context = CLICommandContext(CLIState("local"))
    adapter = InteractiveCLIAdapter(
        registry,
        lambda: context,
        output=DummyOutput(),
    )

    assert adapter._application.erase_when_done is True


def test_prompt_toolkit_arrow_key_selects_slash_completion() -> None:
    registry = build_command_registry()
    context = CLICommandContext(CLIState("local"))

    async def scenario() -> str:
        with create_pipe_input() as pipe:
            adapter = InteractiveCLIAdapter(
                registry,
                lambda: context,
                input=pipe,
                output=DummyOutput(),
            )
            task = asyncio.create_task(adapter.read())
            await asyncio.sleep(0.05)
            pipe.send_text("/st")
            await asyncio.sleep(0.05)
            pipe.send_text("\x1b[B")
            await asyncio.sleep(0.05)
            pipe.send_text("\r")
            await asyncio.sleep(0.05)
            pipe.send_text("\r")
            return await asyncio.wait_for(task, 2)

    assert asyncio.run(scenario()) == "/status"


@pytest.mark.parametrize("columns", [20, 40, 80, 120])
def test_input_frame_renders_closed_at_supported_windows_widths(columns: int) -> None:
    registry = build_command_registry()
    context = CLICommandContext(CLIState("local"))
    output = _RecordingOutput(columns)

    async def scenario() -> str:
        with create_pipe_input() as pipe:
            adapter = InteractiveCLIAdapter(
                registry,
                lambda: context,
                input=pipe,
                output=output,
            )
            task = asyncio.create_task(adapter.read())
            await asyncio.sleep(0.08)
            pipe.send_text("宽度测试\r")
            return await asyncio.wait_for(task, 2)

    assert asyncio.run(scenario()) == "宽度测试"
    assert "╭─ 输入 ─" in output.text
    assert FRAME_TOP_RIGHT in output.text
    assert FRAME_BOTTOM_LEFT in output.text
    assert FRAME_BOTTOM_RIGHT in output.text
    assert FRAME_VERTICAL in output.text


def test_input_frame_handles_chinese_multiline_and_resize() -> None:
    registry = build_command_registry()
    context = CLICommandContext(CLIState("local"))
    output = _RecordingOutput(40)

    async def scenario() -> str:
        with create_pipe_input() as pipe:
            adapter = InteractiveCLIAdapter(
                registry,
                lambda: context,
                input=pipe,
                output=output,
            )
            task = asyncio.create_task(adapter.read())
            await asyncio.sleep(0.05)
            pipe.send_text("中文第一行\r第二行")
            await asyncio.sleep(0.08)
            output.columns = 20
            adapter._application.invalidate()
            await asyncio.sleep(0.08)
            pipe.send_text("\r")
            return await asyncio.wait_for(task, 2)

    assert asyncio.run(scenario()) == "中文第一行\n第二行"
    assert output.text.count(FRAME_TOP_LEFT) >= 2
    assert output.text.count(FRAME_BOTTOM_RIGHT) >= 2
    assert "中文第一行" in output.text


def test_input_frame_keeps_slash_completion_inside_live_region() -> None:
    registry = build_command_registry()
    context = CLICommandContext(CLIState("local"))
    output = _RecordingOutput(80)

    async def scenario() -> str:
        with create_pipe_input() as pipe:
            adapter = InteractiveCLIAdapter(
                registry,
                lambda: context,
                input=pipe,
                output=output,
            )
            task = asyncio.create_task(adapter.read())
            await asyncio.sleep(0.05)
            pipe.send_text("/wor")
            for _ in range(20):
                if "/working" in output.text:
                    break
                await asyncio.sleep(0.05)
            pipe.send_text("\r")
            return await asyncio.wait_for(task, 2)

    assert asyncio.run(scenario()) == "/wor"
    assert "/working" in output.text
    assert "/workspace" in output.text
    assert FRAME_TOP_LEFT in output.text
    assert FRAME_BOTTOM_RIGHT in output.text


def test_prompt_toolkit_virtual_terminal_multiline_history_ctrl_c_and_ctrl_d() -> None:
    @dataclass
    class Controller:
        busy: bool = False
        queue_depth: int = 0
        cancelled: int = 0

        def cancel_current_turn(self) -> bool:
            if not self.busy:
                return False
            self.cancelled += 1
            self.busy = False
            return True

    registry = build_command_registry()
    context = CLICommandContext(CLIState("local"))
    controller = Controller()

    async def scenario() -> tuple[str, str, str, int]:
        with create_pipe_input() as pipe:
            adapter = InteractiveCLIAdapter(
                registry,
                lambda: context,
                controller,
                input=pipe,
                output=DummyOutput(),
            )

            first_task = asyncio.create_task(adapter.read())
            await asyncio.sleep(0.05)
            pipe.send_text("第一行\x1b\r第二行\r")
            first = await asyncio.wait_for(first_task, 2)

            history_task = asyncio.create_task(adapter.read())
            await asyncio.sleep(0.05)
            pipe.send_text("\x1b[A\r")
            history = await asyncio.wait_for(history_task, 2)

            controller.busy = True
            cancel_task = asyncio.create_task(adapter.read())
            await asyncio.sleep(0.05)
            pipe.send_bytes(b"\x03")
            await asyncio.sleep(0.05)
            pipe.send_text("继续\r")
            after_cancel = await asyncio.wait_for(cancel_task, 2)

            eof_task = asyncio.create_task(adapter.read())
            await asyncio.sleep(0.05)
            pipe.send_bytes(b"\x04")
            eof = await asyncio.wait_for(eof_task, 2)
            return first, history, after_cancel + eof, controller.cancelled

    first, history, tail, cancelled = asyncio.run(scenario())
    assert first == "第一行\n第二行"
    assert history == first
    assert tail == "继续/exit"
    assert cancelled == 1


def test_agent_loop_user_cancel_keeps_pump_alive_for_queued_message() -> None:
    class Runner:
        async def handle_inbound(self, message: InboundMessage) -> OutboundMessage:
            if message.content == "slow":
                await asyncio.Event().wait()
            return OutboundMessage(message.channel, message.chat_id, message.content)

    async def scenario() -> tuple[OutboundMessage, OutboundMessage]:
        bus = MessageBus()
        loop = AgentLoop(bus, Runner())  # type: ignore[arg-type]
        await loop.start()
        await bus.publish_inbound(InboundMessage("cli", "local", "user", "slow"))
        while not loop.busy:
            await asyncio.sleep(0)
        await bus.publish_inbound(InboundMessage("cli", "local", "user", "next"))
        assert loop.cancel_current_turn()
        first = await asyncio.wait_for(bus.consume_outbound(), 1)
        second = await asyncio.wait_for(bus.consume_outbound(), 1)
        await loop.stop()
        return first, second

    first, second = asyncio.run(scenario())
    assert first.metadata["error_type"] == "user-cancelled"
    assert second.content == "next"


def test_shared_controller_keeps_terminal_modes_semantically_equal() -> None:
    async def scenario() -> tuple[list[InputOutcome], list[InboundMessage]]:
        outcomes: list[InputOutcome] = []
        messages: list[InboundMessage] = []
        for _mode in ("interactive", "plain"):
            bus = MessageBus()
            controller = CLIController(bus, queue_limit=2)
            outcomes.append(await controller.handle_input("/status"))
            outcomes.append(await controller.handle_input("//literal"))
            messages.append(await bus.consume_inbound())
            outcomes.append(await controller.handle_input("/exit"))
        return outcomes, messages

    outcomes, messages = asyncio.run(scenario())
    assert outcomes[0] == outcomes[3]
    assert outcomes[1] == outcomes[4]
    assert outcomes[2] == outcomes[5]
    assert [message.content for message in messages] == ["/literal", "/literal"]


def test_shared_controller_applies_queue_limit_before_adapter_io() -> None:
    @dataclass
    class BusyController:
        busy: bool = True
        queue_depth: int = 1

        def cancel_current_turn(self) -> bool:
            return False

    async def scenario() -> tuple[InputOutcome, bool]:
        bus = MessageBus()
        controller = CLIController(
            bus,
            turn_controller=BusyController(),
            queue_limit=1,
        )
        outcome = await controller.handle_input("new task")
        return outcome, bus._inbound.empty()

    outcome, empty = asyncio.run(scenario())
    assert "队列已满" in outcome.notice
    assert outcome.published is False
    assert empty is True


def test_plain_adapter_is_line_only_and_converts_iterator_end_to_eof() -> None:
    inputs = iter(["hello"])
    output: list[str] = []
    adapter = PlainCLIAdapter(
        lambda _: next(inputs),
        lambda value, **_: output.append(str(value)),
    )

    async def scenario() -> str:
        await adapter.start()
        first = await adapter.read()
        with pytest.raises(EOFError):
            await adapter.read()
        adapter.write("plain\n")
        await adapter.close()
        return first

    assert asyncio.run(scenario()) == "hello"
    assert output == ["plain\n"]
    assert "\x1b" not in "".join(output)
    assert not any(character in "".join(output) for character in "╭╮╰╯│─")


def test_async_invalidate_keeps_frame_and_cursor_input_available() -> None:
    registry = build_command_registry()
    context = CLICommandContext(CLIState("local"))
    output = _RecordingOutput(80)

    async def scenario() -> str:
        with create_pipe_input() as pipe:
            adapter = InteractiveCLIAdapter(
                registry,
                lambda: context,
                input=pipe,
                output=output,
            )
            task = asyncio.create_task(adapter.read())
            await asyncio.sleep(0.05)
            pipe.send_text("异步")
            await asyncio.sleep(0.05)
            adapter._application.invalidate()
            await asyncio.sleep(0.08)
            pipe.send_text("恢复\r")
            return await asyncio.wait_for(task, 2)

    assert asyncio.run(scenario()) == "异步恢复"
    assert output.text.count(FRAME_TOP_LEFT) == 1
    assert output.text.count(FRAME_BOTTOM_RIGHT) <= 1
    assert "异步" in output.text


def test_interactive_lifecycle_does_not_create_render_debug_file() -> None:
    context = CLICommandContext(CLIState("local"))
    adapter = InteractiveCLIAdapter(
        build_command_registry(),
        lambda: context,
        output=DummyOutput(),
    )

    async def scenario() -> tuple[bool, bool]:
        with create_app_session(output=DummyOutput()):
            await adapter.start()
            started = adapter._patch is not None
            await adapter.close()
        return started, adapter._patch is None

    assert asyncio.run(scenario()) == (True, True)
    assert not Path("memoli_agent/channels/_render_debug.log").exists()


def test_interactive_start_failure_falls_back_to_plain(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FailingInteractive:
        def __init__(self, *_: object, **__: object) -> None:
            return None

        async def start(self) -> None:
            raise OSError("terminal failed")

        async def read(self) -> str:
            raise AssertionError("failing adapter must not read")

        def write(self, _: str) -> None:
            return None

        async def close(self) -> None:
            return None

    reads = iter(["/exit"])

    async def plain_read(_: PlainCLIAdapter) -> str:
        return next(reads)

    monkeypatch.setattr(
        cli_channel,
        "detect_terminal_capabilities",
        lambda _: TerminalCapabilities(True, False, True),
    )
    monkeypatch.setattr(cli_channel, "initialize_utf8_terminal", lambda: True)
    monkeypatch.setattr(cli_channel, "InteractiveCLIAdapter", FailingInteractive)
    monkeypatch.setattr(PlainCLIAdapter, "read", plain_read)

    asyncio.run(cli_channel.run_cli(MessageBus()))
    assert "已降级到 plain CLI" in capsys.readouterr().out
