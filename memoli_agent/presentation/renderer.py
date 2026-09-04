"""单写者终端 renderer 与可独立测试的状态归约器。"""

from __future__ import annotations

import asyncio
import io
import shutil
from collections import OrderedDict
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field, replace
from typing import Literal

from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text

from memoli_agent.bus.events import OutboundMessage
from memoli_agent.channels.controller import StartupInfo
from memoli_agent.presentation.events import PresentationEvent, PresentationEventKind


@dataclass(frozen=True, slots=True)
class ToolRow:
    step_id: str
    name: str
    status: str
    elapsed_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class RenderState:
    session_key: str
    trace_id: str = ""
    phase: str = "idle"
    active_text: str = ""
    streamed_text: str = ""
    committed: tuple[str, ...] = ()
    tools: tuple[ToolRow, ...] = ()
    usage: tuple[tuple[str, int], ...] = ()
    checkpoint_status: str = "unavailable"
    error_type: str = ""
    queue_depth: int = 0


def reduce_event(
    state: RenderState,
    event: PresentationEvent,
    *,
    max_active_chars: int = 16_000,
    max_tool_rows: int = 6,
) -> RenderState:
    """纯函数归约；拒绝其他 session 和已过期 trace 的乱序事件。"""

    if event.session_key != state.session_key:
        return state
    terminal = {
        PresentationEventKind.TURN_COMPLETED,
        PresentationEventKind.TURN_FAILED,
        PresentationEventKind.TURN_CANCELLED,
    }
    if state.trace_id and event.trace_id != state.trace_id:
        if event.kind != PresentationEventKind.TURN_STARTED:
            return state
    if event.kind == PresentationEventKind.TURN_STARTED:
        return replace(
            state,
            trace_id=event.trace_id,
            phase="turn",
            active_text="",
            streamed_text="",
            tools=(),
            usage=(),
            error_type="",
        )
    if event.kind == PresentationEventKind.MODEL_STARTED:
        return replace(state, phase="model")
    if event.kind == PresentationEventKind.TEXT_DELTA:
        full = state.streamed_text + event.text
        return replace(
            state,
            phase="model",
            streamed_text=full,
            active_text=full[-max_active_chars:],
        )
    if event.kind in {
        PresentationEventKind.PROGRESS_UPDATE,
        PresentationEventKind.REASONING_SUMMARY,
    }:
        return replace(state, phase=event.kind.value)
    if event.kind == PresentationEventKind.USAGE_UPDATED:
        return replace(state, usage=event.usage)
    if event.kind in {
        PresentationEventKind.TOOL_STARTED,
        PresentationEventKind.TOOL_FINISHED,
    }:
        rows = OrderedDict((row.step_id, row) for row in state.tools)
        step_id = event.step_id or f"tool:{event.text}"
        rows[step_id] = ToolRow(
            step_id,
            event.text,
            event.status
            or (
                "running"
                if event.kind == PresentationEventKind.TOOL_STARTED
                else "completed"
            ),
            event.elapsed_seconds,
        )
        return replace(state, phase="tool", tools=tuple(rows.values())[-max_tool_rows:])
    if event.kind == PresentationEventKind.CHECKPOINT_CHANGED:
        return replace(state, checkpoint_status=event.status or "updated")
    if event.kind in terminal:
        unfinished_status = {
            PresentationEventKind.TURN_FAILED: "failed",
            PresentationEventKind.TURN_CANCELLED: "cancelled",
            PresentationEventKind.TURN_COMPLETED: "not-executed",
        }[event.kind]
        return replace(
            state,
            phase=event.status or event.kind.value,
            error_type=event.error_type,
            tools=tuple(
                replace(row, status=unfinished_status)
                if row.status == "running"
                else row
                for row in state.tools
            ),
        )
    return state


def commit_outbound(
    state: RenderState, outbound: OutboundMessage
) -> tuple[RenderState, str]:
    """以 Outbound 为权威，只返回尚未展示的尾部或完整最终文本。"""

    content = outbound.content
    streamed = state.streamed_text
    visible = (
        content[len(streamed) :]
        if streamed and content.startswith(streamed)
        else content
    )
    metadata = outbound.metadata or {}
    trace_id = str(metadata.get("trace_id") or state.trace_id)
    updated = replace(
        state,
        trace_id=trace_id,
        phase=str(metadata.get("status") or "idle"),
        active_text="",
        streamed_text="",
        committed=(*state.committed, content),
        error_type=str(metadata.get("error_type") or ""),
    )
    return updated, visible


@dataclass(frozen=True, slots=True)
class RenderItem:
    kind: Literal["input", "event", "outbound", "notice", "startup", "stop"]
    event: PresentationEvent | None = None
    outbound: OutboundMessage | None = None
    startup: StartupInfo | None = None
    text: str = ""


@dataclass(slots=True)
class TerminalRenderer:
    """所有终端输出均通过此队列，由唯一 task 顺序写出。"""

    session_key: str
    writer: Callable[[str], None]
    refresh_hz: int = 12
    max_tool_rows: int = 6
    color: bool = True
    markdown: bool = True
    state: RenderState = field(init=False)
    _queue: asyncio.Queue[RenderItem] = field(init=False)
    _task: asyncio.Task[None] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.state = RenderState(self.session_key)
        self._queue = asyncio.Queue(maxsize=512)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="terminal_renderer")

    async def close(self) -> None:
        if self._task is None:
            return
        await self._queue.put(RenderItem("stop"))
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def submit_event(self, event: PresentationEvent) -> None:
        self._submit(RenderItem("event", event=event))

    def submit_input(self, text: str) -> None:
        """将增强输入框的临时内容提交到稳定滚动区。"""

        self._submit(RenderItem("input", text=text))

    def submit_outbound(self, outbound: OutboundMessage) -> None:
        self._submit(RenderItem("outbound", outbound=outbound))

    def notice(self, text: str | StartupInfo) -> None:
        if isinstance(text, StartupInfo):
            self._submit(RenderItem("startup", startup=text))
        else:
            self._submit(RenderItem("notice", text=text))

    def _submit(self, item: RenderItem) -> None:
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            # Outbound 不可丢；清理一个 Observer 更新后重试。
            if item.kind != "outbound":
                return
            with suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            with suppress(asyncio.QueueFull):
                self._queue.put_nowait(item)

    async def _run(self) -> None:
        frame_seconds = 1 / self.refresh_hz
        pending_text = ""
        deferred: RenderItem | None = None
        while True:
            item = deferred or await self._queue.get()
            deferred = None
            if item.kind == "stop":
                if pending_text:
                    self._write(pending_text)
                return
            if item.kind == "startup" and item.startup is not None:
                if pending_text:
                    self._write(pending_text)
                    pending_text = ""
                self._write(_render_banner(item.startup, color=self.color))
            elif item.kind == "input":
                if pending_text:
                    self._write(pending_text)
                    pending_text = ""
                self._write(_render_user_input(item.text, color=self.color))
            elif item.kind == "event" and item.event is not None:
                before = self.state
                self.state = reduce_event(
                    self.state,
                    item.event,
                    max_tool_rows=self.max_tool_rows,
                )
                if item.event.kind == PresentationEventKind.TEXT_DELTA:
                    # Windows 上无换行的半行输出会被 prompt_toolkit 重绘覆盖；
                    # 增量只进入状态，等待权威 Outbound 后完整渲染 Markdown。
                    pass
                elif item.event.kind == PresentationEventKind.TOOL_STARTED:
                    # 工具开始运行时立即显示
                    if pending_text:
                        self._write(pending_text)
                        pending_text = ""
                    row = self.state.tools[-1] if self.state.tools else None
                    if row and before.tools != self.state.tools:
                        self._write(_render_tool_line(row, color=self.color))
                elif item.event.kind == PresentationEventKind.TOOL_FINISHED:
                    if pending_text:
                        self._write(pending_text)
                        pending_text = ""
                    row = self.state.tools[-1] if self.state.tools else None
                    if row and before.tools != self.state.tools:
                        self._write(_render_tool_line(row, color=self.color))
                elif item.event.kind == PresentationEventKind.MODEL_STARTED:
                    # 模型推理开始时显示思考动画
                    if pending_text:
                        self._write(pending_text)
                        pending_text = ""
                    self._write(_render_thinking(color=self.color))
                elif item.event.kind == PresentationEventKind.PROGRESS_UPDATE:
                    if pending_text:
                        self._write(pending_text)
                        pending_text = ""
                    self._write(
                        _render_text_line(
                            f"进度：{item.event.text}", style="dim", color=self.color
                        )
                    )
                elif item.event.kind == PresentationEventKind.REASONING_SUMMARY:
                    if pending_text:
                        self._write(pending_text)
                        pending_text = ""
                    self._write(
                        _render_text_line(
                            f"推理摘要：{item.event.text}",
                            style="dim",
                            color=self.color,
                        )
                    )
                elif item.event.kind == PresentationEventKind.TURN_STARTED:
                    # 在新一轮开始时插入分隔线
                    if pending_text:
                        self._write(pending_text)
                        pending_text = ""
                    self._write(_render_separator(color=self.color))
                elif item.event.kind in {
                    PresentationEventKind.TURN_COMPLETED,
                    PresentationEventKind.TURN_FAILED,
                    PresentationEventKind.TURN_CANCELLED,
                }:
                    # 回合结束后显示使用量统计
                    if pending_text:
                        self._write(pending_text)
                        pending_text = ""
                    before_rows = {row.step_id: row for row in before.tools}
                    for row in self.state.tools:
                        previous = before_rows.get(row.step_id)
                        if (
                            previous is not None
                            and previous.status == "running"
                            and row.status != "running"
                        ):
                            self._write(_render_tool_line(row, color=self.color))
                    if self.state.usage:
                        self._write(_render_usage(self.state.usage, color=self.color))
            elif item.kind == "outbound" and item.outbound is not None:
                if pending_text:
                    self._write(pending_text)
                    pending_text = ""
                self.state, _ = commit_outbound(self.state, item.outbound)
                if item.outbound.content:
                    rendered = (
                        _render_markdown(item.outbound.content, color=self.color)
                        if self.markdown
                        else item.outbound.content + "\n"
                    )
                    self._write("Memoli > " + rendered)
                metadata = item.outbound.metadata or {}
                trace_id = str(metadata.get("trace_id") or "")
                error_type = str(metadata.get("error_type") or "")
                if error_type:
                    retryable = bool(metadata.get("retryable"))
                    self._write(_render_error(error_type, retryable, color=self.color))
                elif trace_id:
                    self._write(_render_trace(trace_id, color=self.color))
            elif item.kind == "notice":
                if pending_text:
                    self._write(pending_text)
                    pending_text = ""
                self._write(item.text.rstrip() + "\n")
            if pending_text:
                try:
                    next_item = await asyncio.wait_for(
                        self._queue.get(), timeout=frame_seconds
                    )
                except TimeoutError:
                    self._write(pending_text)
                    pending_text = ""
                else:
                    self._write(pending_text)
                    pending_text = ""
                    deferred = next_item

    def _write(self, text: str) -> None:
        try:
            self.writer(text)
        except Exception:
            # Renderer 是 Observer；终端故障不能取消 Agent turn。
            return


def _render_markdown(text: str, *, color: bool) -> str:
    buffer = io.StringIO()
    console = Console(
        file=buffer,
        force_terminal=color,
        color_system="auto" if color else None,
        no_color=not color,
        width=_terminal_width(),
    )
    console.print(Markdown(text), end="")
    return buffer.getvalue()


def _render_banner(info: StartupInfo, *, color: bool) -> str:
    """渲染启动欢迎横幅——无框、层次分明、呼吸感。"""

    buffer = io.StringIO()
    console = Console(
        file=buffer,
        force_terminal=color,
        color_system="auto" if color else None,
        no_color=not color,
        width=_terminal_width(),
    )
    # 标题行
    title = Text()
    title.append("◈ ", style="bold cyan" if color else "")
    title.append(f"Memoli v{info.version}", style="bold cyan" if color else "")
    title.append(" — Memory-focused Agent Runtime", style="dim" if color else "")
    console.print(title)
    console.print()

    # 模型信息行
    model_line = Text("  ")
    model_line.append(
        f"🤖 {info.model} ({info.provider})",
        style="bold" if color else "",
    )
    model_line.append("  ·  ")
    stream_icon = "✅" if info.stream else "❌"
    model_line.append(f"💾 流式 {stream_icon}")
    model_line.append("  ·  ")
    model_line.append(f"📂 {info.workspace}")
    console.print(model_line)

    # 组件状态行
    on = "✅" if color else "ON"
    off = "❌" if color else "OFF"
    comp_line = Text("  ")
    comp_line.append(f"🧠 Memory {on if info.memory else off}")
    comp_line.append(f"  📋 Working {on if info.working_memory else off}")
    comp_line.append(f"  🎯 Skills {on if info.skills else off}")
    comp_line.append(f"  🔌 MCP {on if info.mcp else off}")
    comp_line.append(f"  🔮 Proactive {on if info.proactive else off}")
    console.print(comp_line)

    # 会话行
    console.print(Text(f"  🔑 {info.session_key}", style="dim" if color else ""))
    console.print()

    # 帮助提示
    console.print(
        Text("  输入 / 查看命令，/help 显示完整帮助", style="italic" if color else "")
    )
    console.print()
    return buffer.getvalue()


def _render_separator(*, color: bool) -> str:
    """渲染对话分隔线。"""

    buffer = io.StringIO()
    console = Console(
        file=buffer,
        force_terminal=color,
        color_system="auto" if color else None,
        no_color=not color,
        width=_terminal_width(),
    )
    console.print(Rule(style="dim" if color else ""))
    return buffer.getvalue()


_TOOL_FRIENDLY_NAMES: dict[str, str] = {
    "file_read": "📄 读取文件",
    "file_write": "✏️ 写入文件",
    "code_execute": "💻 执行代码",
    "web_search": "🔍 网络搜索",
    "update_working_checkpoint": "📋 更新工作状态",
    "ask_user": "💬 询问用户",
    "skill_load": "🎯 加载技能",
    "tool_search": "🔎 搜索工具",
    "memory_manage": "🧠 管理记忆",
}


def _friendly_tool_name(name: str) -> str:
    """将工具原始名转为友好显示名，未知名保持原样。"""

    return _TOOL_FRIENDLY_NAMES.get(name, name)


def _render_tool_line(row: ToolRow, *, color: bool) -> str:
    """渲染工具调用为一行紧凑状态。"""

    name = _friendly_tool_name(row.name)
    elapsed = f"  {row.elapsed_seconds:.2f}s" if row.elapsed_seconds is not None else ""

    if color:
        if row.status == "completed":
            icon, status_style = "✓", "green"
        elif row.status == "failed":
            icon, status_style = "✗", "red"
        else:
            icon, status_style = "⏳", "yellow"
        buffer = io.StringIO()
        console = Console(
            file=buffer,
            force_terminal=True,
            color_system="auto",
            no_color=False,
            width=_terminal_width(),
        )
        line = Text("  🔧 ")
        line.append(name, style="bold")
        line.append(f"  {icon} {row.status}", style=status_style)
        if elapsed:
            line.append(elapsed, style="dim")
        console.print(line)
        return buffer.getvalue()
    else:
        icon = "●"
        return f"  🔧 {name}  {icon} {row.status}{elapsed}\n"


def _render_error(error_type: str, retryable: bool, *, color: bool) -> str:
    """渲染错误信息为紧凑行内格式。"""

    retry_label = "是" if retryable else "否"
    if color:
        buffer = io.StringIO()
        console = Console(
            file=buffer,
            force_terminal=True,
            color_system="auto",
            no_color=False,
            width=_terminal_width(),
        )
        line = Text("  ⚠ ")
        line.append("Error", style="bold red")
        line.append(f"  {error_type}", style="red")
        line.append(f"  可重试: {retry_label}")
        if retryable:
            line.append("  → 输入 /stop 后重试", style="dim")
        console.print(line)
        return buffer.getvalue()
    line = f"  ⚠ Error  {error_type}  可重试: {retry_label}"
    if retryable:
        line += "  → 输入 /stop 后重试"
    return line + "\n"


def _render_trace(trace_id: str, *, color: bool) -> str:
    """渲染 trace 信息为淡色附加行。"""

    return _render_text_line(f"trace: {trace_id}", style="dim", color=color)


def _render_thinking(*, color: bool) -> str:
    """渲染思考状态提示。"""

    label = "⏳ 思考中..." if color else "思考中..."
    return _render_text_line(label, style="dim", color=color)


def _render_usage(usage: tuple[tuple[str, int], ...], *, color: bool) -> str:
    """渲染 token 使用量统计为淡色附加行。"""

    parts = []
    for key, value in usage:
        if key in (
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_creation_tokens",
        ):
            short = key.replace("_tokens", "").replace("_", " ")
            parts.append(f"{short}={value:,}")
    if not parts:
        return ""
    label = "💡 tokens: " + " | ".join(parts)
    return _render_text_line(label, style="dim", color=color)


def _render_user_input(text: str, *, color: bool) -> str:
    """把提交内容安全渲染为与编辑区一致的静态圆角输入框。"""

    content = Text()
    content.append("你 ▸ ", style="bold cyan" if color else "")
    content.append(text)
    buffer = io.StringIO()
    console = Console(
        file=buffer,
        force_terminal=color,
        color_system="auto" if color else None,
        no_color=not color,
        width=_terminal_width(),
        markup=False,
    )
    console.print(
        Panel(
            content,
            title="输入",
            title_align="left",
            border_style="cyan" if color else "",
            box=box.ROUNDED,
            safe_box=False,
            padding=(0, 1),
            expand=True,
        )
    )
    return buffer.getvalue()


def _render_text_line(text: str, *, style: str, color: bool) -> str:
    return _render_text(Text(text, style=style if color else ""), color=color)


def _render_text(text: Text, *, color: bool) -> str:
    buffer = io.StringIO()
    console = Console(
        file=buffer,
        force_terminal=color,
        color_system="auto" if color else None,
        no_color=not color,
        width=_terminal_width(),
        markup=False,
    )
    console.print(text)
    return buffer.getvalue()


def _terminal_width() -> int:
    """读取当前宿主终端宽度，并为测试/重定向提供稳定回退。"""

    return max(20, shutil.get_terminal_size(fallback=(100, 24)).columns)
