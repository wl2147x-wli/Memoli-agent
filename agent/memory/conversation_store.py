"""
Conversation history persistence using SQLite.

Design:
- sessions table: per-session metadata (channel_type, last_active, msg_count)
- messages table: individual messages stored as JSON, append-only
- Pruning: age-based only (sessions not updated within N days are deleted)
- Thread-safe via a single in-process lock

Storage path: <agent workspace>/memory/long-term/index.db (shared with the
memory index)
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from common.log import logger


# ---------------------------------------------------------------------------
# 表结构
# ---------------------------------------------------------------------------

# 核心对话表结构。会话和消息是这份文件中不可替代的部分，
# 所以它们的创建必须始终成功，
# 本脚本中不应出现任何可能失败的可选逻辑。
_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT    PRIMARY KEY,
    channel_type      TEXT    NOT NULL DEFAULT '',
    title             TEXT    NOT NULL DEFAULT '',
    context_start_seq INTEGER NOT NULL DEFAULT 0,
    created_at        INTEGER NOT NULL,
    last_active       INTEGER NOT NULL,
    msg_count         INTEGER NOT NULL DEFAULT 0,
    pinned            INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT    NOT NULL,
    seq          INTEGER NOT NULL,
    role         TEXT    NOT NULL,
    content      TEXT    NOT NULL,
    created_at   INTEGER NOT NULL,
    extras       TEXT    NOT NULL DEFAULT '',
    UNIQUE (session_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_messages_session
    ON messages (session_id, seq);

CREATE INDEX IF NOT EXISTS idx_sessions_last_active
    ON sessions (last_active);
"""

# Runs 是同一文件中的辅助表，与核心表结构分开存放，这样
# 这里发生的任何问题——如存在同名的遗留表、升级只进行到一半——
# 只会让运行跟踪降级，而不会影响对话历史。
#
# 运行（run）是代理工作的一种可寻址、可持久化的单元：
# 委派出去的任务、生成的子代理或计划作业，都可以在发起它们的
# 那次调用返回之后，被重新查找到、恢复并汇报结果。
# 它与会话（正在和谁对话）、代理（由谁来做工作）
# 是不同的概念。
_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT    PRIMARY KEY,
    agent_id     TEXT    NOT NULL DEFAULT '',
    -- Reserved for the tenancy dimension; empty until per-user isolation lands,
    -- so filtering by owner is an additive query change rather than a schema one.
    user_id      TEXT    NOT NULL DEFAULT '',
    session_id   TEXT    NOT NULL DEFAULT '',
    -- The run that spawned this one (a delegation or subagent). Empty for a
    -- top-level run. Lets a whole delegation tree be walked from any node.
    parent_run_id TEXT   NOT NULL DEFAULT '',
    -- Free-form external work handle and where it came from. task_source is
    -- empty for a native CowAgent run; a non-empty value names the external
    -- system and task_id then addresses a work item within it. TEXT on purpose:
    -- it must hold external ids, never a foreign key into a table we own.
    task_id      TEXT    NOT NULL DEFAULT '',
    task_source  TEXT    NOT NULL DEFAULT '',
    status       TEXT    NOT NULL DEFAULT 'running',
    started_at   INTEGER NOT NULL,
    ended_at     INTEGER,
    error        TEXT    NOT NULL DEFAULT '',
    extras       TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_runs_session
    ON runs (session_id, started_at);

CREATE INDEX IF NOT EXISTS idx_runs_parent
    ON runs (parent_run_id);

CREATE INDEX IF NOT EXISTS idx_runs_task
    ON runs (task_source, task_id);
"""

# 迁移：为早前创建的数据库补充 channel_type 列。
_MIGRATION_ADD_CHANNEL_TYPE = """
ALTER TABLE sessions ADD COLUMN channel_type TEXT NOT NULL DEFAULT '';
"""

_MIGRATION_ADD_TITLE = """
ALTER TABLE sessions ADD COLUMN title TEXT NOT NULL DEFAULT '';
"""

_MIGRATION_ADD_CONTEXT_START_SEQ = """
ALTER TABLE sessions ADD COLUMN context_start_seq INTEGER NOT NULL DEFAULT 0;
"""

# 用户置顶的会话，始终排在会话列表的顶部。
_MIGRATION_ADD_PINNED = """
ALTER TABLE sessions ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;
"""

# 为每条消息的附件准备的通用 JSON sidecar（如 TTS 音频 URL，供将来使用）。
# 该字段始终可选——读取方必须容忍列缺失、内容为空或 JSON 无效。
_MIGRATION_ADD_MSG_EXTRAS = """
ALTER TABLE messages ADD COLUMN extras TEXT NOT NULL DEFAULT '';
"""

# 把每条消息归因到产生它的运行记录上，从而可以重建运行轨迹，
# 并把委派 / 子代理产生的轮次与各自的父运行关联起来。
# 在运行跟踪启用之前写入的消息，此字段为空。
_MIGRATION_ADD_MSG_RUN_ID = """
ALTER TABLE messages ADD COLUMN run_id TEXT NOT NULL DEFAULT '';
"""

DEFAULT_MAX_AGE_DAYS: int = 30


def _is_visible_user_message(content: Any) -> bool:
    """
    Return True when a user-role message represents actual user input
    (not an internal tool_result injected by the agent loop).
    """
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get("type") == "text"
            for b in content
        )
    return False


def _extract_display_text(content: Any) -> str:
    """
    Extract the human-readable text portion from a message content value.
    Returns an empty string for tool_use / tool_result blocks.
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        return "\n".join(p for p in parts if p).strip()
    return ""


# 写入会话的内部标记，供代理内部记账使用
# （调度程序注入的定时任务、自我演化撤销）。它们必须留在已存储的
# 内容里（LLM 会读取它们，例如查找可用于撤销的 backup_id），
# 但绝不能在聊天历史 UI 中原样展示给用户。
_SCHEDULED_DISPLAY_MARKERS = ("[SCHEDULED]", "Scheduled task")
_EVOLUTION_DISPLAY_MARKER = "[EVOLUTION]"


def _is_internal_user_marker(text: str) -> bool:
    """True if a user-turn text is an internal injection marker (hide from UI)."""
    t = (text or "").lstrip()
    return any(t.startswith(m) for m in _SCHEDULED_DISPLAY_MARKERS)


def _is_evolution_text(text: str) -> bool:
    """True if assistant text is a self-evolution summary (before cleaning)."""
    return (text or "").lstrip().startswith(_EVOLUTION_DISPLAY_MARKER)


def _clean_display_text(text: str) -> str:
    """Strip internal markers from assistant text for user-facing display.

    Removes a leading ``[EVOLUTION]`` tag and a trailing ``(backup_id: ...)``
    undo hint. The raw stored message is untouched, so undo + LLM context still
    work; only the rendered chat bubble is cleaned.
    """
    if not text:
        return text
    cleaned = text
    stripped = cleaned.lstrip()
    if stripped.startswith(_EVOLUTION_DISPLAY_MARKER):
        cleaned = stripped[len(_EVOLUTION_DISPLAY_MARKER):].lstrip()
    # 去掉消息末尾的 backup_id 撤销提示行，例如
    #   “（backup_id：20260607-...；要撤消，恢复此备份）”
    cleaned = re.sub(
        r"\n*\(backup_id:[^\)]*\)\s*$",
        "",
        cleaned,
    ).rstrip()
    return cleaned


def _extract_tool_calls(content: Any) -> List[Dict[str, Any]]:
    """
    Extract tool_use blocks from an assistant message content.
    Returns a list of {name, arguments} dicts (result filled in later).
    """
    if not isinstance(content, list):
        return []
    return [
        {"id": b.get("id", ""), "name": b.get("name", ""), "arguments": b.get("input", {})}
        for b in content
        if isinstance(b, dict) and b.get("type") == "tool_use"
    ]


def _extract_tool_results(content: Any) -> Dict[str, dict]:
    """
    Extract tool_result blocks from a user message, keyed by tool_use_id.
    Values are {"result": str, "is_error": bool}.
    """
    if not isinstance(content, list):
        return {}
    results = {}
    for b in content:
        if not isinstance(b, dict) or b.get("type") != "tool_result":
            continue
        tool_id = b.get("tool_use_id", "")
        result_content = b.get("content", "")
        if isinstance(result_content, list):
            result_content = "\n".join(
                rb.get("text", "") for rb in result_content
                if isinstance(rb, dict) and rb.get("type") == "text"
            )
        results[tool_id] = {"result": str(result_content), "is_error": bool(b.get("is_error", False))}
    return results


def _group_into_display_turns(
    rows: List[tuple],
    include_thinking: bool = True,
) -> List[Dict[str, Any]]:
    """
    Convert raw DB rows into display turns. Rows loaded for the web history
    include ``seq`` as their first field; older callers may still pass the
    legacy ``(role, content_json, created_at, extras)`` shape.

    One display turn = one visible user message  +  one merged assistant reply.
    All intermediate assistant messages (those carrying tool_use) and the final
    assistant text reply produced for the same user query are collapsed into a
    single assistant turn, exactly matching the live SSE rendering where tools
    and the final answer appear inside the same bubble.

    Grouping rules:
    - A visible user message starts a new group.
    - tool_result user messages are internal; their content is attached to the
      matching tool_use entry via tool_use_id and they never become own turns.
    - All assistant messages within a group are merged:
        * tool_use blocks → tool_calls list (result filled from tool_results)
        * text blocks → last non-empty text becomes the display content
    """
    # ------------------------------------------------------------------ #
    # 第 1 遍：将行分成组，每个组以可见的用户消息开头
    # ------------------------------------------------------------------ #
    # 组=（用户行|无，[后续行]）
    # user_row：（内容，创建时间）
    groups: List[tuple] = []
    cur_user: Optional[tuple] = None
    cur_rest: List[tuple] = []
    started = False

    for row in rows:
        if len(row) == 5:
            seq, role, raw_content, created_at, raw_extras = row
        else:
            seq = None
            role, raw_content, created_at, raw_extras = row
        try:
            content = json.loads(raw_content)
        except Exception:
            content = raw_content
        try:
            extras = json.loads(raw_extras) if raw_extras else {}
            if not isinstance(extras, dict):
                extras = {}
        except Exception:
            extras = {}

        if role == "user" and _is_visible_user_message(content):
            if started:
                groups.append((cur_user, cur_rest))
            cur_user = (content, created_at, extras, seq)
            cur_rest = []
            started = True
        else:
            cur_rest.append((role, content, created_at, extras, seq))

    if started:
        groups.append((cur_user, cur_rest))

    # ------------------------------------------------------------------ #
    # 第 2 步：为每一组构建展示轮次
    # ------------------------------------------------------------------ #
    turns: List[Dict[str, Any]] = []

    for user_row, rest in groups:
        # 用户轮次
        if user_row:
            content, created_at, _u_extras, user_seq = user_row
            text = _extract_display_text(content)
            # 隐藏内部注入的标记（调度程序 / 自我演化），
            # 用户就不会看到“[SCHEDULED] 自我演化”这类合成气泡；
            # 之后的助手回复仍然照常渲染。
            if text and not _is_internal_user_marker(text):
                turn = {"role": "user", "content": text, "created_at": created_at}
                if user_seq is not None:
                    turn["_seq"] = user_seq
                turns.append(turn)

        # 构建一个保留原始顺序的步骤列表：
        #   思考 → 内容 → 工具调用 → 内容 → ...
        steps: List[Dict[str, Any]] = []
        tool_results: Dict[str, str] = {}
        final_text = ""
        final_ts: Optional[int] = None
        final_seq: Optional[int] = None
        merged_extras: Dict[str, Any] = {}

        for role, content, created_at, extras, seq in rest:
            if role == "assistant" and isinstance(extras, dict):
                merged_extras.update(extras)
            if role == "user":
                tool_results.update(_extract_tool_results(content))
            elif role == "assistant":
                # 遍历内容块，以保留它们相互交错的顺序
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "thinking":
                            if not include_thinking:
                                continue
                            txt = block.get("thinking", "").strip()
                            if txt:
                                steps.append({"type": "thinking", "content": txt})
                        elif btype == "text":
                            txt = block.get("text", "").strip()
                            if txt:
                                steps.append({"type": "content", "content": txt})
                                final_text = txt
                        elif btype == "tool_use":
                            steps.append({
                                "type": "tool",
                                "id": block.get("id", ""),
                                "name": block.get("name", ""),
                                "arguments": block.get("input", {}),
                            })
                elif isinstance(content, str) and content.strip():
                    steps.append({"type": "content", "content": content.strip()})
                    final_text = content.strip()
                final_ts = created_at
                if seq is not None:
                    final_seq = seq

        # 将工具结果回填到对应的工具步骤上
        for step in steps:
            if step["type"] == "tool":
                tr = tool_results.get(step.get("id", ""), {})
                if not isinstance(tr, dict):
                    tr = {"result": tr}
                step["result"] = tr.get("result", "")
                step["is_error"] = tr.get("is_error", False)

        # 要在清理标记之前先识别出自我演化气泡，
        # 这样即便展示文本已清理干净，UI 仍能把它标注出来。
        is_evolution = _is_evolution_text(final_text)

        # 从面向用户的助手文本中清除内部标记。它同时作用于
        # 最终文本和每个内容步骤，因此渲染出的气泡
        # 显示的是干净文本，而入库的消息仍保留原标记。
        final_text = _clean_display_text(final_text)
        for step in steps:
            if step.get("type") == "content":
                step["content"] = _clean_display_text(step.get("content", ""))

        if steps or final_text:
            turn = {
                "role": "assistant",
                "content": final_text,
                "steps": steps,
                "created_at": final_ts or (user_row[1] if user_row else 0),
            }
            if is_evolution:
                turn["kind"] = "evolution"
            if merged_extras:
                turn["extras"] = merged_extras
            if final_seq is not None:
                turn["_seq"] = final_seq
            turns.append(turn)

    return turns


class ConversationStore:
    """
    SQLite-backed store for per-session conversation history.

    Usage:
        store = ConversationStore(db_path)
        store.append_messages("user_123", new_messages, channel_type="feishu")
        msgs = store.load_messages("user_123", max_turns=30)
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._lock = threading.RLock()  # 使用 RLock，便于支持可重入加锁
        self._schema_identity: tuple = ()
        # 确认 runs 表存在后即为 True。若它不存在，
        # 运行记账就会退化为空操作，因此绝不会破坏轮次
        # 或历史查询——runs 只是会话存储的辅助部分。
        self._runs_ready = False
        self._init_db()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def load_messages(
        self,
        session_id: str,
        max_turns: int = 30,
        with_authors: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Load the most recent messages for a session, for injection into the LLM.

        ALL message types (user text, assistant tool_use, tool_result) are returned
        in their original JSON form so the LLM can reconstruct the full context.

        max_turns is a *visible-turn* count: we count only user messages whose
        content is actual user text (not tool_result blocks).  This prevents
        tool-heavy sessions from exhausting the turn budget prematurely.

        Args:
            session_id: Unique session identifier.
            max_turns: Maximum number of visible user-assistant turns to keep.
            with_authors: Also report which Agent wrote each message, as an
                ``agent_id`` key. Off by default because the answer is only
                ever "the one Agent in this conversation"; a shared transcript
                is where it matters, and where an Agent reading back its own
                history would otherwise take a colleague's work for its own.

        Returns:
            Chronologically ordered list of message dicts (role, content).
        """
        with self._lock:
            conn = self._connect()
            try:
                # 按 context_start_seq 截取：只加载该边界处及其之后的消息
                ctx_row = conn.execute(
                    "SELECT context_start_seq FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                ctx_start = ctx_row[0] if ctx_row else 0

                columns = "seq, role, content" + (", extras" if with_authors else "")
                rows = conn.execute(
                    f"""
                    SELECT {columns}
                    FROM messages
                    WHERE session_id = ? AND seq >= ?
                    ORDER BY seq DESC
                    """,
                    (session_id, ctx_start),
                ).fetchall()
            finally:
                conn.close()

        if not rows:
            return []

        authors = {row[0]: self._author_of(row[3]) for row in rows} if with_authors else {}

        visible_turn_seqs: List[int] = []
        for seq, role, raw_content, *_ in rows:
            if role != "user":
                continue
            try:
                content = json.loads(raw_content)
            except Exception:
                content = raw_content
            if _is_visible_user_message(content):
                visible_turn_seqs.append(seq)

        if len(visible_turn_seqs) <= max_turns:
            cutoff_seq = None
        else:
            cutoff_seq = visible_turn_seqs[max_turns - 1]

        result = []
        for seq, role, raw_content, *_ in reversed(rows):
            if cutoff_seq is not None and seq < cutoff_seq:
                continue
            try:
                content = json.loads(raw_content)
            except Exception:
                content = raw_content
            # 去掉 thinking 块——它们入库只是为了给 UI 展示
            if role == "assistant" and isinstance(content, list):
                content = [b for b in content if b.get("type") != "thinking"]
            message = {"role": role, "content": content}
            if authors.get(seq):
                message["agent_id"] = authors[seq]
            result.append(message)
        return result

    @staticmethod
    def _author_of(raw_extras: Any) -> str:
        """The Agent stamped on a stored message, if any.

        Absent on every message written by a conversation's own Agent, which is
        all of them until somebody else is invited in.
        """
        if not raw_extras:
            return ""
        try:
            extras = json.loads(raw_extras) if isinstance(raw_extras, str) else raw_extras
        except ValueError:
            return ""
        if not isinstance(extras, dict):
            return ""
        agent_id = extras.get("agent_id")
        return agent_id if isinstance(agent_id, str) else ""

    def append_messages(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
        channel_type: str = "",
        create_if_missing: bool = True,
        run_id: Optional[str] = None,
    ) -> bool:
        """
        Append new messages to a session's history.

        Seq numbers continue from the session's current maximum, so
        concurrent callers on distinct sessions never collide.

        Args:
            session_id: Unique session identifier.
            messages: List of message dicts to append.
            channel_type: Source channel (e.g. "feishu", "web", "wechat").
                          Only written on session creation; ignored on update.
            create_if_missing: When False, do nothing if the session row is
                          gone. Callers that already stored the user turn use
                          this so a session deleted mid-run is not recreated
                          from the reply alone.
            run_id: The run these messages belong to. Falls back to the ambient
                          RuntimeIdentity's run id, so callers inside a run do
                          not have to thread it through. A per-message ``run_id``
                          key overrides it for that one message.

        Returns:
            True when the messages were written, False when the session was
            missing and ``create_if_missing`` is False.
        """
        if not messages:
            return False

        if run_id is None:
            from common.utils import current_agent_run_id
            run_id = current_agent_run_id() or ""

        now = int(time.time())
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    if not create_if_missing:
                        exists = conn.execute(
                            "SELECT 1 FROM sessions WHERE session_id = ?",
                            (session_id,),
                        ).fetchone()
                        if not exists:
                            return False

                    # INSERT OR IGNORE 在首次访问时创建会话行，
                    # UPDATE 则每次都刷新 last_active；
                    # 分两步执行即可避开需要 SQLite >= 3.24 的 upsert 写法。
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO sessions
                            (session_id, channel_type, created_at, last_active, msg_count)
                        VALUES (?, ?, ?, ?, 0)
                        """,
                        (session_id, channel_type, now, now),
                    )
                    conn.execute(
                        "UPDATE sessions SET last_active = ? WHERE session_id = ?",
                        (now, session_id),
                    )

                    # 确定本批次消息的起始序号。
                    row = conn.execute(
                        "SELECT COALESCE(MAX(seq), -1) FROM messages WHERE session_id = ?",
                        (session_id,),
                    ).fetchone()
                    next_seq = row[0] + 1

                    for msg in messages:
                        role = msg.get("role", "")
                        content = json.dumps(
                            msg.get("content", ""), ensure_ascii=False
                        )
                        extras_obj = msg.get("extras") or {}
                        extras = json.dumps(extras_obj, ensure_ascii=False) if extras_obj else ""
                        msg_run_id = str(msg.get("run_id") or run_id or "")
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO messages
                                (session_id, seq, role, content, created_at, extras, run_id)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (session_id, next_seq, role, content, now, extras, msg_run_id),
                        )
                        next_seq += 1

                    conn.execute(
                        """
                        UPDATE sessions
                        SET msg_count = (
                            SELECT COUNT(*) FROM messages WHERE session_id = ?
                        )
                        WHERE session_id = ?
                        """,
                        (session_id, session_id),
                    )

                    # 从第一条可见的用户消息自动生成标题
                    cur_title = conn.execute(
                        "SELECT title FROM sessions WHERE session_id = ?",
                        (session_id,),
                    ).fetchone()
                    if cur_title and not cur_title[0]:
                        for msg in messages:
                            if msg.get("role") == "user":
                                content = msg.get("content", "")
                                text = _extract_display_text(content)
                                if text:
                                    title = text[:50].split("\n")[0]
                                    conn.execute(
                                        "UPDATE sessions SET title = ? WHERE session_id = ?",
                                        (title, session_id),
                                    )
                                    break
                    return True
            finally:
                conn.close()

    def clear_context(self, session_id: str) -> int:
        """
        Set the context boundary to after the current last message.
        Messages before this boundary are still stored but excluded from LLM context.

        Returns the new context_start_seq value.
        """
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    row = conn.execute(
                        "SELECT COALESCE(MAX(seq), -1) FROM messages WHERE session_id = ?",
                        (session_id,),
                    ).fetchone()
                    new_start = row[0] + 1
                    conn.execute(
                        "UPDATE sessions SET context_start_seq = ? WHERE session_id = ?",
                        (new_start, session_id),
                    )
                    return new_start
            finally:
                conn.close()

    def get_context_start_seq(self, session_id: str) -> int:
        """Return the context_start_seq for a session (0 if not set)."""
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT context_start_seq FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                return row[0] if row else 0
            finally:
                conn.close()

    def get_latest_pair_seqs(self, session_id: str) -> Dict[str, Optional[int]]:
        """Return the seq numbers of the latest visible user message and the
        latest assistant message in a session.

        A "visible" user message is one whose content is real user text
        (not just a tool_result block), so tool-execution turns do not
        shadow the actual user query.

        Returns:
            Dict with keys ``user_seq`` and ``bot_seq``; either may be None
            when no matching message exists.
        """
        result: Dict[str, Optional[int]] = {"user_seq": None, "bot_seq": None}
        with self._lock:
            conn = self._connect()
            try:
                # 最新的助手消息（代价小：按 seq DESC 取一行即可）。
                row = conn.execute(
                    "SELECT seq FROM messages "
                    "WHERE session_id = ? AND role = 'assistant' "
                    "ORDER BY seq DESC LIMIT 1",
                    (session_id,),
                ).fetchone()
                if row:
                    result["bot_seq"] = int(row[0])

                # 最新可见的用户消息：扫描最近的用户行并
                # 跳过纯 tool_result 条目。
                rows = conn.execute(
                    "SELECT seq, content FROM messages "
                    "WHERE session_id = ? AND role = 'user' "
                    "ORDER BY seq DESC LIMIT 20",
                    (session_id,),
                ).fetchall()
                for seq, content_raw in rows:
                    try:
                        content = json.loads(content_raw)
                    except Exception:
                        result["user_seq"] = int(seq)
                        break
                    if isinstance(content, list):
                        has_text = any(
                            isinstance(b, dict) and b.get("type") == "text"
                            for b in content
                        )
                        has_tool_result = any(
                            isinstance(b, dict) and b.get("type") == "tool_result"
                            for b in content
                        )
                        if has_text and not has_tool_result:
                            result["user_seq"] = int(seq)
                            break
                    else:
                        result["user_seq"] = int(seq)
                        break
            finally:
                conn.close()
        return result

    def clear_session(self, session_id: str) -> None:
        """Delete all messages and the session record for a given session_id."""
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    conn.execute(
                        "DELETE FROM messages WHERE session_id = ?", (session_id,)
                    )
                    conn.execute(
                        "DELETE FROM sessions WHERE session_id = ?", (session_id,)
                    )
            finally:
                conn.close()

    def delete_message_pair(self, session_id: str, user_seq: int, delete_user: bool = True, cascade: bool = False) -> int:
        """Delete a user message and/or its corresponding assistant reply.

        The assistant reply is identified as all messages between user_seq
        and the next visible user message (or end of session).

        Args:
            session_id: Session identifier.
            user_seq: The seq number of the user message.
            delete_user: If True (default), delete the user message too.
                        If False, only delete assistant reply (for regenerate scenarios).
            cascade: If True, also delete all subsequent turns after this one.
                    Used by edit-message which removes this turn and everything after.

        Returns:
            Number of message rows deleted.
        """
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    # 验证这是一条用户消息
                    row = conn.execute(
                        "SELECT role FROM messages WHERE session_id = ? AND seq = ?",
                        (session_id, user_seq),
                    ).fetchone()
                    if not row or row[0] != "user":
                        return 0

                    if cascade:
                        # 从该消息起一直删除到会话结束
                        start_seq = user_seq if delete_user else user_seq + 1
                        end_seq_row = conn.execute(
                            "SELECT MAX(seq) FROM messages WHERE session_id = ?",
                            (session_id,),
                        ).fetchone()
                        end_seq = (end_seq_row[0] or user_seq) + 1
                    else:
                        # 找出下一条可见用户消息的 seq（纯 tool_result 不算）
                        # 分批查询，避免一次载入太多行
                        next_user_seq = None
                        batch_size = 100
                        offset = 0
                        while True:
                            batch = conn.execute(
                                """
                                SELECT seq, content FROM messages
                                WHERE session_id = ? AND seq > ? AND role = 'user'
                                ORDER BY seq ASC
                                LIMIT ? OFFSET ?
                                """,
                                (session_id, user_seq, batch_size, offset),
                            ).fetchall()
                            if not batch:
                                break
                            for seq, content in batch:
                                try:
                                    content_obj = json.loads(content)
                                except Exception:
                                    content_obj = content
                                if _is_visible_user_message(content_obj):
                                    next_user_seq = seq
                                    break
                            if next_user_seq is not None:
                                break
                            offset += batch_size

                        # 确定删除的结束边界
                        if next_user_seq is not None:
                            end_seq = next_user_seq
                        else:
                            end_seq_row = conn.execute(
                                "SELECT MAX(seq) FROM messages WHERE session_id = ?",
                                (session_id,),
                            ).fetchone()
                            end_seq = (end_seq_row[0] or user_seq) + 1

                        # 确定删除的起始边界
                        start_seq = user_seq if delete_user else user_seq + 1

                    # 删除 start_seq（含）到 end_seq（不含）之间的消息
                    cur = conn.execute(
                        "DELETE FROM messages WHERE session_id = ? AND seq >= ? AND seq < ?",
                        (session_id, start_seq, end_seq),
                    )
                    deleted = cur.rowcount

                    # 更新会话 msg_count
                    conn.execute(
                        """
                        UPDATE sessions
                        SET msg_count = (
                            SELECT COUNT(*) FROM messages WHERE session_id = ?
                        )
                        WHERE session_id = ?
                        """,
                        (session_id, session_id),
                    )

                    return deleted
            finally:
                conn.close()

    def prune_scheduled_messages(
        self,
        session_id: str,
        keep_last_n: int,
        markers: Optional[List[str]] = None,
    ) -> int:
        """
        Keep at most ``keep_last_n`` scheduler-injected user/assistant pairs in
        the session, deleting the older ones.

        A scheduler-injected pair is identified by a user message whose first
        text block starts with one of ``markers``; the immediately following
        assistant message (next seq) is treated as its paired output.

        Only scheduler-tagged messages are touched; regular user turns are
        never deleted. Safe to call repeatedly; no-op if nothing to prune.

        Args:
            session_id: Session to prune.
            keep_last_n: Maximum scheduler pairs to retain (must be >= 0).
            markers: Text prefixes that identify scheduler user messages.
                Defaults to ``["[SCHEDULED]", "Scheduled task"]`` so that
                pairs written by older versions are also recognised.

        Returns:
            Number of message rows deleted.
        """
        if keep_last_n < 0:
            keep_last_n = 0
        if markers is None:
            markers = ["[SCHEDULED]", "Scheduled task"]

        def _matches_marker(raw_content: str) -> bool:
            try:
                parsed = json.loads(raw_content)
            except Exception:
                parsed = raw_content
            text = _extract_display_text(parsed) if not isinstance(parsed, str) else parsed
            if not text:
                return False
            return any(text.startswith(m) for m in markers)

        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    """
                    SELECT seq, role, content
                    FROM messages
                    WHERE session_id = ?
                    ORDER BY seq ASC
                    """,
                    (session_id,),
                ).fetchall()

                # 找出调度器注入的消息对：每对形如 (user_seq, assistant_seq?)
                pairs: List[tuple] = []  # (user_seq、assistant_seq_or_None) 列表
                for idx, (seq, role, raw_content) in enumerate(rows):
                    if role != "user" or not _matches_marker(raw_content):
                        continue
                    assistant_seq = None
                    # 若紧邻的下一条消息是助手消息，就与之配成一对。
                    if idx + 1 < len(rows):
                        next_seq, next_role, _ = rows[idx + 1]
                        if next_role == "assistant":
                            assistant_seq = next_seq
                    pairs.append((seq, assistant_seq))

                if len(pairs) <= keep_last_n:
                    return 0

                to_delete_pairs = pairs[: len(pairs) - keep_last_n]
                seqs_to_delete: List[int] = []
                for user_seq, assistant_seq in to_delete_pairs:
                    seqs_to_delete.append(user_seq)
                    if assistant_seq is not None:
                        seqs_to_delete.append(assistant_seq)

                if not seqs_to_delete:
                    return 0

                placeholders = ",".join("?" * len(seqs_to_delete))
                with conn:
                    conn.execute(
                        f"DELETE FROM messages WHERE session_id = ? AND seq IN ({placeholders})",
                        (session_id, *seqs_to_delete),
                    )
                    conn.execute(
                        """
                        UPDATE sessions
                        SET msg_count = (
                            SELECT COUNT(*) FROM messages WHERE session_id = ?
                        )
                        WHERE session_id = ?
                        """,
                        (session_id, session_id),
                    )
                return len(seqs_to_delete)
            finally:
                conn.close()

    def cleanup_old_sessions(self, max_age_days: Optional[int] = None) -> int:
        """
        Delete sessions that have not been active within max_age_days.
        Web channel sessions are excluded — they are meant to be permanent.

        Args:
            max_age_days: Override the default retention period.

        Returns:
            Number of sessions deleted.
        """
        try:
            from config import conf
            max_age = max_age_days or conf().get(
                "conversation_max_age_days", DEFAULT_MAX_AGE_DAYS
            )
        except Exception:
            max_age = max_age_days or DEFAULT_MAX_AGE_DAYS

        cutoff = int(time.time()) - max_age * 86400
        deleted = 0

        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    stale = conn.execute(
                        "SELECT session_id FROM sessions "
                        "WHERE last_active < ? AND channel_type != 'web'",
                        (cutoff,),
                    ).fetchall()
                    for (sid,) in stale:
                        conn.execute(
                            "DELETE FROM messages WHERE session_id = ?", (sid,)
                        )
                        conn.execute(
                            "DELETE FROM sessions WHERE session_id = ?", (sid,)
                        )
                        deleted += 1
            finally:
                conn.close()

        if deleted:
            logger.info(f"[ConversationStore] Pruned {deleted} expired sessions")
        return deleted

    def attach_extras_to_last_assistant(
        self,
        session_id: str,
        extras: Dict[str, Any],
    ) -> Optional[int]:
        """
        Merge ``extras`` into the latest assistant message of a session.

        Used by post-processing (e.g. TTS) that needs to annotate an already
        persisted bot reply with attachments such as audio URLs.

        Returns the message seq that was updated, or ``None`` if no assistant
        message exists or the update could not be applied.
        """
        if not extras:
            return None
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT seq, extras FROM messages
                    WHERE session_id = ? AND role = 'assistant'
                    ORDER BY seq DESC LIMIT 1
                    """,
                    (session_id,),
                ).fetchone()
                if not row:
                    return None
                seq, raw = row
                try:
                    cur = json.loads(raw) if raw else {}
                    if not isinstance(cur, dict):
                        cur = {}
                except Exception:
                    cur = {}
                cur.update(extras)
                conn.execute(
                    "UPDATE messages SET extras = ? WHERE session_id = ? AND seq = ?",
                    (json.dumps(cur, ensure_ascii=False), session_id, seq),
                )
                conn.commit()
                return seq
            except Exception as e:
                logger.warning(f"[ConversationStore] attach_extras failed: {e}")
                return None
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # 运行记录：可寻址、可持久化的单元
    # ------------------------------------------------------------------

    @staticmethod
    def _run_row_to_dict(row: tuple) -> Dict[str, Any]:
        (
            run_id, agent_id, user_id, session_id, parent_run_id,
            task_id, task_source, status, started_at, ended_at, error, raw_extras,
        ) = row
        try:
            extras = json.loads(raw_extras) if raw_extras else {}
            if not isinstance(extras, dict):
                extras = {}
        except Exception:
            extras = {}
        return {
            "run_id": run_id,
            "agent_id": agent_id,
            "user_id": user_id,
            "session_id": session_id,
            "parent_run_id": parent_run_id,
            "task_id": task_id,
            "task_source": task_source,
            "status": status,
            "started_at": started_at,
            "ended_at": ended_at,
            "error": error,
            "extras": extras,
        }

    _RUN_COLUMNS = (
        "run_id, agent_id, user_id, session_id, parent_run_id, "
        "task_id, task_source, status, started_at, ended_at, error, extras"
    )

    def create_run(
        self,
        run_id: str,
        *,
        agent_id: str = "",
        user_id: str = "",
        session_id: str = "",
        parent_run_id: str = "",
        task_id: str = "",
        task_source: str = "",
        status: str = "running",
        extras: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Record the start of a run. Idempotent: a second call with the same
        run_id is ignored so a retried entry point does not duplicate the row.

        Returns True when a new row was written, False when it already existed.
        """
        if not run_id:
            raise ValueError("run_id is required")
        if not self._runs_ready:
            return False
        now = int(time.time())
        extras_json = (
            json.dumps(extras, ensure_ascii=False) if extras else ""
        )
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    cur = conn.execute(
                        """
                        INSERT OR IGNORE INTO runs
                            (run_id, agent_id, user_id, session_id, parent_run_id,
                             task_id, task_source, status, started_at, ended_at,
                             error, extras)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, '', ?)
                        """,
                        (
                            run_id, agent_id, user_id, session_id, parent_run_id,
                            task_id, task_source, status, now, extras_json,
                        ),
                    )
                    return cur.rowcount > 0
            finally:
                conn.close()

    def finish_run(
        self,
        run_id: str,
        status: str = "done",
        error: str = "",
        extras: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Mark a run finished (or failed). Sets ended_at and, when given,
        merges ``extras`` into the stored sidecar. Returns True if the run
        existed.
        """
        if not run_id or not self._runs_ready:
            return False
        now = int(time.time())
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    if extras:
                        row = conn.execute(
                            "SELECT extras FROM runs WHERE run_id = ?", (run_id,)
                        ).fetchone()
                        if row is None:
                            return False
                        try:
                            cur_extras = json.loads(row[0]) if row[0] else {}
                            if not isinstance(cur_extras, dict):
                                cur_extras = {}
                        except Exception:
                            cur_extras = {}
                        cur_extras.update(extras)
                        extras_json = json.dumps(cur_extras, ensure_ascii=False)
                        cur = conn.execute(
                            """
                            UPDATE runs
                            SET status = ?, error = ?, ended_at = ?, extras = ?
                            WHERE run_id = ?
                            """,
                            (status, error, now, extras_json, run_id),
                        )
                    else:
                        cur = conn.execute(
                            """
                            UPDATE runs
                            SET status = ?, error = ?, ended_at = ?
                            WHERE run_id = ?
                            """,
                            (status, error, now, run_id),
                        )
                    return cur.rowcount > 0
            finally:
                conn.close()

    def update_run_extras(self, run_id: str, extras: Dict[str, Any]) -> bool:
        """Merge keys into a run's sidecar without touching its lifecycle.

        Lets an observer attach a payload to a run it did not execute, so the
        status stays owned by whoever actually ran the work. Returns True if
        the run existed.
        """
        if not run_id or not extras or not self._runs_ready:
            return False
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    row = conn.execute(
                        "SELECT extras FROM runs WHERE run_id = ?", (run_id,)
                    ).fetchone()
                    if row is None:
                        return False
                    try:
                        merged = json.loads(row[0]) if row[0] else {}
                        if not isinstance(merged, dict):
                            merged = {}
                    except Exception:
                        merged = {}
                    merged.update(extras)
                    conn.execute(
                        "UPDATE runs SET extras = ? WHERE run_id = ?",
                        (json.dumps(merged, ensure_ascii=False), run_id),
                    )
                    return True
            finally:
                conn.close()

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return a single run by id, or None."""
        if not run_id or not self._runs_ready:
            return None
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    f"SELECT {self._RUN_COLUMNS} FROM runs WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
            finally:
                conn.close()
        return self._run_row_to_dict(row) if row else None

    def list_runs(
        self,
        session_id: Optional[str] = None,
        parent_run_id: Optional[str] = None,
        task_source: Optional[str] = None,
        task_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List runs, newest first, filtered by any combination of the given
        dimensions. ``parent_run_id=''`` selects top-level runs only.
        """
        if not self._runs_ready:
            return []
        clauses: List[str] = []
        params: List[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if parent_run_id is not None:
            clauses.append("parent_run_id = ?")
            params.append(parent_run_id)
        if task_source is not None:
            clauses.append("task_source = ?")
            params.append(task_source)
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(1, limit))
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    f"SELECT {self._RUN_COLUMNS} FROM runs {where} "
                    "ORDER BY started_at DESC, run_id DESC LIMIT ?",
                    tuple(params),
                ).fetchall()
            finally:
                conn.close()
        return [self._run_row_to_dict(r) for r in rows]

    def load_history_page(
        self,
        session_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """
        Load a page of conversation history for UI display, grouped into turns.

        Each "turn" maps to one of:
          - A user message (role="user", content=str)
          - An assistant message (role="assistant", content=str,
            tool_calls=[{name, arguments, result}] when tools were used)

        Internal tool_result user messages are merged into the preceding
        assistant entry's tool_calls list and never appear as standalone items.

        Pages are numbered from 1 (most recent).  Messages within a page are
        returned in chronological order.

        Returns:
            {
                "messages": [
                    {
                        "role": "user" | "assistant",
                        "content": str,
                        "tool_calls": [...],   # assistant only, may be []
                        "created_at": int,
                    },
                    ...
                ],
                "total": <visible turn count>,
                "page": <current page>,
                "page_size": <page_size>,
                "has_more": bool,
            }
        """
        page = max(1, page)
        with self._lock:
            conn = self._connect()
            try:
                ctx_row = conn.execute(
                    "SELECT context_start_seq FROM sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
                ctx_start = ctx_row[0] if ctx_row else 0

                # extras 列是后续通过迁移加入的，需兼容没有该列的旧数据库：
                # 出错时回退到不含 extras 的查询，用空字符串兜底。
                try:
                    rows = conn.execute(
                        """
                        SELECT seq, role, content, created_at, extras
                        FROM messages
                        WHERE session_id = ?
                        ORDER BY seq ASC
                        """,
                        (session_id,),
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = [
                        (seq, role, content, created_at, "")
                        for (seq, role, content, created_at) in conn.execute(
                            """
                            SELECT seq, role, content, created_at
                            FROM messages
                            WHERE session_id = ?
                            ORDER BY seq ASC
                            """,
                            (session_id,),
                        ).fetchall()
                    ]
            finally:
                conn.close()

        # 组装展示轮次时要尊重当前的 enable_thinking 开关，
        # 因此把它关掉后，之前保存的 thinking 块也会一并隐藏。
        try:
            from config import conf
            include_thinking = bool(conf().get("enable_thinking", False))
        except Exception:
            include_thinking = False

        visible = _group_into_display_turns(rows, include_thinking=include_thinking)

        total = len(visible)
        offset = (page - 1) * page_size
        page_items = list(reversed(visible))[offset: offset + page_size]
        page_items = list(reversed(page_items))

        return {
            "messages": page_items,
            "context_start_seq": ctx_start,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": offset + page_size < total,
        }

    def list_sessions(
        self,
        channel_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """
        List sessions with pinned ones first, then last_active DESC, with an
        optional channel_type filter.

        Pinned sessions sort ahead of everything else rather than only ahead of
        the rows on the same page, so a pin still reaches the top of the list
        when the conversation is old enough to sit several pages down.

        Returns:
            {
                "sessions": [{session_id, title, created_at, last_active,
                              msg_count, pinned}, ...],
                "total": int,
                "page": int,
                "page_size": int,
                "has_more": bool,
            }
        """
        page = max(1, page)
        with self._lock:
            conn = self._connect()
            try:
                if channel_type:
                    total = conn.execute(
                        "SELECT COUNT(*) FROM sessions WHERE channel_type = ?",
                        (channel_type,),
                    ).fetchone()[0]
                    rows = conn.execute(
                        """
                        SELECT session_id, title, created_at, last_active, msg_count, pinned
                        FROM sessions
                        WHERE channel_type = ?
                        ORDER BY pinned DESC, last_active DESC
                        LIMIT ? OFFSET ?
                        """,
                        (channel_type, page_size, (page - 1) * page_size),
                    ).fetchall()
                else:
                    total = conn.execute(
                        "SELECT COUNT(*) FROM sessions",
                    ).fetchone()[0]
                    rows = conn.execute(
                        """
                        SELECT session_id, title, created_at, last_active, msg_count, pinned
                        FROM sessions
                        ORDER BY pinned DESC, last_active DESC
                        LIMIT ? OFFSET ?
                        """,
                        (page_size, (page - 1) * page_size),
                    ).fetchall()
            finally:
                conn.close()

        sessions = [
            {
                "session_id": r[0],
                "title": r[1],
                "created_at": r[2],
                "last_active": r[3],
                "msg_count": r[4],
                "pinned": bool(r[5]),
            }
            for r in rows
        ]
        return {
            "sessions": sessions,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": (page - 1) * page_size + page_size < total,
        }

    def rename_session(self, session_id: str, title: str) -> bool:
        """Update the title of a session. Returns True if the session existed."""
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    cur = conn.execute(
                        "UPDATE sessions SET title = ? WHERE session_id = ?",
                        (title, session_id),
                    )
                    return cur.rowcount > 0
            finally:
                conn.close()

    def set_pinned(self, session_id: str, pinned: bool) -> bool:
        """Pin or unpin a session. Returns True if the session existed."""
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    cur = conn.execute(
                        "UPDATE sessions SET pinned = ? WHERE session_id = ?",
                        (1 if pinned else 0, session_id),
                    )
                    return cur.rowcount > 0
            finally:
                conn.close()

    def list_session_ids(self, channel_type: Optional[str] = None) -> List[str]:
        """Every session id, optionally filtered by channel.

        One cheap single-column scan, used to work out how many distinct project
        spaces are actually in play without paging through full session rows.
        """
        with self._lock:
            conn = self._connect()
            try:
                if channel_type:
                    rows = conn.execute(
                        "SELECT session_id FROM sessions WHERE channel_type = ?",
                        (channel_type,),
                    ).fetchall()
                else:
                    rows = conn.execute("SELECT session_id FROM sessions").fetchall()
            finally:
                conn.close()
        return [r[0] for r in rows]

    def get_stats(self) -> Dict[str, Any]:
        """Return basic stats keyed by channel_type, for monitoring."""
        with self._lock:
            conn = self._connect()
            try:
                total_sessions = conn.execute(
                    "SELECT COUNT(*) FROM sessions"
                ).fetchone()[0]
                total_messages = conn.execute(
                    "SELECT COUNT(*) FROM messages"
                ).fetchone()[0]
                by_channel = conn.execute(
                    """
                    SELECT channel_type, COUNT(*) as cnt
                    FROM sessions
                    GROUP BY channel_type
                    ORDER BY cnt DESC
                    """
                ).fetchall()
                return {
                    "total_sessions": total_sessions,
                    "total_messages": total_messages,
                    "by_channel": {row[0] or "unknown": row[1] for row in by_channel},
                }
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # 内部辅助函数
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._raw_connect()
        try:
            # 先建核心表，且不做保护：如果连这些表都建不出来，
            # 说明存储确实不可用，此时应让错误直接暴露出来。
            conn.executescript(_DDL)
            conn.commit()
            self._migrate(conn)
            # runs 表属于辅助功能，其建表过程被单独隔离，因此遗留表、
            # 未完成的升级或其它意外都只会让运行跟踪降级，
            # 而不会把对话历史拉下线。
            self._init_runs(conn)
        finally:
            conn.close()
        self._schema_identity = self._db_identity()

    def _init_runs(self, conn: sqlite3.Connection) -> None:
        """Create the runs table without ever risking the core schema."""
        try:
            self._retire_incompatible_runs_table(conn)
            conn.executescript(_RUNS_DDL)
            conn.commit()
            self._runs_ready = True
        except Exception as e:
            self._runs_ready = False
            logger.warning(
                f"[ConversationStore] Run tracking unavailable ({e}); "
                "conversation history is unaffected"
            )
            try:
                conn.rollback()
            except Exception:
                pass

    def _retire_incompatible_runs_table(self, conn: sqlite3.Connection) -> None:
        """Move aside a pre-existing ``runs`` table that predates this schema.

        An earlier, since-removed feature shipped a differently shaped ``runs``
        table in the same file. Its columns do not match the one the current
        code owns, so ``CREATE TABLE IF NOT EXISTS`` leaves the old table in
        place and a later ``CREATE INDEX`` on a column it lacks aborts the whole
        init script -- which takes every conversation query down with it. The
        old table is renamed rather than dropped so its rows stay recoverable,
        and the marker column check makes this a no-op on both the current
        schema and a database that never had the legacy table.
        """
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'"
            ).fetchone()
            if not exists:
                return
            cols = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
            if "task_source" in cols:
                return
            backup = "runs_legacy_backup"
            # 绝不覆盖更早的备份：若 runs_legacy_backup 已被占用，
            # 就换用带时间戳的名字来存放旧表。
            if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (backup,),
            ).fetchone():
                backup = f"runs_legacy_backup_{int(time.time())}"
            # 否则旧表上的索引会与新的建表 DDL
            # 将要创建的索引相互冲突。
            for (idx_name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='runs' AND name NOT LIKE 'sqlite_%'"
            ).fetchall():
                conn.execute(f'DROP INDEX IF EXISTS "{idx_name}"')
            conn.execute(f"ALTER TABLE runs RENAME TO {backup}")
            conn.commit()
            logger.warning(
                "[ConversationStore] Renamed a legacy runs table to "
                f"{backup}; its rows are preserved there"
            )
        except Exception as e:
            logger.warning(
                f"[ConversationStore] Could not retire legacy runs table: {e}"
            )

    def _db_identity(self) -> tuple:
        """Identify the physical file behind _db_path, or () when it is missing."""
        try:
            st = self._db_path.stat()
        except OSError:
            return ()
        return (st.st_dev, st.st_ino)

    def _ensure_schema(self) -> None:
        """Recreate the conversation tables when the shared DB file was swapped.

        The long-term memory index lives in the same file and may quarantine and
        replace it on corruption. Without this check, every later query would
        keep failing with "no such table: sessions" for the whole process
        lifetime, so new messages would silently stop being persisted.
        """
        if self._db_identity() == self._schema_identity:
            return
        logger.warning(
            "[ConversationStore] Shared DB file was replaced; recreating conversation schema"
        )
        self._init_db()

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Apply incremental schema migrations on existing databases."""
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        if "channel_type" not in cols:
            try:
                conn.execute(_MIGRATION_ADD_CHANNEL_TYPE)
                conn.commit()
                logger.info("[ConversationStore] Migrated: added channel_type column")
            except Exception as e:
                logger.warning(f"[ConversationStore] Migration failed: {e}")
        if "title" not in cols:
            try:
                conn.execute(_MIGRATION_ADD_TITLE)
                conn.commit()
                logger.info("[ConversationStore] Migrated: added title column")
            except Exception as e:
                logger.warning(f"[ConversationStore] Migration (title) failed: {e}")
        if "context_start_seq" not in cols:
            try:
                conn.execute(_MIGRATION_ADD_CONTEXT_START_SEQ)
                conn.commit()
                logger.info("[ConversationStore] Migrated: added context_start_seq column")
            except Exception as e:
                logger.warning(f"[ConversationStore] Migration (context_start_seq) failed: {e}")
        if "pinned" not in cols:
            try:
                conn.execute(_MIGRATION_ADD_PINNED)
                conn.commit()
                logger.info("[ConversationStore] Migrated: added pinned column")
            except Exception as e:
                logger.warning(f"[ConversationStore] Migration (pinned) failed: {e}")

        msg_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "extras" not in msg_cols:
            try:
                conn.execute(_MIGRATION_ADD_MSG_EXTRAS)
                conn.commit()
                logger.info("[ConversationStore] Migrated: added messages.extras column")
            except Exception as e:
                logger.warning(f"[ConversationStore] Migration (extras) failed: {e}")
        if "run_id" not in msg_cols:
            try:
                conn.execute(_MIGRATION_ADD_MSG_RUN_ID)
                conn.commit()
                logger.info("[ConversationStore] Migrated: added messages.run_id column")
            except Exception as e:
                logger.warning(f"[ConversationStore] Migration (run_id) failed: {e}")

    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            self._ensure_schema()
        return self._raw_connect()

    def _raw_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------

_store_instance: Optional[ConversationStore] = None
_store_instances: Dict[str, ConversationStore] = {}
_store_lock = threading.RLock()


def _resolve_store_path(workspace_root=None) -> Path:
    if workspace_root is None:
        try:
            from agent.memory.config import get_default_memory_config
            return get_default_memory_config().get_db_path().resolve()
        except Exception:
            from common.utils import expand_path
            return (
                Path(expand_path("~/cow")) / "memory" / "long-term" / "index.db"
            ).resolve()
    from agent.memory.config import MemoryConfig
    from common.utils import expand_path
    workspace = Path(expand_path(str(workspace_root))).resolve()
    return MemoryConfig(workspace_root=str(workspace)).get_db_path().resolve()


def get_conversation_store(workspace_root=None) -> ConversationStore:
    """
    Return the ConversationStore for one complete agent workspace.

    Reuses that workspace's long-term memory database, keeping one SQLite file
    per agent at ``<workspace>/memory/long-term/index.db``.
    The conversation tables (sessions / messages) are separate from the
    memory tables (memory_chunks / file_metadata). Omitting ``workspace_root``
    preserves the original single-agent behaviour.
    """
    global _store_instance
    db_path = _resolve_store_path(workspace_root)
    key = str(db_path)
    store = _store_instances.get(key)
    if store is not None:
        if workspace_root is None:
            _store_instance = store
        return store

    with _store_lock:
        store = _store_instances.get(key)
        if store is None:
            store = ConversationStore(db_path)
            _store_instances[key] = store
            logger.debug(f"[ConversationStore] Using workspace DB at: {db_path}")
        if workspace_root is None:
            _store_instance = store
        return store


def clear_conversation_store_cache() -> None:
    """Forget cached store objects. Intended for config reloads and tests."""
    global _store_instance
    with _store_lock:
        _store_instances.clear()
        _store_instance = None
