"""Runtime 向本地表现层暴露的只读、安全检查接口。"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from memoli_agent.agent.context_management import ContextCompiler
from memoli_agent.agent.skills.runtime import SkillRuntime
from memoli_agent.agent.tools.control import WorkingStateStore
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.working.models import WorkingStateSnapshot
from memoli_agent.bootstrap.config import AppConfig


@dataclass(frozen=True, slots=True)
class RuntimeView:
    schema_version: int
    version: str
    provider: str
    model: str
    stream: bool
    workspace: str
    session_key: str
    busy: bool
    queue_depth: int
    features: tuple[tuple[str, bool], ...]


@dataclass(frozen=True, slots=True)
class ToolView:
    name: str
    available: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RuntimeInspector:
    """只返回不可变 DTO/文本，不暴露可变组件实例。"""

    config: AppConfig
    working_state: WorkingStateStore | None
    tool_registry: ToolRegistry | None = None
    turn_controller: Any | None = None
    skill_runtime: SkillRuntime | None = None
    context_compiler: ContextCompiler | None = None
    memory_runtime: Any | None = None

    def working_snapshot(self, session_key: str) -> WorkingStateSnapshot:
        if not self.config.working_memory.enabled or self.working_state is None:
            return WorkingStateSnapshot(session_key, "disabled")
        return self.working_state.snapshot(session_key)

    def runtime_view(self, session_key: str = "") -> RuntimeView:
        llm = self.config.llm
        controller = self.turn_controller
        return RuntimeView(
            schema_version=1,
            version=_runtime_version(),
            provider=llm.provider if not llm.uses_profiles else "profile-route",
            model=llm.primary_model[:128],
            stream=llm.stream,
            workspace=str(self.config.runtime.workspace),
            session_key=session_key[:256],
            busy=bool(controller and controller.busy),
            queue_depth=int(controller.queue_depth if controller else 0),
            features=(
                ("memory", self.config.memory.enabled),
                ("working_memory", self.config.working_memory.enabled),
                ("embedding", self.config.memory.embedding.enabled),
                ("consolidation", self.config.memory.consolidation_enabled),
                ("skills", self.config.skills.enabled),
                ("mcp", self.config.mcp.enabled),
                ("proactive", self.config.proactive.enabled),
                ("subagents", self.config.subagent.enabled),
            ),
        )

    def status(self) -> dict[str, Any]:
        view = self.runtime_view()
        return {
            "version": view.version,
            "provider": view.provider,
            "model": view.model,
            "stream": view.stream,
            "workspace": view.workspace,
            "busy": view.busy,
            "queue_depth": view.queue_depth,
            **dict(view.features),
        }

    def tools(self, *, limit: int = 50) -> tuple[ToolView, ...]:
        if self.tool_registry is None:
            return ()
        views = [
            ToolView(tool.name[:128], True)
            for tool in self.tool_registry.list_tools()[: max(0, limit)]
        ]
        return tuple(sorted(views, key=lambda item: item.name.casefold()))

    def render_status(self, session_key: str = "") -> str:
        view = self.runtime_view(session_key)
        features = "\n".join(
            f"{name}: {_on_off(enabled)}" for name, enabled in view.features
        )
        return (
            f"provider: {view.provider}\nmodel: {view.model}\n"
            f"stream: {_on_off(view.stream)}\nworkspace: {view.workspace}\n"
            f"busy: {str(view.busy).lower()}\nqueue_depth: {view.queue_depth}\n"
            f"{features}"
        )

    def render_view(self, name: str, *, session_key: str = "") -> str:
        view = self.runtime_view(session_key)
        features = dict(view.features)
        if name == "workspace":
            return f"workspace: {view.workspace}"
        if name == "model":
            return (
                f"provider: {view.provider}\nmodel: {view.model}\n"
                f"stream: {_on_off(view.stream)}"
            )
        if name == "tools":
            tools = self.tools()
            if not tools:
                return (
                    "tools: unavailable"
                    if self.tool_registry is None
                    else "tools: empty"
                )
            return "tools:\n" + "\n".join(
                f"- {item.name}: {'available' if item.available else item.reason}"
                for item in tools
            )
        if name == "memory":
            snapshot = self.working_snapshot(session_key) if session_key else None
            checkpoint = (
                snapshot.availability if snapshot is not None else "unavailable"
            )
            base = (
                f"memory: {_on_off(features['memory'])}\n"
                f"embedding: {_on_off(features['embedding'])}\n"
                f"consolidation: {_on_off(features['consolidation'])}\n"
                f"working_memory: {_on_off(features['working_memory'])}\n"
                f"checkpoint: {checkpoint}"
            )
            if self.memory_runtime is None:
                return base
            diagnostics = self.memory_runtime.diagnostics().get("offline", {})
            pending = diagnostics.get("pending_chat_by_session", {})
            session_pending = int(pending.get(session_key, 0)) if session_key else 0
            threshold = diagnostics.get("chat_turn_threshold", 20)
            return (
                f"{base}\n"
                f"pending_chat: {session_pending}/{threshold}\n"
                f"recent_trigger: {diagnostics.get('recent_trigger_kind') or 'none'}\n"
                f"consumptions: {diagnostics.get('consumptions', {})}\n"
                f"governance: {diagnostics.get('governance', {})}\n"
                f"consolidation: {diagnostics.get('requests', {})}\n"
                f"stale-dead-letter: {diagnostics.get('stale_dead_letter', 0)}\n"
                f"projection: completed/ready-output="
                f"{diagnostics.get('projection_ready_output', 0)} "
                f"backlog={diagnostics.get('projection_backlog', 0)}"
            )[:4_000]
        if name == "context":
            # §8.2：/context 命令注入 epoch/恢复等级；旧 /inspect context 无这些依赖，
            # 用默认值渲染（epoch=0/recovery=unknown），仍展示 ratio/各层/frontier 等
            # 编译期信号。未编译时 latest_summary 回退到仓库派生状态（§8.2）。
            return self.render_context(
                session_key, epoch=0, restoration="unknown", restorable=False
            )
        if name == "skills":
            if not features["skills"]:
                return "skills: OFF\ncatalog: disabled"
            if self.skill_runtime is None:
                return "skills: ON\ncatalog: unavailable"
            # 只读 active 元数据；不建立 snapshot，也不触发 skill_load。
            versions = sorted(
                self.skill_runtime.repository.list_active(),
                key=lambda item: item.name.casefold(),
            )[:20]
            if not versions:
                return "skills: ON\ncatalog: empty"
            lines = ["skills: ON", f"catalog_items: {len(versions)}"]
            lines.extend(
                f"- {item.name[:80]}@{item.version[:40]} "
                f"[{item.source_type[:32]}]: {item.description[:160]}"
                for item in versions
            )
            return "\n".join(lines)[:4_000]
        return f"{name}: unavailable"

    def render_context(
        self,
        session_key: str,
        *,
        epoch: int = 0,
        restoration: str = "unknown",
        restorable: bool = False,
    ) -> str:
        """§8.2 runtime/CLI context 诊断：渲染 epoch、恢复等级、pre/post ratio、
        各层预算、frontier、压缩模式、熔断与 outbox 状态。

        §8.3 安全：``latest_summary`` 聚合 ``ContextCompilation.metadata()`` 与
        ``diagnostic_summary``，二者均只含哈希/计数/稳定引用/原因/模式名，不含 API
        key/隐藏 reasoning/embedding/未脱敏 payload（原文留在 trajectory 审计层）。
        """

        if not self.config.context.enabled:
            return "context: OFF"
        summary = (
            self.context_compiler.latest_summary(session_key)
            if self.context_compiler is not None and session_key
            else {}
        )
        ctx_cfg = self.config.context
        lines: list[str] = ["context: ON"]
        lines.append(f"epoch: {epoch}")
        lines.append(
            f"recovery: {restoration} (restorable={str(restorable).lower()})"
        )
        estimator = summary.get("token_estimator", "unknown")
        exact = summary.get("token_estimate_exact")
        exact_label = (
            "exact" if exact is True else "inexact" if exact is False else "unknown"
        )
        lines.append(
            f"estimator: {estimator} ({exact_label}), "
            f"model: {summary.get('model_profile', 'unknown')}"
        )
        lines.append(
            "tokens: estimated="
            f"{summary.get('estimated_input_tokens', 0)} "
            f"available={summary.get('available_input_tokens', 0)} "
            f"candidate={summary.get('candidate_input_tokens', 0)}"
        )
        lines.append(
            "reduction: "
            f"pre_reduction={_fmt_ratio(summary.get('pre_reduction_ratio'))} "
            f"usage={_fmt_ratio(summary.get('context_usage_ratio'))}"
        )
        failures = int(summary.get("compaction_failures", 0))
        limit = ctx_cfg.compaction_failure_limit
        circuit = "open" if failures >= limit else "closed"
        plan = summary.get("compaction_plan") or {}
        lines.append(
            f"compaction: mode={summary.get('compaction_mode', 'normal')} "
            f"failures={failures}/{limit} (circuit {circuit}) "
            f"[batch={plan.get('batch_size', 0)} target={plan.get('target_tokens', 0)}]"
        )
        if summary.get("emergency_compacted"):
            lines.append("compaction: emergency_compacted=true")
        lines.append(
            f"outbox: pending={int(summary.get('outbox_pending', 0))} "
            f"failed={int(summary.get('outbox_failed', 0))}"
        )
        lines.append(
            "frontier: "
            f"active={int(summary.get('frontier_active_count', 0))} "
            f"level={int(summary.get('archive_level', 0))} "
            f"budget={ctx_cfg.archive_frontier_tokens} tokens / "
            f"{ctx_cfg.archive_frontier_max_items} nodes"
        )
        src_turns = (
            "none"
            if ctx_cfg.source_read_max_turns is None
            else f"{ctx_cfg.source_read_max_turns} turns"
        )
        src_bytes = (
            "none"
            if ctx_cfg.source_read_max_bytes is None
            else f"{ctx_cfg.source_read_max_bytes} bytes"
        )
        lines.append(
            "effective budget: "
            f"soft={ctx_cfg.soft_threshold_ratio} "
            f"hard={ctx_cfg.hard_threshold_ratio} "
            f"tail={ctx_cfg.recent_tail_tokens} "
            f"archive={ctx_cfg.archive_tokens} "
            f"batch={ctx_cfg.compaction_batch_tokens} "
            f"source_read={src_turns}/{src_bytes} "
            f"plugin={ctx_cfg.plugin_max_tokens}"
        )
        layers = summary.get("layers") or []
        if layers:
            lines.append("layers:")
            for item in layers:
                reason = item.get("reason")
                lines.append(
                    f"- {item.get('layer', '?')}: "
                    f"candidate={item.get('candidate_tokens', 0)} "
                    f"kept={item.get('kept_tokens', 0)} "
                    f"omitted={item.get('omitted_tokens', 0)}"
                    + (f" [{reason}]" if reason else "")
                )
        prefix = str(summary.get("stable_prefix_hash", ""))[:12]
        tools_hash = str(summary.get("tool_schema_hash", ""))[:12]
        ctx_hash = str(summary.get("context_hash", ""))[:12]
        capability_revision = int(summary.get("capability_revision", 0) or 0)
        lines.append(
            f"capability_revision: {capability_revision or 'unavailable'}"
        )
        lines.append(
            "hashes: "
            f"prefix={prefix or '-'} tools={tools_hash or '-'} "
            f"context={ctx_hash or '-'}"
        )
        cached = int(summary.get("cached_blocks", 0))
        hit = summary.get("cache_hit_ratio")
        if hit is not None or cached or "cached_input_tokens" in summary:
            lines.append(
                "cache: "
                f"hit_ratio={_fmt_ratio(hit)} "
                f"cached_input={summary.get('cached_input_tokens', 0)} "
                f"creation={summary.get('cache_creation_input_tokens', 0)} "
                f"blocks={cached}"
            )
        actions = summary.get("diagnostic_actions") or ()
        actions_label = ", ".join(actions) if actions else "none"
        lines.append(f"diagnostic_actions: {actions_label}")
        return "\n".join(lines)[:4_000]


def _runtime_version() -> str:
    try:
        return version("memoli-agent")
    except PackageNotFoundError:
        return "0.1.0"


def _on_off(value: object) -> str:
    return "ON" if bool(value) else "OFF"


def _fmt_ratio(value: object) -> str:
    """§8.2 把比率/数值格式化为两位小数；缺失或非数值时回退 ``-``。"""

    if isinstance(value, int | float):
        return f"{float(value):.2f}"
    if value is None:
        return "-"
    return str(value)
