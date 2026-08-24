"""持久化 Agent Tree、Task DAG 与任务生命周期。"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from memoli_agent.agent.subagent.models import (
    AgentArtifact,
    AgentMessage,
    AgentTask,
    ContextPackage,
    TaskAttempt,
    TaskEdge,
    TaskStatus,
    can_transition,
    utc_now_iso,
)

_SCHEMA_VERSION = 2


class TaskGraphError(RuntimeError):
    """任务图持久化或状态操作失败。"""


class TaskNotFoundError(TaskGraphError):
    """任务不存在。"""


class InvalidTaskTransitionError(TaskGraphError):
    """任务状态转换不合法。"""


class CyclicDependencyError(TaskGraphError):
    """任务依赖会形成环。"""


class TaskGraphRepository:
    """SQLite 任务图 repository；所有写入都在单事务内完成。"""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self.database = str(database)
        if self.database != ":memory:":
            Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.database, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    async def start(self) -> None:
        """保留异步生命周期边界；构造阶段已完成幂等 migration。"""

        await asyncio.sleep(0)

    async def close(self) -> None:
        await asyncio.to_thread(self.close_sync)

    def close_sync(self) -> None:
        with self._lock:
            self._connection.close()

    def create_task(
        self, task: AgentTask, dependencies: Iterable[str] = ()
    ) -> AgentTask:
        dependency_ids = tuple(dict.fromkeys(dependencies))
        with self._lock, self._connection:
            for dependency_id in dependency_ids:
                self._require_task(dependency_id)
            self._connection.execute(
                """
                INSERT INTO agent_tasks(
                    task_id, agent_id, root_agent_id, parent_agent_id,
                    parent_task_id, root_session_key, profile_name, objective,
                    context_json, status, depth, task_dir, max_iterations,
                    max_elapsed_seconds, side_effecting, background, trace_id,
                    result_summary, result_json,
                    error_type, error_message, blocked_reason, completion_notified,
                    created_at, started_at, finished_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                self._task_values(task),
            )
            for dependency_id in dependency_ids:
                self._insert_dependency(dependency_id, task.task_id)
        return task

    def get_task(self, task_id: str) -> AgentTask | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM agent_tasks WHERE task_id=?", (task_id,)
            ).fetchone()
        return self._from_task_row(row) if row is not None else None

    def get_task_by_agent(self, agent_id: str) -> AgentTask | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM agent_tasks WHERE agent_id=?", (agent_id,)
            ).fetchone()
        return self._from_task_row(row) if row is not None else None

    def list_tasks(self, root_session_key: str = "") -> list[AgentTask]:
        query = "SELECT * FROM agent_tasks"
        values: tuple[str, ...] = ()
        if root_session_key:
            query += " WHERE root_session_key=?"
            values = (root_session_key,)
        query += " ORDER BY created_at, task_id"
        with self._lock:
            rows = self._connection.execute(query, values).fetchall()
        return [self._from_task_row(row) for row in rows]

    def dependencies(self, task_id: str) -> list[str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT source_task_id FROM task_edges "
                "WHERE target_task_id=? AND edge_type='depends_on' "
                "ORDER BY source_task_id",
                (task_id,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def dependents(self, task_id: str) -> list[str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT target_task_id FROM task_edges "
                "WHERE source_task_id=? AND edge_type='depends_on' "
                "ORDER BY target_task_id",
                (task_id,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def add_dependency(self, source_task_id: str, target_task_id: str) -> TaskEdge:
        edge = TaskEdge(source_task_id, target_task_id)
        with self._lock, self._connection:
            self._require_task(source_task_id)
            self._require_task(target_task_id)
            self._insert_dependency(source_task_id, target_task_id)
        return edge

    def transition(
        self,
        task_id: str,
        target: TaskStatus,
        *,
        expected: TaskStatus | Iterable[TaskStatus] | None = None,
        reason: str = "",
        trace_id: str | None = None,
        result_summary: str | None = None,
        result_data: dict[str, object] | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        task = self.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        expected_values = (
            {expected}
            if isinstance(expected, TaskStatus)
            else set(expected or {task.status})
        )
        if task.status not in expected_values:
            return False
        if not can_transition(task.status, target):
            raise InvalidTaskTransitionError(f"{task.status} -> {target}")
        now = utc_now_iso()
        started_at = now if target is TaskStatus.RUNNING else task.started_at
        finished_at = (
            now
            if target in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
            else task.finished_at
        )
        with self._lock, self._connection:
            cursor = self._connection.execute(
                """
                UPDATE agent_tasks SET status=?, trace_id=?, result_summary=?,
                    result_json=?, error_type=?, error_message=?, blocked_reason=?,
                    started_at=?, finished_at=?, updated_at=?
                WHERE task_id=? AND status=?
                """,
                (
                    target.value,
                    trace_id if trace_id is not None else task.trace_id,
                    result_summary
                    if result_summary is not None
                    else task.result_summary,
                    json.dumps(
                        result_data if result_data is not None else task.result_data,
                        ensure_ascii=False,
                    ),
                    error_type if error_type is not None else task.error_type,
                    error_message if error_message is not None else task.error_message,
                    reason,
                    started_at,
                    finished_at,
                    now,
                    task_id,
                    task.status.value,
                ),
            )
            if cursor.rowcount:
                self._connection.execute(
                    "INSERT INTO task_state_log(task_id, from_status, to_status, "
                    "reason, created_at) VALUES (?,?,?,?,?)",
                    (task_id, task.status.value, target.value, reason, now),
                )
        return bool(cursor.rowcount)

    def create_attempt(self, attempt: TaskAttempt) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO task_attempts(attempt_id, task_id, attempt_no, trace_id, "
                "status, started_at, finished_at, error_type) VALUES (?,?,?,?,?,?,?,?)",
                (
                    attempt.attempt_id,
                    attempt.task_id,
                    attempt.attempt_no,
                    attempt.trace_id,
                    attempt.status,
                    attempt.started_at,
                    attempt.finished_at,
                    attempt.error_type,
                ),
            )

    def finish_attempt(
        self, attempt_id: str, status: str, error_type: str = ""
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE task_attempts SET status=?, finished_at=?, error_type=? "
                "WHERE attempt_id=?",
                (status, utc_now_iso(), error_type, attempt_id),
            )

    def attempts(self, task_id: str) -> list[TaskAttempt]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM task_attempts WHERE task_id=? ORDER BY attempt_no",
                (task_id,),
            ).fetchall()
        return [TaskAttempt(**dict(row)) for row in rows]

    def record_message(self, message: AgentMessage) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO agent_messages(message_id, task_id, from_agent_id, "
                "to_agent_id, message_type, content, created_at, delivered_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    message.message_id,
                    message.task_id,
                    message.from_agent_id,
                    message.to_agent_id,
                    message.message_type,
                    message.content,
                    message.created_at,
                    message.delivered_at,
                ),
            )

    def record_artifact(self, artifact: AgentArtifact) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO agent_artifacts(artifact_id, task_id, "
                "agent_id, "
                "path, kind, mime_type, sha256, size, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    artifact.artifact_id,
                    artifact.task_id,
                    artifact.agent_id,
                    str(artifact.path),
                    artifact.kind,
                    artifact.mime_type,
                    artifact.sha256,
                    artifact.size,
                    artifact.created_at,
                ),
            )

    def artifacts(self, task_id: str) -> list[AgentArtifact]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM agent_artifacts WHERE task_id=? ORDER BY created_at",
                (task_id,),
            ).fetchall()
        return [
            AgentArtifact(**{**dict(row), "path": Path(str(row["path"]))})
            for row in rows
        ]

    def refresh_task_readiness(self, task_id: str) -> TaskStatus:
        task = self.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        if task.status not in {TaskStatus.PENDING, TaskStatus.BLOCKED}:
            return task.status
        dependencies = [self.get_task(item) for item in self.dependencies(task_id)]
        missing = [item for item in dependencies if item is None]
        failed = [
            item
            for item in dependencies
            if item is not None
            and item.status
            in {TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.INTERRUPTED}
        ]
        unfinished = [
            item
            for item in dependencies
            if item is not None and item.status is not TaskStatus.COMPLETED
        ]
        if missing or failed or unfinished:
            reason = (
                "dependency_failed"
                if failed
                else "dependency_missing"
                if missing
                else "dependency_pending"
            )
            if task.status is TaskStatus.PENDING:
                self.transition(task_id, TaskStatus.BLOCKED, reason=reason)
            elif task.blocked_reason != reason:
                with self._lock, self._connection:
                    self._connection.execute(
                        "UPDATE agent_tasks SET blocked_reason=?, updated_at=? "
                        "WHERE task_id=? AND status=?",
                        (reason, utc_now_iso(), task_id, TaskStatus.BLOCKED.value),
                    )
            return TaskStatus.BLOCKED
        self.transition(task_id, TaskStatus.RUNNABLE, reason="dependencies_satisfied")
        return TaskStatus.RUNNABLE

    def refresh_dependents(self, task_id: str) -> list[AgentTask]:
        ready: list[AgentTask] = []
        for dependent_id in self.dependents(task_id):
            if self.refresh_task_readiness(dependent_id) is TaskStatus.RUNNABLE:
                task = self.get_task(dependent_id)
                if task is not None:
                    ready.append(task)
        return ready

    def recover_interrupted(self) -> list[str]:
        recovered: list[str] = []
        for task in self.list_tasks():
            if task.status in {TaskStatus.RUNNING, TaskStatus.WAITING_INPUT}:
                if self.transition(
                    task.task_id,
                    TaskStatus.INTERRUPTED,
                    expected=task.status,
                    reason="runtime_restarted",
                ):
                    recovered.append(task.task_id)
        return recovered

    def mark_completion_notified(self, task_id: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE agent_tasks SET completion_notified=1, updated_at=? "
                "WHERE task_id=? AND completion_notified=0",
                (utc_now_iso(), task_id),
            )
        return bool(cursor.rowcount)

    def replace_context(self, task_id: str, context: ContextPackage) -> AgentTask:
        with self._lock, self._connection:
            self._connection.execute(
                "UPDATE agent_tasks SET context_json=?, updated_at=? WHERE task_id=?",
                (
                    json.dumps(context.to_dict(), ensure_ascii=False),
                    utc_now_iso(),
                    task_id,
                ),
            )
        task = self.get_task(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return replace(task, context_package=context)

    def _insert_dependency(self, source_task_id: str, target_task_id: str) -> None:
        if source_task_id == target_task_id or self._path_exists(
            target_task_id, source_task_id
        ):
            raise CyclicDependencyError(
                f"依赖会形成环：{source_task_id} -> {target_task_id}"
            )
        self._connection.execute(
            "INSERT OR IGNORE INTO task_edges(source_task_id, target_task_id, "
            "edge_type, created_at) VALUES (?,?,?,?)",
            (source_task_id, target_task_id, "depends_on", utc_now_iso()),
        )

    def _path_exists(self, source: str, target: str) -> bool:
        row = self._connection.execute(
            """
            WITH RECURSIVE reachable(task_id) AS (
                SELECT target_task_id FROM task_edges WHERE source_task_id=?
                UNION
                SELECT e.target_task_id FROM task_edges e
                JOIN reachable r ON e.source_task_id=r.task_id
            )
            SELECT 1 FROM reachable WHERE task_id=? LIMIT 1
            """,
            (source, target),
        ).fetchone()
        return row is not None

    def _require_task(self, task_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM agent_tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        if row is None:
            raise TaskNotFoundError(task_id)
        return row

    def _initialize(self) -> None:
        current = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
        if current not in {0, 1, _SCHEMA_VERSION}:
            raise TaskGraphError(f"不支持的 subagent schema 版本：{current}")
        if current == _SCHEMA_VERSION:
            return
        if current == 1:
            self._migrate_v1_to_v2()
            return
        with self._connection:
            self._connection.executescript(_SCHEMA_SQL)

    def _migrate_v1_to_v2(self) -> None:
        columns = {
            str(row[1])
            for row in self._connection.execute("PRAGMA table_info(agent_tasks)")
        }
        with self._connection:
            if "background" not in columns:
                self._connection.execute(
                    "ALTER TABLE agent_tasks ADD COLUMN background INTEGER "
                    "NOT NULL DEFAULT 0"
                )
            if "result_json" not in columns:
                self._connection.execute(
                    "ALTER TABLE agent_tasks ADD COLUMN result_json TEXT "
                    "NOT NULL DEFAULT '{}'"
                )
            self._connection.execute("PRAGMA user_version = 2")

    @staticmethod
    def _task_values(task: AgentTask) -> tuple[object, ...]:
        return (
            task.task_id,
            task.agent_id,
            task.root_agent_id,
            task.parent_agent_id,
            task.parent_task_id,
            task.root_session_key,
            task.profile_name,
            task.objective,
            json.dumps(task.context_package.to_dict(), ensure_ascii=False),
            task.status.value,
            task.depth,
            str(task.task_dir),
            task.max_iterations,
            task.max_elapsed_seconds,
            int(task.side_effecting),
            int(task.background),
            task.trace_id,
            task.result_summary,
            json.dumps(task.result_data, ensure_ascii=False),
            task.error_type,
            task.error_message,
            task.blocked_reason,
            int(task.completion_notified),
            task.created_at,
            task.started_at,
            task.finished_at,
            task.updated_at,
        )

    @staticmethod
    def _from_task_row(row: sqlite3.Row) -> AgentTask:
        values = dict(row)
        raw_context = json.loads(str(values.pop("context_json")))
        values["result_data"] = json.loads(str(values.pop("result_json")))
        for key in (
            "acceptance_criteria",
            "constraints",
            "confirmed_facts",
            "memory_refs",
            "artifact_refs",
            "dependency_results",
        ):
            raw_context[key] = tuple(raw_context.get(key) or ())
        values["context_package"] = ContextPackage(**raw_context)
        values["status"] = TaskStatus(str(values["status"]))
        values["task_dir"] = Path(str(values["task_dir"]))
        values["side_effecting"] = bool(values["side_effecting"])
        values["background"] = bool(values["background"])
        values["completion_notified"] = bool(values["completion_notified"])
        return AgentTask(**values)


_SCHEMA_SQL = """
CREATE TABLE agent_tasks (
    task_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL UNIQUE,
    root_agent_id TEXT NOT NULL,
    parent_agent_id TEXT NOT NULL,
    parent_task_id TEXT NOT NULL DEFAULT '',
    root_session_key TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    objective TEXT NOT NULL,
    context_json TEXT NOT NULL,
    status TEXT NOT NULL,
    depth INTEGER NOT NULL CHECK(depth >= 1),
    task_dir TEXT NOT NULL,
    max_iterations INTEGER NOT NULL CHECK(max_iterations > 0),
    max_elapsed_seconds REAL NOT NULL CHECK(max_elapsed_seconds > 0),
    side_effecting INTEGER NOT NULL DEFAULT 0,
    background INTEGER NOT NULL DEFAULT 0,
    trace_id TEXT NOT NULL DEFAULT '',
    result_summary TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    error_type TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    blocked_reason TEXT NOT NULL DEFAULT '',
    completion_notified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE TABLE task_edges (
    source_task_id TEXT NOT NULL REFERENCES agent_tasks(task_id),
    target_task_id TEXT NOT NULL REFERENCES agent_tasks(task_id),
    edge_type TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(source_task_id, target_task_id, edge_type)
);
CREATE TABLE agent_messages (
    message_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES agent_tasks(task_id),
    from_agent_id TEXT NOT NULL,
    to_agent_id TEXT NOT NULL,
    message_type TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    delivered_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE agent_artifacts (
    artifact_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES agent_tasks(task_id),
    agent_id TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE task_attempts (
    attempt_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES agent_tasks(task_id),
    attempt_no INTEGER NOT NULL,
    trace_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    error_type TEXT NOT NULL DEFAULT '',
    UNIQUE(task_id, attempt_no)
);
CREATE TABLE task_state_log (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES agent_tasks(task_id),
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_agent_tasks_session_status
    ON agent_tasks(root_session_key, status, created_at);
CREATE INDEX idx_agent_tasks_parent ON agent_tasks(parent_agent_id, created_at);
CREATE INDEX idx_task_edges_target ON task_edges(target_task_id, edge_type);
CREATE INDEX idx_task_edges_source ON task_edges(source_task_id, edge_type);
CREATE INDEX idx_agent_messages_target ON agent_messages(to_agent_id, created_at);
CREATE INDEX idx_agent_artifacts_task ON agent_artifacts(task_id, created_at);
CREATE INDEX idx_task_attempts_task ON task_attempts(task_id, attempt_no);
PRAGMA user_version = 2;
"""
