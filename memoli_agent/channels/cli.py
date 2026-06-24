"""最小 CLI 通道。

第十阶段开始，CLI 同时运行输入任务和输出任务：

- 输入任务负责读取终端输入并发布 InboundMessage。
- 输出任务持续消费 OutboundMessage，因此主动消息也能自动显示。
"""

from __future__ import annotations

import asyncio
from contextlib import suppress

from memoli_agent.bus.events import InboundMessage
from memoli_agent.bus.queue import MessageBus


async def run_cli(bus: MessageBus) -> None:
    """运行命令行交互循环。"""

    print("Memoli-agent 已启动。输入 /exit 或 /quit 退出。", flush=True)

    stop_event = asyncio.Event()
    output_task = asyncio.create_task(
        _print_outbound_loop(bus, stop_event),
        name="cli_output",
    )

    try:
        await _read_input_loop(bus, stop_event)
    finally:
        stop_event.set()
        output_task.cancel()
        with suppress(asyncio.CancelledError):
            await output_task


async def _read_input_loop(bus: MessageBus, stop_event: asyncio.Event) -> None:
    """读取用户输入并发布到入站队列。"""

    while not stop_event.is_set():
        text = (await asyncio.to_thread(input, "> ")).strip()

        if not text:
            continue

        if text in {"/exit", "/quit"}:
            print("再见。", flush=True)
            stop_event.set()
            return

        await bus.publish_inbound(
            InboundMessage(
                channel="cli",
                chat_id="local",
                sender="user",
                content=text,
            )
        )


async def _print_outbound_loop(
    bus: MessageBus,
    stop_event: asyncio.Event,
) -> None:
    """持续打印出站消息。"""

    while not stop_event.is_set():
        outbound = await bus.consume_outbound()
        print(outbound.content, flush=True)
