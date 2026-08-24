"""与终端表现无关的 CLI 共享控制器。"""

from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from memoli_agent.agent.context_management import ContextStateRepository
from memoli_agent.agent.memory.governance import MemoryGovernanceService
from memoli_agent.agent.memory.models import MemoryScope
from memoli_agent.agent.session import SessionManager
from memoli_agent.agent.trajectory import TrajectoryStore
from memoli_agent.bootstrap.inspection import RuntimeInspector
from memoli_agent.bus.events import InboundMessage, OutboundMessage
from memoli_agent.bus.queue import MessageBus
from memoli_agent.channels.commands import (
    CommandContext,
    CommandRegistry,
    TurnController,
    build_command_registry,
)


@dataclass(slots=True)
class CLIState:
    """只保存命令和关联所需状态；流式状态归 renderer 所有。"""

    chat_id: str
    last_trace_id: str = ""

    @property
    def session_key(self) -> str:
        return f"cli:{self.chat_id}"


@dataclass(frozen=True, slots=True)
class StartupInfo:
    """结构化启动信息，供 renderer 渲染为美观横幅。"""

    version: str = "unknown"
    session_key: str = ""
    model: str = "unavailable"
    provider: str = "unavailable"
    stream: bool = False
    workspace: str = "unavailable"
    memory: bool = False
    working_memory: bool = False
    skills: bool = False
    mcp: bool = False
    proactive: bool = False


@dataclass(frozen=True, slots=True)
class InputOutcome:
    notice: str = ""
    stop: bool = False
    published: bool = False


class CLIController:
    """统一两种终端模式的命令、背压和消息提交语义。"""

    def __init__(
        self,
        bus: MessageBus,
        *,
        chat_id: str = "local",
        inspector: RuntimeInspector | None = None,
        session_manager: SessionManager | None = None,
        turn_controller: TurnController | None = None,
        queue_limit: int = 8,
        registry: CommandRegistry | None = None,
        memory_governance: MemoryGovernanceService | None = None,
        trajectory_store: TrajectoryStore | None = None,
        context_repository: ContextStateRepository | None = None,
    ) -> None:
        self.bus = bus
        self.state = CLIState(chat_id)
        self.inspector = inspector
        self.turn_controller = turn_controller
        self.queue_limit = queue_limit
        self.registry = registry or build_command_registry()
        self._memory_review_count = 0
        self._memory_review_checked_at = 0.0
        self.context = CommandContext(
            self.state,
            inspector,
            session_manager,
            turn_controller,
            memory_governance,
            trajectory_store,
            context_repository,
        )

    async def handle_input(self, raw_text: str) -> InputOutcome:
        text = raw_text.strip()
        if not text:
            return InputOutcome()
        result = self.registry.route(text, self.context)
        if result.handled:
            return InputOutcome(result.message, result.stop)
        controller = self.turn_controller
        if (
            controller is not None
            and controller.busy
            and controller.queue_depth >= self.queue_limit
        ):
            return InputOutcome(
                f"输入队列已满（{controller.queue_depth}/{self.queue_limit}），"
                "请等待或输入 /stop。"
            )
        await self.bus.publish_inbound(
            InboundMessage(
                channel="cli",
                chat_id=self.state.chat_id,
                sender="user",
                content=result.forwarded_text,
            )
        )
        notice = ""
        if controller is not None and (controller.busy or controller.queue_depth):
            notice = f"已排队，当前 queue={controller.queue_depth}。"
        return InputOutcome(notice, published=True)

    def observe_outbound(self, outbound: OutboundMessage) -> None:
        trace_id = str((outbound.metadata or {}).get("trace_id") or "")
        if trace_id:
            self.state.last_trace_id = trace_id

    def startup_info(self) -> StartupInfo:
        """返回结构化启动信息，供 renderer 渲染为美观横幅。"""

        status = self.inspector.status() if self.inspector else {}
        return StartupInfo(
            version=str(status.get("version", "unknown")),
            session_key=self.state.session_key,
            model=str(status.get("model", "unavailable")),
            provider=str(status.get("provider", "unavailable")),
            stream=bool(status.get("stream")),
            workspace=str(status.get("workspace", "unavailable")),
            memory=bool(status.get("memory")),
            working_memory=bool(status.get("working_memory")),
            skills=bool(status.get("skills")),
            mcp=bool(status.get("mcp")),
            proactive=bool(status.get("proactive")),
        )

    def status_line(self) -> str:
        controller = self.turn_controller
        phase = "busy" if controller is not None and controller.busy else "idle"
        queue = controller.queue_depth if controller is not None else 0
        model = "unavailable"
        workspace = "unavailable"
        working = "unavailable"
        progress = "iteration=unavailable elapsed=unavailable"
        reviews = self._memory_review_count
        if self.inspector is not None:
            view = self.inspector.runtime_view(self.state.session_key)
            model = view.model
            workspace = view.workspace
            snapshot = self.inspector.working_snapshot(self.state.session_key)
            working = snapshot.availability
            if snapshot.runtime_status is not None:
                runtime = snapshot.runtime_status
                progress = (
                    f"iteration={runtime.iteration}/{runtime.max_iterations} "
                    f"elapsed={runtime.elapsed_seconds:.1f}s"
                )
        if (
            self.context.memory_governance is not None
            and monotonic() - self._memory_review_checked_at >= 2.0
        ):
            try:
                reviews = self.context.memory_governance.store.count_needs_user_review(
                    MemoryScope()
                )
            except Exception:
                reviews = self._memory_review_count
            self._memory_review_count = reviews
            self._memory_review_checked_at = monotonic()
        return (
            f"Memoli | {model} | {phase} | queue={queue} | {progress} | "
            f"memory-review={reviews} | working={working} | workspace={workspace} | "
            f"{self.state.session_key}"
        )
