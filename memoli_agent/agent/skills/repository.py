"""版本化 Skill 注册表的 SQLite 实现。"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memoli_agent.agent.skills.models import SkillBinding, SkillPackage, SkillVersion

_SCHEMA_VERSION = 1
_STATES = {
    "draft",
    "candidate",
    "validated",
    "canary",
    "active",
    "deprecated",
    "rejected",
    "revoked",
}


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SkillRegistryError(RuntimeError):
    """注册表操作失败。"""


class SkillRevisionConflict(SkillRegistryError):
    """管理操作使用了过期 Registry revision。"""


class SQLiteSkillRepository:
    """保存 Skill 元数据、版本、激活指针、会话快照和治理事件。"""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._lock = threading.RLock()
        try:
            self._migrate()
        except Exception:
            self._connection.close()
            raise

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def register_package(
        self,
        package: SkillPackage,
        artifact_path: Path,
        *,
        source_type: str = "local",
        owner: str = "host",
        actor: str = "host",
        reason: str = "install",
    ) -> SkillVersion:
        """幂等注册一个不可变版本；同版本不同哈希会被拒绝。"""

        now = utc_now_iso()
        manifest_json = json.dumps(
            {
                "name": package.manifest.name,
                "version": package.manifest.version,
                "description": package.manifest.description,
                "requires": package.manifest.requirements.to_dict(),
                "requested_permissions": package.manifest.requested_permissions,
                "risk": package.manifest.risk,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO skills(
                    name, owner, source_type, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (package.manifest.name, owner, source_type, now),
            )
            skill_id = int(
                self._connection.execute(
                    "SELECT id FROM skills WHERE name = ?", (package.manifest.name,)
                ).fetchone()["id"]
            )
            existing = self._connection.execute(
                "SELECT * FROM skill_versions WHERE skill_id = ? AND version = ?",
                (skill_id, package.manifest.version),
            ).fetchone()
            if existing is not None:
                if str(existing["content_hash"]) != package.content_hash:
                    raise SkillRegistryError("同名同版本已存在，但内容哈希不同。")
                result = self.get_version(
                    package.manifest.name, package.manifest.version
                )
                assert result is not None
                return result
            self._bump_revision()
            previous = self._connection.execute(
                """
                SELECT id FROM skill_versions
                WHERE skill_id = ? ORDER BY id DESC LIMIT 1
                """,
                (skill_id,),
            ).fetchone()
            cursor = self._connection.execute(
                """
                INSERT INTO skill_versions(
                    skill_id, version, description, state, previous_version_id,
                    artifact_path, content_hash, manifest_json, created_at
                ) VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?)
                """,
                (
                    skill_id,
                    package.manifest.version,
                    package.manifest.description,
                    int(previous["id"]) if previous is not None else None,
                    str(artifact_path),
                    package.content_hash,
                    manifest_json,
                    now,
                ),
            )
            if cursor.lastrowid is None:
                raise SkillRegistryError("Skill 版本注册未返回标识。")
            version_id = cursor.lastrowid
            self._record_event(
                "installed",
                skill_id,
                version_id,
                {"hash": package.content_hash, "artifact_path": str(artifact_path)},
                now,
                actor,
                reason,
            )
            result = self.get_version(
                package.manifest.name, package.manifest.version
            )
            assert result is not None
            return result

    def list_versions(self, name: str | None = None) -> list[SkillVersion]:
        query = """
            SELECT v.*, s.name, s.owner, s.source_type FROM skill_versions v
            JOIN skills s ON s.id = v.skill_id
        """
        arguments: tuple[Any, ...] = ()
        if name is not None:
            query += " WHERE s.name = ?"
            arguments = (name,)
        query += " ORDER BY s.name, v.id DESC"
        with self._lock:
            rows = self._connection.execute(query, arguments).fetchall()
        return [self._row_to_version(row, str(row["name"])) for row in rows]

    def get_version(self, name: str, version: str | None = None) -> SkillVersion | None:
        query = """
            SELECT v.*, s.name, s.owner, s.source_type FROM skill_versions v
            JOIN skills s ON s.id = v.skill_id
            WHERE s.name = ?
        """
        arguments: tuple[Any, ...]
        if version is None:
            query += " ORDER BY v.id DESC LIMIT 1"
            arguments = (name,)
        else:
            query += " AND v.version = ?"
            arguments = (name, version)
        with self._lock:
            row = self._connection.execute(query, arguments).fetchone()
        return None if row is None else self._row_to_version(row, str(row["name"]))

    def list_active(self) -> list[SkillVersion]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT v.*, s.name, s.owner, s.source_type
                FROM skill_active_versions a
                JOIN skill_versions v ON v.id = a.version_id
                JOIN skills s ON s.id = a.skill_id
                WHERE v.state = 'active'
                ORDER BY s.name
                """
            ).fetchall()
        return [self._row_to_version(row, str(row["name"])) for row in rows]

    def activate(
        self,
        name: str,
        version: str,
        *,
        actor: str = "host",
        reason: str = "activate",
        event_type: str = "activated",
        expected_revision: int | None = None,
    ) -> SkillVersion:
        """原子切换单一激活指针。"""

        with self._lock, self._connection:
            self._bump_revision(expected_revision)
            target = self._required_row(name, version)
            if str(target["state"]) in {"deprecated", "revoked"}:
                raise SkillRegistryError("已弃用或撤销的版本不能激活。")
            skill_id = int(target["skill_id"])
            previous = self._connection.execute(
                """
                SELECT version_id, previous_version_id
                FROM skill_active_versions WHERE skill_id = ?
                """,
                (skill_id,),
            ).fetchone()
            previous_is_different = previous is not None and int(
                previous["version_id"]
            ) != int(target["id"])
            if previous_is_different and previous is not None:
                self._connection.execute(
                    """
                    UPDATE skill_versions SET state = 'candidate'
                    WHERE id = ? AND state = 'active'
                    """,
                    (int(previous["version_id"]),),
                )
            self._connection.execute(
                "UPDATE skill_versions SET state = 'active' WHERE id = ?",
                (int(target["id"]),),
            )
            self._connection.execute(
                """
                INSERT INTO skill_active_versions(
                    skill_id, version_id, previous_version_id,
                    actor, reason, activated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(skill_id) DO UPDATE SET
                    previous_version_id = skill_active_versions.version_id,
                    version_id = excluded.version_id,
                    actor = excluded.actor,
                    reason = excluded.reason,
                    activated_at = excluded.activated_at
                """,
                (
                    skill_id,
                    int(target["id"]),
                    int(previous["version_id"]) if previous is not None else None,
                    actor,
                    reason,
                    utc_now_iso(),
                ),
            )
            self._record_event(
                event_type,
                skill_id,
                int(target["id"]),
                {
                    "version": version,
                    "previous_version_id": (
                        int(previous["version_id"]) if previous is not None else None
                    ),
                },
                actor=actor,
                reason=reason,
            )
        result = self.get_version(name, version)
        assert result is not None
        return result

    def deprecate(
        self,
        name: str,
        version: str,
        *,
        actor: str = "host",
        reason: str,
        expected_revision: int | None = None,
    ) -> SkillVersion:
        return self._set_terminal_state(
            name,
            version,
            "deprecated",
            actor=actor,
            reason=reason,
            expected_revision=expected_revision,
        )

    def revoke(
        self,
        name: str,
        version: str,
        *,
        actor: str = "host",
        reason: str,
        expected_revision: int | None = None,
    ) -> SkillVersion:
        return self._set_terminal_state(
            name,
            version,
            "revoked",
            actor=actor,
            reason=reason,
            expected_revision=expected_revision,
        )

    def rollback(
        self,
        name: str,
        *,
        actor: str = "host",
        reason: str,
        expected_revision: int | None = None,
    ) -> SkillVersion:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT s.id AS skill_id, a.previous_version_id, v.version
                FROM skills s
                JOIN skill_active_versions a ON a.skill_id = s.id
                LEFT JOIN skill_versions v ON v.id = a.previous_version_id
                WHERE s.name = ?
                """,
                (name,),
            ).fetchone()
        if row is None or row["previous_version_id"] is None:
            raise SkillRegistryError("不存在可回滚的上一激活版本。")
        return self.activate(
            name,
            str(row["version"]),
            actor=actor,
            reason=reason,
            event_type="rolled_back",
            expected_revision=expected_revision,
        )

    def governance(self, name: str, version: str) -> dict[str, Any]:
        """返回宿主 inspect/list 所需的 active 批准事实。"""

        with self._lock:
            row = self._connection.execute(
                """
                SELECT a.actor, a.reason, a.activated_at
                FROM skills s
                JOIN skill_versions v ON v.skill_id = s.id
                LEFT JOIN skill_active_versions a ON a.version_id = v.id
                WHERE s.name = ? AND v.version = ?
                """,
                (name, version),
            ).fetchone()
        if row is None:
            raise SkillRegistryError(f"Skill 版本不存在：{name}@{version}")
        return {
            "approved": row["actor"] is not None,
            "approved_by": str(row["actor"] or ""),
            "approval_reason": str(row["reason"] or ""),
            "activated_at": str(row["activated_at"] or ""),
        }

    def create_snapshot(
        self,
        session_instance_id: str,
        session_key: str,
        versions: list[SkillVersion],
    ) -> list[SkillBinding]:
        """首次调用创建快照；已有快照（包括空快照）保持不变。"""

        now = utc_now_iso()
        with self._lock, self._connection:
            existing = self._connection.execute(
                "SELECT 1 FROM skill_session_snapshots WHERE session_instance_id = ?",
                (session_instance_id,),
            ).fetchone()
            if existing is None:
                self._connection.execute(
                    """
                    INSERT INTO skill_session_snapshots(
                        session_instance_id, session_key, created_at
                    ) VALUES (?, ?, ?)
                    """,
                    (session_instance_id, session_key, now),
                )
                for version in versions:
                    self._connection.execute(
                        """
                        INSERT INTO skill_session_bindings(
                            session_instance_id, session_key, skill_id,
                            version_id, bound_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            session_instance_id,
                            session_key,
                            version.skill_id,
                            version.version_id,
                            now,
                        ),
                    )
        return self.list_bindings(session_instance_id)

    def list_bindings(self, session_instance_id: str) -> list[SkillBinding]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT b.*, s.name, v.version FROM skill_session_bindings b
                JOIN skills s ON s.id = b.skill_id
                JOIN skill_versions v ON v.id = b.version_id
                WHERE b.session_instance_id = ?
                ORDER BY s.name
                """,
                (session_instance_id,),
            ).fetchall()
        return [
            SkillBinding(
                session_instance_id=str(row["session_instance_id"]),
                session_key=str(row["session_key"]),
                version_id=int(row["version_id"]),
                name=str(row["name"]),
                version=str(row["version"]),
                bound_at=str(row["bound_at"]),
            )
            for row in rows
        ]

    def get_bound_version(
        self, session_instance_id: str, name: str
    ) -> SkillVersion | None:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT v.*, s.name, s.owner, s.source_type
                FROM skill_session_bindings b
                JOIN skill_versions v ON v.id = b.version_id
                JOIN skills s ON s.id = b.skill_id
                WHERE b.session_instance_id = ? AND s.name = ?
                """,
                (session_instance_id, name),
            ).fetchone()
        return None if row is None else self._row_to_version(row, str(row["name"]))

    def _set_terminal_state(
        self,
        name: str,
        version: str,
        state: str,
        *,
        actor: str,
        reason: str,
        expected_revision: int | None,
    ) -> SkillVersion:
        if state not in {"deprecated", "revoked"}:
            raise ValueError("终态无效。")
        with self._lock, self._connection:
            self._bump_revision(expected_revision)
            row = self._required_row(name, version)
            self._connection.execute(
                "UPDATE skill_versions SET state = ? WHERE id = ?",
                (state, int(row["id"])),
            )
            self._connection.execute(
                "DELETE FROM skill_active_versions WHERE version_id = ?",
                (int(row["id"]),),
            )
            self._record_event(
                state,
                int(row["skill_id"]),
                int(row["id"]),
                {},
                actor=actor,
                reason=reason,
            )
        result = self.get_version(name, version)
        assert result is not None
        return result

    def _required_row(self, name: str, version: str) -> sqlite3.Row:
        row = self._connection.execute(
            """
            SELECT v.*, s.name, s.owner, s.source_type FROM skill_versions v
            JOIN skills s ON s.id = v.skill_id
            WHERE s.name = ? AND v.version = ?
            """,
            (name, version),
        ).fetchone()
        if row is None:
            raise SkillRegistryError(f"Skill 版本不存在：{name}@{version}")
        return row

    def _record_event(
        self,
        event_type: str,
        skill_id: int | None,
        version_id: int | None,
        payload: dict[str, Any],
        created_at: str | None = None,
        actor: str = "host",
        reason: str = "",
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO skill_registry_events(
                event_type, skill_id, version_id, actor, reason,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                skill_id,
                version_id,
                actor,
                reason,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                created_at or utc_now_iso(),
            ),
        )

    @property
    def revision(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM skill_meta WHERE key = 'revision'"
            ).fetchone()
        if row is None:
            raise SkillRegistryError("Skill Registry 缺少 revision。")
        return int(row["value"])

    def _bump_revision(self, expected_revision: int | None = None) -> int:
        row = self._connection.execute(
            "SELECT value FROM skill_meta WHERE key = 'revision'"
        ).fetchone()
        if row is None:
            raise SkillRegistryError("Skill Registry 缺少 revision。")
        current = int(row["value"])
        if expected_revision is not None and current != expected_revision:
            raise SkillRevisionConflict(
                "Skill Registry revision 冲突："
                f"期望 {expected_revision}，实际 {current}。"
            )
        next_revision = current + 1
        self._connection.execute(
            "UPDATE skill_meta SET value = ? WHERE key = 'revision'",
            (str(next_revision),),
        )
        return next_revision

    def _migrate(self) -> None:
        with self._lock, self._connection:
            existing_tables = {
                str(row["name"])
                for row in self._connection.execute(
                    """
                    SELECT name FROM sqlite_master
                    WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                    """
                ).fetchall()
            }
            expected_tables = {
                "skill_meta",
                "skills",
                "skill_versions",
                "skill_active_versions",
                "skill_session_snapshots",
                "skill_session_bindings",
                "skill_registry_events",
            }
            if existing_tables:
                if "skill_meta" not in existing_tables:
                    raise SkillRegistryError("现有数据库缺少 Skill schema 版本。")
                current = self._connection.execute(
                    "SELECT value FROM skill_meta WHERE key = 'schema_version'"
                ).fetchone()
                if current is None or int(current["value"]) != _SCHEMA_VERSION:
                    raise SkillRegistryError(
                        "skills.db schema 版本不受当前运行时支持。"
                    )
                if not expected_tables.issubset(existing_tables):
                    raise SkillRegistryError("skills.db schema 不完整，拒绝自动重建。")
                revision = self._connection.execute(
                    "SELECT value FROM skill_meta WHERE key = 'revision'"
                ).fetchone()
                if revision is None:
                    raise SkillRegistryError("skills.db 缺少 revision，拒绝自动修补。")
                return
            self._connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS skill_meta(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS skills(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    owner TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS skill_versions(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    skill_id INTEGER NOT NULL REFERENCES skills(id),
                    version TEXT NOT NULL,
                    description TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN (
                        'draft','candidate','validated','canary','active',
                        'deprecated','rejected','revoked'
                    )),
                    previous_version_id INTEGER REFERENCES skill_versions(id),
                    artifact_path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(skill_id, version)
                );
                CREATE TABLE IF NOT EXISTS skill_active_versions(
                    skill_id INTEGER PRIMARY KEY REFERENCES skills(id),
                    version_id INTEGER NOT NULL UNIQUE REFERENCES skill_versions(id),
                    previous_version_id INTEGER REFERENCES skill_versions(id),
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    activated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS skill_session_snapshots(
                    session_instance_id TEXT PRIMARY KEY,
                    session_key TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS skill_session_bindings(
                    session_instance_id TEXT NOT NULL
                        REFERENCES skill_session_snapshots(session_instance_id),
                    session_key TEXT NOT NULL,
                    skill_id INTEGER NOT NULL REFERENCES skills(id),
                    version_id INTEGER NOT NULL REFERENCES skill_versions(id),
                    bound_at TEXT NOT NULL,
                    PRIMARY KEY(session_instance_id, skill_id)
                );
                CREATE TABLE IF NOT EXISTS skill_registry_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    skill_id INTEGER REFERENCES skills(id),
                    version_id INTEGER REFERENCES skill_versions(id),
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                INSERT INTO skill_meta(key, value) VALUES ('schema_version', '1');
                INSERT INTO skill_meta(key, value) VALUES ('revision', '0');
                COMMIT;
                """
            )

    @staticmethod
    def _row_to_version(row: sqlite3.Row, name: str) -> SkillVersion:
        return SkillVersion(
            version_id=int(row["id"]),
            skill_id=int(row["skill_id"]),
            name=name,
            owner=str(row["owner"]),
            source_type=str(row["source_type"]),
            version=str(row["version"]),
            description=str(row["description"]),
            state=str(row["state"]),
            artifact_path=str(row["artifact_path"]),
            content_hash=str(row["content_hash"]),
            manifest_json=str(row["manifest_json"]),
            created_at=str(row["created_at"]),
        )
