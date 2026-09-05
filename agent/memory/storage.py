"""
Storage layer for memory using SQLite + FTS5

Provides vector and keyword search capabilities
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory.vector_backend import (
    SQLiteVectorBackend,
    VectorBackend,
    VectorRecord,
)

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False
    np = None  # type: ignore[assignment]

# UPSERT（插入与已有行冲突时改为更新）需要 SQLite ≥ 3.24.0 (2018)。
# 较旧的环境（如 CentOS 7 自带 SQLite 3.7）会回退到 INSERT OR REPLACE，
# 这会在更新块时带来 FTS5 rowid 漂移的风险（参见 save_chunk 文档字符串）。
_HAS_UPSERT = sqlite3.sqlite_version_info >= (3, 24, 0)

# ---------------------------------------------------------------------------
# CJK 字符范围，在模块加载时编译一次。
# 涵盖：CJK 符号/标点符号、日语假名（平假名 + 片假名）、
#         CJK 统一表意文字 + 扩展 A、韩语音节（韩文）、
#         CJK 兼容性表意文字和 CJK 扩展 B–F。
# ---------------------------------------------------------------------------
_CJK_RANGES = (
    r'\u3000-\u30ff'          # CJK 符号/标点符号 + 日语假名
    r'\u3400-\u9fff'          # CJK 统一表意文字（包括扩展 A）
    r'\uac00-\ud7af'          # 韩语音节（韩文）
    r'\uf900-\ufaff'          # CJK 兼容性表意文字
    r'\U00020000-\U0002fa1f'  # CJK 扩展 B–F
)
_RE_CONTAINS_CJK   = re.compile(f'[{_CJK_RANGES}]')
_RE_CJK_WORDS      = re.compile(f'[{_CJK_RANGES}]+')
_RE_TRIGRAM_TOKENS = re.compile(f'[{_CJK_RANGES}]+|[A-Za-z0-9_]+')

# sqlite3.OperationalError 是 DatabaseError 的子类，因此“数据库已锁定”、
# “磁盘 I/O 错误”这类错误必须先与真正的损坏区分开，
# 再决定是否尝试任何恢复。
_CORRUPTION_MARKERS = ("malformed", "corrupt", "file is not a database", "encrypted")


def _is_corruption_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _CORRUPTION_MARKERS)


def _split_fts5_damage(report: str) -> tuple[list[str], list[str]]:
    """Split an integrity_check report into FTS5 findings and everything else.

    SQLite 3.44 taught integrity_check to validate FTS3/FTS5 content too, so a
    merely stale search index now shows up as a failure. Those indexes are
    derived data and get rebuilt from the chunks table, whereas other findings
    mean the b-tree itself is damaged.
    """
    fts5, other = [], []
    for line in report.splitlines():
        line = line.strip()
        if not line:
            continue
        (fts5 if "fts5" in line.lower() else other).append(line)
    return fts5, other


@dataclass
class MemoryChunk:
    """Represents a memory chunk with text and embedding"""
    id: str
    user_id: Optional[str]
    scope: str  # 作用域取值："shared" | "user" | "session"
    source: str  # 来源类型："memory" 等
    path: str
    start_line: int
    end_line: int
    text: str
    embedding: Optional[List[float]]
    hash: str
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class SearchResult:
    """Search result with score and snippet"""
    path: str
    start_line: int
    end_line: int
    score: float
    snippet: str
    source: str
    user_id: Optional[str] = None


class MemoryStorage:
    """SQLite-based storage with FTS5 for keyword search"""
    
    def __init__(
        self,
        db_path: Path,
        vector_backend: Optional[VectorBackend] = None,
    ):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
        self.vector_backend = vector_backend
        self.fts5_available = False  # 跟踪 FTS5 可用性
        # RLock 用于保护同一进程内的并发写入。
        # SQLite 的 WAL 模式负责文件级别的读写并发，
        # 但同一进程内的并发写入仍需要 Python 级锁来保证。
        self._lock = threading.RLock()
        self._init_db()
        if self.vector_backend is None:
            assert self.conn is not None
            self.vector_backend = SQLiteVectorBackend(self.conn)
    
    def _check_fts5_support(self) -> bool:
        """Check if SQLite has FTS5 support"""
        try:
            self.conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS fts5_test USING fts5(test)")
            self.conn.execute("DROP TABLE IF EXISTS fts5_test")
            return True
        except sqlite3.OperationalError as e:
            if "no such module: fts5" in str(e):
                return False
            raise

    def _open_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        try:
            conn.row_factory = sqlite3.Row
            # WAL 和 busy_timeout 必须在任何长读取之前设置（尤其是
            # integrity_check），否则并发写入会因 SQLITE_BUSY 失败，
            # 而该错误曾一度被误判为数据库损坏。
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
        except Exception:
            conn.close()
            raise
        return conn

    def _check_integrity(self):
        """Verify the database, recovering without destroying user data.

        This file is shared with the conversation history (sessions / messages
        tables), which is irreplaceable — unlike chunks/files, which are
        re-derivable from the workspace. So it is never deleted here:
          - FTS5-only damage is repaired later from the chunks table.
          - Real corruption quarantines the file so it stays recoverable.
          - Transient failures (locked, disk I/O) are logged and ignored.

        ``PRAGMA integrity_check`` is a full page-by-page scan that also
        validates every FTS5 index. On a large DB sitting on a network
        filesystem (e.g. an NFS PVC) it can take tens of seconds, and it runs
        on *every* open — i.e. on every session's agent init — which dominates
        first-message latency. ``quick_check`` is used instead: it finds the
        same b-tree damage but skips the index validation that costs the time.
        Opening the connection alone is not enough to catch this — that only
        trips on damage to the header or the pages it happens to touch, so an
        interior page zeroed out would otherwise go unnoticed until a read
        landed on it and failed with no chance to recover. FTS5 shadow-table
        damage is not covered by ``quick_check``; it is caught independently by
        ``_fts5_shadow_corrupt`` / ``_trigram_shadow_corrupt`` right before
        use. Set ``memory_integrity_check: true`` in config.json to run the
        full scan instead (e.g. for a one-off diagnostic).
        """
        from common.log import logger
        pragma = "quick_check"
        try:
            from config import conf
            if conf().get("memory_integrity_check", False):
                pragma = "integrity_check"
        except Exception:
            # 无法获取配置（测试/独立运行环境）时，维持既有行为：
            # 执行完整扫描。
            pragma = "integrity_check"
        try:
            rows = self.conn.execute(f"PRAGMA {pragma}").fetchall()
            report = "\n".join(str(r[0]) for r in rows).strip()
        except sqlite3.DatabaseError as e:
            if not _is_corruption_error(e):
                logger.warning(f"[MemoryStorage] Integrity check skipped: {e}")
                return
            report = str(e)

        if report == "ok":
            return

        fts5_lines, other_lines = _split_fts5_damage(report)
        if fts5_lines:
            self._trigram_needs_rebuild = any(
                "chunks_fts_trigram" in ln for ln in fts5_lines
            )
            self._fts5_needs_rebuild = any(
                "chunks_fts" in ln and "chunks_fts_trigram" not in ln
                for ln in fts5_lines
            )
            logger.warning(
                f"[MemoryStorage] FTS5 index damaged, will rebuild from chunks: "
                f"{'; '.join(fts5_lines)}"
            )
        if not other_lines:
            return

        logger.error(
            f"[MemoryStorage] Database corrupted: {'; '.join(other_lines)}"
        )
        self._quarantine_and_recreate()

    def _quarantine_and_recreate(self):
        """Move an unusable database aside (never delete it) and open a fresh one.

        Conversation history lives in the same file, so the old bytes are kept
        under a .corrupt-<ts> suffix for manual recovery.
        """
        from common.log import logger
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

        suffix = f".corrupt-{int(time.time())}"
        for path in (
            self.db_path,
            Path(f"{self.db_path}-wal"),
            Path(f"{self.db_path}-shm"),
        ):
            if not path.exists():
                continue
            try:
                os.replace(str(path), f"{path}{suffix}")
            except OSError as e:
                logger.error(f"[MemoryStorage] Failed to quarantine {path}: {e}")

        logger.error(
            f"[MemoryStorage] Corrupt database moved to {self.db_path}{suffix} and "
            f"replaced by an empty one. Conversation history can be recovered from "
            f"the quarantined copy."
        )
        self.conn = self._open_conn()

    def _init_db(self):
        """Initialize database with schema"""
        self._fts5_needs_rebuild = False
        self._trigram_needs_rebuild = False
        try:
            try:
                self.conn = self._open_conn()
            except sqlite3.DatabaseError as e:
                # 损坏的文件头会使数据库无法打开，下面的完整性检查
                # 也就永远无法执行；先把该文件隔离，再重新初始化。
                if not _is_corruption_error(e):
                    raise
                from common.log import logger
                logger.error(f"[MemoryStorage] Database unreadable: {e}")
                self._quarantine_and_recreate()

            # 检查 FTS5 支持
            self.fts5_available = self._check_fts5_support()
            if not _HAS_UPSERT:
                from common.log import logger
                logger.warning(
                    "[MemoryStorage] SQLite %s < 3.24 — UPSERT unavailable. "
                    "Falling back to INSERT OR REPLACE; FTS5 rowid may drift on "
                    "chunk updates (rebuild index periodically to recover).",
                    sqlite3.sqlite_version,
                )
            if not self.fts5_available:
                from common.log import logger
                logger.debug("[MemoryStorage] FTS5 not available, using LIKE-based keyword search")

            self._check_integrity()
        except Exception as e:
            from common.log import logger
            logger.error(f"[MemoryStorage] Unexpected error during database initialization: {e}")
            raise
        
        # 创建带嵌入向量的块表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                scope TEXT NOT NULL DEFAULT 'shared',
                source TEXT NOT NULL DEFAULT 'memory',
                path TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding TEXT,
                hash TEXT NOT NULL,
                metadata TEXT,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                updated_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        """)
        
        # 创建索引
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_user 
            ON chunks(user_id)
        """)
        
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_scope 
            ON chunks(scope)
        """)
        
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_hash 
            ON chunks(path, hash)
        """)
        
        # 创建 FTS5 虚拟表和触发器（仅在支持时）。
        # 自愈：如果上一个进程在重建过程中崩溃，留下触发器
        # 指向缺失的 chunks_fts 表（或反之亦然），就同时清掉
        # 双方再干净地重建。否则下一次插入块时会报
        # “no such table: chunks_fts” 错误。
        if self.fts5_available:
            if self._fts5_state_inconsistent():
                from common.log import logger
                logger.warning(
                    "[MemoryStorage] FTS5 state inconsistent (triggers/table mismatch). "
                    "Resetting chunks_fts to recover."
                )
                self.conn.execute("DROP TRIGGER IF EXISTS chunks_ai")
                self.conn.execute("DROP TRIGGER IF EXISTS chunks_ad")
                self.conn.execute("DROP TRIGGER IF EXISTS chunks_au")
                self.conn.execute("DROP TABLE IF EXISTS chunks_fts")
                self.conn.commit()
            self._create_fts5_objects()

            # 探测 FTS5 影子表。表结构可能完好，但内部的
            # _data / _idx / _docsize 数据块仍可能已损坏——即
            # 在 bm25 / MATCH 上报“database disk image is malformed”。
            # 一旦发生这种情况，我们依据 chunks 表重建；数据不会丢失，
            # 因为 chunks（内容表）才是事实来源。
            if self._fts5_needs_rebuild or self._fts5_shadow_corrupt():
                from common.log import logger
                logger.warning(
                    "[MemoryStorage] FTS5 shadow tables corrupt; rebuilding from chunks."
                )
                self._rebuild_fts5_from_chunks()

        # 内部键值存储，用于保存持久化的标记（例如回填进度跟踪）
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS _meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # 创建用于 CJK/混合语言搜索的 trigram FTS5 表
        self.trigram_fts5_available = False
        if self.fts5_available:
            try:
                self.conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts_trigram USING fts5(
                        text,
                        id UNINDEXED,
                        user_id UNINDEXED,
                        path UNINDEXED,
                        source UNINDEXED,
                        scope UNINDEXED,
                        content='chunks',
                        content_rowid='rowid',
                        tokenize='trigram case_sensitive 0'
                    )
                """)
                # 迁移旧版本创建的旧 chunks_trigram_au 触发器。
                # 旧版本使用裸“UPDATE chunks_fts_trigram SET ...”
                # 会在块更新时破坏三元组索引，因此这里直接丢弃它，
                # 由下方 CREATE TRIGGER IF NOT EXISTS 安装修复后的
                # 删除+插入版本。删除触发器不会触碰任何数据。
                self._migrate_legacy_trigram_update_trigger()
                self.conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS chunks_trigram_ai
                    AFTER INSERT ON chunks BEGIN
                        INSERT INTO chunks_fts_trigram(rowid, text, id, user_id, path, source, scope)
                        VALUES (new.rowid, new.text, new.id, new.user_id, new.path, new.source, new.scope);
                    END
                """)
                self.conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS chunks_trigram_ad
                    AFTER DELETE ON chunks BEGIN
                        DELETE FROM chunks_fts_trigram WHERE rowid = old.rowid;
                    END
                """)
                # 外部内容 FTS5 在更新时需要删除+插入
                # 模式：裸“UPDATE chunks_fts_trigram SET ...”
                # 会留下索引中的旧标记并损坏三元组影子表
                # （报错“database disk image is malformed”）。
                # 特殊的“delete”命令借助旧行的先前文本清除其标记。
                self.conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS chunks_trigram_au
                    AFTER UPDATE ON chunks BEGIN
                        INSERT INTO chunks_fts_trigram(chunks_fts_trigram, rowid, text, id, user_id, path, source, scope)
                        VALUES ('delete', old.rowid, old.text, old.id, old.user_id, old.path, old.source, old.scope);
                        INSERT INTO chunks_fts_trigram(rowid, text, id, user_id, path, source, scope)
                        VALUES (new.rowid, new.text, new.id, new.user_id, new.path, new.source, new.scope);
                    END
                """)
                # 对现有行做一次性回填。
                # 注意：FTS5 内容表上的 COUNT(*) 恒为 0，因此我们
                # 改用 _meta 中的持久标志，而不是统计三元组行数。
                backfill_done = self.conn.execute(
                    "SELECT 1 FROM _meta WHERE key = 'trigram_backfill_done'"
                ).fetchone()
                chunks_count = self.conn.execute(
                    "SELECT COUNT(*) as c FROM chunks"
                ).fetchone()['c']
                if self._trigram_needs_rebuild or (chunks_count > 0 and not backfill_done):
                    self.conn.execute(
                        "INSERT INTO chunks_fts_trigram(chunks_fts_trigram) VALUES('rebuild')"
                    )
                    self.conn.execute(
                        "INSERT OR REPLACE INTO _meta(key, value) VALUES('trigram_backfill_done', '1')"
                    )
                self.trigram_fts5_available = True
            except Exception:
                from common.log import logger
                logger.warning("[MemoryStorage] trigram FTS5 unavailable, CJK search will use LIKE fallback", exc_info=True)
                self.trigram_fts5_available = False

        # 创建文件元数据表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                source TEXT NOT NULL DEFAULT 'memory',
                hash TEXT NOT NULL,
                mtime INTEGER NOT NULL,
                size INTEGER NOT NULL,
                updated_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        """)

        self.conn.commit()

    def _migrate_legacy_trigram_update_trigger(self):
        """Replace the legacy chunks_trigram_au trigger if present.

        Older versions synced updates with a bare
        "UPDATE chunks_fts_trigram SET ...", which corrupts the external-content
        trigram index on chunk updates. We detect that shape via the stored
        trigger SQL, drop it (dropping a trigger touches no data), and flag a
        trigram rebuild so any already-damaged index is repaired below.
        """
        try:
            row = self.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' "
                "AND name='chunks_trigram_au'"
            ).fetchone()
        except Exception:
            return
        if not row or not row[0]:
            return
        if "UPDATE chunks_fts_trigram" in row[0]:
            from common.log import logger
            logger.warning(
                "[MemoryStorage] Replacing legacy chunks_trigram_au trigger and "
                "rebuilding the trigram index."
            )
            self.conn.execute("DROP TRIGGER IF EXISTS chunks_trigram_au")
            self._trigram_needs_rebuild = True

    def _fts5_state_inconsistent(self) -> bool:
        """Detect a half-broken FTS5 setup (e.g. trigger exists but table doesn't)."""
        try:
            row = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='chunks_fts'"
            ).fetchone()
            table_exists = row is not None
            row = self.conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' "
                "AND name IN ('chunks_ai','chunks_ad','chunks_au')"
            ).fetchone()
            trigger_count = int(row[0]) if row else 0
        except Exception:
            return False
        # 健康状态 = 两者要么都存在（3 个触发器 + 表），要么都不存在。
        return table_exists != (trigger_count > 0)

    def _create_fts5_objects(self):
        """Create chunks_fts virtual table and the 3 sync triggers.

        Idempotent: uses IF NOT EXISTS. Caller must hold self.conn.
        """
        self.conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                text,
                id UNINDEXED,
                user_id UNINDEXED,
                path UNINDEXED,
                source UNINDEXED,
                scope UNINDEXED,
                content='chunks',
                content_rowid='rowid'
            )
        """)
        self.conn.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid, text, id, user_id, path, source, scope)
                VALUES (new.rowid, new.text, new.id, new.user_id, new.path, new.source, new.scope);
            END
        """)
        self.conn.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                DELETE FROM chunks_fts WHERE rowid = old.rowid;
            END
        """)
        self.conn.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
                UPDATE chunks_fts SET text = new.text, id = new.id,
                                     user_id = new.user_id, path = new.path,
                                     source = new.source, scope = new.scope
                WHERE rowid = new.rowid;
            END
        """)

    def reset_fts5(self):
        """Drop and recreate chunks_fts + triggers in one transaction.

        Used by rebuild_index to recover from FTS5 shadow-table corruption
        (bm25/ORDER BY rank may raise "database disk image is malformed"
        even when raw MATCH still works).

        Triggers must be dropped first; otherwise the next chunks INSERT/DELETE
        on the existing connection will hit "no such table: chunks_fts".
        """
        if not self.fts5_available:
            return
        self.conn.execute("DROP TRIGGER IF EXISTS chunks_ai")
        self.conn.execute("DROP TRIGGER IF EXISTS chunks_ad")
        self.conn.execute("DROP TRIGGER IF EXISTS chunks_au")
        self.conn.execute("DROP TABLE IF EXISTS chunks_fts")
        self._create_fts5_objects()
        self.conn.commit()

    def _fts5_shadow_corrupt(self) -> bool:
        """Probe whether bm25 over chunks_fts errors out at startup.

        Schema (table + triggers) can be intact while the underlying
        FTS5 shadow blobs are malformed — typically because the previous
        process crashed mid-write or wrote with a different SQLite build.
        A cheap MATCH probe surfaces it immediately."""
        try:
            self.conn.execute(
                "SELECT bm25(chunks_fts) FROM chunks_fts WHERE chunks_fts MATCH 'a' LIMIT 1"
            ).fetchone()
            return False
        except sqlite3.DatabaseError as e:
            msg = str(e).lower()
            return "malformed" in msg or "corrupt" in msg
        except Exception:
            # 任何其他错误（例如表缺失）都由状态不一致的路径
            # 去处理，此处一律视为健康。
            return False

    def _rebuild_fts5_from_chunks(self):
        """Drop FTS5, recreate it, then INSERT every row from chunks.

        Safe data-wise: chunks (the content table) is the source of truth.
        Done in one transaction so a crash leaves either fully old or fully
        new state, not a partial rebuild.
        """
        # 先重置表结构，借此清除任何已损坏的影子表数据。
        self.reset_fts5()
        # 重新灌入内容。触发器会自动处理后续的写入。
        self.conn.execute("""
            INSERT INTO chunks_fts(rowid, text, id, user_id, path, source, scope)
            SELECT rowid, text, id, user_id, path, source, scope FROM chunks
        """)
        self.conn.commit()

    def save_chunk(self, chunk: MemoryChunk):
        """Save a memory chunk (insert or update by id).

        Uses SQLite UPSERT (INSERT … ON CONFLICT DO UPDATE) instead of
        INSERT OR REPLACE.  INSERT OR REPLACE internally does DELETE+INSERT,
        which changes the row's rowid.  Because both FTS5 tables use
        content_rowid='rowid', a new rowid would leave the old FTS index
        entries pointing at a non-existent rowid and trigger
        "fts5: missing row N from content table" errors.
        ON CONFLICT DO UPDATE fires the AFTER UPDATE trigger (chunks_au /
        chunks_trigram_au) and keeps the original rowid intact.
        """
        if _HAS_UPSERT:
            _SQL = """
                INSERT INTO chunks
                (id, user_id, scope, source, path, start_line, end_line,
                 text, embedding, hash, metadata, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
                ON CONFLICT(id) DO UPDATE SET
                    user_id     = excluded.user_id,
                    scope       = excluded.scope,
                    source      = excluded.source,
                    path        = excluded.path,
                    start_line  = excluded.start_line,
                    end_line    = excluded.end_line,
                    text        = excluded.text,
                    embedding   = excluded.embedding,
                    hash        = excluded.hash,
                    metadata    = excluded.metadata,
                    updated_at  = strftime('%s', 'now')
            """
        else:
            _SQL = """
                INSERT OR REPLACE INTO chunks
                (id, user_id, scope, source, path, start_line, end_line,
                 text, embedding, hash, metadata, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
            """
        params = (
            chunk.id, chunk.user_id, chunk.scope, chunk.source, chunk.path,
            chunk.start_line, chunk.end_line, chunk.text,
            None,
            chunk.hash,
            json.dumps(chunk.metadata) if chunk.metadata else None,
        )
        with self._lock:
            try:
                self.conn.execute(_SQL, params)
                self.vector_backend.upsert([self._to_vector_record(chunk)])
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def save_chunks_batch(self, chunks: List[MemoryChunk]):
        """Save multiple chunks in a batch (insert or update by id).

        See save_chunk for why UPSERT is used instead of INSERT OR REPLACE.
        """
        if _HAS_UPSERT:
            _SQL = """
                INSERT INTO chunks
                (id, user_id, scope, source, path, start_line, end_line,
                 text, embedding, hash, metadata, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
                ON CONFLICT(id) DO UPDATE SET
                    user_id     = excluded.user_id,
                    scope       = excluded.scope,
                    source      = excluded.source,
                    path        = excluded.path,
                    start_line  = excluded.start_line,
                    end_line    = excluded.end_line,
                    text        = excluded.text,
                    embedding   = excluded.embedding,
                    hash        = excluded.hash,
                    metadata    = excluded.metadata,
                    updated_at  = strftime('%s', 'now')
            """
        else:
            _SQL = """
                INSERT OR REPLACE INTO chunks
                (id, user_id, scope, source, path, start_line, end_line,
                 text, embedding, hash, metadata, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
            """
        params_list = [
            (
                c.id, c.user_id, c.scope, c.source, c.path,
                c.start_line, c.end_line, c.text,
                None,
                c.hash,
                json.dumps(c.metadata) if c.metadata else None,
            )
            for c in chunks
        ]
        with self._lock:
            try:
                self.conn.executemany(_SQL, params_list)
                self.vector_backend.upsert([
                    self._to_vector_record(chunk) for chunk in chunks
                ])
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
    
    def get_chunk(self, chunk_id: str) -> Optional[MemoryChunk]:
        """Get a chunk by ID"""
        row = self.conn.execute("""
            SELECT * FROM chunks WHERE id = ?
        """, (chunk_id,)).fetchone()
        
        if not row:
            return None
        
        return self._row_to_chunk(row)
    
    def search_vector(
        self,
        query_embedding: List[float],
        user_id: Optional[str] = None,
        scopes: List[str] = None,
        limit: int = 10
    ) -> List[SearchResult]:
        """Search the configured vector backend."""
        if scopes is None:
            scopes = ["shared"]
            if user_id:
                scopes.append("user")
        metadata_filter = {"scopes": scopes}
        if user_id:
            metadata_filter["user_id"] = user_id
        matches = self.vector_backend.search(
            query_embedding,
            limit=limit,
            metadata_filter=metadata_filter,
        )
        return [
            SearchResult(
                path=match.metadata["path"],
                start_line=match.metadata["start_line"],
                end_line=match.metadata["end_line"],
                score=match.score,
                snippet=self._truncate_text(match.metadata["text"], 500),
                source=match.metadata["source"],
                user_id=match.metadata.get("user_id"),
            )
            for match in matches
        ]
    
    def search_keyword(
        self,
        query: str,
        user_id: Optional[str] = None,
        scopes: List[str] = None,
        limit: int = 10
    ) -> List[SearchResult]:
        """
        Keyword search using FTS5 + LIKE fallback

        Strategy:
        1. If FTS5 available and healthy: try FTS5 first
        2. Always fall back to LIKE for CJK queries
        3. If FTS5 fails OR returns empty for non-CJK, also try LIKE so a
           broken FTS5 shadow table doesn't silently kill keyword search.
        """
        if scopes is None:
            scopes = ["shared"]
            if user_id:
                scopes.append("user")

        # 步骤 1：标准 FTS5（unicode61）——仅用于纯 ASCII 查询。
        # 查询含任何 CJK 字符时跳过该步：unicode61 会把 CJK 拆成单个字符，
        # 无法组成有意义的词元，于是只能命中混合查询里的 ASCII 部分
        # （如 "Python教程" 中的 ASCII 片段），CJK 部分则被静默丢弃。
        # 这类查询直接进入步骤 2（trigram），由它同时处理 ASCII 与 CJK。
        fts1_attempted = False
        if (self.fts5_available
                and not MemoryStorage._contains_cjk(query)
                and MemoryStorage._build_fts_query(query)):
            fts1_attempted = True
            fts_results = self._search_fts5(query, user_id, scopes, limit)
            if fts_results:
                return fts_results

        # 步骤 2：Trigram FTS5 —— 用于 CJK/混合查询，并作为 unicode61
        # 未返回任何结果时的回退（trigram 以 3 字符滑动窗口对所有文字建索引，
        # 因此能捕获 unicode61 分词遗漏的术语）。
        if self.trigram_fts5_available and (
            MemoryStorage._contains_cjk(query) or fts1_attempted
        ):
            trigram_results = self._search_fts5_trigram(query, user_id, scopes, limit)
            if trigram_results:
                return trigram_results

        # 第 3 步：LIKE 兜底 —— 最后的手段（FTS5 不可用，或 CJK 查询
        # 少于 3 个字符导致三元组无法匹配，例如单字符查询）。
        if not self.fts5_available or MemoryStorage._contains_cjk(query):
            return self._search_like(query, user_id, scopes, limit)

        return []
    
    def _search_fts5(
        self,
        query: str,
        user_id: Optional[str],
        scopes: List[str],
        limit: int
    ) -> List[SearchResult]:
        """FTS5 full-text search"""
        fts_query = self._build_fts_query(query)
        if not fts_query:
            return []
        
        scope_placeholders = ','.join('?' * len(scopes))
        params = [fts_query] + scopes
        
        if user_id:
            sql_query = f"""
                SELECT chunks.*, bm25(chunks_fts) as rank
                FROM chunks_fts
                JOIN chunks ON chunks.rowid = chunks_fts.rowid
                WHERE chunks_fts MATCH ? 
                AND chunks.scope IN ({scope_placeholders})
                AND (chunks.scope = 'shared' OR chunks.user_id = ?)
                ORDER BY rank
                LIMIT ?
            """
            params.extend([user_id, limit])
        else:
            sql_query = f"""
                SELECT chunks.*, bm25(chunks_fts) as rank
                FROM chunks_fts
                JOIN chunks ON chunks.rowid = chunks_fts.rowid
                WHERE chunks_fts MATCH ? 
                AND chunks.scope IN ({scope_placeholders})
                ORDER BY rank
                LIMIT ?
            """
            params.append(limit)
        
        try:
            rows = self.conn.execute(sql_query, params).fetchall()
            return [
                SearchResult(
                    path=row['path'],
                    start_line=row['start_line'],
                    end_line=row['end_line'],
                    score=self._bm25_rank_to_score(row['rank']),
                    snippet=self._truncate_text(row['text'], 500),
                    source=row['source'],
                    user_id=row['user_id']
                )
                for row in rows
            ]
        except Exception:
            from common.log import logger
            logger.warning("[MemoryStorage] _search_fts5 failed, returning empty", exc_info=True)
            return []

    def _search_like(
        self,
        query: str,
        user_id: Optional[str],
        scopes: List[str],
        limit: int
    ) -> List[SearchResult]:
        """LIKE-based search.

        Used as the keyword-search fallback when FTS5 is unavailable, fails,
        or returns empty. Supports both CJK runs (1+ chars) and ASCII word
        tokens (3+ chars) so it can serve as a true safety net for any query.
        """
        # CJK 连续串（1 个以上字符，宽 Unicode 范围）+ ASCII 单词（3 个以上字符以免噪音）
        cjk_words = _RE_CJK_WORDS.findall(query)
        ascii_words = [t for t in re.findall(r'[A-Za-z0-9_]+', query) if len(t) >= 3]
        words = cjk_words + ascii_words
        if not words:
            return []

        scope_placeholders = ','.join('?' * len(scopes))

        # 为每个单词构建 LIKE 条件（ASCII 不区分大小写）
        like_conditions = []
        params = []
        for word in words:
            like_conditions.append("LOWER(text) LIKE ?")
            params.append(f'%{word.lower()}%')
        
        where_clause = ' OR '.join(like_conditions)
        params.extend(scopes)
        
        if user_id:
            sql_query = f"""
                SELECT * FROM chunks
                WHERE ({where_clause})
                AND scope IN ({scope_placeholders})
                AND (scope = 'shared' OR user_id = ?)
                LIMIT ?
            """
            params.extend([user_id, limit])
        else:
            sql_query = f"""
                SELECT * FROM chunks
                WHERE ({where_clause})
                AND scope IN ({scope_placeholders})
                LIMIT ?
            """
            params.append(limit)
        
        try:
            rows = self.conn.execute(sql_query, params).fetchall()
            results = []
            for row in rows:
                # 动态打分：包含越多的查询词，得分越高。
                # 使用全部词元（CJK + ASCII），因此纯 ASCII 查询也不会被漏掉。
                # 由于 WHERE 子句用的是 OR，matched_count 通常 ≥ 1，但这里
                # 仍做防御性处理，杜绝意外的零命中行混入结果。
                text_lower = row['text'].lower()
                matched_count = sum(1 for w in words if w.lower() in text_lower)
                if matched_count == 0:
                    continue
                score = min(0.85, 0.3 + 0.15 * matched_count)
                results.append(SearchResult(
                    path=row['path'],
                    start_line=row['start_line'],
                    end_line=row['end_line'],
                    score=score,
                    snippet=self._truncate_text(row['text'], 500),
                    source=row['source'],
                    user_id=row['user_id']
                ))
            results.sort(key=lambda r: r.score, reverse=True)
            return results
        except Exception:
            from common.log import logger
            logger.warning("[MemoryStorage] _search_like failed, returning empty", exc_info=True)
            return []

    def delete_by_path(self, path: str):
        """Delete all chunks and file metadata for a path."""
        with self._lock:
            try:
                self.vector_backend.delete(metadata_filter={"path": path})
                self.conn.execute("DELETE FROM chunks WHERE path = ?", (path,))
                self.conn.execute("DELETE FROM files WHERE path = ?", (path,))
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def get_file_hash(self, path: str) -> Optional[str]:
        """Get stored file hash"""
        row = self.conn.execute("""
            SELECT hash FROM files WHERE path = ?
        """, (path,)).fetchone()
        return row['hash'] if row else None

    def update_file_metadata(self, path: str, source: str, file_hash: str, mtime: int, size: int):
        """Update file metadata"""
        with self._lock:
            self.conn.execute("""
                INSERT OR REPLACE INTO files (path, source, hash, mtime, size, updated_at)
                VALUES (?, ?, ?, ?, ?, strftime('%s', 'now'))
            """, (path, source, file_hash, mtime, size))
            self.conn.commit()
    
    def get_stats(self) -> Dict[str, int]:
        """Get storage statistics"""
        chunks_count = self.conn.execute("""
            SELECT COUNT(*) as cnt FROM chunks
        """).fetchone()['cnt']

        files_count = self.conn.execute("""
            SELECT COUNT(*) as cnt FROM files
        """).fetchone()['cnt']

        embedded_count = self.conn.execute("""
            SELECT COUNT(*) as cnt FROM chunks WHERE embedding IS NOT NULL
        """).fetchone()['cnt']

        return {
            'chunks': chunks_count,
            'files': files_count,
            'embedded': embedded_count,
        }
    
    def close(self):
        """Close database connection"""
        if self.conn:
            try:
                self.conn.commit()  # 确保所有更改均已提交
                self.conn.close()
                self.conn = None  # 标记为已关闭
            except Exception as e:
                from common.log import logger
                logger.warning("[MemoryStorage] Error closing database connection: %s", e)
    
    def __del__(self):
        """Destructor to ensure connection is closed"""
        try:
            self.close()
        except Exception:
            pass  # 忽略清理期间的错误
    
    # 辅助方法

    @staticmethod
    def _to_vector_record(chunk: MemoryChunk) -> VectorRecord:
        return VectorRecord(
            id=chunk.id,
            embedding=chunk.embedding,
            metadata={
                "user_id": chunk.user_id,
                "scope": chunk.scope,
                "source": chunk.source,
                "path": chunk.path,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "text": chunk.text,
                "metadata": chunk.metadata,
            },
        )

    @staticmethod
    def _decode_embedding(raw) -> Optional[List[float]]:
        """Decode embedding from BLOB bytes or legacy JSON string.
        Handles both numpy and numpy-free environments."""
        if raw is None:
            return None
        if isinstance(raw, (bytes, bytearray)):
            if _HAS_NUMPY:
                return np.frombuffer(raw, dtype=np.float32).tolist()
            import struct
            n = len(raw) // 4
            return list(struct.unpack(f'{n}f', raw))
        # 旧版本写入的旧式 JSON 格式
        return json.loads(raw)

    def _row_to_chunk(self, row) -> MemoryChunk:
        """Convert database row to MemoryChunk"""
        return MemoryChunk(
            id=row['id'],
            user_id=row['user_id'],
            scope=row['scope'],
            source=row['source'],
            path=row['path'],
            start_line=row['start_line'],
            end_line=row['end_line'],
            text=row['text'],
            embedding=self._decode_embedding(row['embedding']),
            hash=row['hash'],
            metadata=json.loads(row['metadata']) if row['metadata'] else None
        )
    
    @staticmethod
    def _contains_cjk(text: str) -> bool:
        """Check if text contains CJK or related characters (Chinese, Japanese, Korean)."""
        return bool(_RE_CONTAINS_CJK.search(text))
    
    @staticmethod
    def _build_trigram_query(raw_query: str) -> Optional[str]:
        """
        Build FTS5 MATCH query for the trigram tokenizer.
        Extracts CJK sequences (including single characters) and ASCII words,
        joining them with AND so all terms must appear in the matched chunk.
        """
        tokens = _RE_TRIGRAM_TOKENS.findall(raw_query)
        tokens = [t for t in tokens if t]
        if not tokens:
            return None
        # 转义词元中内嵌的双引号（在 FTS5 的引号短语里，
        # 双引号需写成两个连续的双引号）
        quoted = [f'"{t.replace(chr(34), chr(34)*2)}"' for t in tokens]
        return ' AND '.join(quoted)

    def _search_fts5_trigram(
        self,
        query: str,
        user_id: Optional[str],
        scopes: List[str],
        limit: int
    ) -> List[SearchResult]:
        """Trigram FTS5 search — handles CJK and mixed queries with BM25 ranking."""
        trigram_query = self._build_trigram_query(query)
        if not trigram_query:
            return []

        scope_placeholders = ','.join('?' * len(scopes))
        params = [trigram_query] + list(scopes)

        if user_id:
            sql = f"""
                SELECT chunks.*, bm25(chunks_fts_trigram) as rank
                FROM chunks_fts_trigram
                JOIN chunks ON chunks.rowid = chunks_fts_trigram.rowid
                WHERE chunks_fts_trigram MATCH ?
                AND chunks.scope IN ({scope_placeholders})
                AND (chunks.scope = 'shared' OR chunks.user_id = ?)
                ORDER BY rank
                LIMIT ?
            """
            params.extend([user_id, limit])
        else:
            sql = f"""
                SELECT chunks.*, bm25(chunks_fts_trigram) as rank
                FROM chunks_fts_trigram
                JOIN chunks ON chunks.rowid = chunks_fts_trigram.rowid
                WHERE chunks_fts_trigram MATCH ?
                AND chunks.scope IN ({scope_placeholders})
                ORDER BY rank
                LIMIT ?
            """
            params.append(limit)

        try:
            rows = self.conn.execute(sql, params).fetchall()
            return [
                SearchResult(
                    path=row['path'],
                    start_line=row['start_line'],
                    end_line=row['end_line'],
                    score=self._bm25_rank_to_score(row['rank']),
                    snippet=self._truncate_text(row['text'], 500),
                    source=row['source'],
                    user_id=row['user_id']
                )
                for row in rows
            ]
        except Exception:
            from common.log import logger
            logger.warning("[MemoryStorage] _search_fts5_trigram failed, returning empty", exc_info=True)
            return []

    @staticmethod
    def _build_fts_query(raw_query: str) -> Optional[str]:
        """
        Build FTS5 query from raw text
        
        Works best for English and word-based languages.
        For CJK characters, LIKE search will be used as fallback.
        """
        # 提取单词（主要是英语单词和数字）
        tokens = re.findall(r'[A-Za-z0-9_]+', raw_query)
        if not tokens:
            return None
        
        # 给词元加引号以精确匹配
        quoted = [f'"{t}"' for t in tokens]
        # 使用 OR 连接，匹配更灵活
        return ' OR '.join(quoted)
    
    @staticmethod
    def _bm25_rank_to_score(rank: float) -> float:
        """Convert SQLite BM25 rank to a [0, 1) relevance score.

        SQLite's bm25() returns a non-positive float (0 or negative).
        More negative = more relevant.  max(0, rank) would clip every
        negative value to 0, making every score 1/(1+0) = 1.0 and
        destroying all ranking information.

        abs(rank) / (1 + abs(rank)) maps the absolute relevance magnitude
        to [0, 1): larger |rank| (stronger match) → score closer to 1.
        """
        if rank is None:
            return 0.0
        # 抬高到 0.3 下限，确保任何 FTS5 命中都必然超过常规的
        # min_score 阈值（默认 0.1）。否则小语料库中接近 0 的排名
        # 会算出 ≈0 的分数，从而被下游过滤掉。
        return 0.3 + 0.69 * (abs(rank) / (1.0 + abs(rank)))
    
    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        """Truncate text to max characters"""
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "..."
    
    @staticmethod
    def compute_hash(content: str) -> str:
        """Compute SHA256 hash of content"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
