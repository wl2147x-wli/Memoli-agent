"""插件执行后端：可信进程内模式与容器沙箱模式。"""

from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast

from memoli_agent.agent.plugins.base import Plugin
from memoli_agent.agent.plugins.context import PluginRuntimeContext
from memoli_agent.agent.plugins.events import (
    HookEvent,
    HookKind,
    HookName,
    event_to_dict,
    hook_result_from_dict,
)
from memoli_agent.agent.plugins.manifest import PluginManifest
from memoli_agent.agent.plugins.registrar import PluginRegistrar
from memoli_agent.agent.plugins.rpc import JsonRpcPeer, RpcProtocolError
from memoli_agent.agent.tools.base import ToolResult


class PluginExecutionBackend(Protocol):
    """所有插件后端共享的最小生命周期。"""

    name: str

    async def start(self) -> None: ...
    async def register(self, registrar: PluginRegistrar) -> None: ...
    async def initialize(self, context: PluginRuntimeContext) -> None: ...
    async def shutdown(self) -> None: ...


@dataclass(slots=True)
class InProcessPluginBackend:
    """仅供明确受信任插件使用；它不是安全沙箱。"""

    manifest: PluginManifest
    name: str = "in_process"
    plugin: Plugin | None = field(default=None, init=False)

    async def start(self) -> None:
        module_name, attribute = self.manifest.entrypoint.split(":", 1)
        module_path = self.manifest.plugin_dir / (module_name.replace(".", "/") + ".py")
        if not module_path.is_file():
            raise FileNotFoundError(f"插件入口不存在：{module_path}")
        unique_name = f"_memoli_plugin_{self.manifest.plugin_id}_{module_name}"
        spec = importlib.util.spec_from_file_location(unique_name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法创建插件模块：{module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique_name] = module
        try:
            spec.loader.exec_module(module)
            factory = getattr(module, attribute)
            self.plugin = cast(Plugin, factory() if callable(factory) else factory)
        except Exception:
            sys.modules.pop(unique_name, None)
            raise

    async def register(self, registrar: PluginRegistrar) -> None:
        if self.plugin is None:
            raise RuntimeError("插件后端尚未启动。")
        self.plugin.register(registrar)

    async def initialize(self, context: PluginRuntimeContext) -> None:
        if self.plugin is None:
            raise RuntimeError("插件后端尚未启动。")
        await self.plugin.initialize(context)

    async def shutdown(self) -> None:
        plugin, self.plugin = self.plugin, None
        if plugin is not None:
            await plugin.terminate()


@dataclass(frozen=True, slots=True)
class RemoteTool:
    """把工具调用转发给沙箱 runner。"""

    peer: JsonRpcPeer
    name: str
    description: str
    parameters: dict[str, Any]
    timeout: float

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        raw = await self.peer.request(
            "tool.invoke",
            {"name": self.name, "arguments": arguments},
            timeout=self.timeout,
        )
        return ToolResult(**dict(raw))


@dataclass(slots=True)
class StdioSandboxBackend:
    """基于 runner stdio 协议的沙箱后端基类。"""

    manifest: PluginManifest
    command: list[str]
    capability_handler: Any
    name: str = "sandbox"
    process: asyncio.subprocess.Process | None = field(default=None, init=False)
    peer: JsonRpcPeer | None = field(default=None, init=False)
    stderr: bytes = field(default=b"", init=False)
    _stderr_task: asyncio.Task[None] | None = field(default=None, init=False)

    async def start(self) -> None:
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert self.process.stdin and self.process.stdout and self.process.stderr
        self.peer = JsonRpcPeer(
            self.process.stdout,
            self.process.stdin,
            self.manifest.plugin_id,
            max_message_bytes=self.manifest.resources.max_rpc_bytes,
        )
        self.peer.handlers["capability.call"] = self.capability_handler
        self.peer.start()
        self._stderr_task = asyncio.create_task(self._collect_stderr())
        lifecycle_timeout = max(2.0, self.manifest.resources.hook_deadline_seconds)
        try:
            result = await self.peer.request(
                "plugin.handshake",
                {
                    "plugin_id": self.manifest.plugin_id,
                    "version": self.manifest.version,
                },
                timeout=lifecycle_timeout,
            )
        except Exception as exc:
            await asyncio.sleep(0)
            detail = self.stderr.decode("utf-8", errors="replace")[-4096:]
            raise RpcProtocolError(f"runner 启动失败：{detail or exc}") from exc
        if result.get("plugin_id") != self.manifest.plugin_id:
            raise RpcProtocolError("runner 握手身份不匹配。")

    async def register(self, registrar: PluginRegistrar) -> None:
        peer = self._require_peer()
        contributions = await peer.request(
            "plugin.register",
            {},
            timeout=max(2.0, self.manifest.resources.hook_deadline_seconds),
        )
        for item in contributions.get("hooks", []):
            hook = HookName(item["hook"])
            kind = HookKind(item["kind"])
            handler = str(item["handler"])

            async def callback(
                event: HookEvent, *, handler_name: str = handler
            ) -> object:
                raw = await peer.request(
                    "hook.invoke",
                    {"handler": handler_name, "event": event_to_dict(event)},
                    timeout=self.manifest.resources.hook_deadline_seconds,
                )
                return hook_result_from_dict(raw)

            add = {
                HookKind.TRANSFORMER: registrar.add_transformer,
                HookKind.POLICY: registrar.add_policy,
                HookKind.OBSERVER: registrar.add_observer,
            }[kind]
            add(
                hook,
                callback,
                priority=int(item.get("priority", 0)),
                handler_name=handler,
            )
        for item in contributions.get("tools", []):
            registrar.add_tool(
                RemoteTool(
                    peer=peer,
                    name=str(item["name"]),
                    description=str(item.get("description", "")),
                    parameters=dict(item.get("parameters") or {}),
                    timeout=self.manifest.resources.hook_deadline_seconds,
                )
            )

    async def initialize(self, context: PluginRuntimeContext) -> None:
        await self._require_peer().request(
            "plugin.initialize",
            {
                "context": {
                    "plugin_id": context.plugin_id,
                    "plugin_version": context.plugin_version,
                    "backend": context.backend,
                    "config": dict(context.config),
                }
            },
            timeout=max(2.0, self.manifest.resources.hook_deadline_seconds),
        )

    async def shutdown(self) -> None:
        process, peer = self.process, self.peer
        self.process = None
        self.peer = None
        if peer is not None:
            try:
                await peer.request("plugin.shutdown", {}, timeout=2.0)
            except Exception:
                pass
            await peer.close()
        if process is not None:
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except TimeoutError:
                process.kill()
                await process.wait()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            self._stderr_task = None

    async def _collect_stderr(self) -> None:
        assert self.process and self.process.stderr
        limit = self.manifest.resources.max_output_bytes
        chunks = bytearray()
        while len(chunks) < limit:
            chunk = await self.process.stderr.read(min(8192, limit - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
        self.stderr = bytes(chunks)

    def _require_peer(self) -> JsonRpcPeer:
        if self.peer is None:
            raise RuntimeError("沙箱后端尚未启动。")
        return self.peer


@dataclass(slots=True)
class FakeSandboxBackend(StdioSandboxBackend):
    """用本机 Python runner 测试完整沙箱协议，不提供 OS 隔离。"""

    @classmethod
    def create(
        cls, manifest: PluginManifest, capability_handler: Any
    ) -> FakeSandboxBackend:
        return cls(
            manifest=manifest,
            command=[
                sys.executable,
                "-m",
                "memoli_agent.agent.plugins.runner",
                "--plugin-dir",
                str(manifest.plugin_dir),
                "--plugin-id",
                manifest.plugin_id,
            ],
            capability_handler=capability_handler,
            name="fake_sandbox",
        )


@dataclass(slots=True)
class SandboxPluginBackend(StdioSandboxBackend):
    """使用参数数组启动拒绝式 Docker 沙箱，绝不经 shell。"""

    @classmethod
    def create(
        cls,
        manifest: PluginManifest,
        capability_handler: Any,
        *,
        cli: str,
        image: str,
        managed_dir: Path,
    ) -> SandboxPluginBackend:
        if re.fullmatch(r"(?:[^\s]+@)?sha256:[0-9a-f]{64}", image) is None:
            raise ValueError("沙箱 runner_image 必须固定到 sha256 digest。")
        managed_dir.mkdir(parents=True, exist_ok=True)
        plugin_dir = manifest.plugin_dir.resolve()
        managed = managed_dir.resolve()
        forbidden = {Path.home().resolve(), Path.cwd().resolve()}
        if plugin_dir in forbidden or managed in forbidden:
            raise ValueError("拒绝把用户主目录或 Memoli 根目录挂载到沙箱。")
        command = [
            cli,
            "run",
            "--rm",
            "-i",
            "--network",
            "none",
            "--read-only",
            "--user",
            "65532:65532",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            str(manifest.resources.pids),
            "--memory",
            f"{manifest.resources.memory_mb}m",
            "--memory-swap",
            f"{manifest.resources.memory_mb}m",
            "--cpus",
            str(manifest.resources.cpus),
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--mount",
            f"type=bind,src={plugin_dir},dst=/plugin,readonly",
            "--mount",
            f"type=bind,src={managed},dst=/data",
            image,
            "--plugin-dir",
            "/plugin",
            "--plugin-id",
            manifest.plugin_id,
        ]
        return cls(
            manifest=manifest,
            command=command,
            capability_handler=capability_handler,
            name="sandbox",
        )
