"""CLI 本地命令注册表。

命令在进入 MessageBus 前执行，因此不会调用模型、写入普通会话或创建轨迹。
注册表是路由、帮助和交互补全的唯一事实来源。
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from memoli_agent.agent.context_management import (
    CommittedTurnStore,
    ContextStateRepository,
)
from memoli_agent.agent.memory.governance import MemoryGovernanceService
from memoli_agent.agent.memory.models import MemoryScope
from memoli_agent.agent.session import SessionManager
from memoli_agent.agent.trajectory import TrajectoryStore
from memoli_agent.agent.working.presentation import render_working_card
from memoli_agent.bootstrap.inspection import RuntimeInspector


class CommandState(Protocol):
    """命令可读取的最小前台状态。"""

    chat_id: str
    last_trace_id: str

    @property
    def session_key(self) -> str: ...


class TurnController(Protocol):
    """CLI 可使用的最小 turn 控制边界。"""

    @property
    def busy(self) -> bool: ...

    @property
    def queue_depth(self) -> int: ...

    def cancel_current_turn(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class CommandAvailability:
    available: bool = True
    reason: str = ""


@dataclass(frozen=True, slots=True)
class CommandContext:
    state: CommandState
    inspector: RuntimeInspector | None = None
    session_manager: SessionManager | None = None
    turn_controller: TurnController | None = None
    memory_governance: MemoryGovernanceService | None = None
    # §3.3：/clear 持久推进 epoch 与重置派生 context 状态所需的最小依赖。
    trajectory_store: TrajectoryStore | None = None
    context_repository: ContextStateRepository | None = None


@dataclass(frozen=True, slots=True)
class CommandResult:
    handled: bool
    message: str = ""
    stop: bool = False
    forwarded_text: str = ""


CommandHandler = Callable[[CommandContext, str], CommandResult]
AvailabilityCheck = Callable[[CommandContext], CommandAvailability]


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    description: str
    handler: CommandHandler
    category: str = "常用"
    aliases: tuple[str, ...] = ()
    args_hint: str = ""
    availability: AvailabilityCheck | None = None

    def __post_init__(self) -> None:
        if not self.name.startswith("/") or " " in self.name:
            raise ValueError(f"命令名无效：{self.name}")
        for alias in self.aliases:
            if not alias.startswith("/") or " " in alias:
                raise ValueError(f"命令别名无效：{alias}")


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    raw: str
    name: str
    arguments: str = ""
    literal_slash: bool = False


class CommandRegistry:
    """不可变命令定义的稳定注册、解析和展示。"""

    def __init__(self, specs: Iterable[CommandSpec] = ()) -> None:
        self._specs: list[CommandSpec] = []
        self._lookup: dict[str, CommandSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: CommandSpec) -> None:
        identifiers = (spec.name, *spec.aliases)
        for identifier in identifiers:
            key = identifier.casefold()
            if key in self._lookup:
                other = self._lookup[key]
                raise ValueError(
                    f"CLI 命令冲突：{identifier} 同时属于 {other.name} 和 {spec.name}"
                )
        self._specs.append(spec)
        for identifier in identifiers:
            self._lookup[identifier.casefold()] = spec

    def specs(self) -> tuple[CommandSpec, ...]:
        return tuple(
            sorted(
                self._specs,
                key=lambda item: (item.category.casefold(), item.name.casefold()),
            )
        )

    def parse(self, text: str) -> ParsedCommand | None:
        if text.startswith("//"):
            return ParsedCommand(text, "", text[1:], literal_slash=True)
        if not text.startswith("/"):
            return None
        name, _, arguments = text.partition(" ")
        return ParsedCommand(text, name.casefold(), arguments.strip())

    def resolve(self, name: str) -> CommandSpec | None:
        return self._lookup.get(name.casefold())

    def candidates(
        self, prefix: str, context: CommandContext
    ) -> tuple[CommandSpec, ...]:
        normalized = prefix.casefold()
        matches: list[CommandSpec] = []
        for spec in self.specs():
            identifiers = (spec.name, *spec.aliases)
            if any(
                identifier.casefold().startswith(normalized)
                for identifier in identifiers
            ):
                matches.append(spec)
        return tuple(matches)

    def route(self, text: str, context: CommandContext) -> CommandResult:
        parsed = self.parse(text)
        if parsed is None:
            return CommandResult(False, forwarded_text=text)
        if parsed.literal_slash:
            return CommandResult(False, forwarded_text=parsed.arguments)
        spec = self.resolve(parsed.name)
        if spec is None:
            return CommandResult(
                True,
                f"未知命令：{parsed.name}。输入 /help 查看帮助。",
            )
        availability = (
            spec.availability(context)
            if spec.availability is not None
            else CommandAvailability()
        )
        if not availability.available:
            return CommandResult(
                True, f"{spec.name} unavailable：{availability.reason}"
            )
        return spec.handler(context, parsed.arguments)

    def render_help(self, context: CommandContext) -> str:
        """使用 Rich Table 渲染美化帮助信息。"""

        buffer = io.StringIO()
        console = Console(file=buffer, force_terminal=True, width=100)
        console.rule("Memoli 命令帮助", style="cyan")

        current_category = ""
        table: Table | None = None
        for spec in self.specs():
            if spec.category != current_category:
                current_category = spec.category
                # 用独立局部构造表：Table 构造可能不被 pyright 收窄为非 None，
                # 直接对声明为 ``Table | None`` 的 ``table`` 调 ``add_column`` 会触发
                # reportOptionalMemberAccess；``new_table`` 无 Optional 声明故安全。
                new_table = Table(
                    show_header=True,
                    header_style="bold",
                    border_style="dim",
                    title=f"[{current_category}]",
                    title_style="bold cyan",
                    padding=(0, 1),
                    width=100,
                )
                new_table.add_column("命令", style="cyan", width=24)
                new_table.add_column("说明", width=36)
                new_table.add_column("别名", style="dim", width=18)
                new_table.add_column("状态", width=18)
                table = new_table

            aliases = ", ".join(spec.aliases) if spec.aliases else ""
            availability = (
                spec.availability(context)
                if spec.availability is not None
                else CommandAvailability()
            )
            args = f" {spec.args_hint}" if spec.args_hint else ""
            command_display = escape(f"{spec.name}{args}")
            status = (
                "" if availability.available else f"unavailable: {availability.reason}"
            )
            assert table is not None
            table.add_row(
                command_display,
                spec.description,
                aliases,
                f"[dim]{escape(status)}[/]" if status else "",
            )

            # 检查是否下一个 spec 属于不同分类，如果是则输出当前表格
            next_specs = self.specs()
            idx = list(next_specs).index(spec)
            is_last_in_category = (
                idx == len(next_specs) - 1
                or next_specs[idx + 1].category != current_category
            )
            if is_last_in_category:
                assert table is not None
                console.print(table)
                console.print()

        console.print("[dim]以 // 开头可向模型发送字面 /。[/]")
        return buffer.getvalue()


def build_command_registry() -> CommandRegistry:
    """创建 Memoli 的默认命令集合。"""

    registry = CommandRegistry()

    def add(
        name: str,
        description: str,
        handler: CommandHandler,
        *,
        category: str = "常用",
        aliases: tuple[str, ...] = (),
        args_hint: str = "",
        availability: AvailabilityCheck | None = None,
    ) -> None:
        registry.register(
            CommandSpec(
                name,
                description,
                handler,
                category,
                aliases,
                args_hint,
                availability,
            )
        )

    add(
        "/help",
        "显示此帮助",
        lambda ctx, _: CommandResult(True, registry.render_help(ctx)),
    )
    add("/status", "显示非敏感 Runtime 状态", _status)
    add("/checkpoint", "显示当前工作 checkpoint", _checkpoint, aliases=("/working",))
    add("/trace", "显示最近一次 trace", _trace)
    add(
        "/clear",
        "清除当前进程的短期对话",
        _clear,
        availability=_clear_available,
    )
    add("/stop", "停止当前任务", _stop, availability=None)
    add("/exit", "退出", _exit, aliases=("/quit",))
    add(
        "/workspace",
        "检查当前 workspace",
        _workspace,
        category="组件",
        args_hint="[新路径]",
    )
    add("/model", "检查当前模型", _model, category="组件", args_hint="[模型]")
    add("/tools", "检查工具可用性", _tools, category="组件", args_hint="[配置]")
    add(
        "/memory",
        "Inspect memory or review offline candidates",
        _memory,
        category="组件",
        args_hint="[candidates|show|approve|reject]",
    )
    add("/skills", "检查 Skill catalog", _skills, category="组件", args_hint="[配置]")
    add(
        "/context",
        "显示上下文分层诊断（epoch/压缩/各层/frontier/熔断/outbox）",
        _context,
        category="组件",
    )
    return registry


def _inspection_argument(
    name: str, arguments: str, guidance: str
) -> CommandResult | None:
    if not arguments:
        return None
    return CommandResult(
        True,
        f"{name} 首版只读，不支持运行时切换。请修改 config.toml 的 "
        f"{guidance} 后重启 memoli。",
    )


def _status(ctx: CommandContext, arguments: str) -> CommandResult:
    if arguments:
        return CommandResult(True, "/status 不接受参数。")
    if ctx.inspector is None:
        return CommandResult(True, "Runtime status: unavailable")
    try:
        return CommandResult(True, ctx.inspector.render_status())
    except Exception:
        return CommandResult(True, "Runtime status: unavailable")


def _checkpoint(ctx: CommandContext, arguments: str) -> CommandResult:
    if arguments:
        return CommandResult(True, "/checkpoint 不接受参数。")
    if ctx.inspector is None:
        return CommandResult(True, "工作状态: unavailable")
    return CommandResult(
        True, render_working_card(ctx.inspector.working_snapshot(ctx.state.session_key))
    )


def _trace(ctx: CommandContext, arguments: str) -> CommandResult:
    if arguments:
        return CommandResult(True, "/trace 不接受参数。")
    return CommandResult(True, "trace: " + (ctx.state.last_trace_id or "unavailable"))


def _clear_available(ctx: CommandContext) -> CommandAvailability:
    """活动 turn 期间拒绝 /clear（§3.3）。"""

    controller = ctx.turn_controller
    if controller is not None and controller.busy:
        return CommandAvailability(
            available=False,
            reason="活动 turn 期间不可清理，请先 /stop 或等待完成。",
        )
    return CommandAvailability()


def _clear(ctx: CommandContext, arguments: str) -> CommandResult:
    """推进 conversation epoch 并重置派生 context 状态（§3.3）。

    成功：持久创建新 epoch（trajectory store）+ 重置派生 snapshot/frontier/preview
    可见状态（context_repository）+ 同步进程内 epoch 镜像。失败（store 不可用或
    推进失败）：保持旧 epoch，绝不只清内存后声称对话已清理。轨迹、payload、
    长期记忆与 working-state 各自保留策略不受影响（§3.4）。
    """

    if arguments:
        return CommandResult(True, "/clear 不接受参数。")
    store = ctx.trajectory_store
    advance = getattr(store, "advance_epoch", None) if store is not None else None
    if advance is None:
        return CommandResult(
            True,
            "未装配持久 epoch 存储，已保持旧 epoch；"
            "checkpoint、长期记忆和轨迹未删除。",
        )
    try:
        new_epoch = advance(ctx.state.session_key)
    except Exception:
        return CommandResult(
            True,
            "无法持久创建新 conversation epoch，已保持旧 epoch；"
            "checkpoint、长期记忆和轨迹未删除。",
        )
    # 重置派生 context 状态：snapshot/frontier/preview/diagnostics（§3.4）。
    # §5.6：失败计数按 session 维度持久化，reset_session 重置失败会令旧 epoch
    # 计数残留、可能让新 epoch 首次 emergency 误触熔断。重置失败不回滚已推进的
    # epoch（新 epoch 对旧派生状态本就不可见），但必须显式报告，不静默吞。
    reset_failed = False
    if ctx.context_repository is not None:
        try:
            ctx.context_repository.reset_session(ctx.state.session_key)
            # §7.4 preview 派生索引 epoch 清理：把早于新 epoch 的冻结预览标记
            # 不可见（不删，保留审计/可重建派生索引）。原始 payload 由 trajectory
            # 独立保留，不受影响（design line 91）。reset_session 已不删 previews，
            # 故此处负责派生索引的可见性清理。
            ctx.context_repository.clear_epoch_previews(
                ctx.state.session_key, before_epoch=new_epoch
            )
        except Exception:
            reset_failed = True
    # 同步进程内 epoch 镜像；权威值仍由 trajectory store 决定。
    if ctx.session_manager is not None:
        session = ctx.session_manager.get_or_create(ctx.state.session_key)
        session.conversation_epoch = new_epoch
    if reset_failed:
        return CommandResult(
            True,
            "已创建新 conversation epoch，但派生上下文状态重置失败"
            "（失败计数可能残留）；checkpoint、长期记忆和轨迹未删除，"
            "可再次 /clear 重试重置。",
        )
    return CommandResult(
        True,
        "已创建新 conversation epoch 并重置派生上下文状态；"
        "checkpoint、长期记忆和轨迹未删除。",
    )


def _stop(ctx: CommandContext, arguments: str) -> CommandResult:
    if arguments:
        return CommandResult(True, "/stop 不接受参数。")
    if ctx.turn_controller is None or not ctx.turn_controller.cancel_current_turn():
        return CommandResult(True, "当前没有可停止的任务。")
    return CommandResult(True, "正在停止当前任务……")


def _exit(_: CommandContext, arguments: str) -> CommandResult:
    if arguments:
        return CommandResult(True, "/exit 不接受参数。")
    return CommandResult(True, "再见。", stop=True)


def _workspace(ctx: CommandContext, arguments: str) -> CommandResult:
    rejected = _inspection_argument("/workspace", arguments, "runtime.workspace")
    if rejected:
        return rejected
    return _inspect(ctx, "workspace")


def _model(ctx: CommandContext, arguments: str) -> CommandResult:
    rejected = _inspection_argument("/model", arguments, "llm")
    if rejected:
        return rejected
    return _inspect(ctx, "model")


def _tools(ctx: CommandContext, arguments: str) -> CommandResult:
    rejected = _inspection_argument("/tools", arguments, "tools")
    if rejected:
        return rejected
    return _inspect(ctx, "tools")


def _memory(ctx: CommandContext, arguments: str) -> CommandResult:
    if not arguments:
        return _inspect(ctx, "memory", session_key=ctx.state.session_key)
    service = ctx.memory_governance
    if service is None:
        return CommandResult(True, "memory governance: unavailable")
    parts = arguments.split()
    action = parts[0].casefold()
    scope = MemoryScope()
    try:
        if action == "candidates":
            rows = service.list_candidates(scope, limit=20)
            if not rows:
                return CommandResult(True, "No candidates need review.")
            lines = [f"Offline candidates ({len(rows)}):"]
            lines.extend(
                f"- {row['claim_id']} rev={row['revision']} "
                f"state={row.get('governance_state', 'pending')} "
                f"{str(row.get('content', ''))[:120]}"
                for row in rows
            )
            return CommandResult(True, "\n".join(lines))
        if action == "show" and len(parts) == 2:
            return CommandResult(
                True,
                json.dumps(
                    service.show_candidate(parts[1], scope),
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        if action == "recovery" and len(parts) == 1:
            return CommandResult(
                True,
                json.dumps(service.list_recovery(scope), ensure_ascii=False, indent=2),
            )
        if action == "retry-job" and len(parts) in {2, 3}:
            if len(parts) != 3 or parts[2].casefold() != "confirm":
                return CommandResult(
                    True,
                    f"Confirmation required: /memory retry-job {parts[1]} confirm",
                )
            return CommandResult(
                True,
                json.dumps(
                    service.retry_job(parts[1], scope), ensure_ascii=False, indent=2
                ),
            )
        if action in {"retry-request", "suppress-request"} and len(parts) in {2, 3}:
            if len(parts) != 3 or parts[2].casefold() != "confirm":
                return CommandResult(
                    True,
                    f"Confirmation required: /memory {action} {parts[1]} confirm",
                )
            return CommandResult(
                True,
                json.dumps(
                    service.recover_request(
                        parts[1],
                        scope,
                        action="retry" if action == "retry-request" else "suppress",
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        if action in {"approve", "reject"} and len(parts) in {3, 4}:
            if len(parts) != 4 or parts[3].casefold() != "confirm":
                return CommandResult(
                    True,
                    f"Confirmation required: /memory {action} "
                    f"{parts[1]} {parts[2]} confirm",
                )
            audit = service.decide_user(
                parts[1],
                scope,
                decision_kind=action,
                expected_revision=int(parts[2]),
                actor=f"user:{ctx.state.session_key}",
            )
            return CommandResult(
                True,
                f"candidate={audit.candidate_id} outcome={audit.outcome} "
                f"revision={audit.actual_revision} decision={audit.decision_id}",
            )
    except (KeyError, PermissionError, RuntimeError, TypeError, ValueError) as exc:
        return CommandResult(True, f"memory governance failed: {type(exc).__name__}")
    return CommandResult(
        True,
        "Usage: /memory candidates | /memory show <id> | "
        "/memory approve|reject <id> <revision> confirm | /memory recovery | "
        "/memory retry-job|retry-request|suppress-request <id> confirm",
    )


def _skills(ctx: CommandContext, arguments: str) -> CommandResult:
    rejected = _inspection_argument("/skills", arguments, "skills")
    if rejected:
        return rejected
    return _inspect(ctx, "skills", session_key=ctx.state.session_key)


def _inspect(ctx: CommandContext, view: str, *, session_key: str = "") -> CommandResult:
    if ctx.inspector is None:
        return CommandResult(True, f"{view}: unavailable")
    try:
        return CommandResult(
            True, ctx.inspector.render_view(view, session_key=session_key)
        )
    except Exception:
        return CommandResult(True, f"{view}: unavailable")


def _sync_epoch(ctx: CommandContext, session_key: str) -> int:
    """§8.2 同步读取当前 conversation epoch（命令派发期纯读，不改写状态）。

    优先用 trajectory store 的同步只读镜像（与 ``/clear`` 的同步 ``advance_epoch``
    同前提：事件循环被阻塞、此刻无 Reasoner 写入）；不可用则回退到进程内 Session
    epoch 镜像，最后回退 1。任何异常都降级为默认值，不让诊断命令失败。
    """

    store = ctx.trajectory_store
    reader = (
        getattr(store, "current_epoch_sync", None) if store is not None else None
    )
    if reader is not None:
        try:
            return int(reader(session_key))
        except Exception:
            pass
    if ctx.session_manager is not None:
        try:
            return int(
                ctx.session_manager.get_or_create(session_key).conversation_epoch
            )
        except Exception:
            pass
    return 1


def _derive_recovery(ctx: CommandContext) -> tuple[str, bool]:
    """§8.2 同步推导「恢复能力」：轨迹是否为 durable committed store + capture 模式。

    返回 ``(restoration 标签, restorable)``。不查每 turn 的 exact/governed/legacy
    等级（那是 ContextSource 的异步能力、且留在 trace 审计层，§8.2 只显示能力 +
    降级原因）。规则对齐 design line 97「恢复能力」+ §2.6：轨迹关闭/metadata-only/
    不可读 → restorable=false。
    """

    store = ctx.trajectory_store
    if store is None or not isinstance(store, CommittedTurnStore):
        # 轨迹关闭（NullTrajectoryStore）或非 durable：隔离来源，不可跨重启恢复。
        return ("unavailable", False)
    capture = (
        ctx.inspector.config.trajectory.capture_content
        if ctx.inspector is not None
        else "redacted"
    )
    if capture == "metadata-only":
        # §2.6：metadata-only 仅留事件元数据，无法重建可见内容 → restorable=false。
        return ("metadata-only", False)
    if capture == "full-local":
        return ("full-local", True)
    # redacted（默认）：durable + 可读，内容脱敏但 turn 结构可恢复 → restorable=true。
    return ("redacted", True)


def _context(ctx: CommandContext, arguments: str) -> CommandResult:
    """§8.2 渲染上下文分层诊断（epoch/恢复等级/pre-post ratio/各层预算/frontier/
    压缩模式/熔断/outbox 状态）。仅哈希/计数/稳定原因，不含 payload/API key/隐藏
    reasoning/embedding（§8.3 安全）。"""

    if arguments:
        return CommandResult(True, "/context 不接受参数。")
    if ctx.inspector is None:
        return CommandResult(True, "context: unavailable")
    session_key = ctx.state.session_key
    epoch = _sync_epoch(ctx, session_key)
    restoration, restorable = _derive_recovery(ctx)
    try:
        return CommandResult(
            True,
            ctx.inspector.render_context(
                session_key,
                epoch=epoch,
                restoration=restoration,
                restorable=restorable,
            ),
        )
    except Exception:
        return CommandResult(True, "context: unavailable")
