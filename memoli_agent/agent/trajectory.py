"""Agent 运行轨迹的类型、SQLite 存储与 JSONL 导出。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import secrets
import sqlite3
import zlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

SCHEMA_VERSION = 2
DEFAULT_SENSITIVE_KEYS = frozenset(
    {"api_key", "authorization", "cookie", "password", "secret", "token"}
)
HIDDEN_REASONING_KEYS = frozenset({"reasoning", "thinking", "chain_of_thought"})


def utc_now_iso() -> str:
    """返回可排序的 UTC 时间。"""

    return datetime.now(UTC).isoformat()


def new_trace_id() -> str:
    """生成与 OpenTelemetry 长度兼容的 trace ID。"""

    return secrets.token_hex(16)


def new_span_id() -> str:
    """生成与 OpenTelemetry 长度兼容的 span ID。"""

    return secrets.token_hex(8)


class TrajectoryError(RuntimeError):
    """轨迹存储的统一异常。"""


class TrajectorySchemaError(TrajectoryError):
    """轨迹数据库 schema 不兼容。"""


class SpanKind(StrEnum):
    """首版支持的少量 span 类型。"""

    AGENT = "agent"
    LLM = "llm"
    TOOL = "tool"
    MEMORY = "memory"
    GUARDRAIL = "guardrail"


@dataclass(frozen=True, slots=True)
class TraceProjection:
    """便于查询的 trace 当前状态。"""

    trace_id: str
    session_id: str
    started_at: str
    status: str = "running"
    ended_at: str | None = None
    termination_reason: str | None = None
    final_output: Any = None
    provider: str = ""
    model: str = ""
    fallback_used: bool = False
    usage: dict[str, Any] = field(default_factory=dict)
    iteration_count: int = 0
    runtime_version: str = "0.1.0"


@dataclass(frozen=True, slots=True)
class SpanProjection:
    """便于查询的 span 当前状态。"""

    span_id: str
    trace_id: str
    parent_span_id: str | None
    kind: SpanKind
    name: str
    started_at: str
    status: str = "running"
    ended_at: str | None = None
    input_data: Any = None
    output_data: Any = None
    error_type: str | None = None
    error_message: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NewTrajectoryEvent:
    """一次原子提交：追加事件，并同步更新可选投影。"""

    trace_id: str
    event_type: str
    payload: Any = None
    span_id: str | None = None
    occurred_at: str = field(default_factory=utc_now_iso)
    trace: TraceProjection | None = None
    span: SpanProjection | None = None


@dataclass(frozen=True, slots=True)
class TrajectoryEvent:
    """已经获得 trace 内顺序号的事件。"""

    trace_id: str
    sequence: int
    event_type: str
    occurred_at: str
    span_id: str | None = None
    payload_id: int | None = None
    schema_version: int = SCHEMA_VERSION


class TrajectoryStore(Protocol):
    """Reasoner 依赖的最小轨迹存储协议。"""

    async def start(self) -> None: ...

    async def close(self) -> None: ...

    async def record(self, item: NewTrajectoryEvent) -> TrajectoryEvent: ...


@dataclass(slots=True)
class NullTrajectoryStore:
    """显式关闭轨迹时使用。"""

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def record(self, item: NewTrajectoryEvent) -> TrajectoryEvent:
        return TrajectoryEvent(
            trace_id=item.trace_id,
            sequence=0,
            event_type=item.event_type,
            occurred_at=item.occurred_at,
            span_id=item.span_id,
        )


@dataclass(slots=True)
class InMemoryTrajectoryStore:
    """测试用内存存储。"""

    events: list[TrajectoryEvent] = field(default_factory=list)
    event_payloads: list[Any] = field(default_factory=list)
    traces: dict[str, TraceProjection] = field(default_factory=dict)
    spans: dict[str, SpanProjection] = field(default_factory=dict)
    _next_payload_id: int = 1

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def record(self, item: NewTrajectoryEvent) -> TrajectoryEvent:
        sequence = 1 + sum(event.trace_id == item.trace_id for event in self.events)
        payload_id = self._next_payload_id
        self._next_payload_id += 1
        event = TrajectoryEvent(
            trace_id=item.trace_id,
            sequence=sequence,
            event_type=item.event_type,
            occurred_at=item.occurred_at,
            span_id=item.span_id,
            payload_id=payload_id,
        )
        if item.trace is not None:
            self.traces[item.trace.trace_id] = item.trace
        if item.span is not None:
            self.spans[item.span.span_id] = item.span
        self.event_payloads.append(item.payload)
        self.events.append(event)
        return event


class SQLiteTrajectoryStore:
    """单 writer SQLite 轨迹存储。"""

    def __init__(
        self,
        database: str | Path,
        *,
        payload_directory: str | Path,
        capture_content: str = "redacted",
        max_inline_bytes: int = 65_536,
        max_payload_bytes: int = 4_194_304,
        sensitive_keys: list[str] | tuple[str, ...] = (),
    ) -> None:
        if capture_content not in {"metadata-only", "redacted", "full-local"}:
            raise ValueError("trajectory.capture_content 配置无效。")
        if max_inline_bytes <= 0 or max_payload_bytes < max_inline_bytes:
            raise ValueError("trajectory payload 大小限制无效。")

        self.database = Path(database)
        self.payload_directory = Path(payload_directory)
        self.capture_content = capture_content
        self.max_inline_bytes = max_inline_bytes
        self.max_payload_bytes = max_payload_bytes
        self.sensitive_keys = DEFAULT_SENSITIVE_KEYS | frozenset(
            key.lower() for key in sensitive_keys
        )
        self._connection: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self._pending_external_paths: list[Path] = []

    async def start(self) -> None:
        async with self._lock:
            if self._connection is None:
                await asyncio.to_thread(self._start_sync)

    async def close(self) -> None:
        async with self._lock:
            if self._connection is not None:
                await asyncio.to_thread(self._close_sync)

    async def record(self, item: NewTrajectoryEvent) -> TrajectoryEvent:
        async with self._lock:
            if self._connection is None:
                raise TrajectoryError("轨迹数据库尚未启动。")
            try:
                return await asyncio.to_thread(self._record_sync, item)
            except TrajectoryError:
                raise
            except Exception as exc:
                raise TrajectoryError(
                    f"轨迹写入失败：{type(exc).__name__}"
                ) from exc

    async def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        """读取一个 trace 及其全部关联记录。"""

        async with self._lock:
            if self._connection is None:
                raise TrajectoryError("轨迹数据库尚未启动。")
            return await asyncio.to_thread(self._get_trace_sync, trace_id)

    async def read_payload_json(self, payload_id: int) -> Any:
        """读取内联、压缩或外置 payload 的原始 JSON。"""

        async with self._lock:
            if self._connection is None:
                raise TrajectoryError("轨迹数据库尚未启动。")
            try:
                return await asyncio.to_thread(self._read_payload_json_sync, payload_id)
            except TrajectoryError:
                raise
            except Exception as exc:
                raise TrajectoryError(
                    f"payload 读取失败：{type(exc).__name__}"
                ) from exc

    async def collect_orphan_payloads(
        self,
        *,
        grace_seconds: float = 3600.0,
        dry_run: bool = True,
        limit: int = 100,
    ) -> list[str]:
        """列出或删除无引用 payload；默认 dry-run，且只处理受管目录。"""

        if grace_seconds < 0 or limit <= 0:
            raise ValueError("payload GC 参数无效。")
        async with self._lock:
            if self._connection is None:
                raise TrajectoryError("轨迹数据库尚未启动。")
            return await asyncio.to_thread(
                self._collect_orphan_payloads_sync, grace_seconds, dry_run, limit
            )

    async def query_traces(
        self,
        *,
        session_id: str | None = None,
        termination_reason: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        span_kind: SpanKind | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
    ) -> list[dict[str, Any]]:
        """使用索引字段筛选 trace。"""

        filters = {
            "session_id": session_id,
            "termination_reason": termination_reason,
            "provider": provider,
            "model": model,
            "span_kind": span_kind.value if span_kind else None,
            "started_after": started_after,
            "started_before": started_before,
        }
        async with self._lock:
            if self._connection is None:
                raise TrajectoryError("轨迹数据库尚未启动。")
            return await asyncio.to_thread(self._query_traces_sync, filters)

    def _start_sync(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.payload_directory.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.database, check_same_thread=False, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA busy_timeout = 5000")
            self._initialize_schema(connection)
        except Exception:
            connection.close()
            raise
        self._connection = connection

    def _close_sync(self) -> None:
        connection = self._connection
        assert connection is not None
        self._connection = None
        connection.close()

    def _initialize_schema(self, connection: sqlite3.Connection) -> None:
        """只允许显式版本；遇到未来版本绝不重建数据。"""

        has_meta = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='trajectory_meta'"
        ).fetchone()
        if has_meta:
            row = connection.execute(
                "SELECT value FROM trajectory_meta WHERE key='schema_version'"
            ).fetchone()
            version = int(row[0]) if row else 0
            if version > SCHEMA_VERSION:
                raise TrajectorySchemaError(
                    f"不支持的轨迹 schema version：{version}，当前为 {SCHEMA_VERSION}。"
                )
            if version == 1:
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute(
                        "CREATE INDEX IF NOT EXISTS idx_events_span_id "
                        "ON events(span_id)"
                    )
                    connection.execute(
                        "UPDATE trajectory_meta SET value=? WHERE key='schema_version'",
                        (str(SCHEMA_VERSION),),
                    )
                    connection.commit()
                except Exception:
                    _safe_rollback(connection)
                    raise
            return

        try:
            # DDL 与版本号在同一事务中提交，失败时不会留下半套 schema。
            connection.execute("BEGIN IMMEDIATE")
            for statement in _schema_statements(_SCHEMA_SQL):
                connection.execute(statement)
            connection.execute(
                "INSERT INTO trajectory_meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.commit()
        except sqlite3.Error:
            _safe_rollback(connection)
            raise

    def _record_sync(self, item: NewTrajectoryEvent) -> TrajectoryEvent:
        connection = self._require_connection()
        self._pending_external_paths = []
        try:
            connection.execute("BEGIN IMMEDIATE")
            event_payload_id = self._save_payload(connection, item.payload)
            trace = item.trace
            if trace is not None:
                final_output_id = self._save_payload(connection, trace.final_output)
                self._upsert_trace(connection, trace, final_output_id)
            span = item.span
            if span is not None:
                input_id = self._save_payload(connection, span.input_data)
                output_id = self._save_payload(connection, span.output_data)
                self._upsert_span(connection, span, input_id, output_id)

            row = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE trace_id=?",
                (item.trace_id,),
            ).fetchone()
            sequence = int(row[0])
            connection.execute(
                """
                INSERT INTO events(
                    trace_id, span_id, sequence, event_type, occurred_at,
                    payload_id, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.trace_id,
                    item.span_id,
                    sequence,
                    item.event_type,
                    item.occurred_at,
                    event_payload_id,
                    SCHEMA_VERSION,
                ),
            )
            connection.commit()
            self._pending_external_paths.clear()
        except Exception:
            _safe_rollback(connection)
            for path in self._pending_external_paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
            self._pending_external_paths.clear()
            raise

        return TrajectoryEvent(
            trace_id=item.trace_id,
            span_id=item.span_id,
            sequence=sequence,
            event_type=item.event_type,
            occurred_at=item.occurred_at,
            payload_id=event_payload_id,
        )

    def _save_payload(
        self,
        connection: sqlite3.Connection,
        value: Any,
    ) -> int | None:
        if value is None:
            return None

        cleaned = _clean_value(value, self.capture_content, self.sensitive_keys)
        raw = json.dumps(
            cleaned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        existing = connection.execute(
            "SELECT payload_id FROM payloads WHERE sha256=?", (digest,)
        ).fetchone()
        if existing:
            return int(existing[0])

        inline_text: str | None = None
        blob: bytes | None = None
        external_uri: str | None = None
        compression = "none"
        transformed = 0
        truncated = int(_contains_truncation(cleaned))

        if len(raw) <= self.max_inline_bytes:
            inline_text = raw.decode("utf-8")
            stored_size = len(raw)
        else:
            compressed = zlib.compress(raw)
            compression = "zlib"
            transformed = 1
            stored_size = len(compressed)
            if stored_size <= self.max_payload_bytes:
                blob = compressed
            else:
                external_uri = self._write_external_payload(digest, compressed)

        cursor = connection.execute(
            """
            INSERT INTO payloads(
                content_type, encoding, compression, redaction_status, sha256,
                original_size, stored_size, inline_text, blob, external_uri,
                transformed, truncated
            ) VALUES ('application/json', 'utf-8', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                compression,
                self.capture_content,
                digest,
                len(raw),
                stored_size,
                inline_text,
                blob,
                external_uri,
                transformed,
                truncated,
            ),
        )
        payload_id = cursor.lastrowid
        if payload_id is None:
            raise TrajectoryError("SQLite 未返回 payload ID。")
        return payload_id

    def _write_external_payload(self, digest: str, content: bytes) -> str:
        root = self.payload_directory.resolve()
        target = (root / f"{digest}.json.zlib").resolve()
        if target.parent != root:
            raise TrajectoryError("payload 路径越界。")
        if not target.exists():
            temporary = target.with_suffix(".tmp")
            try:
                temporary.write_bytes(content)
                temporary.replace(target)
                self._pending_external_paths.append(target)
            finally:
                temporary.unlink(missing_ok=True)
        return target.relative_to(root).as_posix()

    def _upsert_trace(
        self,
        connection: sqlite3.Connection,
        trace: TraceProjection,
        final_output_id: int | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO traces(
                trace_id, session_id, started_at, ended_at, status,
                termination_reason, final_output_payload_id, provider, model,
                fallback_used, usage_json, iteration_count, runtime_version,
                schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trace_id) DO UPDATE SET
                ended_at=excluded.ended_at,
                status=excluded.status,
                termination_reason=excluded.termination_reason,
                final_output_payload_id=COALESCE(
                    excluded.final_output_payload_id,
                    traces.final_output_payload_id
                ),
                provider=excluded.provider,
                model=excluded.model,
                fallback_used=excluded.fallback_used,
                usage_json=excluded.usage_json,
                iteration_count=excluded.iteration_count,
                runtime_version=excluded.runtime_version
            """,
            (
                trace.trace_id,
                trace.session_id,
                trace.started_at,
                trace.ended_at,
                trace.status,
                trace.termination_reason,
                final_output_id,
                trace.provider,
                trace.model,
                int(trace.fallback_used),
                _canonical_json(trace.usage),
                trace.iteration_count,
                trace.runtime_version,
                SCHEMA_VERSION,
            ),
        )

    def _upsert_span(
        self,
        connection: sqlite3.Connection,
        span: SpanProjection,
        input_id: int | None,
        output_id: int | None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO spans(
                span_id, trace_id, parent_span_id, kind, name, started_at,
                ended_at, status, input_payload_id, output_payload_id,
                error_type, error_message, attributes_json, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(span_id) DO UPDATE SET
                ended_at=excluded.ended_at,
                status=excluded.status,
                input_payload_id=COALESCE(
                    excluded.input_payload_id,
                    spans.input_payload_id
                ),
                output_payload_id=COALESCE(
                    excluded.output_payload_id,
                    spans.output_payload_id
                ),
                error_type=excluded.error_type,
                error_message=excluded.error_message,
                attributes_json=excluded.attributes_json
            """,
            (
                span.span_id,
                span.trace_id,
                span.parent_span_id,
                span.kind.value,
                span.name,
                span.started_at,
                span.ended_at,
                span.status,
                input_id,
                output_id,
                span.error_type,
                span.error_message,
                _canonical_json(span.attributes),
                SCHEMA_VERSION,
            ),
        )

    def _get_trace_sync(self, trace_id: str) -> dict[str, Any] | None:
        connection = self._require_connection()
        trace = connection.execute(
            "SELECT * FROM traces WHERE trace_id=?", (trace_id,)
        ).fetchone()
        if trace is None:
            return None
        spans = connection.execute(
            "SELECT * FROM spans WHERE trace_id=? ORDER BY started_at, span_id",
            (trace_id,),
        ).fetchall()
        events = connection.execute(
            "SELECT * FROM events WHERE trace_id=? ORDER BY sequence", (trace_id,)
        ).fetchall()
        payload_ids = {
            int(value)
            for row in [trace, *spans, *events]
            for key, value in dict(row).items()
            if key.endswith("payload_id") and value is not None
        }
        payloads = []
        if payload_ids:
            placeholders = ",".join("?" for _ in payload_ids)
            payloads = connection.execute(
                f"SELECT * FROM payloads WHERE payload_id IN ({placeholders}) "
                "ORDER BY payload_id",
                tuple(sorted(payload_ids)),
            ).fetchall()
        return {
            "trace": dict(trace),
            "spans": [dict(row) for row in spans],
            "events": [dict(row) for row in events],
            "payloads": [_exportable_payload(row) for row in payloads],
        }

    def _query_traces_sync(
        self, filters: dict[str, str | None]
    ) -> list[dict[str, Any]]:
        connection = self._require_connection()
        clauses: list[str] = []
        values: list[str] = []
        for key in ("session_id", "termination_reason", "provider", "model"):
            value = filters[key]
            if value is not None:
                clauses.append(f"t.{key}=?")
                values.append(value)
        if filters["started_after"] is not None:
            clauses.append("t.started_at>=?")
            values.append(str(filters["started_after"]))
        if filters["started_before"] is not None:
            clauses.append("t.started_at<=?")
            values.append(str(filters["started_before"]))
        if filters["span_kind"] is not None:
            clauses.append(
                "EXISTS(SELECT 1 FROM spans s WHERE s.trace_id=t.trace_id AND s.kind=?)"
            )
            values.append(str(filters["span_kind"]))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = connection.execute(
            f"SELECT t.* FROM traces t {where} ORDER BY t.started_at", values
        ).fetchall()
        return [dict(row) for row in rows]

    def _read_payload_json_sync(self, payload_id: int) -> Any:
        connection = self._require_connection()
        row = connection.execute(
            "SELECT * FROM payloads WHERE payload_id=?", (payload_id,)
        ).fetchone()
        if row is None:
            raise TrajectoryError(f"payload 不存在：{payload_id}")
        if row["inline_text"] is not None:
            raw = str(row["inline_text"]).encode("utf-8")
        elif row["blob"] is not None:
            raw = bytes(row["blob"])
        elif row["external_uri"] is not None:
            root = self.payload_directory.resolve()
            target = (root / str(row["external_uri"])).resolve()
            if target.parent != root:
                raise TrajectoryError("payload 引用路径越界。")
            try:
                raw = target.read_bytes()
            except OSError as exc:
                raise TrajectoryError("payload 外部文件无法读取。") from exc
        else:
            return None
        if row["compression"] == "zlib":
            try:
                raw = zlib.decompress(raw)
            except zlib.error as exc:
                raise TrajectoryError("payload 压缩数据损坏。") from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TrajectoryError("payload JSON 无法解析。") from exc

    def _collect_orphan_payloads_sync(
        self, grace_seconds: float, dry_run: bool, limit: int
    ) -> list[str]:
        connection = self._require_connection()
        referenced = {
            int(row[0])
            for query in (
                "SELECT final_output_payload_id FROM traces "
                "WHERE final_output_payload_id IS NOT NULL",
                "SELECT input_payload_id FROM spans WHERE input_payload_id IS NOT NULL",
                "SELECT output_payload_id FROM spans "
                "WHERE output_payload_id IS NOT NULL",
                "SELECT payload_id FROM events WHERE payload_id IS NOT NULL",
            )
            for row in connection.execute(query)
        }
        now = datetime.now(UTC).timestamp()
        candidates: list[tuple[int | None, str, Path]] = []
        rows = connection.execute(
            "SELECT payload_id, external_uri FROM payloads "
            "WHERE external_uri IS NOT NULL"
        ).fetchall()
        known_uris = {str(row["external_uri"]) for row in rows}
        root = self.payload_directory.resolve()
        for row in rows:
            payload_id = int(row["payload_id"])
            if payload_id in referenced:
                continue
            uri = str(row["external_uri"])
            target = (root / uri).resolve()
            if target.parent == root and _older_than(target, now, grace_seconds):
                candidates.append((payload_id, uri, target))
        for target in root.glob("*.json.zlib"):
            uri = target.name
            if uri not in known_uris and _older_than(target, now, grace_seconds):
                candidates.append((None, uri, target.resolve()))
        candidates = sorted(candidates, key=lambda item: item[1])[:limit]
        if dry_run:
            return [item[1] for item in candidates]
        connection.execute("BEGIN IMMEDIATE")
        try:
            for payload_id, _, target in candidates:
                target.unlink(missing_ok=True)
                if payload_id is not None:
                    connection.execute(
                        "DELETE FROM payloads WHERE payload_id=?", (payload_id,)
                    )
            connection.commit()
        except Exception:
            _safe_rollback(connection)
            raise
        return [item[1] for item in candidates]

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise TrajectoryError("轨迹数据库尚未启动。")
        return self._connection


async def export_trace_jsonl(store: SQLiteTrajectoryStore, trace_id: str) -> str:
    """从已提交数据生成确定性 JSONL，不修改源数据库。"""

    bundle = await store.get_trace(trace_id)
    if bundle is None:
        raise TrajectoryError(f"轨迹不存在：{trace_id}")

    records: list[dict[str, Any]] = [_versioned_record("trace", bundle["trace"])]
    records.extend(_versioned_record("event", event) for event in bundle["events"])
    records.extend(_versioned_record("span", span) for span in bundle["spans"])
    records.extend(
        _versioned_record("payload", payload) for payload in bundle["payloads"]
    )
    return "\n".join(_canonical_json(record) for record in records) + "\n"


def _clean_value(
    value: Any,
    capture_content: str,
    sensitive_keys: frozenset[str],
    _seen: set[int] | None = None,
) -> Any:
    """先最小化内容，再递归清除凭证和隐藏推理。"""

    if capture_content == "metadata-only":
        return {"captured": False, "value_type": type(value).__name__}
    if _seen is None:
        _seen = set()
    compound = isinstance(value, dict | list | tuple | set) or hasattr(
        value, "__dataclass_fields__"
    )
    if compound:
        marker = id(value)
        if marker in _seen:
            return {"converted": True, "reason": "cycle"}
        _seen.add(marker)
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = _deterministic_key(raw_key)
            if key in cleaned:
                return {"converted": True, "reason": "key-collision"}
            lowered = key.lower()
            if lowered in sensitive_keys:
                cleaned[key] = "[REDACTED]"
            elif lowered in HIDDEN_REASONING_KEYS:
                cleaned[key] = "[HIDDEN_REASONING_NOT_RECORDED]"
            else:
                cleaned[key] = _clean_value(
                    raw_value, capture_content, sensitive_keys, _seen
                )
        return cleaned
    if isinstance(value, list | tuple | set):
        return [
            _clean_value(item, capture_content, sensitive_keys, _seen)
            for item in value
        ]
    if isinstance(value, bytes):
        return {
            "binary": True,
            "sha256": hashlib.sha256(value).hexdigest(),
            "size": len(value),
            "truncated": True,
        }
    if isinstance(value, str):
        return _redact_string(value)
    if value is None or isinstance(value, int | float | bool):
        return value
    if hasattr(value, "to_dict"):
        return _clean_value(value.to_dict(), capture_content, sensitive_keys, _seen)
    if hasattr(value, "__dataclass_fields__"):
        return _clean_value(asdict(value), capture_content, sensitive_keys, _seen)
    return {
        "converted": True,
        "reason": "unsupported-type",
        "value_type": f"{type(value).__module__}.{type(value).__qualname__}",
    }


def _deterministic_key(value: Any) -> str:
    """把非字符串字典键转换为稳定表示，不调用任意对象的 ``str``。"""

    if isinstance(value, str):
        return value
    if value is None:
        return "@key:null"
    if isinstance(value, bool):
        return f"@key:bool:{str(value).lower()}"
    if isinstance(value, int):
        return f"@key:int:{value}"
    if isinstance(value, float):
        if not math.isfinite(value):
            return f"@key:float:{repr(value)}"
        return f"@key:float:{json.dumps(value, allow_nan=False)}"
    return f"@key:type:{type(value).__module__}.{type(value).__qualname__}"


def _contains_truncation(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value.get("truncated")) or any(
            _contains_truncation(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_truncation(item) for item in value)
    return False


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _exportable_payload(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    blob = payload.pop("blob", None)
    if blob is not None:
        payload["blob_sha256"] = hashlib.sha256(blob).hexdigest()
    return payload


_SCHEMA_SQL = """
CREATE TABLE trajectory_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE payloads (
    payload_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_type TEXT NOT NULL,
    encoding TEXT NOT NULL,
    compression TEXT NOT NULL,
    redaction_status TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    original_size INTEGER NOT NULL,
    stored_size INTEGER NOT NULL,
    inline_text TEXT,
    blob BLOB,
    external_uri TEXT,
    transformed INTEGER NOT NULL DEFAULT 0,
    truncated INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE traces (
    trace_id TEXT PRIMARY KEY CHECK(length(trace_id) = 32),
    session_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    termination_reason TEXT,
    final_output_payload_id INTEGER REFERENCES payloads(payload_id),
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    fallback_used INTEGER NOT NULL DEFAULT 0,
    usage_json TEXT NOT NULL DEFAULT '{}',
    iteration_count INTEGER NOT NULL DEFAULT 0,
    runtime_version TEXT NOT NULL,
    schema_version INTEGER NOT NULL
);

CREATE TABLE spans (
    span_id TEXT PRIMARY KEY CHECK(length(span_id) = 16),
    trace_id TEXT NOT NULL REFERENCES traces(trace_id),
    parent_span_id TEXT REFERENCES spans(span_id),
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    input_payload_id INTEGER REFERENCES payloads(payload_id),
    output_payload_id INTEGER REFERENCES payloads(payload_id),
    error_type TEXT,
    error_message TEXT,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    schema_version INTEGER NOT NULL
);

CREATE TABLE events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL REFERENCES traces(trace_id),
    span_id TEXT REFERENCES spans(span_id),
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_id INTEGER REFERENCES payloads(payload_id),
    schema_version INTEGER NOT NULL,
    UNIQUE(trace_id, sequence)
);

CREATE INDEX idx_traces_session_time ON traces(session_id, started_at);
CREATE INDEX idx_traces_outcome_time ON traces(termination_reason, started_at);
CREATE INDEX idx_traces_provider_model ON traces(provider, model);
CREATE INDEX idx_spans_trace_kind ON spans(trace_id, kind);
CREATE INDEX idx_events_trace_sequence ON events(trace_id, sequence);
CREATE INDEX idx_events_span_id ON events(span_id);
"""


_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)(api[_-]?key|access[_-]?token|token|password|secret|authorization|cookie)"
        r"(\s*[:=]\s*)([^\s&#;,]+)"
    ),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|xox[baprs]-[A-Za-z0-9-]{12,})\b"),
)


def _redact_string(value: str) -> str:
    redacted = value
    redacted = _SECRET_VALUE_PATTERNS[0].sub(r"\1 [REDACTED]", redacted)
    redacted = _SECRET_VALUE_PATTERNS[1].sub(r"\1\2[REDACTED]", redacted)
    redacted = _SECRET_VALUE_PATTERNS[2].sub("[REDACTED]", redacted)
    return redacted


def _safe_rollback(connection: sqlite3.Connection) -> None:
    try:
        connection.rollback()
    except sqlite3.Error:
        pass


def _schema_statements(script: str) -> tuple[str, ...]:
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines():
        buffer += line + "\n"
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        statements.append(buffer.strip())
    return tuple(statements)


def _versioned_record(record_type: str, value: dict[str, Any]) -> dict[str, Any]:
    source_version = value.get("schema_version")
    record = {**value, "record_type": record_type, "schema_version": SCHEMA_VERSION}
    if source_version is not None and source_version != SCHEMA_VERSION:
        record["source_schema_version"] = source_version
    return record


def _older_than(path: Path, now: float, grace_seconds: float) -> bool:
    try:
        return path.is_file() and now - path.stat().st_mtime >= grace_seconds
    except OSError:
        return False
