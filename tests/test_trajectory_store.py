from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path

import pytest

import memoli_agent.agent.trajectory as trajectory_module
from memoli_agent.agent.trajectory import (
    SCHEMA_VERSION,
    NewTrajectoryEvent,
    SpanKind,
    SpanProjection,
    SQLiteTrajectoryStore,
    TraceProjection,
    TrajectoryError,
    TrajectorySchemaError,
    export_trace_jsonl,
    new_span_id,
    new_trace_id,
    utc_now_iso,
)


def run(coroutine):  # type: ignore[no-untyped-def]
    return asyncio.run(coroutine)


def build_store(tmp_path: Path, **kwargs) -> SQLiteTrajectoryStore:  # type: ignore[no-untyped-def]
    return SQLiteTrajectoryStore(
        tmp_path / "trajectories.db",
        payload_directory=tmp_path / "payloads",
        **kwargs,
    )


def test_sqlite_store_records_queries_and_exports_deterministically(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        store = build_store(tmp_path)
        await store.start()
        trace_id = new_trace_id()
        root_id = new_span_id()
        started = utc_now_iso()
        trace = TraceProjection(trace_id, "session-a", started, provider="fake")
        root = SpanProjection(
            root_id,
            trace_id,
            None,
            SpanKind.AGENT,
            "turn",
            started,
            input_data={"content": "你好"},
        )
        first = await store.record(
            NewTrajectoryEvent(
                trace_id,
                "trace_started",
                {"content": "你好"},
                span_id=root_id,
                trace=trace,
                span=root,
            )
        )
        finished_trace = TraceProjection(
            trace_id,
            "session-a",
            started,
            status="completed",
            ended_at=utc_now_iso(),
            termination_reason="completed",
            final_output="完成",
            provider="fake",
            iteration_count=1,
        )
        second = await store.record(
            NewTrajectoryEvent(
                trace_id,
                "trace_finished",
                {"final_output": "完成"},
                span_id=root_id,
                trace=finished_trace,
                span=SpanProjection(
                    root_id,
                    trace_id,
                    None,
                    SpanKind.AGENT,
                    "turn",
                    started,
                    status="completed",
                    ended_at=utc_now_iso(),
                    output_data="完成",
                ),
            )
        )

        assert (first.sequence, second.sequence) == (1, 2)
        bundle = await store.get_trace(trace_id)
        assert bundle is not None
        assert [event["event_type"] for event in bundle["events"]] == [
            "trace_started",
            "trace_finished",
        ]
        assert bundle["trace"]["termination_reason"] == "completed"
        assert len(bundle["spans"]) == 1
        queried = await store.query_traces(
            session_id="session-a",
            termination_reason="completed",
            provider="fake",
            span_kind=SpanKind.AGENT,
        )
        assert [item["trace_id"] for item in queried] == [trace_id]
        first_export = await export_trace_jsonl(store, trace_id)
        second_export = await export_trace_jsonl(store, trace_id)
        assert first_export == second_export
        with pytest.raises(TrajectoryError, match="轨迹不存在"):
            await export_trace_jsonl(store, new_trace_id())
        assert await export_trace_jsonl(store, trace_id) == first_export
        assert '"record_type":"trace"' in first_export
        assert '"record_type":"event"' in first_export
        assert store._connection is not None
        assert store._connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        await store.close()

    run(scenario())

    with sqlite3.connect(tmp_path / "trajectories.db") as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        assert "idx_events_trace_sequence" in indexes


def test_sensitive_and_hidden_content_is_redacted(tmp_path: Path) -> None:
    async def scenario() -> str:
        store = build_store(tmp_path, sensitive_keys=["private_key"])
        await store.start()
        trace_id = new_trace_id()
        started = utc_now_iso()
        await store.record(
            NewTrajectoryEvent(
                trace_id,
                "trace_started",
                {
                    "api_key": "secret-value",
                    "nested": {"private_key": "private-value"},
                    "reasoning": "hidden-thought",
                    "headers": ["Authorization: Bearer top-secret-token"],
                    "url": "https://example.test/?api_key=url-secret&x=1",
                },
                trace=TraceProjection(trace_id, "private", started),
            )
        )
        exported = await export_trace_jsonl(store, trace_id)
        await store.close()
        return exported

    exported = run(scenario())
    assert "secret-value" not in exported
    assert "private-value" not in exported
    assert "hidden-thought" not in exported
    assert "top-secret-token" not in exported
    assert "url-secret" not in exported
    assert "REDACTED" in exported
    assert "HIDDEN_REASONING_NOT_RECORDED" in exported


def test_large_payload_uses_managed_external_storage(tmp_path: Path) -> None:
    async def scenario() -> tuple[dict, str]:
        store = build_store(tmp_path, max_inline_bytes=16, max_payload_bytes=32)
        await store.start()
        trace_id = new_trace_id()
        await store.record(
            NewTrajectoryEvent(
                trace_id,
                "trace_started",
                {"content": "".join(chr(33 + index % 90) for index in range(10_000))},
                trace=TraceProjection(trace_id, "large", utc_now_iso()),
            )
        )
        bundle = await store.get_trace(trace_id)
        exported = await export_trace_jsonl(store, trace_id)
        await store.close()
        assert bundle is not None
        return bundle, exported

    bundle, exported = run(scenario())
    external = [item for item in bundle["payloads"] if item["external_uri"]]
    assert external
    assert all(".." not in item["external_uri"] for item in external)
    assert (tmp_path / "payloads" / external[0]["external_uri"]).is_file()
    assert '"external_uri":"' in exported
    assert '"transformed":1' in exported


def test_unknown_schema_version_is_not_rebuilt(tmp_path: Path) -> None:
    database = tmp_path / "future.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE trajectory_meta(key TEXT PRIMARY KEY, value TEXT)"
        )
        connection.execute(
            "INSERT INTO trajectory_meta VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION + 1),),
        )
        connection.execute("CREATE TABLE keep_me(value TEXT)")
        connection.commit()

    store = SQLiteTrajectoryStore(
        database,
        payload_directory=tmp_path / "payloads",
    )
    with pytest.raises(TrajectorySchemaError):
        run(store.start())

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name='keep_me'"
        ).fetchone()


def test_schema_v1_is_migrated_without_rebuilding_data(tmp_path: Path) -> None:
    store = build_store(tmp_path)
    run(store.start())
    run(store.close())
    with sqlite3.connect(tmp_path / "trajectories.db") as connection:
        connection.execute("DROP INDEX idx_events_span_id")
        connection.execute(
            "UPDATE trajectory_meta SET value='1' WHERE key='schema_version'"
        )
        connection.commit()

    migrated = build_store(tmp_path)
    run(migrated.start())
    run(migrated.close())
    with sqlite3.connect(tmp_path / "trajectories.db") as connection:
        version = connection.execute(
            "SELECT value FROM trajectory_meta WHERE key='schema_version'"
        ).fetchone()[0]
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
    assert version == str(SCHEMA_VERSION)
    assert "idx_events_span_id" in indexes


def test_external_payload_is_removed_when_transaction_rolls_back(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    async def scenario() -> None:
        store = build_store(tmp_path, max_inline_bytes=8, max_payload_bytes=16)
        await store.start()

        def fail(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise sqlite3.OperationalError("expected")

        monkeypatch.setattr(store, "_upsert_trace", fail)
        with pytest.raises(TrajectoryError):
            await store.record(
                NewTrajectoryEvent(
                    new_trace_id(),
                    "trace_started",
                    {"content": "0123456789" * 1000},
                    trace=TraceProjection(new_trace_id(), "s", utc_now_iso()),
                )
            )
        assert list((tmp_path / "payloads").glob("*.json.zlib")) == []
        await store.close()

    run(scenario())


def test_corrupt_compressed_payload_is_wrapped(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = build_store(tmp_path, max_inline_bytes=8, max_payload_bytes=100_000)
        await store.start()
        trace_id = new_trace_id()
        event = await store.record(
            NewTrajectoryEvent(
                trace_id,
                "trace_started",
                {"content": "0123456789" * 100},
                trace=TraceProjection(trace_id, "s", utc_now_iso()),
            )
        )
        assert event.payload_id is not None
        assert store._connection is not None
        store._connection.execute(
            "UPDATE payloads SET blob=? WHERE payload_id=?",
            (b"broken-zlib", event.payload_id),
        )
        with pytest.raises(TrajectoryError, match="压缩数据损坏"):
            await store.read_payload_json(event.payload_id)
        await store.close()

    run(scenario())


def test_orphan_payload_gc_is_bounded_and_dry_run_by_default(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = build_store(tmp_path)
        await store.start()
        orphan = tmp_path / "payloads" / "orphan.json.zlib"
        orphan.write_bytes(b"orphan")
        old = time.time() - 10
        import os

        os.utime(orphan, (old, old))
        assert await store.collect_orphan_payloads(grace_seconds=1) == [orphan.name]
        assert orphan.exists()
        assert await store.collect_orphan_payloads(
            grace_seconds=1, dry_run=False, limit=1
        ) == [orphan.name]
        assert not orphan.exists()
        await store.close()

    run(scenario())


def test_non_string_keys_are_deterministic_and_collisions_are_explicit(
    tmp_path: Path,
) -> None:
    class UnsafeKey:
        def __str__(self) -> str:
            return "api_key=must-not-be-rendered"

    async def scenario() -> object:
        store = build_store(tmp_path)
        await store.start()
        trace_id = new_trace_id()
        event = await store.record(
            NewTrajectoryEvent(
                trace_id,
                "key_conversion",
                {UnsafeKey(): "first", UnsafeKey(): "second"},
                trace=TraceProjection(trace_id, "session", utc_now_iso()),
            )
        )
        assert event.payload_id is not None
        payload = await store.read_payload_json(event.payload_id)
        await store.close()
        return payload

    assert run(scenario()) == {"converted": True, "reason": "key-collision"}


def test_failed_schema_creation_rolls_back(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    database = tmp_path / "broken.db"
    monkeypatch.setattr(
        trajectory_module,
        "_SCHEMA_SQL",
        "CREATE TABLE partial(value TEXT); INVALID SQL",
    )
    store = SQLiteTrajectoryStore(
        database,
        payload_directory=tmp_path / "payloads",
    )

    with pytest.raises(sqlite3.Error):
        run(store.start())

    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='partial'"
            ).fetchone()
            is None
        )


def test_unfinished_trace_remains_queryable(tmp_path: Path) -> None:
    async def scenario() -> dict:
        store = build_store(tmp_path)
        await store.start()
        trace_id = new_trace_id()
        await store.record(
            NewTrajectoryEvent(
                trace_id,
                "trace_started",
                {"state": "started"},
                trace=TraceProjection(trace_id, "crashed", utc_now_iso()),
            )
        )
        bundle = await store.get_trace(trace_id)
        await store.close()
        assert bundle is not None
        return bundle

    bundle = run(scenario())
    assert bundle["trace"]["status"] == "running"
    assert bundle["trace"]["termination_reason"] is None
    assert all(event["event_type"] != "trace_finished" for event in bundle["events"])


def test_in_memory_payload_ids_are_monotonic_after_list_mutation() -> None:
    async def scenario() -> tuple[int | None, int | None]:
        store = trajectory_module.InMemoryTrajectoryStore()
        first = await store.record(NewTrajectoryEvent(new_trace_id(), "first", {}))
        store.event_payloads.clear()
        second = await store.record(NewTrajectoryEvent(new_trace_id(), "second", {}))
        return first.payload_id, second.payload_id

    assert run(scenario()) == (1, 2)
