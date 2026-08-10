from __future__ import annotations

import asyncio
from pathlib import Path

from memoli_agent.agent.trajectory import SQLiteTrajectoryStore
from memoli_agent.bootstrap.app import build_app_runtime
from memoli_agent.bootstrap.config import AppConfig, LLMConfig, TrajectoryConfig
from memoli_agent.bus.events import InboundMessage


def test_runtime_writes_trace_and_closes_store(tmp_path: Path) -> None:
    async def scenario() -> tuple[str, dict[str, object]]:
        config = AppConfig(
            llm=LLMConfig(provider="echo"),
            trajectory=TrajectoryConfig(
                database=str(tmp_path / "trace.db"),
                payload_directory=str(tmp_path / "payloads"),
            ),
        )
        runtime = build_app_runtime(config)
        await runtime.start()
        outbound = await runtime.agent_loop.process(
            InboundMessage(
                channel="cli", chat_id="local", sender="tester", content="你好"
            )
        )
        trace_id = str(outbound.metadata["trace_id"])
        assert isinstance(runtime.trajectory_store, SQLiteTrajectoryStore)
        bundle = await runtime.trajectory_store.get_trace(trace_id)
        await runtime.shutdown()
        assert bundle is not None
        return outbound.content, bundle

    content, bundle = asyncio.run(scenario())
    assert content == "Echo: 你好"
    assert bundle["trace"]["termination_reason"] == "completed"  # type: ignore[index]
    assert (tmp_path / "trace.db").is_file()


def test_disabled_trajectory_creates_no_database(tmp_path: Path) -> None:
    async def scenario() -> None:
        database = tmp_path / "disabled.db"
        config = AppConfig(
            llm=LLMConfig(provider="echo"),
            trajectory=TrajectoryConfig(
                enabled=False,
                database=str(database),
                payload_directory=str(tmp_path / "payloads"),
            ),
        )
        runtime = build_app_runtime(config)
        await runtime.start()
        await runtime.agent_loop.process(
            InboundMessage(
                channel="cli", chat_id="local", sender="tester", content="你好"
            )
        )
        await runtime.shutdown()
        assert not database.exists()

    asyncio.run(scenario())
