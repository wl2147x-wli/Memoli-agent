from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from memoli_agent.agent.plugins.backends import FakeSandboxBackend, SandboxPluginBackend
from memoli_agent.agent.plugins.capabilities import PluginStateStore, ScopedPluginState
from memoli_agent.agent.plugins.context import PluginRuntimeContext
from memoli_agent.agent.plugins.events import HookName, TurnAfterEvent
from memoli_agent.agent.plugins.hooks import HookBus
from memoli_agent.agent.plugins.manager import PluginManager
from memoli_agent.agent.plugins.manifest import PluginManifest, load_manifest
from memoli_agent.agent.plugins.registrar import (
    PluginRegistrar,
    RegistrationTransaction,
)
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.bootstrap.config import (
    PluginSandboxConfig,
    PluginsConfig,
    _build_app_config,
)


def _write_plugin(root: Path, plugin_id: str, body: str, hooks: str = "[]") -> None:
    target = root / plugin_id
    target.mkdir(parents=True)
    (target / "plugin.toml").write_text(
        f'id="{plugin_id}"\nversion="1.0.0"\nhooks={hooks}\n', encoding="utf-8"
    )
    (target / "plugin.py").write_text(body, encoding="utf-8")


def test_plugin_manager_activation_is_atomic_and_shutdown_is_idempotent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "good",
        """
class P:
    def register(self, registrar):
        from memoli_agent.agent.plugins.events import HookName
        registrar.add_observer(HookName.TURN_AFTER, self.observe)
    def observe(self, event): pass
    async def initialize(self, context): pass
    async def terminate(self): pass
def create_plugin(): return P()
""",
        '["turn.after"]',
    )
    _write_plugin(
        root,
        "bad",
        """
class P:
    def register(self, registrar):
        from memoli_agent.agent.plugins.events import HookName
        registrar.add_observer(HookName.TURN_AFTER, self.observe)
    def observe(self, event): pass
    async def initialize(self, context): raise RuntimeError('boom')
    async def terminate(self): pass
def create_plugin(): return P()
""",
        '["turn.after"]',
    )
    config = PluginsConfig(
        enabled=["good", "bad"],
        trusted=["good", "bad"],
        state_database=str(tmp_path / "state.db"),
    )
    bus = HookBus()
    manager = PluginManager(
        config,
        tmp_path / "workspace",
        bus,
        ToolRegistry(hook_bus=bus),
        plugin_roots=(root,),
    )
    results = asyncio.run(manager.activate_plugins())
    assert [(item.name, item.success) for item in results] == [
        ("bad", False),
        ("good", True),
    ]
    assert [item.plugin_id for item in bus.registrations()] == ["good"]
    asyncio.run(manager.terminate_plugins())
    asyncio.run(manager.terminate_plugins())
    assert bus.registrations() == []


def test_transaction_close_failure_does_not_skip_backend_shutdown(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(root, "close-test", "def create_plugin(): return object()")

    class Backend:
        name = "tracking"

        def __init__(self) -> None:
            self.shutdown_calls = 0

        async def start(self) -> None:
            return None

        async def register(self, registrar: PluginRegistrar) -> None:
            return None

        async def initialize(self, context: PluginRuntimeContext) -> None:
            return None

        async def shutdown(self) -> None:
            self.shutdown_calls += 1

    class FailingTransaction(RegistrationTransaction):
        def close(self) -> None:
            raise RuntimeError("expected")

    backend = Backend()
    config = PluginsConfig(
        enabled=["close-test"],
        trusted=["close-test"],
        state_database=str(tmp_path / "state.db"),
    )
    manager = PluginManager(
        config,
        tmp_path / "workspace",
        HookBus(),
        ToolRegistry(),
        plugin_roots=(root,),
        backend_factory=lambda *args: backend,  # type: ignore[arg-type]
    )
    asyncio.run(manager.activate_plugins())
    manager._active[0].transaction = FailingTransaction()  # noqa: SLF001
    asyncio.run(manager.terminate_plugins())

    assert backend.shutdown_calls == 1
    assert any(result.stage == "terminate" for result in manager.load_results)


def test_untrusted_in_process_request_is_tightened_to_sandbox(tmp_path: Path) -> None:
    config = PluginsConfig(enabled=["x"], trusted=[], force_sandbox=[])
    manager = PluginManager(config, tmp_path, HookBus(), ToolRegistry())
    manifest = PluginManifest(plugin_id="x", version="1.0.0")
    assert manager._effective_mode(manifest).value == "sandbox"


def test_fake_sandbox_runs_full_handshake_and_hook_protocol(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "remote",
        """
class P:
    def register(self, registrar):
        from memoli_agent.agent.plugins.events import HookName
        registrar.add_observer(HookName.TURN_AFTER, self.observe)
    def observe(self, event): return None
    async def initialize(self, context): pass
    async def terminate(self): pass
def create_plugin(): return P()
""",
        '["turn.after"]',
    )

    async def scenario() -> None:
        manifest = load_manifest(root / "remote", "remote")

        async def capability(params: dict[str, object]) -> object:
            raise PermissionError("测试插件未获能力")

        backend = FakeSandboxBackend.create(manifest, capability)
        bus = HookBus()
        registry = ToolRegistry(hook_bus=bus)
        transaction = RegistrationTransaction()
        state_store = PluginStateStore(tmp_path / "state.db")
        state_store.start()
        try:
            await backend.start()
            await backend.register(
                PluginRegistrar(manifest, backend.name, 0, bus, registry, transaction)
            )
            await backend.initialize(
                PluginRuntimeContext(
                    "remote",
                    "1.0.0",
                    backend.name,
                    state=ScopedPluginState("remote", state_store),
                )
            )
            transaction.commit()
            await bus.observe(HookName.TURN_AFTER, TurnAfterEvent())
        finally:
            transaction.close()
            await backend.shutdown()
            state_store.close()
        assert bus.registrations() == []

    asyncio.run(scenario())


def test_sandbox_infinite_hook_is_timed_out_and_process_is_terminated(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        manifest = load_manifest(
            Path("tests/fixtures/plugins/resource_bomb"), "resource_bomb"
        )

        async def capability(params: dict[str, object]) -> object:
            raise PermissionError("未授权")

        backend = FakeSandboxBackend.create(manifest, capability)
        bus = HookBus(default_deadline_seconds=0.1)
        transaction = RegistrationTransaction()
        await backend.start()
        await backend.register(
            PluginRegistrar(
                manifest,
                backend.name,
                0,
                bus,
                ToolRegistry(hook_bus=bus),
                transaction,
            )
        )
        await backend.initialize(
            PluginRuntimeContext("resource_bomb", "1.0.0", backend.name)
        )
        transaction.commit()
        # Observer fail-open；远端无限循环必须受宿主 deadline 限制。
        await asyncio.wait_for(
            bus.observe(HookName.TURN_AFTER, TurnAfterEvent()), timeout=0.5
        )
        transaction.close()
        await backend.shutdown()
        assert backend.process is None

    asyncio.run(scenario())


def test_sandbox_command_is_deny_by_default_and_uses_no_shell(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    manifest = PluginManifest(
        plugin_id="sandboxed", version="1.0.0", plugin_dir=plugin_dir
    )
    backend = SandboxPluginBackend.create(
        manifest,
        lambda params: None,
        cli="docker",
        image="runner@sha256:" + "a" * 64,
        managed_dir=tmp_path / "managed",
    )
    joined = " ".join(backend.command)
    assert backend.command[:2] == ["docker", "run"]
    for required in (
        "--network none",
        "--read-only",
        "--user 65532:65532",
        "--cap-drop ALL",
        "no-new-privileges:true",
        "--pids-limit",
        "--memory-swap",
        "/plugin,readonly",
    ):
        assert required in joined
    for forbidden in ("--privileged", "--network host", "docker.sock"):
        assert forbidden not in joined


def test_sandbox_requires_immutable_image_and_never_falls_back(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    manifest = PluginManifest(
        plugin_id="sandboxed", version="1.0.0", plugin_dir=plugin_dir
    )
    with pytest.raises(ValueError, match="digest"):
        SandboxPluginBackend.create(
            manifest,
            lambda params: None,
            cli="missing-docker",
            image="runner:latest",
            managed_dir=tmp_path / "managed",
        )


def test_plugin_config_contract_and_old_disabled_config() -> None:
    config = _build_app_config({"plugins": {"enabled": []}})
    assert config.plugins.enabled == []
    assert config.plugins.trusted == []
    sandbox = PluginSandboxConfig(memory_mb=64, cpus=0.25, pids=8)
    assert sandbox.memory_mb == 64
    with pytest.raises(ValueError):
        PluginsConfig(enabled=[], trusted=["not-enabled"])


@pytest.mark.container
def test_real_container_runner_contract() -> None:
    import subprocess

    probe = subprocess.run(
        ["docker", "version", "--format", "{{.Server.Version}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        pytest.skip("Docker daemon 不可用，真实容器测试显式跳过")
    pytest.skip("需要先用 docker/plugin-runner/build.ps1 生成本机固定 digest 镜像")
