"""工作状态 SQLite repository。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from memoli_agent.agent.working.models import CheckpointPatch, WorkingCheckpoint

_SCHEMA_VERSION = 1
_LIST_FIELDS = {"constraints", "decisions", "artifacts"}
_PATCH_FIELDS = {
    "objective",
    "current_step",
    "next_action",
    "key_info",
    "related_sop",
    "constraints",
    "decisions",
    "artifacts",
    "status",
}


class RevisionConflictError(RuntimeError):
    """调用者基于过期 revision 更新状态。"""


class WorkingStateReadError(RuntimeError):
    """只读查询无法安全返回已提交 checkpoint。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class WorkingStateRepository:
    """按 session/task 保存最新版 checkpoint，并保留 revision 日志。"""

    def __init__(self, database: str | Path = ":memory:") -> None:
        self.database = str(database)
        if self.database != ":memory:":
            Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def close(self) -> None:
        self._connection.close()

    def get(self, session_key: str) -> WorkingCheckpoint | None:
        row = self._connection.execute(
            "SELECT * FROM working_checkpoints WHERE session_key = ?",
            (session_key,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def patch(self, session_key: str, patch: CheckpointPatch) -> WorkingCheckpoint:
        """在单事务中检查 revision 并写入新版本。"""

        current = self.get(session_key) or WorkingCheckpoint(session_key=session_key)
        if (
            patch.expected_revision is not None
            and patch.expected_revision != current.revision
        ):
            raise RevisionConflictError(
                f"checkpoint revision 冲突：期望 {patch.expected_revision}，"
                f"实际 {current.revision}。"
            )
        values = asdict(current)
        for name in _PATCH_FIELDS:
            value = getattr(patch, name)
            if value is not None:
                values[name] = value
        values["revision"] = current.revision + 1
        values["stale"] = False
        values["updated_at"] = datetime.now(UTC).isoformat()
        updated = WorkingCheckpoint(**values)
        encoded = self._to_values(updated)
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO working_checkpoints (
                    session_key, objective, current_step, next_action, key_info,
                    related_sop, constraints_json, decisions_json, artifacts_json,
                    status, revision, stale, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_key) DO UPDATE SET
                    objective=excluded.objective,
                    current_step=excluded.current_step,
                    next_action=excluded.next_action,
                    key_info=excluded.key_info,
                    related_sop=excluded.related_sop,
                    constraints_json=excluded.constraints_json,
                    decisions_json=excluded.decisions_json,
                    artifacts_json=excluded.artifacts_json,
                    status=excluded.status,
                    revision=excluded.revision,
                    stale=excluded.stale,
                    updated_at=excluded.updated_at
                """,
                encoded,
            )
            self._connection.execute(
                "INSERT INTO working_revisions("
                "session_key, revision, state_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    session_key,
                    updated.revision,
                    json.dumps(asdict(updated), ensure_ascii=False),
                    updated.updated_at,
                ),
            )
        return updated

    def complete(
        self, session_key: str, expected_revision: int | None = None
    ) -> WorkingCheckpoint:
        return self.patch(
            session_key,
            CheckpointPatch(expected_revision=expected_revision, status="completed"),
        )

    def mark_stale_except(self, session_key: str) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE working_checkpoints SET stale = 1 "
                "WHERE session_key <> ? AND status = 'active'",
                (session_key,),
            )

    def restore(self, session_key: str) -> WorkingCheckpoint | None:
        current = self.get(session_key)
        if current is None:
            return None
        return self.patch(
            session_key,
            CheckpointPatch(expected_revision=current.revision, status="active"),
        )

    def _initialize(self) -> None:
        current = self._connection.execute("PRAGMA user_version").fetchone()[0]
        if current not in {0, _SCHEMA_VERSION}:
            raise RuntimeError(f"不支持的 working-state schema 版本：{current}")
        if current == _SCHEMA_VERSION:
            return
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE working_checkpoints (
                    session_key TEXT PRIMARY KEY,
                    objective TEXT NOT NULL,
                    current_step TEXT NOT NULL,
                    next_action TEXT NOT NULL,
                    key_info TEXT NOT NULL,
                    related_sop TEXT NOT NULL,
                    constraints_json TEXT NOT NULL,
                    decisions_json TEXT NOT NULL,
                    artifacts_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    stale INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE working_revisions (
                    session_key TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(session_key, revision)
                );
                PRAGMA user_version = 1;
                """
            )

    @staticmethod
    def _to_values(checkpoint: WorkingCheckpoint) -> tuple[object, ...]:
        return (
            checkpoint.session_key,
            checkpoint.objective,
            checkpoint.current_step,
            checkpoint.next_action,
            checkpoint.key_info,
            checkpoint.related_sop,
            json.dumps(checkpoint.constraints, ensure_ascii=False),
            json.dumps(checkpoint.decisions, ensure_ascii=False),
            json.dumps(checkpoint.artifacts, ensure_ascii=False),
            checkpoint.status,
            checkpoint.revision,
            int(checkpoint.stale),
            checkpoint.updated_at,
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WorkingCheckpoint:
        values = dict(row)
        for name in _LIST_FIELDS:
            values[name] = tuple(json.loads(values.pop(f"{name}_json")))
        values["stale"] = bool(values["stale"])
        return WorkingCheckpoint(**values)


def read_checkpoint_readonly(
    database: str | Path,
    session_key: str,
) -> WorkingCheckpoint | None:
    """只读打开既有数据库；查询不得创建文件、目录或 schema。"""

    path = Path(database)
    if not path.is_file():
        return None
    connection: sqlite3.Connection | None = None
    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=0.2)
        connection.row_factory = sqlite3.Row
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != _SCHEMA_VERSION:
            raise WorkingStateReadError("unsupported-schema")
        row = connection.execute(
            "SELECT * FROM working_checkpoints WHERE session_key = ?",
            (session_key,),
        ).fetchone()
        return WorkingStateRepository._from_row(row) if row is not None else None
    except WorkingStateReadError:
        raise
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        code = "busy" if "locked" in message or "busy" in message else "storage-error"
        raise WorkingStateReadError(code) from None
    except sqlite3.DatabaseError:
        raise WorkingStateReadError("storage-error") from None
    finally:
        if connection is not None:
            connection.close()
