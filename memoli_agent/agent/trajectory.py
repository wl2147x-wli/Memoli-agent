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

SCHEMA_VERSION = 4
# 跨轮规范化 committed turn 的事件词汇表；事实层拥有其名称。
TURN_INPUT_COMMITTED = "turn_input_committed"
ASSISTANT_MESSAGE_COMMITTED = "assistant_message_committed"
TOOL_MESSAGE_COMMITTED = "tool_message_committed"
TURN_OUTPUT_COMMITTED = "turn_output_committed"
# §6.6 经 outbox 异步重放投递的审计事件类型：每个由唯一 span_id 标识一次逻辑
# 提交，重放幂等去重按 (trace_id, span_id, event_type)（partial UNIQUE
# events_audit_dedup + record 预检兜底并发）。故意不含 turn/assistant/
# tool_message_committed——它们共用 root span、一轮内合法多次，blanket
# UNIQUE 会丢多工具轮的后续结果。本集合与 compaction.py 的 outbox event_type
# 字符串保持一致（避免 trajectory→compaction 循环 import）。
_AUDIT_EVENT_TYPES = frozenset({"context_compaction_committed"})
COMMITTED_EVENT_TYPES = frozenset(
    {
        TURN_INPUT_COMMITTED,
        ASSISTANT_MESSAGE_COMMITTED,
        TOOL_MESSAGE_COMMITTED,
        TURN_OUTPUT_COMMITTED,
    }
)
# 跨轮 reader 只接受已终止且状态合格的 turn（排除 failed/cancelled/budget）。
QUALIFIED_TURN_STATUSES = frozenset({"completed", "needs-user"})
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
    context_epoch: int = 1
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

    def sanitize_for_capture(self, value: Any) -> Any: ...


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

    def sanitize_for_capture(self, value: Any) -> Any:
        return value

    def current_epoch_sync(self, session_id: str) -> int:
        # 轨迹关闭：无持久 epoch，诊断显示默认 1 且 restorable=false（§2.6）。
        return 1


@dataclass(slots=True)
class InMemoryTrajectoryStore:
    """测试用内存存储。"""

    events: list[TrajectoryEvent] = field(default_factory=list)
    event_payloads: list[Any] = field(default_factory=list)
    traces: dict[str, TraceProjection] = field(default_factory=dict)
    spans: dict[str, SpanProjection] = field(default_factory=dict)
    epochs: dict[str, int] = field(default_factory=dict)
    _next_payload_id: int = 1

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def record(self, item: NewTrajectoryEvent) -> TrajectoryEvent:
        # §6.6 审计事件幂等：经 outbox 重放的 context_compaction_committed 同
        # (trace_id, span_id, event_type) 已投递则返回已有事件，不重复入队/写
        # payload（partial UNIQUE events_audit_dedup 兜底并发）。
        if item.event_type in _AUDIT_EVENT_TYPES:
            for event in self.events:
                if (
                    event.trace_id == item.trace_id
                    and event.span_id == item.span_id
                    and event.event_type == item.event_type
                ):
                    return event
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

    def sanitize_for_capture(self, value: Any) -> Any:
        return value

    async def current_epoch(self, session_id: str) -> int:
        """读取/初始化 session 的当前 epoch（内存版，镜像 SQLite 行为）。"""

        self.epochs[session_id] = max(1, self.epochs.get(session_id, 0))
        return self.epochs[session_id]

    def current_epoch_sync(self, session_id: str) -> int:
        """同步只读当前 conversation epoch（§8.2 CLI 诊断；纯读，不初始化）。

        与异步 ``current_epoch`` 的区别：不写入默认 epoch，无记录返回 1（与异步默认
        一致），仅用于命令派发期的只读诊断。命令同步运行于事件循环线程、此刻无
        Reasoner 写入，只读访问安全（§3.3 同 advance_epoch 的同步前提）。
        """

        return max(1, self.epochs.get(session_id, 0))

    async def create_next_epoch(self, session_id: str) -> int:
        self.epochs[session_id] = max(1, self.epochs.get(session_id, 0)) + 1
        return self.epochs[session_id]

    def advance_epoch(self, session_id: str) -> int:
        """同步推进 conversation epoch（/clear 命令同步调用）；返回新 epoch。

        镜像 ``SQLiteTrajectoryStore.advance_epoch`` 的语义，便于在不落盘的测试
        存储上验证 /clear 的 epoch 推进与派生状态重置（§3.3/§3.6）。
        """

        self.epochs[session_id] = max(1, self.epochs.get(session_id, 0)) + 1
        return self.epochs[session_id]

    async def next_turn_seq(self, session_id: str, epoch: int) -> int:
        count = sum(
            trace.session_id == session_id and trace.context_epoch == epoch
            for trace in self.traces.values()
        )
        return count + 1

    async def read_committed_turns(
        self,
        *,
        session_id: str,
        epoch: int,
        exclude_trace_id: str | None = None,
        after_turn_seq: int | None = None,
        max_turns: int | None = None,
    ) -> list[dict[str, Any]]:
        turns = [
            trace
            for trace in self.traces.values()
            if trace.session_id == session_id
            and trace.context_epoch == epoch
            and trace.ended_at is not None
            and trace.status in QUALIFIED_TURN_STATUSES
            and (exclude_trace_id is None or trace.trace_id != exclude_trace_id)
        ]
        turns.sort(key=lambda trace: (trace.started_at, trace.trace_id))
        result: list[dict[str, Any]] = []
        for turn_seq, trace in enumerate(turns, start=1):
            # §6.7 稳定序号：turn_seq 为完整有序集内的序位（非截断子集序位），
            # 供续读游标 after_turn_seq 精确续读 ordinal > after_turn_seq 的 turn。
            if after_turn_seq is not None and turn_seq <= after_turn_seq:
                continue
            committed = [
                event
                for event in self.events
                if event.trace_id == trace.trace_id
                and event.event_type in COMMITTED_EVENT_TYPES
            ]
            committed.sort(key=lambda event: event.sequence)
            messages: list[dict[str, Any]] = []
            corrupt = False
            # 内联 payload_id 非空过滤（原 resolvable 列表等价）：局部变量使 pyright
            # 收窄为非 None，无 payload 的 committed 事件静默跳过、不计 corrupt。
            for event in committed:
                payload_id = event.payload_id
                if payload_id is None:
                    continue
                envelope = self.event_payloads[payload_id - 1]
                if isinstance(envelope, dict):
                    messages.append(envelope)
                else:
                    corrupt = True
            result.append(
                {
                    "trace_id": trace.trace_id,
                    "epoch": trace.context_epoch,
                    "turn_seq": turn_seq,
                    "status": trace.status,
                    "started_at": trace.started_at,
                    "ended_at": trace.ended_at,
                    "messages": messages,
                    "corrupt": corrupt,
                }
            )
            if max_turns is not None and max_turns > 0 and len(result) >= max_turns:
                break
        return result

    async def restoration_level(self, session_id: str, epoch: int) -> str:
        # 内存存储保留完整 payload，可精确回放；空 epoch 仍视为可精确恢复（无内容）。
        return "exact"

    async def read_legacy_turns(
        self,
        *,
        session_id: str,
        epoch: int,
        exclude_trace_id: str | None = None,
        after_turn_seq: int | None = None,
        max_turns: int | None = None,
    ) -> list[dict[str, Any]]:
        """内存版 legacy-inferred 重构（镜像 SQLite 行为，供测试用）。"""

        turns = [
            trace
            for trace in self.traces.values()
            if trace.session_id == session_id
            and trace.context_epoch == epoch
            and trace.ended_at is not None
            and trace.status in QUALIFIED_TURN_STATUSES
            and (exclude_trace_id is None or trace.trace_id != exclude_trace_id)
        ]
        turns.sort(key=lambda trace: (trace.started_at, trace.trace_id))
        result: list[dict[str, Any]] = []
        for turn_seq, trace in enumerate(turns, start=1):
            # §6.7 稳定序号 + 续读游标（与 durable read_committed_turns 对齐）。
            if after_turn_seq is not None and turn_seq <= after_turn_seq:
                continue
            trace_events = [
                event
                for event in self.events
                if event.trace_id == trace.trace_id
            ]
            trace_events.sort(key=lambda event: event.sequence)
            if any(
                event.event_type in COMMITTED_EVENT_TYPES
                for event in trace_events
            ):
                # 有 committed 事件的 trace 由 durable reader 负责。
                continue
            events: list[tuple[str, dict[str, Any]]] = []
            for event in trace_events:
                payload = {}
                if event.payload_id is not None:
                    raw = self.event_payloads[event.payload_id - 1]
                    if isinstance(raw, dict):
                        payload = raw
                events.append((event.event_type, payload))
            messages, restoration = _reconstruct_legacy_turn(events)
            for envelope in messages:
                envelope["turn_seq"] = turn_seq
                envelope["epoch"] = trace.context_epoch
            result.append(
                {
                    "trace_id": trace.trace_id,
                    "epoch": trace.context_epoch,
                    "turn_seq": turn_seq,
                    "status": trace.status,
                    "started_at": trace.started_at,
                    "ended_at": trace.ended_at,
                    "messages": messages,
                    "restoration": restoration,
                }
            )
            if max_turns is not None and max_turns > 0 and len(result) >= max_turns:
                break
        return result


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
                raise TrajectoryError(f"轨迹写入失败：{type(exc).__name__}") from exc

    def sanitize_for_capture(self, value: Any) -> Any:
        """Apply the exact configured trajectory governance before model preview."""

        return _clean_value(value, self.capture_content, self.sensitive_keys)

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

    async def current_epoch(self, session_id: str) -> int:
        """读取 session 当前 conversation epoch；无记录时原子写入 epoch 1。"""

        async with self._lock:
            if self._connection is None:
                raise TrajectoryError("轨迹数据库尚未启动。")
            return await asyncio.to_thread(self._current_epoch_sync, session_id)

    async def create_next_epoch(self, session_id: str) -> int:
        """原子推进 conversation epoch（`/clear` 调用）；返回新 epoch。"""

        async with self._lock:
            if self._connection is None:
                raise TrajectoryError("轨迹数据库尚未启动。")
            try:
                return await asyncio.to_thread(
                    self._create_next_epoch_sync, session_id
                )
            except TrajectoryError:
                raise
            except Exception as exc:
                raise TrajectoryError(
                    f"epoch 推进失败：{type(exc).__name__}"
                ) from exc

    def advance_epoch(self, session_id: str) -> int:
        """同步推进 conversation epoch（``/clear`` 命令同步调用）；返回新 epoch。

        ``/clear`` 在活动 turn 期间被拒绝、且其同步处理运行于事件循环线程：此刻
        无 Reasoner 写入、事件循环被阻塞故无新 ``asyncio.to_thread`` worker 可被
        调度，直接调用同步内部因此安全。WAL + ``busy_timeout`` 保证与后台
        consolidation 只读访问不冲突；极端锁竞争时抛 ``TrajectoryError``，由
        ``/clear`` 据此报告失败并保持旧 epoch（§3.3）。未装配 trajectory store
        （``NullTrajectoryStore``）时调用方经 ``hasattr`` 能力检查不会触达本方法。
        """

        try:
            return self._create_next_epoch_sync(session_id)
        except TrajectoryError:
            raise
        except Exception as exc:
            raise TrajectoryError(
                f"epoch 推进失败：{type(exc).__name__}"
            ) from exc

    def current_epoch_sync(self, session_id: str) -> int:
        """同步只读当前 conversation epoch（§8.2 CLI 诊断；纯读，不改写状态）。

        与异步 ``current_epoch``/内部 ``_current_epoch_sync`` 的区别：不执行
        ``BEGIN IMMEDIATE``、不 ``INSERT OR IGNORE`` 初始化 epoch 1——诊断命令
        只读不应在查询中改写状态。无记录返回 1（与异步默认一致）。命令派发在事件
        循环线程同步运行、此刻无 Reasoner 写入，WAL 下纯 SELECT 与后台只读/写
        consolidation 不冲突（与 ``advance_epoch`` 同步前提一致，§3.3/§8.2）。
        """

        try:
            connection = self._require_connection()
            row = connection.execute(
                "SELECT COALESCE(MAX(epoch), 1) FROM session_epochs WHERE session_id=?",
                (session_id,),
            ).fetchone()
            return int(row[0])
        except TrajectoryError:
            raise
        except Exception as exc:
            raise TrajectoryError(
                f"epoch 读取失败：{type(exc).__name__}"
            ) from exc

    async def next_turn_seq(self, session_id: str, epoch: int) -> int:
        """返回 (session, epoch) 内下一个 turn 序号（含当前未终止 trace）。"""

        async with self._lock:
            if self._connection is None:
                raise TrajectoryError("轨迹数据库尚未启动。")
            return await asyncio.to_thread(
                self._next_turn_seq_sync, session_id, epoch
            )

    async def read_committed_turns(
        self,
        *,
        session_id: str,
        epoch: int,
        exclude_trace_id: str | None = None,
        after_turn_seq: int | None = None,
        max_turns: int | None = None,
    ) -> list[dict[str, Any]]:
        """读取当前 epoch 中已终止、顺序完整的规范化 turn（跨轮事实来源）。"""

        async with self._lock:
            if self._connection is None:
                raise TrajectoryError("轨迹数据库尚未启动。")
            return await asyncio.to_thread(
                self._read_committed_turns_sync,
                session_id,
                epoch,
                exclude_trace_id,
                max_turns,
                after_turn_seq,
            )

    async def restoration_level(self, session_id: str, epoch: int) -> str:
        """按 capture_content 与 payload 完整性返回恢复等级（exact/governed/...）。"""

        async with self._lock:
            if self._connection is None:
                raise TrajectoryError("轨迹数据库尚未启动。")
            return await asyncio.to_thread(
                self._restoration_level_sync, session_id, epoch
            )

    async def read_legacy_turns(
        self,
        *,
        session_id: str,
        epoch: int,
        exclude_trace_id: str | None = None,
        after_turn_seq: int | None = None,
        max_turns: int | None = None,
    ) -> list[dict[str, Any]]:
        """从旧事件（无 committed 事件）有界重构 legacy-inferred turn（§2.7）。"""

        async with self._lock:
            if self._connection is None:
                raise TrajectoryError("轨迹数据库尚未启动。")
            return await asyncio.to_thread(
                self._read_legacy_turns_sync,
                session_id,
                epoch,
                exclude_trace_id,
                max_turns,
                after_turn_seq,
            )

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
            if version < SCHEMA_VERSION:
                self._apply_migrations(connection, version)
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

    def _apply_migrations(
        self, connection: sqlite3.Connection, from_version: int
    ) -> None:
        """按顺序应用从 from_version 到 SCHEMA_VERSION 的 additive 迁移。

        每个 step 只做加列/加表/加索引，绝不删除旧数据；旧 trace 写默认 epoch=1。
        """

        migrations = {
            1: _migration_v1_to_v2,
            2: _migration_v2_to_v3,
            3: _migration_v3_to_v4,
        }
        try:
            connection.execute("BEGIN IMMEDIATE")
            version = from_version
            while version < SCHEMA_VERSION:
                step = migrations.get(version)
                if step is None:
                    raise TrajectorySchemaError(
                        f"缺少 v{version} 到 v{version + 1} 的迁移路径。"
                    )
                step(connection)
                version += 1
                connection.execute(
                    "UPDATE trajectory_meta SET value=? WHERE key='schema_version'",
                    (str(version),),
                )
            connection.commit()
        except Exception:
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

            # §6.6 审计事件幂等：经 outbox 重放的 context_compaction_committed
            # 同 (trace_id, span_id, event_type) 已存在则提交本轮幂等的
            # payload/trace/span upsert（均为 INSERT OR IGNORE/UPSERT，无副作用）
            # 后返回已有事件，不重复分配 sequence 或写 events 行（partial UNIQUE
            # events_audit_dedup 兜底并发；BEGIN IMMEDIATE 持写锁使进程内无竞争）。
            if item.event_type in _AUDIT_EVENT_TYPES:
                existing = connection.execute(
                    "SELECT sequence, payload_id FROM events "
                    "WHERE trace_id=? AND span_id=? AND event_type=?",
                    (item.trace_id, item.span_id, item.event_type),
                ).fetchone()
                if existing is not None:
                    connection.commit()
                    self._pending_external_paths.clear()
                    return TrajectoryEvent(
                        trace_id=item.trace_id,
                        span_id=item.span_id,
                        sequence=int(existing["sequence"]),
                        event_type=item.event_type,
                        occurred_at=item.occurred_at,
                        payload_id=existing["payload_id"],
                    )

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
                trace_id, session_id, context_epoch, started_at, ended_at, status,
                termination_reason, final_output_payload_id, provider, model,
                fallback_used, usage_json, iteration_count, runtime_version,
                schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                trace.context_epoch,
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

    def _current_epoch_sync(self, session_id: str) -> int:
        connection = self._require_connection()
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "INSERT OR IGNORE INTO session_epochs"
                "(session_id, epoch, created_at, parent_epoch) VALUES(?, 1, ?, NULL)",
                (session_id, utc_now_iso()),
            )
            row = connection.execute(
                "SELECT COALESCE(MAX(epoch), 1) FROM session_epochs WHERE session_id=?",
                (session_id,),
            ).fetchone()
            connection.commit()
        except Exception:
            _safe_rollback(connection)
            raise
        return int(row[0])

    def _create_next_epoch_sync(self, session_id: str) -> int:
        connection = self._require_connection()
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "INSERT OR IGNORE INTO session_epochs"
                "(session_id, epoch, created_at, parent_epoch) VALUES(?, 1, ?, NULL)",
                (session_id, utc_now_iso()),
            )
            row = connection.execute(
                "SELECT COALESCE(MAX(epoch), 1) FROM session_epochs WHERE session_id=?",
                (session_id,),
            ).fetchone()
            current = int(row[0])
            next_epoch = current + 1
            # 并发 /clear 或重试时 UNIQUE(session_id,epoch) 冲突即视为幂等成功。
            connection.execute(
                "INSERT OR IGNORE INTO session_epochs"
                "(session_id, epoch, created_at, parent_epoch) VALUES(?, ?, ?, ?)",
                (session_id, next_epoch, utc_now_iso(), current),
            )
            connection.commit()
        except Exception:
            _safe_rollback(connection)
            raise
        return next_epoch

    def _next_turn_seq_sync(self, session_id: str, epoch: int) -> int:
        connection = self._require_connection()
        row = connection.execute(
            "SELECT COUNT(*) FROM traces WHERE session_id=? AND context_epoch=?",
            (session_id, epoch),
        ).fetchone()
        return int(row[0]) + 1

    def _read_committed_turns_sync(
        self,
        session_id: str,
        epoch: int,
        exclude_trace_id: str | None,
        max_turns: int | None,
        after_turn_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        connection = self._require_connection()
        status_placeholders = ",".join("?" for _ in QUALIFIED_TURN_STATUSES)
        clauses = [
            "session_id=?",
            "context_epoch=?",
            "ended_at IS NOT NULL",
            f"status IN ({status_placeholders})",
        ]
        params: list[Any] = [session_id, epoch, *QUALIFIED_TURN_STATUSES]
        if exclude_trace_id:
            clauses.append("trace_id != ?")
            params.append(exclude_trace_id)
        # §6.7 稳定序号 + 续读游标：ORDER BY started_at, trace_id 下的序位即
        # turn_seq；OFFSET after_turn_seq 跳过已读、LIMIT max_turns 有界抓取。
        # enumerate start = offset+1 使 turn_seq 与无 OFFSET 时的完整序位一致
        # （供 after_turn_seq 续读游标跨页稳定）。
        offset = int(after_turn_seq) if after_turn_seq and after_turn_seq > 0 else 0
        if max_turns and max_turns > 0:
            limit = f"LIMIT {int(max_turns)} OFFSET {offset}"
        elif offset:
            limit = f"LIMIT -1 OFFSET {offset}"
        else:
            limit = ""
        traces = connection.execute(
            "SELECT trace_id, started_at, ended_at, status, context_epoch "
            "FROM traces WHERE "
            f"{' AND '.join(clauses)} ORDER BY started_at, trace_id {limit}",
            params,
        ).fetchall()
        turns: list[dict[str, Any]] = []
        for turn_seq, trace in enumerate(traces, start=offset + 1):
            trace_id = trace["trace_id"]
            event_rows = connection.execute(
                "SELECT payload_id FROM events WHERE trace_id=? AND event_type IN "
                f"({','.join('?' for _ in COMMITTED_EVENT_TYPES)}) "
                "ORDER BY sequence",
                (trace_id, *COMMITTED_EVENT_TYPES),
            ).fetchall()
            messages: list[dict[str, Any]] = []
            resolvable = [
                row for row in event_rows if row["payload_id"] is not None
            ]
            for event_row in resolvable:
                envelope = self._resolve_envelope_sync(
                    int(event_row["payload_id"])
                )
                if envelope is not None:
                    messages.append(envelope)
            # 任一 committed envelope 不可读即 corrupt turn（整体排除，§2.5）。
            corrupt = len(messages) < len(resolvable)
            turns.append(
                {
                    "trace_id": trace_id,
                    "epoch": int(trace["context_epoch"]),
                    "turn_seq": turn_seq,
                    "status": trace["status"],
                    "started_at": trace["started_at"],
                    "ended_at": trace["ended_at"],
                    "messages": messages,
                    "corrupt": corrupt,
                }
            )
        return turns

    def _resolve_envelope_sync(self, payload_id: int) -> dict[str, Any] | None:
        try:
            envelope = self._read_payload_json_sync(payload_id)
        except TrajectoryError:
            return None
        return envelope if isinstance(envelope, dict) else None

    def _restoration_level_sync(self, session_id: str, epoch: int) -> str:
        # capture_content 决定能否恢复可见内容；metadata-only 永远不可恢复。
        if self.capture_content == "metadata-only":
            return "unavailable"
        base = "governed" if self.capture_content == "redacted" else "exact"
        # 该 epoch 内任一 committed turn 出现不可读 envelope（corrupt=True）即整体
        # 降级为 legacy-inferred，提示调用方回退兼容读取（§2.5/§2.7）。corrupt 已
        # 区分「有 committed 事件但不可读」与「无 committed 事件的旧 trace」。
        turns = self._read_committed_turns_sync(session_id, epoch, None, None)
        if any(turn.get("corrupt") for turn in turns):
            return "legacy-inferred"
        return base

    def _read_legacy_turns_sync(
        self,
        session_id: str,
        epoch: int,
        exclude_trace_id: str | None,
        max_turns: int | None,
        after_turn_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        """从旧事件重构 legacy-inferred turn；有 committed 事件的 trace 跳过。"""

        connection = self._require_connection()
        status_placeholders = ",".join("?" for _ in QUALIFIED_TURN_STATUSES)
        clauses = [
            "session_id=?",
            "context_epoch=?",
            "ended_at IS NOT NULL",
            f"status IN ({status_placeholders})",
        ]
        params: list[Any] = [session_id, epoch, *QUALIFIED_TURN_STATUSES]
        if exclude_trace_id:
            clauses.append("trace_id != ?")
            params.append(exclude_trace_id)
        # §6.7 稳定序号 + 续读游标（与 _read_committed_turns_sync 对齐）。
        # legacy reader 跳过有 committed 事件的 trace，但 turn_seq 仍为完整有序集
        # 序位；纯 legacy epoch（无 committed 事件）下游标随产出 turn 稳定推进。
        offset = int(after_turn_seq) if after_turn_seq and after_turn_seq > 0 else 0
        if max_turns and max_turns > 0:
            limit = f"LIMIT {int(max_turns)} OFFSET {offset}"
        elif offset:
            limit = f"LIMIT -1 OFFSET {offset}"
        else:
            limit = ""
        traces = connection.execute(
            "SELECT trace_id, started_at, ended_at, status, context_epoch "
            "FROM traces WHERE "
            f"{' AND '.join(clauses)} ORDER BY started_at, trace_id {limit}",
            params,
        ).fetchall()
        result: list[dict[str, Any]] = []
        for turn_seq, trace in enumerate(traces, start=offset + 1):
            trace_id = trace["trace_id"]
            # 有 committed 事件的 trace 由 durable reader 负责，这里只处理旧 trace。
            committed_count = connection.execute(
                "SELECT COUNT(*) FROM events WHERE trace_id=? AND event_type IN "
                f"({','.join('?' for _ in COMMITTED_EVENT_TYPES)})",
                (trace_id, *COMMITTED_EVENT_TYPES),
            ).fetchone()[0]
            if committed_count:
                continue
            event_rows = connection.execute(
                "SELECT event_type, payload_id FROM events WHERE trace_id=? "
                "ORDER BY sequence",
                (trace_id,),
            ).fetchall()
            events: list[tuple[str, dict[str, Any]]] = []
            for row in event_rows:
                event_type = str(row["event_type"])
                payload_id = row["payload_id"]
                payload: dict[str, Any] = {}
                if payload_id is not None:
                    try:
                        resolved = self._read_payload_json_sync(int(payload_id))
                    except TrajectoryError:
                        resolved = None
                    if isinstance(resolved, dict):
                        payload = resolved
                events.append((event_type, payload))
            messages, restoration = _reconstruct_legacy_turn(events)
            context_epoch = int(trace["context_epoch"])
            for envelope in messages:
                envelope["turn_seq"] = turn_seq
                envelope["epoch"] = context_epoch
            result.append(
                {
                    "trace_id": trace_id,
                    "epoch": context_epoch,
                    "turn_seq": turn_seq,
                    "status": trace["status"],
                    "started_at": trace["started_at"],
                    "ended_at": trace["ended_at"],
                    "messages": messages,
                    "restoration": restoration,
                }
            )
        return result

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise TrajectoryError("轨迹数据库尚未启动。")
        return self._connection


def _wire_tool_calls(
    calls: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any], ...]:
    """把旧事件里的 tool_calls 规范为 provider wire 形状（legacy-inferred）。"""

    if not calls:
        return ()
    wired: list[dict[str, Any]] = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        call_id = call.get("id") or call.get("tool_call_id") or ""
        name = call.get("name") or (call.get("function") or {}).get("name") or ""
        arguments = call.get("arguments")
        if isinstance(arguments, dict | list):
            arguments = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        elif arguments is None:
            arguments = ""
        wired.append(
            {
                "id": str(call_id),
                "type": "function",
                "function": {"name": str(name), "arguments": str(arguments)},
            }
        )
    return tuple(wired)


def _legacy_envelope_hash(body: dict[str, Any]) -> str:
    return "msg:" + hashlib.sha256(
        json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()[:24]


def _reconstruct_legacy_turn(
    events: list[tuple[str, dict[str, Any]]],
) -> tuple[list[dict[str, Any]], str]:
    """从旧事件（无 committed 事件）有界重构一个 turn 的消息序列。

    返回 (envelope 列表, 恢复等级)。无法保持 tool/response fidelity 时等级为
    ``unavailable``（调用方据此排除整 turn，§2.7）。
    """

    first_request_messages: list[dict[str, Any]] | None = None
    responded: list[dict[str, Any]] = []
    tool_finished: list[dict[str, Any]] = []
    final_output = ""
    for event_type, payload in events:
        if not isinstance(payload, dict):
            continue
        if event_type == "model_requested" and first_request_messages is None:
            first_request_messages = list(payload.get("messages") or [])
        elif event_type == "model_responded":
            responded.append(payload)
        elif event_type == "tool_finished":
            tool_finished.append(payload)
        elif event_type == "trace_finished":
            final_output = str(payload.get("final_output") or "")

    # 没有 user 输入即无法构成 turn。
    user_content = ""
    if first_request_messages:
        for message in reversed(first_request_messages):
            if isinstance(message, dict) and message.get("role") == "user":
                user_content = str(message.get("content") or "")
                break
    if not user_content:
        return [], "unavailable"

    messages: list[dict[str, Any]] = []
    seq = 1

    def _append(role: str, content: str, **extra: Any) -> None:
        nonlocal seq
        body: dict[str, Any] = {"role": role, "content": content}
        body.update(extra)
        messages.append(
            {
                "turn_seq": 0,
                "message_seq": seq,
                "role": role,
                "content": content,
                "tool_call_id": extra.get("tool_call_id"),
                "tool_name": extra.get("name"),
                "tool_calls": extra.get("tool_calls", ()),
                "content_hash": _legacy_envelope_hash(body),
                "capture_mode": "legacy",
                "degradation": "legacy-inferred",
            }
        )
        seq += 1

    _append("user", user_content)

    tool_by_id: dict[str, dict[str, Any]] = {}
    for tf in tool_finished:
        call_id = str(tf.get("tool_call_id") or "")
        if call_id:
            tool_by_id[call_id] = tf

    # 按响应顺序配对 assistant tool-call 与 tool 结果；未配对的 tool 结果破坏 fidelity。
    for response in responded:
        calls = response.get("tool_calls")
        if not calls:
            continue
        _append(
            "assistant",
            str(response.get("content") or ""),
            tool_calls=_wire_tool_calls(calls),
        )
        for call in calls:
            if not isinstance(call, dict):
                continue
            call_id = str(call.get("id") or call.get("tool_call_id") or "")
            tf = tool_by_id.get(call_id)
            if tf is None:
                return [], "unavailable"
            _append(
                "tool",
                str(tf.get("model_content") or tf.get("raw_content") or ""),
                tool_call_id=call_id,
                name=str(tf.get("name") or ""),
            )

    # 最终输出：优先 trace_finished.final_output（已确定的 turn 输出）。
    output_content = final_output
    if not output_content:
        for response in reversed(responded):
            if not response.get("tool_calls"):
                output_content = str(response.get("content") or "")
                if output_content:
                    break
    if output_content:
        _append("assistant", output_content)

    if not any(env["role"] == "assistant" for env in messages):
        # 没有任何 assistant 输出，无法构成可恢复 turn。
        return [], "unavailable"
    return messages, "legacy-inferred"


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
            _clean_value(item, capture_content, sensitive_keys, _seen) for item in value
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
    context_epoch INTEGER NOT NULL DEFAULT 1,
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

CREATE TABLE session_epochs (
    session_id TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    parent_epoch INTEGER,
    PRIMARY KEY(session_id, epoch)
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
CREATE INDEX idx_traces_session_epoch ON traces(session_id, context_epoch, started_at);
CREATE INDEX idx_traces_outcome_time ON traces(termination_reason, started_at);
CREATE INDEX idx_traces_provider_model ON traces(provider, model);
CREATE INDEX idx_spans_trace_kind ON spans(trace_id, kind);
CREATE INDEX idx_events_trace_sequence ON events(trace_id, sequence);
CREATE INDEX idx_events_span_id ON events(span_id);
-- §6.6 审计事件幂等：outbox 重放的 context_*_committed 按
-- (trace_id, span_id, event_type) 去重（partial UNIQUE，仅作用于经 outbox
-- 异步投递的审计事件，不触碰共用 root span 的 committed 消息事件）。
CREATE UNIQUE INDEX IF NOT EXISTS events_audit_dedup
    ON events(trace_id, span_id, event_type)
    WHERE event_type = 'context_compaction_committed';
CREATE INDEX idx_session_epochs_current ON session_epochs(session_id, epoch DESC);
"""


_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)(api[_-]?key|access[_-]?token|token|password|secret|authorization|cookie)"
        r"(\s*[:=]\s*)([^\s&#;,]+)"
    ),
    re.compile(
        r"\b(sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|xox[baprs]-[A-Za-z0-9-]{12,})\b"
    ),
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


def _migration_v1_to_v2(connection: sqlite3.Connection) -> None:
    """v1→v2：补 events(span_id) 索引。"""

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_span_id ON events(span_id)"
    )


def _has_column(connection: sqlite3.Connection, table: str, column: str) -> bool:
    """检查表是否已有指定列（让 ALTER 幂等，避免半迁移 DB 重复升级报错）。"""

    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _migration_v2_to_v3(connection: sqlite3.Connection) -> None:
    """v2→v3：additive 加入 conversation epoch 与 session_epochs 仓库。

    - traces 增加 context_epoch 列（旧 trace 默认 epoch=1，不删除/不改写）；
    - 新增 session_epochs 表作为持久 epoch 仓库（/clear 原子推进）。

    幂等：列/表/索引已存在时跳过，兼容「结构已落地但版本号未推进」的半迁移 DB。
    """

    if not _has_column(connection, "traces", "context_epoch"):
        connection.execute(
            "ALTER TABLE traces ADD COLUMN context_epoch INTEGER NOT NULL DEFAULT 1"
        )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS session_epochs ("
        "session_id TEXT NOT NULL, epoch INTEGER NOT NULL, "
        "created_at TEXT NOT NULL, parent_epoch INTEGER, "
        "PRIMARY KEY(session_id, epoch)"
        ")"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_epochs_current "
        "ON session_epochs(session_id, epoch DESC)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_traces_session_epoch "
        "ON traces(session_id, context_epoch, started_at)"
    )


def _migration_v3_to_v4(connection: sqlite3.Connection) -> None:
    """v3→v4：审计事件幂等去重——为 outbox 重放的 ``context_compaction_committed``
    加 partial UNIQUE(trace_id, span_id, event_type)。

    §6.6 场景「archive transaction commits but audit delivery is delayed」要求
    重放幂等且不得重复轨迹事件。partial UNIQUE 仅作用于经 outbox 异步投递的审计
    事件（每个由唯一 span_id 标识一次逻辑提交），故意不覆盖 committed 消息事件
    （turn/assistant/tool_message_committed 共用 root span，一轮内合法多次）。
    本变更之前无重放路径，旧 DB 不会含该类审计重复，故建索引不会冲突；半迁移
    DB 用 ``IF NOT EXISTS`` 幂等跳过。
    """

    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS events_audit_dedup "
        "ON events(trace_id, span_id, event_type) "
        "WHERE event_type = 'context_compaction_committed'"
    )


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
