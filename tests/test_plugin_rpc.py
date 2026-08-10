from __future__ import annotations

import asyncio
import json

import pytest

from memoli_agent.agent.plugins.rpc import (
    PROTOCOL_VERSION,
    JsonRpcPeer,
    RpcProtocolError,
)


class MemoryWriter:
    def __init__(self) -> None:
        self.data = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.data.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def _response(request_id: str, **extra: object) -> bytes:
    return (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "protocol": PROTOCOL_VERSION,
                "id": request_id,
                "plugin_id": "plugin",
                **extra,
            }
        ).encode()
        + b"\n"
    )


def test_rpc_round_trip_and_timeout() -> None:
    async def scenario() -> None:
        reader = asyncio.StreamReader()
        writer = MemoryWriter()
        peer = JsonRpcPeer(reader, writer, "plugin")  # type: ignore[arg-type]
        task = asyncio.create_task(peer.request("plugin.handshake", {}, timeout=0.2))
        await asyncio.sleep(0)
        request = json.loads(bytes(writer.data))
        reader.feed_data(_response(request["id"], result={"ok": True}))
        assert await task == {"ok": True}
        with pytest.raises(TimeoutError):
            await peer.request("hook.invoke", {}, timeout=0.01)
        await peer.close()

    asyncio.run(scenario())


def test_rpc_rejects_oversize_depth_identity_and_non_json() -> None:
    async def scenario() -> None:
        reader = asyncio.StreamReader()
        writer = MemoryWriter()
        peer = JsonRpcPeer(reader, writer, "plugin", max_message_bytes=256, max_depth=3)  # type: ignore[arg-type]
        with pytest.raises(RpcProtocolError, match="大小"):
            await peer.request("tool.invoke", {"data": "x" * 1000}, timeout=0.1)
        valid = {
            "jsonrpc": "2.0",
            "protocol": PROTOCOL_VERSION,
            "id": "id",
            "plugin_id": "other",
            "result": None,
        }
        with pytest.raises(RpcProtocolError, match="身份"):
            peer._validate(valid)
        valid["plugin_id"] = "plugin"
        valid["result"] = {"a": {"b": {"c": {"d": 1}}}}
        with pytest.raises(RpcProtocolError, match="嵌套"):
            peer._validate(valid)

        task = asyncio.create_task(peer.request("hook.invoke", {}, timeout=0.2))
        await asyncio.sleep(0)
        reader.feed_data(b"malicious stdout\n")
        with pytest.raises(RpcProtocolError, match="非 JSON"):
            await task
        await peer.close()

    asyncio.run(scenario())


def test_rpc_unknown_method_returns_structured_error() -> None:
    async def scenario() -> None:
        reader = asyncio.StreamReader()
        writer = MemoryWriter()
        peer = JsonRpcPeer(reader, writer, "plugin")  # type: ignore[arg-type]
        peer.start()
        reader.feed_data(
            _response(
                "request",
                method="unknown.method",
                params={},
                deadline_ms=100,
            )
        )
        await asyncio.sleep(0.01)
        response = json.loads(bytes(writer.data))
        assert response["error"]["code"] == "method_not_found"
        await peer.close()

    asyncio.run(scenario())
