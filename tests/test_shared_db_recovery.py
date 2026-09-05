# 编码：utf-8
"""
Regression tests for conversation history surviving memory-index recovery.

`ConversationStore` (sessions / messages) and `MemoryStorage` (chunks / files /
FTS5) share a single SQLite file, `memory/long-term/index.db`. Only the memory
side is re-derivable from the workspace, so recovering it must never take the
conversation history down with it — the failure mode being pinned here is
"no such table: sessions" after the memory index repaired itself.
"""
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.memory.conversation_store import ConversationStore
from agent.memory.storage import MemoryChunk, MemoryStorage


class TestSharedDbRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "index.db"
        # 这些案例故意损坏数据库。他们的恢复日志是
        # 与真实事件无法区分，并且 pytest 共享 run.log
        # 与正在运行的应用程序一起使用，因此请将其保留在文件之外。
        self._log = logging.getLogger("log")
        self._log_level = self._log.level
        self._log.setLevel(logging.CRITICAL + 1)

    def tearDown(self):
        self._log.setLevel(self._log_level)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- 助手 -------------------------------------------------------

    def _store_with_history(self) -> ConversationStore:
        store = ConversationStore(self.db)
        store.append_messages(
            "s1",
            [{"role": "user", "content": "hello"},
             {"role": "assistant", "content": "hi"}],
            channel_type="web",
        )
        return store

    def _memory_with_chunk(self) -> MemoryStorage:
        storage = MemoryStorage(self.db)
        storage.save_chunk(MemoryChunk(
            id="c1", user_id=None, scope="shared", source="memory",
            path="a.md", start_line=1, end_line=1, text="hello world",
            embedding=None, hash="h1",
        ))
        storage.conn.commit()
        return storage

    def _quarantined(self):
        return [p.name for p in self.tmp.iterdir() if ".corrupt-" in p.name]

    # -- 测试 ---------------------------------------------------------

    def test_damaged_fts5_index_does_not_drop_conversation_history(self):
        """Since SQLite 3.44 integrity_check also validates FTS5 content, so a
        stale search index reports as a failure. It must be rebuilt in place."""
        store = self._store_with_history()
        storage = self._memory_with_chunk()
        storage.close()

        raw = sqlite3.connect(self.db)
        raw.execute(
            "DELETE FROM chunks_fts_data WHERE id=(SELECT MAX(id) FROM chunks_fts_data)"
        )
        raw.commit()
        self.assertNotEqual(
            raw.execute("PRAGMA integrity_check").fetchone()[0], "ok"
        )
        raw.close()

        recovered = MemoryStorage(self.db)
        self.assertEqual(
            recovered.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok"
        )
        self.assertEqual(
            recovered.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0], 1
        )
        recovered.close()

        self.assertEqual(len(store.load_messages("s1")), 2)
        self.assertEqual(self._quarantined(), [])

    def test_corrupt_database_is_quarantined_not_deleted(self):
        store = ConversationStore(self.db)
        for i in range(300):
            store.append_messages(
                f"s{i}", [{"role": "user", "content": "x" * 400}], channel_type="web"
            )
        MemoryStorage(self.db).close()
        sqlite3.connect(self.db).execute("PRAGMA journal_mode=DELETE")

        with open(self.db, "r+b") as f:
            f.seek(4096 * 3)
            f.write(b"\x00" * 4096)

        MemoryStorage(self.db).close()
        self.assertEqual(len(self._quarantined()), 1)

    def test_unreadable_database_is_quarantined_not_deleted(self):
        self._store_with_history()
        MemoryStorage(self.db).close()

        with open(self.db, "r+b") as f:
            f.seek(0)
            f.write(b"GARBAGE!" * 2)

        MemoryStorage(self.db).close()
        self.assertEqual(len(self._quarantined()), 1)

    def test_store_recreates_schema_when_db_file_is_replaced(self):
        """A replaced file used to leave the process-wide store permanently
        broken, silently dropping every message for the rest of its lifetime."""
        store = self._store_with_history()

        for name in ("", "-wal", "-shm"):
            Path(f"{self.db}{name}").unlink(missing_ok=True)
        MemoryStorage(self.db).close()  # 仅使用内存表重新创建文件

        store.append_messages(
            "s2", [{"role": "user", "content": "after"}], channel_type="web"
        )
        self.assertEqual(len(store.load_messages("s2")), 1)
        self.assertEqual(store.list_sessions()["total"], 1)

    def test_transient_error_is_not_treated_as_corruption(self):
        """sqlite3.OperationalError subclasses DatabaseError, so "database is
        locked" must not be mistaken for corruption."""
        self._store_with_history()
        MemoryStorage(self.db).close()

        calls = {"n": 0}

        class LockedOnce(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                # 检查编译指示；运行哪一个是一种性能选择，
                # 这就是关于它的失败如何分类。
                if sql.startswith("PRAGMA ") and sql.endswith("_check") and calls["n"] == 0:
                    calls["n"] += 1
                    raise sqlite3.OperationalError("database is locked")
                return super().execute(sql, *args, **kwargs)

        real_connect = sqlite3.connect

        def connect_locked(*args, **kwargs):
            kwargs["factory"] = LockedOnce
            return real_connect(*args, **kwargs)

        with unittest.mock.patch("sqlite3.connect", connect_locked):
            storage = MemoryStorage(self.db)

        self.assertEqual(calls["n"], 1)
        self.assertEqual(self._quarantined(), [])
        self.assertEqual(
            storage.conn.execute(
                "SELECT COUNT(*) FROM sessions"
            ).fetchone()[0], 1
        )
        storage.close()


class TestTrigramUpdateTrigger(unittest.TestCase):
    """The trigram FTS5 index must survive updates to an existing chunk.

    External-content FTS5 corrupts ("database disk image is malformed") when an
    UPDATE trigger rewrites the row with a bare "UPDATE ... SET" instead of the
    delete+insert pattern. These cases pin the fix and its migration.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "index.db"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _chunk(self, text: str, embedding=None) -> MemoryChunk:
        return MemoryChunk(
            id="c1", user_id=None, scope="shared", source="memory",
            path="a.md", start_line=1, end_line=1, text=text,
            embedding=embedding, hash="h",
        )

    def test_updating_chunk_keeps_trigram_index_healthy(self):
        storage = MemoryStorage(self.db)
        if not storage.trigram_fts5_available:
            self.skipTest("trigram FTS5 unavailable in this SQLite build")
        storage.save_chunk(self._chunk("人工智能教程"))
        # 使用旧触发器会引发“数据库磁盘映像格式错误”。
        storage.save_chunk(self._chunk("机器学习笔记"))
        self.assertEqual(
            [r.path for r in storage.search_keyword("机器学习")], ["a.md"]
        )
        # 更新后旧令牌必须从索引中消失。
        self.assertEqual(storage.search_keyword("人工智能教程"), [])
        storage.close()

    def test_legacy_update_trigger_is_migrated_on_open(self):
        storage = MemoryStorage(self.db)
        if not storage.trigram_fts5_available:
            self.skipTest("trigram FTS5 unavailable in this SQLite build")
        storage.save_chunk(self._chunk("深度学习入门"))
        storage.close()

        # 降级到旧有错误的触发器以模拟旧数据库。
        conn = sqlite3.connect(str(self.db))
        conn.execute("DROP TRIGGER IF EXISTS chunks_trigram_au")
        conn.execute(
            "CREATE TRIGGER chunks_trigram_au AFTER UPDATE ON chunks BEGIN "
            "UPDATE chunks_fts_trigram SET text=new.text, id=new.id, "
            "user_id=new.user_id, path=new.path, source=new.source, "
            "scope=new.scope WHERE rowid=new.rowid; END"
        )
        conn.commit()
        conn.close()

        storage = MemoryStorage(self.db)
        trigger_sql = storage.conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='chunks_trigram_au'"
        ).fetchone()[0]
        self.assertNotIn("UPDATE chunks_fts_trigram", trigger_sql)
        # 现在更新不会损坏索引。
        storage.save_chunk(self._chunk("强化学习进阶"))
        self.assertEqual(
            [r.path for r in storage.search_keyword("强化学习")], ["a.md"]
        )
        self.assertEqual(storage.search_keyword("深度学习入门"), [])
        storage.close()


if __name__ == "__main__":
    unittest.main()
