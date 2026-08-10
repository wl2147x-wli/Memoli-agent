"""manifest-first、事务式且可隔离失败的插件管理器。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from memoli_agent.agent.plugins.backends import (
    InProcessPluginBackend,
    PluginExecutionBackend,
    SandboxPluginBackend,
)
from memoli_agent.agent.plugins.base import PluginExecutionMode, PluginLoadResult
from memoli_agent.agent.plugins.capabilities import (
    CapabilityBroker,
    HostCapabilityClient,
    PluginStateStore,
    ScopedPluginState,
    compute_effective_capabilities,
)
from memoli_agent.agent.plugins.context import PluginRuntimeContext
from memoli_agent.agent.plugins.hooks import HookBus
from memoli_agent.agent.plugins.manifest import (
    PluginManifest,
    load_manifest,
    sort_manifests,
)
from memoli_agent.agent.plugins.registrar import (
    PluginRegistrar,
    RegistrationTransaction,
)
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import (
    NewTrajectoryEvent,
    NullTrajectoryStore,
    SpanKind,
    SpanProjection,
    TraceProjection,
    TrajectoryStore,
    new_span_id,
    new_trace_id,
    utc_now_iso,
)
from memoli_agent.bootstrap.config import PluginsConfig

BackendFactory = Callable[[PluginManifest, str, Any], PluginExecutionBackend]


@dataclass(slots=True)
class _ActivePlugin:
    manifest: PluginManifest
    backend: PluginExecutionBackend
    transaction: RegistrationTransaction


@dataclass(slots=True)
class PluginManager:
    """插件启用白名单的原子激活与逆序关闭。"""

    config: PluginsConfig
    workspace: Path
    hook_bus: HookBus
    tool_registry: ToolRegistry
    trajectory_store: TrajectoryStore = field(default_factory=NullTrajectoryStore)
    plugin_roots: tuple[Path, ...] = ()
    backend_factory: BackendFactory | None = None
    load_results: list[PluginLoadResult] = field(default_factory=list)
    _active: list[_ActivePlugin] = field(default_factory=list)
    _state_store: PluginStateStore = field(init=False)
    _broker: CapabilityBroker = field(init=False)
    _trace_id: str = field(default="", init=False)
    _span_id: str = field(default="", init=False)
    _started: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._state_store = PluginStateStore(Path(self.config.state_database))
        self._broker = CapabilityBroker(
            self.workspace,
            self._state_store,
            trajectory_store=self.trajectory_store,
        )
        if not self.plugin_roots:
            builtin_root = Path(__file__).resolve().parents[2] / "plugins"
            self.plugin_roots = (builtin_root,)

    @property
    def runtime_trace_id(self) -> str:
        return self._trace_id

    async def activate_plugins(self) -> list[PluginLoadResult]:
        """校验 manifest 后按依赖顺序逐个原子激活。"""

        if self._started:
            return list(self.load_results)
        self._started = True
        self._state_store.start()
        await self._start_runtime_trace()
        manifests: list[PluginManifest] = []
        self.load_results.clear()
        for plugin_id in self.config.enabled:
            try:
                manifests.append(
                    load_manifest(self._find_plugin_dir(plugin_id), plugin_id)
                )
            except Exception as exc:
                self.load_results.append(self._failure(plugin_id, "manifest", exc))
        try:
            ordered = sort_manifests(manifests)
        except Exception as exc:
            for manifest in manifests:
                self.load_results.append(
                    self._failure(manifest.plugin_id, "dependencies", exc)
                )
            return list(self.load_results)

        for dependency_order, manifest in enumerate(ordered):
            await self._activate_one(manifest, dependency_order)
        return list(self.load_results)

    async def terminate_plugins(self) -> None:
        """逆序撤销贡献并关闭后端；重复调用安全。"""

        for active in reversed(self._active):
            errors: list[str] = []
            try:
                active.transaction.close()
            except Exception as exc:
                errors.append(f"registration:{type(exc).__name__}")
            try:
                await active.backend.shutdown()
            except Exception as exc:
                errors.append(f"backend:{type(exc).__name__}")
            if errors:
                self.load_results.append(
                    PluginLoadResult(
                        active.manifest.plugin_id,
                        False,
                        "terminate",
                        ",".join(errors),
                        active.backend.name,
                    )
                )
            self._broker.revoke(active.manifest.plugin_id)
            try:
                await self._record(
                    "plugin_backend_terminated",
                    active.manifest,
                    active.backend.name,
                    {"errors": errors},
                )
            except Exception as exc:
                self.load_results.append(
                    PluginLoadResult(
                        active.manifest.plugin_id,
                        False,
                        "terminate-trace",
                        type(exc).__name__,
                        active.backend.name,
                    )
                )
        self._active.clear()
        self._state_store.close()
        await self._finish_runtime_trace()
        self._started = False

    async def _activate_one(self, manifest: PluginManifest, order: int) -> None:
        manifest = self._constrain_manifest(manifest)
        transaction = RegistrationTransaction()
        backend: PluginExecutionBackend | None = None
        mode = self._effective_mode(manifest)
        grants = compute_effective_capabilities(
            manifest,
            set(self.config.approved_capabilities.get(manifest.plugin_id, [])),
            set(self.config.system_allowed_capabilities),
        )
        self._broker.grant(manifest.plugin_id, grants)

        async def capability_handler(params: dict[str, Any]) -> Any:
            return await self._broker.call(
                manifest.plugin_id,
                str(params.get("capability") or ""),
                dict(params.get("arguments") or {}),
                trace_id=str(params.get("trace_id") or ""),
            )

        try:
            backend = self._make_backend(manifest, mode, capability_handler)
            await self._record("plugin_backend_starting", manifest, backend.name, {})
            await backend.start()
            registrar = PluginRegistrar(
                manifest,
                backend.name,
                order,
                self.hook_bus,
                self.tool_registry,
                transaction,
            )
            await backend.register(registrar)
            context = PluginRuntimeContext(
                plugin_id=manifest.plugin_id,
                plugin_version=manifest.version,
                backend=backend.name,
                config=manifest.config,
                capabilities=HostCapabilityClient(manifest.plugin_id, self._broker),
                state=(
                    ScopedPluginState(manifest.plugin_id, self._state_store)
                    if grants.names & {"state.get", "state.set"}
                    else None
                ),
            )
            await backend.initialize(context)
            transaction.commit()
            self._active.append(_ActivePlugin(manifest, backend, transaction))
            self.load_results.append(
                PluginLoadResult(manifest.plugin_id, True, "active", "", backend.name)
            )
            await self._record("plugin_backend_started", manifest, backend.name, {})
        except Exception as exc:
            transaction.rollback()
            if backend is not None:
                try:
                    await backend.shutdown()
                except Exception:
                    pass
            self._broker.revoke(manifest.plugin_id)
            self.load_results.append(
                self._failure(
                    manifest.plugin_id,
                    "activate",
                    exc,
                    backend.name if backend else mode.value,
                )
            )
            await self._record(
                "plugin_backend_failed",
                manifest,
                backend.name if backend else mode.value,
                {"error_type": type(exc).__name__, "error": str(exc)},
            )

    def _effective_mode(self, manifest: PluginManifest) -> PluginExecutionMode:
        if manifest.plugin_id in self.config.force_sandbox:
            return PluginExecutionMode.SANDBOX
        if manifest.execution is PluginExecutionMode.SANDBOX:
            return PluginExecutionMode.SANDBOX
        if manifest.plugin_id not in self.config.trusted:
            return PluginExecutionMode.SANDBOX
        return PluginExecutionMode.IN_PROCESS

    def _constrain_manifest(self, manifest: PluginManifest) -> PluginManifest:
        """系统上限只能收紧插件声明，不能被 manifest 放大。"""

        sandbox = self.config.sandbox
        resources = replace(
            manifest.resources,
            hook_deadline_seconds=min(
                manifest.resources.hook_deadline_seconds,
                self.config.hook_deadline_seconds,
                sandbox.wall_time_seconds,
            ),
            memory_mb=min(manifest.resources.memory_mb, sandbox.memory_mb),
            cpus=min(manifest.resources.cpus, sandbox.cpus),
            pids=min(manifest.resources.pids, sandbox.pids),
            max_output_bytes=min(
                manifest.resources.max_output_bytes, sandbox.max_output_bytes
            ),
            max_rpc_bytes=min(manifest.resources.max_rpc_bytes, sandbox.max_rpc_bytes),
        )
        return replace(manifest, resources=resources)

    def _make_backend(
        self,
        manifest: PluginManifest,
        mode: PluginExecutionMode,
        capability_handler: Any,
    ) -> PluginExecutionBackend:
        if self.backend_factory is not None:
            return self.backend_factory(manifest, mode.value, capability_handler)
        if mode is PluginExecutionMode.IN_PROCESS:
            return InProcessPluginBackend(manifest)
        sandbox = self.config.sandbox
        return SandboxPluginBackend.create(
            manifest,
            capability_handler,
            cli=sandbox.container_cli,
            image=sandbox.runner_image,
            managed_dir=self.workspace / ".plugin-sandbox" / manifest.plugin_id,
        )

    def _find_plugin_dir(self, plugin_id: str) -> Path:
        for root in self.plugin_roots:
            candidate = root / plugin_id
            if candidate.is_dir():
                return candidate
        raise FileNotFoundError(f"启用插件不存在：{plugin_id}")

    @staticmethod
    def _failure(
        plugin_id: str, stage: str, exc: Exception, backend: str = ""
    ) -> PluginLoadResult:
        return PluginLoadResult(
            plugin_id, False, stage, f"{type(exc).__name__}: {exc}", backend
        )

    async def _start_runtime_trace(self) -> None:
        self._trace_id, self._span_id = new_trace_id(), new_span_id()
        now = utc_now_iso()
        await self.trajectory_store.record(
            NewTrajectoryEvent(
                trace_id=self._trace_id,
                span_id=self._span_id,
                event_type="plugin_runtime_started",
                payload={},
                trace=TraceProjection(
                    trace_id=self._trace_id,
                    session_id="runtime:plugins",
                    started_at=now,
                    provider="runtime",
                    model="plugins",
                ),
                span=SpanProjection(
                    span_id=self._span_id,
                    trace_id=self._trace_id,
                    parent_span_id=None,
                    kind=SpanKind.AGENT,
                    name="plugin-runtime",
                    started_at=now,
                ),
            )
        )

    async def _finish_runtime_trace(self) -> None:
        if not self._trace_id:
            return
        await self.trajectory_store.record(
            NewTrajectoryEvent(
                trace_id=self._trace_id,
                span_id=self._span_id,
                event_type="plugin_runtime_stopped",
                payload={},
            )
        )
        self._trace_id = self._span_id = ""

    async def _record(
        self,
        event_type: str,
        manifest: PluginManifest,
        backend: str,
        extra: dict[str, Any],
    ) -> None:
        if not self._trace_id:
            return
        await self.trajectory_store.record(
            NewTrajectoryEvent(
                trace_id=self._trace_id,
                span_id=self._span_id,
                event_type=event_type,
                payload={
                    "plugin_id": manifest.plugin_id,
                    "plugin_version": manifest.version,
                    "backend": backend,
                    **extra,
                },
            )
        )
