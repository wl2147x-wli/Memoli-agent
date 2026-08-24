"""CLI 终端 I/O 适配器合同与最小 plain 实现。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol


class CLIAdapter(Protocol):
    async def start(self) -> None: ...

    async def read(self) -> str: ...

    def write(self, text: str) -> None: ...

    async def close(self) -> None: ...


class PlainCLIAdapter:
    """无 ANSI、无动画的逐行 fallback。"""

    def __init__(
        self,
        input_reader: Callable[[str], str] = input,
        writer: Callable[..., None] = print,
    ) -> None:
        self.input_reader = input_reader
        self.writer = writer

    async def start(self) -> None:
        return None

    async def read(self) -> str:
        def read_line() -> str:
            try:
                return self.input_reader("你 > ")
            except StopIteration as exc:
                # StopIteration 不能直接进入 asyncio Future，否则 Future 会挂起。
                raise EOFError from exc

        return await asyncio.to_thread(read_line)

    def write(self, text: str) -> None:
        self.writer(text, end="", flush=True)

    async def close(self) -> None:
        return None
