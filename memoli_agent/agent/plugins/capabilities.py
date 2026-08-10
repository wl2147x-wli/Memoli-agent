"""插件私有状态与宿主能力代理。"""

from __future__ import annotations

import fnmatch
import json
import sqlite3
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any

from memoli_agent.agent.plugins.manifest import PluginManifest
from memoli_agent.agent.trajectory import (
    NewTrajectoryEvent,
    NullTrajectoryStore,
    TrajectoryStore,
)


class CapabilityDenied(PermissionError):
    """插件能力未声明、未批准或越界。"""


IMPLEMENTED_CAPABILITIES = frozenset(
    {"state.get", "state.set", "workspace.read", "workspace.write"}
)


@dataclass(slots=True)
class PluginStateStore:
    """按 plugin ID 命名空间隔离的本地 KV。"""

    database: Path
    _connection: sqlite3.Connection | None = field(default=None, init=False)

    def start(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS plugin_state (
                plugin_id TEXT NOT NULL,
                state_key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                PRIMARY KEY(plugin_id, state_key)
            )
            """
        )
        connection.commit()
        self._connection = connection

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def get(self, plugin_id: str, key: str, default: Any = None) -> Any:
        row = (
            self._require()
            .execute(
                "SELECT value_json FROM plugin_state WHERE plugin_id=? AND state_key=?",
                (plugin_id, key),
            )
            .fetchone()
        )
        return default if row is None else json.loads(str(row[0]))

    def set(self, plugin_id: str, key: str, value: Any) -> None:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 262_144:
            raise ValueError("单个插件状态值超过 256 KiB。")
        connection = self._require()
        connection.execute(
            """
            INSERT INTO plugin_state(plugin_id, state_key, value_json)
            VALUES (?, ?, ?)
            ON CONFLICT(plugin_id, state_key) DO UPDATE
            SET value_json=excluded.value_json
            """,
            (plugin_id, key, encoded),
        )
        connection.commit()

    def _require(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("PluginStateStore 尚未启动。")
        return self._connection


@dataclass(frozen=True, slots=True)
class ScopedPluginState:
    """只允许访问当前插件命名空间的状态能力。"""

    plugin_id: str
    store: PluginStateStore

    def get(self, key: str, default: Any = None) -> Any:
        return self.store.get(self.plugin_id, key, default)

    def set(self, key: str, value: Any) -> None:
        self.store.set(self.plugin_id, key, value)


@dataclass(frozen=True, slots=True)
class EffectiveCapabilities:
    """manifest、用户批准和系统上限的交集。"""

    names: frozenset[str] = frozenset()
    workspace_read: tuple[str, ...] = ()
    workspace_write: tuple[str, ...] = ()


def compute_effective_capabilities(
    manifest: PluginManifest,
    approved: set[str],
    system_allowed: set[str],
) -> EffectiveCapabilities:
    requested = set(manifest.permissions.capabilities)
    if manifest.permissions.workspace_read:
        requested.add("workspace.read")
    if manifest.permissions.workspace_write:
        requested.add("workspace.write")
    names = frozenset(
        requested & approved & system_allowed & set(IMPLEMENTED_CAPABILITIES)
    )
    return EffectiveCapabilities(
        names=names,
        workspace_read=(
            manifest.permissions.workspace_read if "workspace.read" in names else ()
        ),
        workspace_write=(
            manifest.permissions.workspace_write if "workspace.write" in names else ()
        ),
    )


@dataclass(slots=True)
class CapabilityBroker:
    """宿主资源访问的唯一插件入口。"""

    workspace: Path
    state_store: PluginStateStore
    trajectory_store: TrajectoryStore = field(default_factory=NullTrajectoryStore)
    max_file_bytes: int = 1_048_576
    _grants: dict[str, EffectiveCapabilities] = field(default_factory=dict)

    def grant(self, plugin_id: str, capabilities: EffectiveCapabilities) -> None:
        self._grants[plugin_id] = capabilities

    def revoke(self, plugin_id: str) -> None:
        self._grants.pop(plugin_id, None)

    async def call(
        self,
        plugin_id: str,
        capability: str,
        arguments: dict[str, Any],
        *,
        trace_id: str = "",
    ) -> Any:
        """校验并执行单次能力请求。"""

        grant = self._grants.get(plugin_id)
        if grant is None or capability not in grant.names:
            await self._record(trace_id, plugin_id, capability, "denied", "not-granted")
            raise CapabilityDenied(f"插件未获能力授权：{capability}")
        try:
            if capability == "state.get":
                result = self.state_store.get(
                    plugin_id,
                    str(arguments.get("key") or ""),
                    arguments.get("default"),
                )
            elif capability == "state.set":
                self.state_store.set(
                    plugin_id,
                    str(arguments.get("key") or ""),
                    arguments.get("value"),
                )
                result = None
            elif capability == "workspace.read":
                result = self._read_workspace(
                    str(arguments.get("path") or ""), grant.workspace_read
                )
            elif capability == "workspace.write":
                result = self._write_workspace(
                    str(arguments.get("path") or ""),
                    str(arguments.get("content") or ""),
                    grant.workspace_write,
                )
            else:
                raise CapabilityDenied(f"能力尚未实现：{capability}")
        except Exception as exc:
            await self._record(
                trace_id, plugin_id, capability, "denied", type(exc).__name__
            )
            raise
        await self._record(trace_id, plugin_id, capability, "completed", "")
        return result

    def _read_workspace(self, raw_path: str, patterns: tuple[str, ...]) -> str:
        target = self._resolve_workspace_path(raw_path, patterns, must_exist=True)
        if not target.is_file():
            raise CapabilityDenied("workspace.read 只允许普通文件。")
        data = target.read_bytes()
        if len(data) > self.max_file_bytes:
            raise CapabilityDenied("文件超过插件读取上限。")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CapabilityDenied("workspace.read 只允许 UTF-8 文本。") from exc

    def _write_workspace(
        self,
        raw_path: str,
        content: str,
        patterns: tuple[str, ...],
    ) -> dict[str, Any]:
        encoded = content.encode("utf-8")
        if len(encoded) > self.max_file_bytes:
            raise CapabilityDenied("写入内容超过插件上限。")
        target = self._resolve_workspace_path(raw_path, patterns, must_exist=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(encoded)
        return {
            "path": target.relative_to(self.workspace.resolve()).as_posix(),
            "bytes": len(encoded),
        }

    def _resolve_workspace_path(
        self,
        raw_path: str,
        patterns: tuple[str, ...],
        *,
        must_exist: bool,
    ) -> Path:
        path = PurePath(raw_path)
        if (
            not raw_path
            or path.is_absolute()
            or ".." in path.parts
            or "~" in path.parts
        ):
            raise CapabilityDenied("插件路径必须是 workspace 内相对路径。")
        root = self.workspace.resolve()
        candidate = root.joinpath(*path.parts)
        self._reject_links(root, candidate)
        resolved = candidate.resolve(strict=must_exist)
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise CapabilityDenied("插件路径逃出 workspace。") from exc
        if not any(fnmatch.fnmatch(relative, pattern) for pattern in patterns):
            raise CapabilityDenied("插件路径不在授权模式内。")
        return resolved

    @staticmethod
    def _reject_links(root: Path, target: Path) -> None:
        current = root
        relative_parts = target.relative_to(root).parts
        for part in relative_parts:
            current = current / part
            if not current.exists():
                continue
            try:
                info = current.lstat()
            except OSError as exc:
                raise CapabilityDenied("无法安全检查插件路径。") from exc
            is_reparse = bool(
                getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            )
            if stat.S_ISLNK(info.st_mode) or is_reparse:
                raise CapabilityDenied("插件路径不得经过符号链接或 reparse point。")

    async def _record(
        self,
        trace_id: str,
        plugin_id: str,
        capability: str,
        status: str,
        reason: str,
    ) -> None:
        if not trace_id:
            return
        await self.trajectory_store.record(
            NewTrajectoryEvent(
                trace_id=trace_id,
                event_type=(
                    "plugin_capability_denied"
                    if status == "denied"
                    else "plugin_capability_completed"
                ),
                payload={
                    "plugin_id": plugin_id,
                    "capability": capability,
                    "status": status,
                    "reason": reason,
                },
            )
        )


@dataclass(frozen=True, slots=True)
class HostCapabilityClient:
    """进程内插件使用的最小能力客户端。"""

    plugin_id: str
    broker: CapabilityBroker

    async def call(
        self,
        capability: str,
        arguments: dict[str, Any],
        *,
        trace_id: str = "",
    ) -> Any:
        return await self.broker.call(
            self.plugin_id, capability, arguments, trace_id=trace_id
        )
