"""不触发 Runtime/Provider 的终端能力探测。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TextIO

from memoli_agent.bootstrap.config import CLIChannelConfig


@dataclass(frozen=True, slots=True)
class TerminalCapabilities:
    interactive: bool
    color: bool
    utf8: bool
    reason: str = ""


def detect_terminal_capabilities(
    config: CLIChannelConfig,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    environ: dict[str, str] | None = None,
) -> TerminalCapabilities:
    env = os.environ if environ is None else environ
    stdin_tty = bool(getattr(stdin, "isatty", lambda: False)())
    stdout_tty = bool(getattr(stdout, "isatty", lambda: False)())
    interactive = config.interactive and stdin_tty and stdout_tty
    reason = ""
    if not config.interactive:
        reason = "interactive-disabled"
    elif not stdin_tty or not stdout_tty:
        reason = "non-tty"
    no_color = "NO_COLOR" in env
    color = config.color == "always" or (
        config.color == "auto" and stdout_tty and not no_color
    )
    if config.color == "never" or no_color:
        color = False
    encoding = str(getattr(stdout, "encoding", "") or "").lower().replace("-", "")
    utf8 = encoding in {"utf8", "utf_8"} or sys.platform != "win32"
    return TerminalCapabilities(interactive, color, utf8, reason)


def initialize_utf8_terminal(
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    platform: str = sys.platform,
) -> bool:
    """在 Windows 增强终端启动时显式使用 UTF-8；失败时允许调用方降级。"""

    if platform != "win32":
        return True
    try:
        for stream in (stdin, stdout):
            reconfigure = getattr(stream, "reconfigure", None)
            if callable(reconfigure):
                reconfigure(encoding="utf-8", errors="replace")
        if not bool(getattr(stdout, "isatty", lambda: False)()):
            return True
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        if not kernel32.SetConsoleCP(65001) or not kernel32.SetConsoleOutputCP(65001):
            return False
        return True
    except (AttributeError, OSError, ValueError):
        return False
