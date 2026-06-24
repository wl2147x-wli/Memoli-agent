"""通道装配模块。

第二阶段只装配 CLI 通道。后续如果增加 IPC、WebSocket 或其他通道，
也应优先在这里统一启动，而不是把通道启动逻辑散落到 main.py。
"""

from __future__ import annotations

from memoli_agent.bootstrap.config import AppConfig
from memoli_agent.bus.queue import MessageBus
from memoli_agent.channels.cli import run_cli


async def run_configured_channels(config: AppConfig, bus: MessageBus) -> None:
    """根据配置启动已启用的消息通道。"""

    if config.channels.cli.enabled:
        await run_cli(bus)
        return

    print("CLI 通道已在配置中关闭，当前没有可运行的输入通道。", flush=True)
