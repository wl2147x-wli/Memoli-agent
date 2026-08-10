from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import memoli_agent.agent.mcp.registry as registry_module
from memoli_agent.agent.mcp.client import MCPToolSpec, build_registered_tool_name
from memoli_agent.agent.mcp.registry import MCPClientManager
from memoli_agent.bootstrap.config import MCPServerConfig


@dataclass
class FakeClient:
    config: MCPServerConfig
    closed: int = 0
    connected: int = 0
    tools: list[str] = field(default_factory=lambda: ["tool"])
    fail_close: bool = False

    async def connect(self) -> None:
        self.connected += 1
        if self.config.command == "fail":
            raise RuntimeError("secret connection detail")

    async def list_tools(self) -> list[MCPToolSpec]:
        return [
            MCPToolSpec(
                self.config.name,
                name,
                build_registered_tool_name(self.config.name, name),
                "",
                {"type": "object"},
            )
            for name in self.tools
        ]

    async def close(self) -> None:
        self.closed += 1
        if self.fail_close:
            raise RuntimeError("secret close detail")


def test_partial_failure_rolls_back_failed_and_previously_connected_clients(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    clients: list[FakeClient] = []

    def factory(config: MCPServerConfig) -> FakeClient:
        client = FakeClient(config)
        clients.append(client)
        return client

    monkeypatch.setattr(registry_module, "MCPClient", factory)
    manager = MCPClientManager(
        [MCPServerConfig("ok", command="ok"), MCPServerConfig("bad", command="fail")]
    )
    results = asyncio.run(manager.connect_all())

    assert [result.success for result in results] == [False, False]
    assert "secret connection detail" not in results[1].message
    assert clients[0].closed == 1
    assert clients[1].closed == 1
    assert manager.clients == {}


def test_safe_name_collision_rejects_conflicting_server(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    clients: list[FakeClient] = []

    def factory(config: MCPServerConfig) -> FakeClient:
        client = FakeClient(config)
        clients.append(client)
        return client

    monkeypatch.setattr(registry_module, "MCPClient", factory)
    manager = MCPClientManager(
        [MCPServerConfig("a b", command="ok"), MCPServerConfig("a_b", command="ok")]
    )
    results = asyncio.run(manager.connect_all())

    assert [result.success for result in results] == [False, False]
    assert "a b.tool" in results[1].message
    assert "a_b.tool" in results[1].message
    assert clients[1].closed == 1
    assert manager.tool_specs == []


def test_empty_server_list_and_repeated_connect_close_are_idempotent(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    clients: list[FakeClient] = []

    def factory(config: MCPServerConfig) -> FakeClient:
        client = FakeClient(config, tools=[])
        clients.append(client)
        return client

    monkeypatch.setattr(registry_module, "MCPClient", factory)
    empty = MCPClientManager([])
    assert asyncio.run(empty.connect_all()) == []
    asyncio.run(empty.close_all())

    manager = MCPClientManager([MCPServerConfig("empty", command="ok")])
    assert asyncio.run(manager.connect_all())[0].tool_count == 0
    assert asyncio.run(manager.connect_all())[0].tool_count == 0
    assert clients[0].closed == 1
    asyncio.run(manager.close_all())
    asyncio.run(manager.close_all())


def test_close_failure_does_not_skip_remaining_clients(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    clients: list[FakeClient] = []

    def factory(config: MCPServerConfig) -> FakeClient:
        client = FakeClient(config, fail_close=config.name == "broken")
        clients.append(client)
        return client

    monkeypatch.setattr(registry_module, "MCPClient", factory)
    manager = MCPClientManager(
        [MCPServerConfig("broken", command="ok"), MCPServerConfig("ok", command="ok")]
    )
    assert all(result.success for result in asyncio.run(manager.connect_all()))
    asyncio.run(manager.close_all())
    assert [client.closed for client in clients] == [1, 1]
    assert manager.clients == {}
