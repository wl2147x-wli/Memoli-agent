"""通用沙箱插件 runner；stdout 专用于 JSON-RPC 帧。"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

from memoli_agent.agent.plugins.base import Plugin
from memoli_agent.agent.plugins.context import PluginRuntimeContext
from memoli_agent.agent.plugins.events import (
    HookEvent,
    HookKind,
    HookName,
    event_from_dict,
    hook_result_to_dict,
)
from memoli_agent.agent.plugins.manifest import PluginManifest, load_manifest
from memoli_agent.agent.plugins.rpc import PROTOCOL_VERSION, JsonRpcPeer


@dataclass(slots=True)
class RemoteRegistrar:
    """在 runner 内收集声明，不接触宿主注册表。"""

    manifest: PluginManifest
    hooks: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, Any]] = field(default_factory=list)
    callbacks: dict[str, Any] = field(default_factory=dict)
    tool_objects: dict[str, Any] = field(default_factory=dict)

    def add_transformer(
        self,
        hook: HookName,
        callback: Any,
        *,
        priority: int = 0,
        handler_name: str = "",
    ) -> None:
        self._hook(hook, HookKind.TRANSFORMER, callback, priority, handler_name)

    def add_policy(
        self,
        hook: HookName,
        callback: Any,
        *,
        priority: int = 0,
        handler_name: str = "",
    ) -> None:
        self._hook(hook, HookKind.POLICY, callback, priority, handler_name)

    def add_observer(
        self,
        hook: HookName,
        callback: Any,
        *,
        priority: int = 0,
        handler_name: str = "",
    ) -> None:
        self._hook(hook, HookKind.OBSERVER, callback, priority, handler_name)

    def add_tool(self, tool: Any) -> None:
        if tool.name not in self.manifest.tools or tool.name in self.tool_objects:
            raise PermissionError(f"沙箱插件工具未声明或重复：{tool.name}")
        self.tool_objects[tool.name] = tool
        self.tools.append(
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
        )

    def _hook(
        self,
        hook: HookName,
        kind: HookKind,
        callback: Any,
        priority: int,
        handler_name: str,
    ) -> None:
        if hook not in self.manifest.hooks:
            raise PermissionError(f"manifest 未声明插件 Hook：{hook.value}")
        name = handler_name or getattr(callback, "__name__", type(callback).__name__)
        if name in self.callbacks:
            raise ValueError(f"沙箱插件 handler 重复：{name}")
        self.callbacks[name] = callback
        self.hooks.append(
            {
                "hook": hook.value,
                "kind": kind.value,
                "priority": priority,
                "handler": name,
            }
        )


@dataclass(frozen=True, slots=True)
class RunnerCapabilityClient:
    plugin_id: str
    peer: JsonRpcPeer

    async def call(
        self, capability: str, arguments: dict[str, Any], *, trace_id: str = ""
    ) -> Any:
        return await self.peer.request(
            "capability.call",
            {"capability": capability, "arguments": arguments, "trace_id": trace_id},
            timeout=5.0,
        )


@dataclass(slots=True)
class RunnerServer:
    manifest: PluginManifest
    plugin: Plugin
    peer: JsonRpcPeer
    registrar: RemoteRegistrar = field(init=False)
    stopped: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        self.registrar = RemoteRegistrar(self.manifest)

    def install_handlers(self) -> None:
        self.peer.handlers.update(
            {
                "plugin.handshake": self.handshake,
                "plugin.register": self.register,
                "plugin.initialize": self.initialize,
                "hook.invoke": self.invoke_hook,
                "tool.invoke": self.invoke_tool,
                "plugin.shutdown": self.shutdown,
            }
        )

    async def handshake(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("plugin_id") != self.manifest.plugin_id:
            raise PermissionError("插件身份不匹配。")
        return {
            "plugin_id": self.manifest.plugin_id,
            "version": self.manifest.version,
            "protocol": PROTOCOL_VERSION,
        }

    async def register(self, params: dict[str, Any]) -> dict[str, Any]:
        del params
        self.plugin.register(cast(Any, self.registrar))
        return {"hooks": self.registrar.hooks, "tools": self.registrar.tools}

    async def initialize(self, params: dict[str, Any]) -> None:
        raw = dict(params.get("context") or {})
        context = PluginRuntimeContext(
            plugin_id=self.manifest.plugin_id,
            plugin_version=self.manifest.version,
            backend="sandbox",
            config=dict(raw.get("config") or {}),
            capabilities=RunnerCapabilityClient(self.manifest.plugin_id, self.peer),
            state=None,
        )
        await self.plugin.initialize(context)

    async def invoke_hook(self, params: dict[str, Any]) -> Any:
        handler_name = str(params.get("handler") or "")
        callback = self.registrar.callbacks.get(handler_name)
        if callback is None:
            raise KeyError(f"未知 Hook handler：{handler_name}")
        hook = next(
            HookName(item["hook"])
            for item in self.registrar.hooks
            if item["handler"] == handler_name
        )
        event: HookEvent = event_from_dict(hook, dict(params.get("event") or {}))
        result = callback(event)
        if asyncio.iscoroutine(result):
            result = await result
        return hook_result_to_dict(result)

    async def invoke_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = str(params.get("name") or "")
        tool = self.registrar.tool_objects.get(name)
        if tool is None:
            raise KeyError(f"未知沙箱工具：{name}")
        result = await tool.run(dict(params.get("arguments") or {}))
        return asdict(result)

    async def shutdown(self, params: dict[str, Any]) -> None:
        del params
        await self.plugin.terminate()
        # 先让 RPC 层发送响应，再结束主循环，避免关闭帧与响应竞争。
        asyncio.get_running_loop().call_later(0.05, self.stopped.set)


def _load_plugin(manifest: PluginManifest) -> Plugin:
    module_name, attribute = manifest.entrypoint.split(":", 1)
    path = manifest.plugin_dir / (module_name.replace(".", "/") + ".py")
    spec = importlib.util.spec_from_file_location("_memoli_sandbox_plugin", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载沙箱插件：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    factory = getattr(module, attribute)
    return cast(Plugin, factory() if callable(factory) else factory)


class _ThreadStdinReader:
    """Windows Proactor 不能可靠包装继承的 stdio，改在线程中阻塞读取。"""

    async def readline(self) -> bytes:
        return await asyncio.to_thread(sys.stdin.buffer.readline)


class _ThreadStdoutWriter:
    def write(self, data: bytes) -> None:
        sys.stdout.buffer.write(data)

    async def drain(self) -> None:
        await asyncio.to_thread(sys.stdout.buffer.flush)

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


async def _stdio_peer(plugin_id: str, max_bytes: int) -> JsonRpcPeer:
    return JsonRpcPeer(
        cast(Any, _ThreadStdinReader()),
        cast(Any, _ThreadStdoutWriter()),
        plugin_id,
        max_message_bytes=max_bytes,
    )


async def _main(plugin_dir: Path, plugin_id: str) -> None:
    manifest = load_manifest(plugin_dir, plugin_id)
    peer = await _stdio_peer(plugin_id, manifest.resources.max_rpc_bytes)
    server = RunnerServer(manifest, _load_plugin(manifest), peer)
    server.install_handlers()
    peer.start()
    await server.stopped.wait()
    await peer.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-dir", type=Path, required=True)
    parser.add_argument("--plugin-id", required=True)
    args = parser.parse_args()
    asyncio.run(_main(args.plugin_dir, args.plugin_id))


if __name__ == "__main__":
    main()
