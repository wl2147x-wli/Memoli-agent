import json
import os
import sys
import time

from bridge.context import *
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel, check_prefix
from channel.chat_message import ChatMessage
from common.log import logger
from config import conf


class _Style:
    """ANSI escape codes for terminal styling. Disabled when not a tty."""

    enabled = sys.stdout.isatty()

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"

    GRAY = "\033[90m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"

    @classmethod
    def wrap(cls, text, *codes):
        if not cls.enabled or not codes:
            return text
        return "".join(codes) + text + cls.RESET


class TerminalAgentRenderer:
    """Render agent stream events to the terminal in real time.

    Reuses the same `on_event` mechanism as the web channel so the terminal
    can show reasoning, tool calls and streaming answer text just like the web UI.
    """

    def __init__(self):
        self._reasoning_active = False
        self._answer_active = False
        self._has_output = False
        # 当事件忽略时，跟踪工具执行开始时间作为后备
        self._tool_started_at = {}

    def _print(self, text, end="", flush=True):
        sys.stdout.write(text)
        if end:
            sys.stdout.write(end)
        if flush:
            sys.stdout.flush()
        self._has_output = True

    def _close_section(self):
        """Finish the currently open streaming section (reasoning or answer)."""
        if self._reasoning_active:
            self._print("", end="\n")
            self._reasoning_active = False
        if self._answer_active:
            self._print("", end="\n")
            self._answer_active = False

    def _format_arguments(self, arguments):
        try:
            if isinstance(arguments, (dict, list)):
                text = json.dumps(arguments, ensure_ascii=False)
            else:
                text = str(arguments)
        except Exception:
            text = str(arguments)
        # 保持终端中的工具输入紧凑
        if len(text) > 300:
            text = text[:300] + "…"
        return text

    def handle_event(self, event: dict):
        try:
            self._handle_event(event)
        except Exception as e:
            logger.debug(f"[Terminal] render event error: {e}")

    def _handle_event(self, event: dict):
        event_type = event.get("type")
        data = event.get("data", {}) or {}

        if event_type == "agent_start":
            self._print("\n" + _Style.wrap("Agent: ", _Style.BOLD, _Style.GREEN), end="\n")

        elif event_type == "reasoning_update":
            delta = data.get("delta", "")
            if not delta:
                return
            if self._answer_active:
                self._close_section()
            if not self._reasoning_active:
                self._print(_Style.wrap("💭 思考  ", _Style.DIM, _Style.MAGENTA), end="\n")
                self._reasoning_active = True
            self._print(_Style.wrap(delta, _Style.DIM, _Style.ITALIC))

        elif event_type == "message_update":
            delta = data.get("delta", "")
            if not delta:
                return
            if self._reasoning_active:
                self._close_section()
            self._answer_active = True
            self._print(delta)

        elif event_type == "tool_execution_start":
            self._close_section()
            tool_name = data.get("tool_name", "tool")
            tool_id = data.get("tool_call_id")
            arguments = data.get("arguments", {})
            self._tool_started_at[tool_id] = time.time()
            header = _Style.wrap(f"🔧 {tool_name}", _Style.BOLD, _Style.CYAN)
            args_str = self._format_arguments(arguments)
            self._print(f"{header} {_Style.wrap(args_str, _Style.GRAY)}", end="\n")

        elif event_type == "tool_execution_end":
            tool_name = data.get("tool_name", "tool")
            tool_id = data.get("tool_call_id")
            status = data.get("status", "success")
            result = data.get("result", "")
            exec_time = data.get("execution_time")
            if exec_time is None and tool_id in self._tool_started_at:
                exec_time = time.time() - self._tool_started_at.pop(tool_id, time.time())
            success = status == "success"
            icon = "✓" if success else "✗"
            color = _Style.GREEN if success else _Style.RED
            result_str = str(result)
            if len(result_str) > 500:
                result_str = result_str[:500] + "…"
            # 缩进多行工具输出以提高可读性
            result_str = result_str.replace("\n", "\n   ")
            cost = f" ({exec_time:.2f}s)" if isinstance(exec_time, (int, float)) else ""
            self._print(
                _Style.wrap(f"   {icon} {tool_name}{cost}", color) + "  " + _Style.wrap(result_str, _Style.GRAY),
                end="\n",
            )

        elif event_type == "file_to_send":
            self._close_section()
            file_path = data.get("path", "")
            file_name = data.get("file_name", "")
            label = file_name or file_path
            self._print(_Style.wrap(f"📎 文件: {label}", _Style.BLUE), end="\n")

        elif event_type == "error":
            self._close_section()
            err_msg = data.get("error") or "unknown error"
            self._print(_Style.wrap(f"❌ {err_msg}", _Style.BOLD, _Style.RED), end="\n")

        elif event_type == "agent_cancelled":
            self._close_section()
            self._print(_Style.wrap("⏹ 已中止", _Style.YELLOW), end="\n")

        elif event_type == "agent_end":
            self._close_section()

    def finish(self):
        """Ensure any open section is closed at the end of a turn."""
        self._close_section()


class TerminalMessage(ChatMessage):
    def __init__(
        self,
        msg_id,
        content,
        ctype=ContextType.TEXT,
        from_user_id="User",
        to_user_id="Chatgpt",
        other_user_id="Chatgpt",
    ):
        self.msg_id = msg_id
        self.ctype = ctype
        self.content = content
        self.from_user_id = from_user_id
        self.to_user_id = to_user_id
        self.other_user_id = other_user_id


class TerminalChannel(ChatChannel):
    NOT_SUPPORT_REPLYTYPE = [ReplyType.VOICE]

    def __init__(self):
        super().__init__()
        # 按 request_id 键控的每个请求渲染器；用于检测是否
        # 代理文本已经流式传输，因此 send() 可以避免重复输出。
        self._renderers = {}
        # 退出时恢复 TTY 属性的回调（在启动时设置）。
        self._restore_terminal = None

    def send(self, reply: Reply, context: Context):
        request_id = context.get("request_id") if context else None
        renderer = self._renderers.pop(request_id, None) if request_id else None
        streamed = renderer is not None and renderer._has_output

        if renderer is not None:
            renderer.finish()

        if reply.type == ReplyType.IMAGE:
            from PIL import Image

            image_storage = reply.content
            image_storage.seek(0)
            img = Image.open(image_storage)
            if not streamed:
                print("\nAgent: ")
            print("<IMAGE>")
            img.show()
        elif reply.type == ReplyType.IMAGE_URL:  # 从 url 下载图像
            import io

            import requests
            from PIL import Image

            img_url = reply.content
            pic_res = requests.get(img_url, stream=True)
            image_storage = io.BytesIO()
            for block in pic_res.iter_content(1024):
                image_storage.write(block)
            image_storage.seek(0)
            img = Image.open(image_storage)
            if not streamed:
                print("\nAgent: ")
            print(img_url)
            img.show()
        else:
            # 当客服人员已经流式传输答案时，跳过重新打印答案
            # 最终文本以避免重复；只是发出一个尾随换行符。
            if streamed:
                print()
            else:
                print("\nAgent: ")
                print(reply.content)
        print("\nUser: ", end="")
        sys.stdout.flush()
        return

    def _silence_console_logging(self):
        """Mute console log output so background-thread logs (web/MCP/scheduler)
        don't flood the interactive terminal. Logs still go to run.log in full.

        Configurable via `terminal_log_level` (default ERROR). The file handler
        is untouched, so run.log keeps the complete log.
        """
        import logging

        level_name = str(conf().get("terminal_log_level", "ERROR")).upper()
        level = getattr(logging, level_name, logging.ERROR)
        root_logger = logging.getLogger("log")
        for handler in root_logger.handlers:
            # 仅提高 stdout/stderr 流处理程序的级别；
            # 将 FileHandler 保持在记录器级别，以便 run.log 保持完整。
            if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
                handler.setLevel(level)

    def _install_terminal_guard(self):
        """Save TTY attributes and register restore hooks so the terminal is
        never left in a broken state (no echo / raw mode / leftover ANSI) after
        the process exits, especially when Ctrl+C interrupts a blocking input().
        """
        if not sys.stdin.isatty():
            return
        try:
            import atexit
            import termios

            saved_attrs = termios.tcgetattr(sys.stdin.fileno())

            def _restore():
                try:
                    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, saved_attrs)
                except Exception:
                    pass
                try:
                    if _Style.enabled:
                        sys.stdout.write(_Style.RESET)
                        sys.stdout.flush()
                except Exception:
                    pass

            self._restore_terminal = _restore
            atexit.register(_restore)
        except Exception as e:
            # termios 在 Windows 上不可用；跳过那里的守卫。
            logger.debug(f"[Terminal] terminal guard not installed: {e}")
            self._restore_terminal = None

    def startup(self):
        context = Context()
        self._silence_console_logging()
        self._install_terminal_guard()
        print("\nPlease input your question:\nUser: ", end="")
        sys.stdout.flush()
        msg_id = 0
        while True:
            try:
                prompt = self.get_input()
            except (KeyboardInterrupt, EOFError):
                self._shutdown()
            msg_id += 1
            trigger_prefixs = conf().get("single_chat_prefix", [""])
            if check_prefix(prompt, trigger_prefixs) is None:
                prompt = trigger_prefixs[0] + prompt  # 为未触发的消息添加触发前缀

            context = self._compose_context(ContextType.TEXT, prompt, msg=TerminalMessage(msg_id, prompt))
            context["isgroup"] = False
            if context:
                # 附加一个代理事件渲染器以便推理/工具调用/
                # 流式答案实时显示在终端中（类似网络的用户体验）。
                request_id = str(msg_id)
                context["request_id"] = request_id
                renderer = TerminalAgentRenderer()
                self._renderers[request_id] = renderer
                context["on_event"] = renderer.handle_event
                self.produce(context)
            else:
                raise Exception("context is None")

    def _shutdown(self):
        """Restore terminal state and terminate the whole process.

        startup() runs in a daemon sub-thread, so sys.exit() would only kill
        this thread and leave the main process (and web/MCP/scheduler threads)
        alive, holding the terminal in a half-occupied state -> laggy input.
        We reset any leftover ANSI styling and hard-exit the process instead.
        """
        # 恢复 TTY 属性并重置任何剩余的 ANSI 样式
        # （例如，中断的中流输出）在终止之前。
        if self._restore_terminal:
            self._restore_terminal()
        elif _Style.enabled:
            sys.stdout.write(_Style.RESET)
        sys.stdout.write("\nExiting...\n")
        sys.stdout.flush()
        # 从守护线程中硬退出整个进程。
        os._exit(0)

    def get_input(self):
        """
        Multi-line input function
        """
        sys.stdout.flush()
        line = input()
        return line
