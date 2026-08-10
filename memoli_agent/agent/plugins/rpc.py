"""沙箱插件使用的有界、版本化 JSON-RPC stdio 协议。"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = "1.0"
RpcHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class RpcProtocolError(RuntimeError):
    """对端违反 RPC framing 或 schema。"""


@dataclass(slots=True)
class JsonRpcPeer:
    """一行一帧的双向异步 RPC；stdout 只承载协议。"""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    plugin_id: str
    max_message_bytes: int = 262_144
    max_depth: int = 24
    handlers: dict[str, RpcHandler] = field(default_factory=dict)
    _pending: dict[str, asyncio.Future[Any]] = field(default_factory=dict)
    _reader_task: asyncio.Task[None] | None = None
    _closed: bool = False
    _write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def start(self) -> None:
        if self._reader_task is None:
            self._reader_task = asyncio.create_task(self._read_loop())

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float,
    ) -> Any:
        if self._closed:
            raise RpcProtocolError("RPC 对端已关闭。")
        self.start()
        request_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[request_id] = future
        try:
            await self._send(
                {
                    "jsonrpc": "2.0",
                    "protocol": PROTOCOL_VERSION,
                    "id": request_id,
                    "plugin_id": self.plugin_id,
                    "method": method,
                    "deadline_ms": max(1, int(timeout * 1000)),
                    "params": params,
                }
            )
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(request_id, None)

    async def close(self) -> None:
        self._closed = True
        if self._reader_task is not None:
            self._reader_task.cancel()
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (BrokenPipeError, ConnectionError):
            pass

    async def _read_loop(self) -> None:
        try:
            while not self._closed:
                raw = await self.reader.readline()
                if not raw:
                    raise RpcProtocolError("RPC 对端意外退出。")
                if len(raw) > self.max_message_bytes:
                    raise RpcProtocolError("RPC 消息超过大小上限。")
                try:
                    message = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise RpcProtocolError("RPC stdout 包含非 JSON 数据。") from exc
                self._validate(message)
                if "method" in message:
                    asyncio.create_task(self._handle_request(message))
                else:
                    self._handle_response(message)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self._closed = True
            for pending in self._pending.values():
                if not pending.done():
                    pending.set_exception(exc)

    async def _handle_request(self, message: dict[str, Any]) -> None:
        request_id = str(message["id"])
        method = str(message["method"])
        handler = self.handlers.get(method)
        if handler is None:
            await self._send_error(request_id, "method_not_found", method)
            return
        try:
            result = await handler(dict(message.get("params") or {}))
            await self._send(
                {
                    "jsonrpc": "2.0",
                    "protocol": PROTOCOL_VERSION,
                    "id": request_id,
                    "plugin_id": self.plugin_id,
                    "result": result,
                }
            )
        except Exception as exc:
            await self._send_error(request_id, type(exc).__name__, str(exc))

    def _handle_response(self, message: dict[str, Any]) -> None:
        request_id = str(message["id"])
        pending = self._pending.get(request_id)
        if pending is None or pending.done():
            raise RpcProtocolError("收到未知或重复 RPC 响应。")
        if "error" in message:
            error = message["error"]
            pending.set_exception(
                RpcProtocolError(
                    f"{error.get('code', 'remote_error')}: {error.get('message', '')}"
                )
            )
        else:
            pending.set_result(message.get("result"))

    async def _send_error(self, request_id: str, code: str, message: str) -> None:
        await self._send(
            {
                "jsonrpc": "2.0",
                "protocol": PROTOCOL_VERSION,
                "id": request_id,
                "plugin_id": self.plugin_id,
                "error": {"code": code, "message": message[:4096]},
            }
        )

    async def _send(self, message: dict[str, Any]) -> None:
        raw = (
            json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode()
            + b"\n"
        )
        if len(raw) > self.max_message_bytes:
            raise RpcProtocolError("RPC 消息超过大小上限。")
        async with self._write_lock:
            self.writer.write(raw)
            await self.writer.drain()

    def _validate(self, message: object) -> None:
        if not isinstance(message, dict) or _json_depth(message) > self.max_depth:
            raise RpcProtocolError("RPC 消息结构无效或嵌套过深。")
        if (
            message.get("jsonrpc") != "2.0"
            or message.get("protocol") != PROTOCOL_VERSION
        ):
            raise RpcProtocolError("RPC 协议版本不兼容。")
        if message.get("plugin_id") != self.plugin_id or not isinstance(
            message.get("id"), str
        ):
            raise RpcProtocolError("RPC 插件身份或请求 ID 无效。")


def _json_depth(value: Any, depth: int = 0) -> int:
    if isinstance(value, dict):
        return max([depth, *(_json_depth(item, depth + 1) for item in value.values())])
    if isinstance(value, list):
        return max([depth, *(_json_depth(item, depth + 1) for item in value)])
    return depth
