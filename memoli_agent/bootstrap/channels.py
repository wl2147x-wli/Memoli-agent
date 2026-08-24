"""通道装配模块。

第二阶段只装配 CLI 通道。后续如果增加 IPC、WebSocket 或其他通道，
也应优先在这里统一启动，而不是把通道启动逻辑散落到 main.py。
"""

from __future__ import annotations

from memoli_agent.agent.context_management import ContextStateRepository
from memoli_agent.agent.memory.governance import MemoryGovernanceService
from memoli_agent.agent.session import SessionManager
from memoli_agent.agent.trajectory import TrajectoryStore
from memoli_agent.bootstrap.config import AppConfig
from memoli_agent.bootstrap.inspection import RuntimeInspector
from memoli_agent.bus.queue import MessageBus
from memoli_agent.channels.cli import run_cli
from memoli_agent.channels.commands import TurnController
from memoli_agent.presentation.events import PresentationEventHub


async def run_configured_channels(
    config: AppConfig,
    bus: MessageBus,
    *,
    chat_id: str = "local",
    inspector: RuntimeInspector | None = None,
    session_manager: SessionManager | None = None,
    presentation_events: PresentationEventHub | None = None,
    turn_controller: TurnController | None = None,
    memory_governance: MemoryGovernanceService | None = None,
    trajectory_store: TrajectoryStore | None = None,
    context_repository: ContextStateRepository | None = None,
) -> None:
    """根据配置启动已启用的消息通道。"""

    if config.channels.cli.enabled:
        await run_cli(
            bus,
            chat_id=chat_id,
            inspector=inspector,
            session_manager=session_manager,
            presentation_events=presentation_events,
            turn_controller=turn_controller,
            cli_config=config.channels.cli,
            memory_governance=memory_governance,
            trajectory_store=trajectory_store,
            context_repository=context_repository,
        )
        return

    print("CLI 通道已在配置中关闭，当前没有可运行的输入通道。", flush=True)
