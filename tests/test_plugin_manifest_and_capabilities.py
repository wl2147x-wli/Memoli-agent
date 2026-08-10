from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from memoli_agent.agent.plugins.base import PluginExecutionMode
from memoli_agent.agent.plugins.capabilities import (
    CapabilityBroker,
    CapabilityDenied,
    PluginStateStore,
    compute_effective_capabilities,
)
from memoli_agent.agent.plugins.context import PluginRuntimeContext
from memoli_agent.agent.plugins.manifest import (
    PluginManifest,
    PluginPermissions,
    load_manifest,
    sort_manifests,
)


def _manifest(plugin_id: str, **kwargs: object) -> PluginManifest:
    return PluginManifest(plugin_id=plugin_id, version="1.0.0", **kwargs)  # type: ignore[arg-type]


def test_manifest_is_read_before_import_and_rejects_privileged_fields(
    tmp_path: Path,
) -> None:
    plugin_dir = tmp_path / "safe"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.py").write_text(
        "raise RuntimeError('不得导入')", encoding="utf-8"
    )
    (plugin_dir / "plugin.toml").write_text(
        'id="safe"\nversion="1.0.0"\nprivileged=true\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="禁止或未知"):
        load_manifest(plugin_dir, "safe")


def test_malicious_privileged_manifest_fixture_is_rejected() -> None:
    fixture = Path("tests/fixtures/plugins/privileged_manifest")
    with pytest.raises(ValueError, match="禁止或未知"):
        load_manifest(fixture, "privileged_manifest")


def test_manifest_dependencies_are_deterministic_and_validated() -> None:
    ordered = sort_manifests(
        [_manifest("child", dependencies=("base",)), _manifest("base")]
    )
    assert [item.plugin_id for item in ordered] == ["base", "child"]
    with pytest.raises(ValueError, match="未启用"):
        sort_manifests([_manifest("child", dependencies=("missing",))])
    with pytest.raises(ValueError, match="循环"):
        sort_manifests(
            [
                _manifest("one", dependencies=("two",)),
                _manifest("two", dependencies=("one",)),
            ]
        )


def test_effective_capabilities_are_three_way_intersection() -> None:
    manifest = _manifest(
        "caps",
        execution=PluginExecutionMode.SANDBOX,
        permissions=PluginPermissions(
            capabilities=("state.get", "network.http"),
            workspace_read=("notes/*.md",),
        ),
    )
    result = compute_effective_capabilities(
        manifest,
        {"state.get", "network.http", "workspace.read"},
        {"state.get", "network.http", "workspace.read"},
    )
    assert result.names == frozenset({"state.get", "workspace.read"})


def test_plugin_context_exposes_no_app_config_registry_memory_or_secret() -> None:
    context = PluginRuntimeContext("plugin", "1.0.0", "sandbox", config={"safe": True})
    public = {name for name in dir(context) if not name.startswith("_")}
    assert public == {
        "backend",
        "capabilities",
        "config",
        "plugin_id",
        "plugin_version",
        "state",
    }
    for forbidden in ("api_key", "tool_registry", "memory_runtime", "database"):
        assert forbidden not in public


def test_state_namespaces_and_workspace_paths_are_isolated(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    notes = workspace / "notes"
    notes.mkdir()
    (notes / "a.md").write_text("hello", encoding="utf-8")
    store = PluginStateStore(tmp_path / "state.db")
    store.start()
    broker = CapabilityBroker(workspace, store)
    manifest = _manifest(
        "alpha",
        permissions=PluginPermissions(
            capabilities=("state.get", "state.set"),
            workspace_read=("notes/*.md",),
        ),
    )
    grant = compute_effective_capabilities(
        manifest,
        {"state.get", "state.set", "workspace.read"},
        {"state.get", "state.set", "workspace.read"},
    )
    broker.grant("alpha", grant)
    asyncio.run(broker.call("alpha", "state.set", {"key": "x", "value": 1}))
    assert asyncio.run(broker.call("alpha", "state.get", {"key": "x"})) == 1
    assert store.get("beta", "x") is None
    assert (
        asyncio.run(broker.call("alpha", "workspace.read", {"path": "notes/a.md"}))
        == "hello"
    )
    for path in ("../secret", str((tmp_path / "secret").resolve())):
        with pytest.raises(CapabilityDenied):
            asyncio.run(broker.call("alpha", "workspace.read", {"path": path}))
    with pytest.raises(CapabilityDenied):
        asyncio.run(broker.call("alpha", "network.http", {"url": "http://localhost"}))
    store.close()


def test_workspace_symlink_escape_is_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = workspace / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("当前 Windows 用户无创建符号链接权限")
    store = PluginStateStore(tmp_path / "state.db")
    store.start()
    broker = CapabilityBroker(workspace, store)
    manifest = _manifest(
        "alpha", permissions=PluginPermissions(workspace_read=("*.txt",))
    )
    broker.grant(
        "alpha",
        compute_effective_capabilities(
            manifest, {"workspace.read"}, {"workspace.read"}
        ),
    )
    with pytest.raises(CapabilityDenied):
        asyncio.run(broker.call("alpha", "workspace.read", {"path": "link.txt"}))
    store.close()
