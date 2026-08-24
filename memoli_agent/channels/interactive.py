"""prompt_toolkit 驱动的轻量交互输入适配器。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from prompt_toolkit import Application
from prompt_toolkit.application import get_app
from prompt_toolkit.auto_suggest import AutoSuggest, AutoSuggestFromHistory, Suggestion
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.input.base import Input
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.defaults import load_key_bindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import (
    ConditionalContainer,
    FloatContainer,
    HSplit,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import AppendAutoSuggestion, BeforeInput
from prompt_toolkit.output.base import Output
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style

from memoli_agent.channels.commands import (
    CommandContext,
    CommandRegistry,
    TurnController,
)

FRAME_TITLE = "输入"
FRAME_TITLE_WIDTH = 9
FRAME_MIN_WIDTH = 20
FRAME_TOP_LEFT = "╭"
FRAME_TOP_RIGHT = "╮"
FRAME_BOTTOM_LEFT = "╰"
FRAME_BOTTOM_RIGHT = "╯"
FRAME_HORIZONTAL = "─"
FRAME_VERTICAL = "│"
PROMPT_SHORTCUTS = "Enter 发送 · Esc+Enter 换行 · / 命令"

FRAME_STYLE = Style.from_dict(
    {
        "input-frame.border": "ansicyan",
        "input-frame.title": "bold ansicyan",
        "input-frame.prompt": "bold ansicyan",
        "input-frame.shortcut": "ansibrightblack",
        "input-frame.busy": "ansiyellow",
        "input-frame.queue": "ansiyellow",
    }
)


def frame_top_fragments(title: str = FRAME_TITLE) -> FormattedText:
    """返回输入框固定左侧标题合同；水平填充由 layout Window 完成。"""

    return FormattedText(
        [
            ("class:input-frame.border", f"{FRAME_TOP_LEFT}{FRAME_HORIZONTAL}"),
            ("class:input-frame.title", f" {title} "),
            ("class:input-frame.border", FRAME_HORIZONTAL),
        ]
    )


def frame_contract() -> dict[str, object]:
    """供测试和只读诊断使用的稳定表现合同。"""

    return {
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


class SafePromptHistory(InMemoryHistory):
    """只保存当前进程的普通用户提示，不落盘、不保存 slash 命令。"""

    @staticmethod
    def _allowed(string: str) -> bool:
        text = string.strip()
        if not text or text.startswith("/"):
            return False
        lowered = text.casefold()
        if any(token in lowered for token in ("api_key=", "authorization:", "bearer ")):
            return False
        return True

    def append_string(self, string: str) -> None:
        if self._allowed(string):
            super().append_string(string)

    def store_string(self, string: str) -> None:
        if not self._allowed(string):
            return
        super().store_string(string)


class RegistryCompleter(Completer):
    def __init__(
        self,
        registry: CommandRegistry,
        context_provider: Callable[[], CommandContext],
        *,
        limit: int = 20,
    ) -> None:
        self.registry = registry
        self.context_provider = context_provider
        self.limit = limit

    def get_completions(self, document: Document, complete_event: object):
        text = document.text_before_cursor
        if not text.startswith("/") or " " in text or "\n" in text:
            return
        for spec in self.registry.candidates(text, self.context_provider())[
            : self.limit
        ]:
            meta = spec.description + (f"  {spec.args_hint}" if spec.args_hint else "")
            completion_text = next(
                identifier
                for identifier in (spec.name, *spec.aliases)
                if identifier.casefold().startswith(text.casefold())
            )
            yield Completion(
                completion_text,
                start_position=-len(text),
                display=completion_text,
                display_meta=meta,
            )


class SlashAndHistorySuggest(AutoSuggest):
    def __init__(
        self,
        registry: CommandRegistry,
        context_provider: Callable[[], CommandContext],
    ) -> None:
        self.registry = registry
        self.context_provider = context_provider
        self.history = AutoSuggestFromHistory()

    def get_suggestion(self, buffer: Buffer, document: Document) -> Suggestion | None:
        text = document.text_before_cursor
        if text.startswith("/") and " " not in text and "\n" not in text:
            matches = self.registry.candidates(text, self.context_provider())
            if len(matches) == 1 and matches[0].name.startswith(text):
                return Suggestion(matches[0].name[len(text) :])
            return None
        return self.history.get_suggestion(buffer, document)


@dataclass(slots=True)
class InteractiveCLIAdapter:
    registry: CommandRegistry
    context_provider: Callable[[], CommandContext]
    turn_controller: TurnController | None = None
    status_provider: Callable[[], str] | None = None
    input: Input | None = None
    output: Output | None = None
    _application: Application[str] = field(init=False)
    _buffer: Buffer = field(init=False)
    _patch: object | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        bindings = KeyBindings()

        @bindings.add("enter")
        def accept(event: object) -> None:
            buffer = event.current_buffer  # type: ignore[attr-defined]
            state = buffer.complete_state
            if state is not None and state.current_completion is not None:
                buffer.apply_completion(state.current_completion)
                return
            buffer.validate_and_handle()

        @bindings.add("tab")
        def complete(event: object) -> None:
            buffer = event.current_buffer  # type: ignore[attr-defined]
            values = list(
                completer.get_completions(
                    buffer.document,
                    CompleteEvent(completion_requested=True),
                )
            )
            if len(values) == 1:
                buffer.apply_completion(values[0])
            else:
                buffer.start_completion(select_first=True)

        @bindings.add("escape", "enter")
        @bindings.add("escape", "c-m")
        def newline(event: object) -> None:
            event.current_buffer.insert_text("\n")  # type: ignore[attr-defined]

        @bindings.add("c-c")
        def cancel_or_clear(event: object) -> None:
            if (
                self.turn_controller is not None
                and self.turn_controller.cancel_current_turn()
            ):
                event.app.invalidate()  # type: ignore[attr-defined]
                return
            event.current_buffer.reset()  # type: ignore[attr-defined]

        @bindings.add("c-d")
        def eof(event: object) -> None:
            buffer = event.current_buffer  # type: ignore[attr-defined]
            if buffer.text:
                buffer.delete()
            else:
                event.app.exit(result="/exit")  # type: ignore[attr-defined]

        @bindings.add("up")
        def history_up(event: object) -> None:
            buffer = event.current_buffer  # type: ignore[attr-defined]
            if buffer.complete_state is not None:
                buffer.complete_previous()
                return
            history_values = buffer.history.get_strings()
            if not buffer.text and history_values:
                buffer.document = Document(
                    history_values[-1], cursor_position=len(history_values[-1])
                )
            elif buffer.document.cursor_position_row == 0:
                buffer.history_backward()
            else:
                buffer.cursor_up()

        @bindings.add("down")
        def history_down(event: object) -> None:
            buffer = event.current_buffer  # type: ignore[attr-defined]
            if buffer.complete_state is not None:
                buffer.complete_next()
                return
            if buffer.document.cursor_position_row == len(buffer.document.lines) - 1:
                buffer.history_forward()
            else:
                buffer.cursor_down()

        history = SafePromptHistory()
        completer = RegistryCompleter(self.registry, self.context_provider)
        self._buffer = Buffer(
            history=history,
            completer=completer,
            complete_while_typing=True,
            auto_suggest=SlashAndHistorySuggest(self.registry, self.context_provider),
            multiline=True,
            accept_handler=self._accept,
        )
        input_control = BufferControl(
            buffer=self._buffer,
            input_processors=[
                BeforeInput(self._prompt_message),
                AppendAutoSuggestion(),
            ],
        )
        input_window = Window(
            input_control,
            height=lambda: self._input_height(),
            wrap_lines=True,
            dont_extend_height=True,
        )
        body = FloatContainer(
            content=self._frame_container(input_window),
            floats=[],
        )
        self._application = Application(
            layout=Layout(body, focused_element=input_window),
            key_bindings=merge_key_bindings([load_key_bindings(), bindings]),
            style=FRAME_STYLE,
            full_screen=False,
            erase_when_done=True,
            input=self.input,
            output=self.output,
        )

    def _frame_container(self, input_window: Window) -> HSplit:
        top = VSplit(
            [
                Window(
                    FormattedTextControl(frame_top_fragments),
                    width=Dimension.exact(FRAME_TITLE_WIDTH),
                    dont_extend_width=True,
                ),
                Window(
                    char=FRAME_HORIZONTAL,
                    style="class:input-frame.border",
                ),
                self._corner_window(FRAME_TOP_RIGHT),
            ],
            height=1,
        )
        middle = VSplit(
            [
                self._side_window(),
                Window(width=1, char=" ", dont_extend_width=True),
                input_window,
                Window(width=1, char=" ", dont_extend_width=True),
                self._side_window(),
            ],
            height=lambda: self._input_height(),
        )
        completions = ConditionalContainer(
            CompletionsMenu(max_height=8, scroll_offset=1),
            filter=Condition(lambda: self._buffer.complete_state is not None),
        )
        bottom = VSplit(
            [
                self._corner_window(FRAME_BOTTOM_LEFT),
                Window(
                    char=FRAME_HORIZONTAL,
                    style="class:input-frame.border",
                ),
                self._corner_window(FRAME_BOTTOM_RIGHT),
            ],
            height=1,
        )
        toolbar = Window(
            FormattedTextControl(self._bottom_toolbar),
            height=1,
            style="class:input-frame.shortcut",
        )
        return HSplit(
            [top, middle, completions, bottom, toolbar],
            width=Dimension(min=FRAME_MIN_WIDTH),
        )

    @staticmethod
    def _corner_window(character: str) -> Window:
        return Window(
            FormattedTextControl(
                FormattedText([("class:input-frame.border", character)])
            ),
            width=1,
            dont_extend_width=True,
        )

    @staticmethod
    def _side_window() -> Window:
        return Window(
            char=FRAME_VERTICAL,
            width=1,
            dont_extend_width=True,
            style="class:input-frame.border",
        )

    @staticmethod
    def _accept(buffer: Buffer) -> bool:
        get_app().exit(result=buffer.text)
        return False

    def _input_height(self) -> int:
        lines = self._buffer.document.lines
        return max(1, min(8, len(lines)))

    async def start(self) -> None:
        manager = patch_stdout(raw=True)
        manager.__enter__()
        self._patch = manager

    async def close(self) -> None:
        if self._patch is not None:
            self._patch.__exit__(None, None, None)  # type: ignore[attr-defined]
            self._patch = None

    async def read(self) -> str:
        return await self._application.run_async()

    @staticmethod
    def write(text: str) -> None:
        print(text, end="", flush=True)

    def _prompt_message(self) -> FormattedText:
        """动态输入提示：空闲时显示 ▸，排队时显示 ⏳。"""

        controller = self.turn_controller
        if controller is not None and controller.busy:
            queue = controller.queue_depth
            if queue > 0:
                return FormattedText(
                    [
                        ("#ansicyan bold", "你"),
                        ("", " "),
                        ("#ansiyellow", f"⏳[queue={queue}]"),
                        ("", " ▸ "),
                    ]
                )
            return FormattedText(
                [
                    ("#ansicyan bold", "你"),
                    ("", " ⏳ ▸ "),
                ]
            )
        return FormattedText(
            [
                ("#ansicyan bold", "你"),
                ("", " ▸ "),
            ]
        )

    def _bottom_toolbar(self) -> FormattedText:
        """格式化状态栏，带图标和颜色。"""

        if self.status_provider is None:
            return FormattedText(
                [
                    ("bold #ansicyan", "◈ Memoli"),
                    ("", " │ ✓ idle │ "),
                    ("class:input-frame.shortcut", PROMPT_SHORTCUTS),
                ]
            )
        try:
            raw = self.status_provider()[:240]
        except Exception:
            return FormattedText(
                [
                    ("bold #ansicyan", "◈ Memoli"),
                    ("", " │ status unavailable │ "),
                    ("class:input-frame.shortcut", PROMPT_SHORTCUTS),
                ]
            )

        # 将 "Memoli | model | phase | ..." 分段着色
        parts = raw.split(" | ")
        if len(parts) < 2:
            return FormattedText(
                [
                    ("", f"{raw} │ "),
                    ("class:input-frame.shortcut", PROMPT_SHORTCUTS),
                ]
            )

        segments: list[tuple[str, str]] = []
        # 品牌
        segments.append(("bold #ansicyan", f"◈ {parts[0]}"))
        # 模型
        if len(parts) > 1:
            segments.append(("", " │ "))
            segments.append(("", f"🤖 {parts[1]}"))
        # 状态
        if len(parts) > 2:
            segments.append(("", " │ "))
            phase = parts[2]
            if phase == "busy":
                segments.append(("bg:#ansiyellow #ansiblack", f" ⏳ {phase} "))
            else:
                segments.append(("", f"✓ {phase}"))
        # 剩余部分
        for part in parts[3:]:
            segments.append(("", " │ "))
            segments.append(("dim", part))
        segments.append(("", " │ "))
        segments.append(("class:input-frame.shortcut", PROMPT_SHORTCUTS))
        return FormattedText(segments)
