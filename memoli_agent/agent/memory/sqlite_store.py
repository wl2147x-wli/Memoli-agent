"""证据化个人记忆的 SQLite 存储与检索。"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from memoli_agent.agent.memory.models import (
    CardProjectionKey,
    EvidenceRef,
    MemoryCard,
    MemoryCardVersion,
    MemoryIndexJob,
    MemoryIndexSource,
    MemoryItem,
    MemoryMutation,
    MemoryQuery,
    MemoryQueryResult,
    MemoryScope,
)

_SCHEMA_VERSION = 3
_LIVE_STATUSES = ("candidate", "active", "approved", "frozen")
_SENSITIVITY = {"public": 0, "private": 1, "sensitive": 2}
_VALID_STATUS = {
    "candidate",
    "active",
    "approved",
    "frozen",
    "superseded",
    "rejected",
    "deleted",
}


class SQLiteMemoryStore:
    """append-only claim、版本化 card 及其检索索引。"""

    def __init__(self, database: str | Path, *, max_cjk_ngram: int = 3) -> None:
        self.database = str(database)
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        self.max_cjk_ngram = max_cjk_ngram
        self._connection = sqlite3.connect(self.database)
        self._connection.row_factory = sqlite3.Row
        self.fts_available = False
        self._closed = False
        try:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._initialize()
        except Exception:
            self._connection.close()
            self._closed = True
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._connection.close()

    def __enter__(self) -> SQLiteMemoryStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def append_claim(
        self, request: MemoryMutation, *, _manage_transaction: bool = True
    ) -> MemoryItem:
        """正式 active/frozen 写入必须关联可审计依据。"""

        content = request.content.strip()
        if not content:
            raise ValueError("记忆内容不能为空。")
        if request.status not in _VALID_STATUS:
            raise ValueError(f"无效记忆状态：{request.status}")
        if request.status in {"active", "frozen"} and not self._has_write_basis(
            request
        ):
            raise PermissionError("正式记忆必须关联显式用户消息、人工主体或批准批次。")
        normalized = _normalize(content)
        content_hash = hashlib.sha256(
            f"{request.scope.kind}:{request.scope.identifier}:{normalized}".encode()
        ).hexdigest()
        if _manage_transaction:
            self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._connection.execute(
                "SELECT * FROM claims WHERE scope_kind=? AND scope_id=? "
                "AND content_hash=? AND status IN "
                "('candidate','active','approved','frozen')",
                (request.scope.kind, request.scope.identifier, content_hash),
            ).fetchone()
            if existing is not None:
                self._enqueue_index_job("claim", existing["claim_id"], content_hash)
                if _manage_transaction:
                    self._connection.commit()
                return self._claim_item(existing, "exact-hash")

            claim_id = f"clm_{uuid.uuid4().hex}"
            created_at = datetime.now(UTC)
            self._connection.execute(
                """
                INSERT INTO claims(
                    claim_id, content, normalized_content, content_hash, source,
                    explicitness, scope_kind, scope_id, sensitivity, status,
                    valid_from, valid_to, created_at, subject, card_kind, importance
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    content,
                    normalized,
                    content_hash,
                    request.source,
                    request.explicitness,
                    request.scope.kind,
                    request.scope.identifier,
                    request.sensitivity,
                    request.status,
                    _iso(request.valid_from),
                    _iso(request.valid_to),
                    created_at.isoformat(),
                    request.subject.strip() or "general",
                    request.card_kind.strip() or "profile",
                    max(0.0, min(float(request.importance), 1.0)),
                ),
            )
            evidence = request.evidence or self._metadata_evidence(request.metadata)
            for ref in evidence:
                self._insert_evidence(claim_id, ref, created_at.isoformat())
            self._insert_claim_search(claim_id, content)
            self._enqueue_index_job("claim", claim_id, content_hash)
            self._enqueue_card_projection(
                request.scope,
                request.subject.strip() or "general",
                request.card_kind.strip() or "profile",
            )
            self._record_revision("claim", claim_id, "create", request.source)
            if _manage_transaction:
                self._connection.commit()
        except Exception:
            if _manage_transaction:
                self._connection.rollback()
            raise
        row = self._connection.execute(
            "SELECT * FROM claims WHERE claim_id = ?", (claim_id,)
        ).fetchone()
        assert row is not None
        return self._claim_item(row, "explicit-write")

    def import_legacy_claims(
        self,
        entries: list[tuple[str, str]],
        *,
        manifest_hash: str,
        scope: MemoryScope | None = None,
        fail_after: int | None = None,
    ) -> tuple[int, int]:
        """单事务幂等导入 legacy 条目；测试可注入失败验证回滚。"""

        scope = scope or MemoryScope()
        imported = 0
        skipped = 0
        with self._connection:
            for index, (content, source_ref) in enumerate(entries):
                normalized = _normalize(content)
                content_hash = hashlib.sha256(
                    f"{scope.kind}:{scope.identifier}:{normalized}".encode()
                ).hexdigest()
                if self._connection.execute(
                    "SELECT 1 FROM claims WHERE scope_kind=? AND scope_id=? "
                    "AND content_hash=? AND status IN "
                    "('candidate','active','approved','frozen')",
                    (scope.kind, scope.identifier, content_hash),
                ).fetchone():
                    skipped += 1
                    continue
                if fail_after is not None and index >= fail_after:
                    raise RuntimeError("legacy import failure injection")
                claim_id = f"legacy_{content_hash[:24]}"
                now = datetime.now(UTC).isoformat()
                self._connection.execute(
                    """
                    INSERT INTO claims(
                        claim_id, content, normalized_content, content_hash, source,
                        explicitness, scope_kind, scope_id, sensitivity, status,
                        valid_from, valid_to, created_at
                    ) VALUES (?, ?, ?, ?, 'legacy-import', 'external', ?,
                              ?, 'private', 'active', NULL, NULL, ?)
                    """,
                    (
                        claim_id,
                        content,
                        normalized,
                        content_hash,
                        scope.kind,
                        scope.identifier,
                        now,
                    ),
                )
                self._insert_evidence(
                    claim_id,
                    EvidenceRef(
                        "legacy-file",
                        source_ref,
                        metadata={"manifest_hash": manifest_hash},
                    ),
                    now,
                )
                self._insert_claim_search(claim_id, content)
                self._enqueue_index_job("claim", claim_id, content_hash)
                self._enqueue_card_projection(
                    scope, "general", "profile"
                )
                self._record_revision("claim", claim_id, "legacy-import", manifest_hash)
                imported += 1
        return imported, skipped

    def create_card(
        self,
        *,
        title: str,
        content: str,
        scope: MemoryScope | None = None,
        status: str = "active",
        sensitivity: str = "private",
        claim_relations: tuple[tuple[str, str], ...] = (),
        actor: str = "human",
        projection_key: str = "",
    ) -> MemoryCard:
        scope = scope or MemoryScope()
        if status not in _VALID_STATUS:
            raise ValueError(f"无效记忆状态：{status}")
        card_id = f"card_{uuid.uuid4().hex}"
        now = datetime.now(UTC).isoformat()
        with self._connection:
            self._connection.execute(
                "INSERT INTO cards(card_id, scope_kind, scope_id, status, sensitivity, "
                "current_version, created_at, projection_key) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    card_id,
                    scope.kind,
                    scope.identifier,
                    status,
                    sensitivity,
                    now,
                    projection_key,
                ),
            )
            version_id = self._insert_card_version(card_id, 1, title, content, now)
            self._insert_card_search(card_id, title, content)
            self._enqueue_index_job(
                "card", card_id, _source_content_hash(f"{title}：{content}")
            )
            for claim_id, relation in claim_relations:
                self.link_card_claim(card_id, claim_id, relation, commit=False)
            self._record_revision("card", card_id, "create", actor)
        return MemoryCard(
            card_id=card_id,
            scope=scope,
            status=status,  # type: ignore[arg-type]
            sensitivity=sensitivity,
            current_version=MemoryCardVersion(
                version_id, card_id, 1, title, content, datetime.fromisoformat(now)
            ),
        )

    def revise_card(
        self, card_id: str, *, title: str, content: str, actor: str
    ) -> MemoryCard:
        card = self._connection.execute(
            "SELECT * FROM cards WHERE card_id = ?", (card_id,)
        ).fetchone()
        if card is None:
            raise KeyError(card_id)
        version = int(card["current_version"]) + 1
        now = datetime.now(UTC).isoformat()
        with self._connection:
            version_id = self._insert_card_version(
                card_id, version, title, content, now
            )
            self._insert_card_search(card_id, title, content)
            self._enqueue_index_job(
                "card", card_id, _source_content_hash(f"{title}：{content}")
            )
            self._connection.execute(
                "UPDATE cards SET current_version = ? WHERE card_id = ?",
                (version, card_id),
            )
            self._record_revision("card", card_id, "revise", actor)
        return MemoryCard(
            card_id,
            MemoryScope(card["scope_kind"], card["scope_id"]),
            card["status"],
            card["sensitivity"],
            MemoryCardVersion(
                version_id,
                card_id,
                version,
                title,
                content,
                datetime.fromisoformat(now),
            ),
        )

    def link_card_claim(
        self, card_id: str, claim_id: str, relation: str, *, commit: bool = True
    ) -> None:
        if relation not in {
            "supports",
            "corrects",
            "contradicts",
            "supersedes",
            "derived-from",
        }:
            raise ValueError(f"无效记忆关系：{relation}")
        self._connection.execute(
            "INSERT OR IGNORE INTO card_claim_relations(card_id, claim_id, relation, "
            "created_at) VALUES (?, ?, ?, ?)",
            (card_id, claim_id, relation, datetime.now(UTC).isoformat()),
        )
        if commit:
            self._connection.commit()

    def link_claims(
        self, source_claim_id: str, target_claim_id: str, relation: str
    ) -> None:
        if relation not in {
            "supports",
            "corrects",
            "contradicts",
            "supersedes",
            "derived-from",
        }:
            raise ValueError(f"无效记忆关系：{relation}")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._connection.execute(
                "INSERT OR IGNORE INTO claim_relations("
                "source_claim_id, target_claim_id, relation, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    source_claim_id,
                    target_claim_id,
                    relation,
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def find_exact_claim(self, content: str, scope: MemoryScope) -> str | None:
        content_hash = hashlib.sha256(
            f"{scope.kind}:{scope.identifier}:{_normalize(content)}".encode()
        ).hexdigest()
        row = self._connection.execute(
            "SELECT claim_id FROM claims WHERE scope_kind=? AND scope_id=? "
            "AND content_hash=? AND status IN "
            "('candidate','active','approved','frozen')",
            (scope.kind, scope.identifier, content_hash),
        ).fetchone()
        return str(row["claim_id"]) if row else None

    def set_status(
        self, entity_type: str, entity_id: str, status: str, actor: str
    ) -> None:
        if status not in _VALID_STATUS:
            raise ValueError(f"无效记忆状态：{status}")
        table, key = self._entity_table(entity_type)
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            current_row = self._connection.execute(
                f"SELECT status FROM {table} WHERE {key}=?",  # noqa: S608
                (entity_id,),
            ).fetchone()
            if current_row is None:
                raise KeyError(entity_id)
            _validate_status_transition(str(current_row["status"]), status, actor)
            cursor = self._connection.execute(
                f"UPDATE {table} SET status = ? WHERE {key} = ?",  # noqa: S608
                (status, entity_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(entity_id)
            self._record_revision(entity_type, entity_id, f"status:{status}", actor)
            source = self.get_index_source(entity_type, entity_id)
            if source is None:
                self._delete_derived_index(entity_type, entity_id)
            else:
                self._enqueue_index_job(entity_type, entity_id, source.content_hash)
            if entity_type == "claim":
                row = self._connection.execute(
                    "SELECT scope_kind, scope_id, subject, card_kind FROM claims "
                    "WHERE claim_id=?",
                    (entity_id,),
                ).fetchone()
                if row is not None:
                    self._enqueue_card_projection(
                        MemoryScope(row["scope_kind"], row["scope_id"]),
                        row["subject"],
                        row["card_kind"],
                    )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def search(self, request: MemoryQuery) -> MemoryQueryResult:
        query = request.query.strip()
        if not query:
            return MemoryQueryResult([])
        rows: list[sqlite3.Row]
        degraded = not self.fts_available
        if "claim" not in request.item_types:
            rows = []
        elif self.fts_available:
            try:
                rows = list(
                    self._connection.execute(
                        """
                        SELECT c.*, bm25(claim_search) AS score
                        FROM claim_search JOIN claims c
                          ON c.claim_id = claim_search.claim_id
                        WHERE claim_search MATCH ? AND c.scope_kind=?
                          AND (?='*' OR c.scope_id IN (?, '*'))
                        ORDER BY score, c.created_at DESC LIMIT ?
                        """,
                        (
                            _fts_query(query, self.max_cjk_ngram),
                            request.scope.kind,
                            request.scope.identifier,
                            request.scope.identifier,
                            request.claim_limit * 4,
                        ),
                    )
                )
            except sqlite3.OperationalError:
                rows, degraded = self._like_claims(
                    query, request.claim_limit * 4, request.scope
                )
        else:
            rows, degraded = self._like_claims(
                query, request.claim_limit * 4, request.scope
            )

        candidate_count = len(rows)
        allowed_sensitivity = _SENSITIVITY.get(request.max_sensitivity, 1)
        now = request.at_time or datetime.now(UTC)
        items: list[MemoryItem] = []
        for row in rows:
            if not _scope_matches(
                MemoryScope(row["scope_kind"], row["scope_id"]), request.scope
            ):
                continue
            if row["status"] not in request.statuses:
                continue
            if _SENSITIVITY.get(row["sensitivity"], 2) > allowed_sensitivity:
                continue
            if not _is_current(row["valid_from"], row["valid_to"], now):
                continue
            items.append(
                self._claim_item(row, "fts5" if not degraded else "keyword-like")
            )
            if len(items) >= request.claim_limit:
                break
        claim_items = items
        card_items: list[MemoryItem] = []
        episode_items: list[MemoryItem] = []
        if "card" in request.item_types:
            card_items = self._search_cards(request, allowed_sensitivity)
            candidate_count += len(card_items)
        if "episode" in request.item_types:
            episode_items = self._search_segments(request)
            candidate_count += len(episode_items)
        selected_cards = card_items[: request.card_limit]
        selected_episodes = episode_items[: request.episode_limit]
        remaining = max(0, request.limit - len(selected_cards))
        reserved_episodes = min(len(selected_episodes), remaining)
        selected_claims = claim_items[
            : min(request.claim_limit, max(0, remaining - reserved_episodes))
        ]
        items = [*selected_cards, *selected_claims, *selected_episodes]
        if len(items) < request.limit:
            selected_ids = {item.item_id for item in items}
            remainder = [
                item
                for item in (*card_items, *claim_items, *episode_items)
                if item.item_id not in selected_ids
            ]
            items.extend(remainder[: request.limit - len(items)])
        items = items[: request.limit]
        return MemoryQueryResult(
            items=items,
            candidate_count=candidate_count,
            filtered_count=candidate_count - len(items),
            degraded=degraded,
            injected_chars=sum(len(item.content) for item in items),
            reason="fts5" if not degraded else "bounded-keyword-fallback",
        )

    def select_core_cards(
        self, scope: MemoryScope, *, limit: int, max_chars: int
    ) -> list[MemoryItem]:
        rows = self._connection.execute(
            """
            SELECT c.*, v.version_id, v.title, v.content,
                   v.created_at AS version_created_at
            FROM cards c JOIN card_versions v
              ON v.card_id = c.card_id AND v.version = c.current_version
            WHERE c.scope_kind = ? AND c.scope_id IN (?, '*')
              AND c.status IN ('active', 'approved', 'frozen')
            ORDER BY CASE c.status WHEN 'frozen' THEN 0 ELSE 1 END,
                     v.created_at DESC LIMIT ?
            """,
            (scope.kind, scope.identifier, limit),
        ).fetchall()
        items: list[MemoryItem] = []
        used = 0
        for row in rows:
            text = f"{row['title']}：{row['content']}"
            if used + len(text) > max_chars:
                break
            used += len(text)
            items.append(
                MemoryItem(
                    content=text,
                    source="card",
                    timestamp=datetime.fromisoformat(row["version_created_at"]),
                    metadata={
                        "scope_kind": row["scope_kind"],
                        "scope_id": row["scope_id"],
                        "sensitivity": row["sensitivity"],
                    },
                    item_id=row["card_id"],
                    item_type="card",
                    status=row["status"],
                    recall_reason="core-card",
                )
            )
        return items

    def list_items(self, scope: MemoryScope) -> list[MemoryItem]:
        rows = self._connection.execute(
            "SELECT * FROM claims WHERE scope_kind = ? AND scope_id = ? "
            "AND status <> 'deleted' ORDER BY created_at DESC",
            (scope.kind, scope.identifier),
        ).fetchall()
        return [self._claim_item(row, "list") for row in rows]

    def export_items(
        self, scope: MemoryScope, *, max_sensitivity: str
    ) -> list[dict[str, Any]]:
        allowed = _SENSITIVITY.get(max_sensitivity, 1)
        claims = [
            {
                "id": item.item_id,
                "type": item.item_type,
                "content": item.content,
                "status": item.status,
                "scope": {
                    "kind": item.metadata.get("scope_kind"),
                    "identifier": item.metadata.get("scope_id"),
                },
                "sensitivity": item.metadata.get("sensitivity"),
                "created_at": item.timestamp.isoformat(),
                "evidence": [
                    {"kind": ref.kind, "ref_id": ref.ref_id} for ref in item.evidence
                ],
            }
            for item in self.list_items(scope)
            if _SENSITIVITY.get(str(item.metadata.get("sensitivity")), 2) <= allowed
        ]
        cards = self.select_core_cards(scope, limit=10_000, max_chars=10_000_000)
        return [
            *claims,
            *[
                {
                    "id": item.item_id,
                    "type": "card",
                    "content": item.content,
                    "status": item.status,
                    "scope": {
                        "kind": item.metadata.get("scope_kind"),
                        "identifier": item.metadata.get("scope_id"),
                    },
                    "sensitivity": item.metadata.get("sensitivity"),
                    "created_at": item.timestamp.isoformat(),
                    "evidence": [],
                }
                for item in cards
                if _SENSITIVITY.get(
                    str(item.metadata.get("sensitivity")), 2
                )
                <= allowed
            ],
        ]

    def add_trajectory_segment(
        self,
        *,
        segment_id: str,
        trace_id: str,
        start_event_id: int,
        end_event_id: int,
        content: str,
        scope: MemoryScope,
        occurred_at: str,
        context_prefix: str = "",
        search_text: str = "",
        segmenter_version: str = "1",
        content_hash: str = "",
        source_refs_json: str = "[]",
    ) -> None:
        searchable = search_text or "\n".join(
            part for part in (context_prefix.strip(), content.strip()) if part
        )
        digest = content_hash or _source_content_hash(searchable)
        with self._connection:
            self._connection.execute(
                """
                INSERT OR REPLACE INTO trajectory_segments(
                    segment_id, trace_id, start_event_id, end_event_id, content,
                    scope_kind, scope_id, occurred_at, context_prefix, search_text,
                    segmenter_version, content_hash, source_refs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    segment_id,
                    trace_id,
                    start_event_id,
                    end_event_id,
                    content,
                    scope.kind,
                    scope.identifier,
                    occurred_at,
                    context_prefix,
                    searchable,
                    segmenter_version,
                    digest,
                    source_refs_json,
                ),
            )
            self._enqueue_index_job("episode", segment_id, digest)

    def replace_trajectory_segments(
        self, trace_id: str, segments: list[dict[str, Any]]
    ) -> None:
        """在单一事务中替换一个 trace 的派生片段。"""

        with self._connection:
            existing = self._connection.execute(
                "SELECT segment_id FROM trajectory_segments WHERE trace_id=?",
                (trace_id,),
            ).fetchall()
            for row in existing:
                self._delete_derived_index("episode", row["segment_id"])
            self._connection.execute(
                "DELETE FROM trajectory_segments WHERE trace_id=?", (trace_id,)
            )
            for segment in segments:
                self._connection.execute(
                    """
                    INSERT INTO trajectory_segments(
                        segment_id, trace_id, start_event_id, end_event_id, content,
                        scope_kind, scope_id, occurred_at, context_prefix, search_text,
                        segmenter_version, content_hash, source_refs_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        segment["segment_id"],
                        trace_id,
                        segment["start_event_id"],
                        segment["end_event_id"],
                        segment["content"],
                        segment["scope"].kind,
                        segment["scope"].identifier,
                        segment["occurred_at"],
                        segment["context_prefix"],
                        segment["search_text"],
                        segment["segmenter_version"],
                        segment["content_hash"],
                        segment["source_refs_json"],
                    ),
                )
                self._enqueue_index_job(
                    "episode", segment["segment_id"], segment["content_hash"]
                )

    def delete_trajectory_segments(self, trace_id: str) -> None:
        """仅删除可重建索引，不触碰 trajectory 权威记录。"""

        with self._connection:
            rows = self._connection.execute(
                "SELECT segment_id FROM trajectory_segments WHERE trace_id=?",
                (trace_id,),
            ).fetchall()
            for row in rows:
                self._delete_derived_index("episode", row["segment_id"])
            self._connection.execute(
                "DELETE FROM trajectory_segments WHERE trace_id = ?", (trace_id,)
            )

    def begin_consolidation(
        self, batch_key: str, trace_start: str, trace_end: str
    ) -> str | None:
        """返回新 run_id；已成功批次返回 None，失败批次允许安全重试。"""

        self._connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._connection.execute(
                "SELECT run_id, status FROM consolidation_runs WHERE batch_key = ?",
                (batch_key,),
            ).fetchone()
            if row is not None and row["status"] == "completed":
                self._connection.commit()
                return None
            run_id = str(row["run_id"]) if row else f"run_{uuid.uuid4().hex}"
            self._connection.execute(
                """
                INSERT INTO consolidation_runs(
                    run_id, batch_key, trace_start, trace_end, status, created_at
                ) VALUES (?, ?, ?, ?, 'running', ?)
                ON CONFLICT(batch_key) DO UPDATE SET
                    status='running', error=NULL, completed_at=NULL
                """,
                (
                    run_id,
                    batch_key,
                    trace_start,
                    trace_end,
                    datetime.now(UTC).isoformat(),
                ),
            )
            persisted = self._connection.execute(
                "SELECT run_id FROM consolidation_runs WHERE batch_key=?", (batch_key,)
            ).fetchone()
            self._connection.commit()
            assert persisted is not None
            return str(persisted["run_id"])
        except Exception:
            self._connection.rollback()
            raise

    def finish_consolidation(self, run_id: str, checkpoint: str) -> None:
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE consolidation_runs SET status='completed', checkpoint=?, "
                "completed_at=? WHERE run_id=?",
                (checkpoint, datetime.now(UTC).isoformat(), run_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(run_id)

    def fail_consolidation(self, run_id: str, error: str) -> None:
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE consolidation_runs SET status='failed', error=? WHERE run_id=?",
                (error[:2_000], run_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(run_id)

    def apply_consolidation_batch(
        self,
        run_id: str,
        checkpoint: str,
        entries: list[tuple[MemoryMutation, tuple[tuple[str, str], ...]]],
    ) -> tuple[str, ...]:
        """在一个事务内写入候选、关系和完成 checkpoint。"""

        self._connection.execute("BEGIN IMMEDIATE")
        candidate_ids: list[str] = []
        try:
            for mutation, relations in entries:
                item = self.append_claim(mutation, _manage_transaction=False)
                candidate_ids.append(item.item_id)
                for target_id, relation in relations:
                    self._connection.execute(
                        "INSERT OR IGNORE INTO claim_relations("
                        "source_claim_id, target_claim_id, relation, created_at) "
                        "VALUES (?, ?, ?, ?)",
                        (
                            item.item_id,
                            target_id,
                            relation,
                            datetime.now(UTC).isoformat(),
                        ),
                    )
            cursor = self._connection.execute(
                "UPDATE consolidation_runs SET status='completed', checkpoint=?, "
                "completed_at=? WHERE run_id=?",
                (checkpoint, datetime.now(UTC).isoformat(), run_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(run_id)
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return tuple(dict.fromkeys(candidate_ids))

    def enqueue_index_job(
        self, memory_type: str, memory_id: str, content_hash: str
    ) -> None:
        with self._connection:
            self._enqueue_index_job(memory_type, memory_id, content_hash)

    def _enqueue_index_job(
        self, memory_type: str, memory_id: str, content_hash: str
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self._connection.execute(
            """
            INSERT INTO memory_index_jobs(
                memory_type, memory_id, content_hash, state, attempts,
                last_error, available_at, updated_at
            ) VALUES (?, ?, ?, 'pending', 0, NULL, ?, ?)
            ON CONFLICT(memory_type, memory_id) DO UPDATE SET
                content_hash=excluded.content_hash,
                state=CASE
                    WHEN memory_index_jobs.content_hash=excluded.content_hash
                         AND memory_index_jobs.state='ready' THEN 'ready'
                    ELSE 'pending'
                END,
                attempts=CASE
                    WHEN memory_index_jobs.content_hash=excluded.content_hash
                    THEN memory_index_jobs.attempts ELSE 0 END,
                last_error=NULL,
                available_at=excluded.available_at,
                updated_at=excluded.updated_at
            """,
            (memory_type, memory_id, content_hash, now, now),
        )

    def claim_index_jobs(self, limit: int) -> list[MemoryIndexJob]:
        now = datetime.now(UTC).isoformat()
        with self._connection:
            rows = self._connection.execute(
                """
                SELECT * FROM memory_index_jobs
                WHERE state IN ('pending', 'retry') AND available_at<=?
                ORDER BY updated_at, memory_type, memory_id LIMIT ?
                """,
                (now, max(1, limit)),
            ).fetchall()
            for row in rows:
                self._connection.execute(
                    "UPDATE memory_index_jobs SET state='running', "
                    "attempts=attempts+1, "
                    "updated_at=? WHERE memory_type=? AND memory_id=?",
                    (now, row["memory_type"], row["memory_id"]),
                )
        return [
            MemoryIndexJob(
                row["memory_type"],
                row["memory_id"],
                row["content_hash"],
                int(row["attempts"]) + 1,
            )
            for row in rows
        ]

    def complete_index_job(
        self,
        job: MemoryIndexJob,
        *,
        model: str,
        version: str,
        dimensions: int,
        vector_blob: bytes,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connection:
            current = self._connection.execute(
                "SELECT content_hash FROM memory_index_jobs "
                "WHERE memory_type=? AND memory_id=?",
                (job.memory_type, job.memory_id),
            ).fetchone()
            if current is None or current["content_hash"] != job.content_hash:
                return
            self._connection.execute(
                """
                INSERT INTO semantic_index(
                    memory_type, memory_id, content_hash, embedding_model,
                    embedding_version, dimensions, vector_blob, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_type, memory_id) DO UPDATE SET
                    content_hash=excluded.content_hash,
                    embedding_model=excluded.embedding_model,
                    embedding_version=excluded.embedding_version,
                    dimensions=excluded.dimensions,
                    vector_blob=excluded.vector_blob,
                    indexed_at=excluded.indexed_at
                """,
                (
                    job.memory_type,
                    job.memory_id,
                    job.content_hash,
                    model,
                    version,
                    dimensions,
                    vector_blob,
                    now,
                ),
            )
            self._connection.execute(
                "UPDATE memory_index_jobs SET state='ready', last_error=NULL, "
                "updated_at=? WHERE memory_type=? AND memory_id=?",
                (now, job.memory_type, job.memory_id),
            )

    def fail_index_job(self, job: MemoryIndexJob, error_type: str) -> None:
        delay = min(300, 2 ** min(job.attempts, 8))
        available = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
        with self._connection:
            self._connection.execute(
                "UPDATE memory_index_jobs SET state='retry', last_error=?, "
                "available_at=?, updated_at=? WHERE memory_type=? AND memory_id=? "
                "AND content_hash=?",
                (
                    error_type[:120],
                    available,
                    datetime.now(UTC).isoformat(),
                    job.memory_type,
                    job.memory_id,
                    job.content_hash,
                ),
            )

    def discard_index_job(
        self, memory_type: str, memory_id: str, content_hash: str
    ) -> None:
        with self._connection:
            self._connection.execute(
                "DELETE FROM memory_index_jobs WHERE memory_type=? AND memory_id=? "
                "AND content_hash=?",
                (memory_type, memory_id, content_hash),
            )
            self._connection.execute(
                "DELETE FROM semantic_index WHERE memory_type=? AND memory_id=? "
                "AND content_hash=?",
                (memory_type, memory_id, content_hash),
            )

    def _delete_derived_index(self, memory_type: str, memory_id: str) -> None:
        self._connection.execute(
            "DELETE FROM memory_index_jobs WHERE memory_type=? AND memory_id=?",
            (memory_type, memory_id),
        )
        self._connection.execute(
            "DELETE FROM semantic_index WHERE memory_type=? AND memory_id=?",
            (memory_type, memory_id),
        )

    def get_index_source(
        self, memory_type: str, memory_id: str
    ) -> MemoryIndexSource | None:
        if memory_type == "claim":
            row = self._connection.execute(
                "SELECT * FROM claims WHERE claim_id=? AND status IN "
                "('active', 'approved', 'frozen')",
                (memory_id,),
            ).fetchone()
            if row is None or not _is_current(
                row["valid_from"], row["valid_to"], datetime.now(UTC)
            ):
                return None
            return MemoryIndexSource(
                "claim",
                row["claim_id"],
                row["content"],
                row["content_hash"],
                MemoryScope(row["scope_kind"], row["scope_id"]),
                row["status"],
                row["sensitivity"],
                row["created_at"],
            )
        if memory_type == "card":
            row = self._connection.execute(
                """
                SELECT c.*, v.title, v.content, v.created_at AS version_created_at
                FROM cards c JOIN card_versions v
                  ON v.card_id=c.card_id AND v.version=c.current_version
                WHERE c.card_id=? AND c.status IN ('active', 'approved', 'frozen')
                """,
                (memory_id,),
            ).fetchone()
            if row is None:
                return None
            content = f"{row['title']}：{row['content']}"
            return MemoryIndexSource(
                "card",
                row["card_id"],
                content,
                _source_content_hash(content),
                MemoryScope(row["scope_kind"], row["scope_id"]),
                row["status"],
                row["sensitivity"],
                row["version_created_at"],
            )
        if memory_type == "episode":
            row = self._connection.execute(
                "SELECT * FROM trajectory_segments WHERE segment_id=?",
                (memory_id,),
            ).fetchone()
            if row is None:
                return None
            return MemoryIndexSource(
                "episode",
                row["segment_id"],
                row["search_text"] or row["content"],
                row["content_hash"],
                MemoryScope(row["scope_kind"], row["scope_id"]),
                "active",
                "private",
                row["occurred_at"],
            )
        return None

    def rebuild_index_jobs(self, memory_type: str | None = None) -> int:
        types = (memory_type,) if memory_type else ("claim", "card", "episode")
        count = 0
        with self._connection:
            for current_type in types:
                self._connection.execute(
                    "DELETE FROM semantic_index WHERE memory_type=?", (current_type,)
                )
                self._connection.execute(
                    "DELETE FROM memory_index_jobs WHERE memory_type=?",
                    (current_type,),
                )
                for memory_id in self._source_ids(current_type):
                    source = self.get_index_source(current_type, memory_id)
                    if source is None:
                        continue
                    self._enqueue_index_job(
                        current_type, memory_id, source.content_hash
                    )
                    count += 1
        return count

    def backfill_index_jobs(self) -> int:
        """只为尚无当前 job/vector 的事实源登记任务。"""

        count = 0
        with self._connection:
            for memory_type in ("claim", "card", "episode"):
                for memory_id in self._source_ids(memory_type):
                    source = self.get_index_source(memory_type, memory_id)
                    if source is None:
                        continue
                    row = self._connection.execute(
                        "SELECT content_hash FROM memory_index_jobs "
                        "WHERE memory_type=? AND memory_id=?",
                        (memory_type, memory_id),
                    ).fetchone()
                    if row is not None and row["content_hash"] == source.content_hash:
                        continue
                    self._enqueue_index_job(
                        memory_type, memory_id, source.content_hash
                    )
                    count += 1
        return count

    def _source_ids(self, memory_type: str) -> list[str]:
        table, key = {
            "claim": ("claims", "claim_id"),
            "card": ("cards", "card_id"),
            "episode": ("trajectory_segments", "segment_id"),
        }[memory_type]
        return [
            str(row[0])
            for row in self._connection.execute(
                f"SELECT {key} FROM {table} ORDER BY {key}"  # noqa: S608
            ).fetchall()
        ]

    def ready_semantic_rows(
        self,
        request: MemoryQuery,
        *,
        model: str,
        version: str,
        dimensions: int,
        limit: int,
    ) -> list[tuple[MemoryItem, bytes]]:
        rows = self._connection.execute(
            """
            SELECT memory_type, memory_id, content_hash, vector_blob
            FROM semantic_index
            WHERE embedding_model=? AND embedding_version=? AND dimensions=?
            ORDER BY memory_type, memory_id LIMIT ?
            """,
            (model, version, dimensions, max(limit * 8, limit)),
        ).fetchall()
        result: list[tuple[MemoryItem, bytes]] = []
        for row in rows:
            if row["memory_type"] not in request.item_types:
                continue
            source = self.get_index_source(row["memory_type"], row["memory_id"])
            if source is None or source.content_hash != row["content_hash"]:
                continue
            scope_matches = _scope_matches(source.scope, request.scope)
            if not scope_matches:
                continue
            if source.status not in request.statuses:
                continue
            if _SENSITIVITY.get(source.sensitivity, 2) > _SENSITIVITY.get(
                request.max_sensitivity, 1
            ):
                continue
            result.append((self._source_item(source, "semantic"), row["vector_blob"]))
        return result[:limit]

    def _source_item(self, source: MemoryIndexSource, reason: str) -> MemoryItem:
        if source.memory_type == "claim":
            row = self._connection.execute(
                "SELECT * FROM claims WHERE claim_id=?", (source.memory_id,)
            ).fetchone()
            assert row is not None
            return self._claim_item(row, reason)
        if source.memory_type == "card":
            return MemoryItem(
                source.content,
                "card",
                datetime.fromisoformat(source.occurred_at),
                metadata={
                    "scope_kind": source.scope.kind,
                    "scope_id": source.scope.identifier,
                    "sensitivity": source.sensitivity,
                },
                item_id=source.memory_id,
                item_type="card",
                status=source.status,
                recall_reason=reason,
            )
        row = self._connection.execute(
            "SELECT * FROM trajectory_segments WHERE segment_id=?",
            (source.memory_id,),
        ).fetchone()
        assert row is not None
        return self._segment_item(row, reason)

    def metadata_candidates(self, request: MemoryQuery, limit: int) -> list[MemoryItem]:
        """返回符合硬约束的核心与近期候选，不依赖文本相似度。"""

        candidates: list[MemoryItem] = []
        if "card" in request.item_types:
            candidates.extend(
                self.select_core_cards(request.scope, limit=limit, max_chars=10**9)
            )
        if "claim" in request.item_types:
            rows = self._connection.execute(
                "SELECT * FROM claims WHERE scope_kind=? AND scope_id IN (?, '*') "
                "ORDER BY importance DESC, created_at DESC LIMIT ?",
                (request.scope.kind, request.scope.identifier, limit * 2),
            ).fetchall()
            now = request.at_time or datetime.now(UTC)
            for row in rows:
                if row["status"] not in request.statuses:
                    continue
                if not _is_current(row["valid_from"], row["valid_to"], now):
                    continue
                if _SENSITIVITY.get(row["sensitivity"], 2) > _SENSITIVITY.get(
                    request.max_sensitivity, 1
                ):
                    continue
                candidates.append(self._claim_item(row, "metadata"))
        return candidates[:limit]

    def eligible_card_claims(self, key: CardProjectionKey) -> list[sqlite3.Row]:
        now = datetime.now(UTC)
        rows = self._connection.execute(
            """
            SELECT c.* FROM claims c
            WHERE c.scope_kind=? AND c.scope_id=? AND c.subject=? AND c.card_kind=?
              AND c.status IN ('active', 'approved')
              AND EXISTS(SELECT 1 FROM evidence e WHERE e.claim_id=c.claim_id)
            ORDER BY c.valid_from, c.created_at, c.claim_id
            """,
            (key.scope.kind, key.scope.identifier, key.subject, key.card_kind),
        ).fetchall()
        return [
            row
            for row in rows
            if _is_current(row["valid_from"], row["valid_to"], now)
        ]

    def find_card_by_projection_key(self, projection_key: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM cards WHERE projection_key=?", (projection_key,)
        ).fetchone()

    def card_current_content(self, card_id: str) -> tuple[str, str] | None:
        row = self._connection.execute(
            """
            SELECT v.title, v.content FROM cards c JOIN card_versions v
              ON v.card_id=c.card_id AND v.version=c.current_version
            WHERE c.card_id=?
            """,
            (card_id,),
        ).fetchone()
        return (row["title"], row["content"]) if row else None

    def card_claim_ids(self, card_id: str) -> tuple[str, ...]:
        rows = self._connection.execute(
            "SELECT DISTINCT claim_id FROM card_claim_relations WHERE card_id=? "
            "ORDER BY claim_id",
            (card_id,),
        ).fetchall()
        return tuple(str(row["claim_id"]) for row in rows)

    def apply_card_projection(
        self,
        key: CardProjectionKey,
        *,
        title: str,
        content: str,
        claim_ids: tuple[str, ...],
    ) -> tuple[str, MemoryCard | None]:
        """原子应用一次证据化 Card 投影。"""

        existing = self.find_card_by_projection_key(key.value)
        if existing is None:
            card = self.create_card(
                title=title,
                content=content,
                scope=key.scope,
                claim_relations=tuple((claim_id, "supports") for claim_id in claim_ids),
                actor="card-builder",
                projection_key=key.value,
            )
            return "created", card
        if existing["status"] == "frozen":
            return "frozen", None
        card_id = str(existing["card_id"])
        current = self.card_current_content(card_id)
        if current == (title, content) and self.card_claim_ids(card_id) == tuple(
            sorted(claim_ids)
        ):
            return "unchanged", None
        version = int(existing["current_version"]) + 1
        now = datetime.now(UTC).isoformat()
        with self._connection:
            version_id = self._insert_card_version(
                card_id, version, title, content, now
            )
            self._connection.execute(
                "UPDATE cards SET current_version=? WHERE card_id=?",
                (version, card_id),
            )
            self._connection.execute(
                "DELETE FROM card_claim_relations WHERE card_id=?", (card_id,)
            )
            for claim_id in sorted(claim_ids):
                self.link_card_claim(card_id, claim_id, "supports", commit=False)
            self._insert_card_search(card_id, title, content)
            self._enqueue_index_job(
                "card", card_id, _source_content_hash(f"{title}：{content}")
            )
            self._record_revision("card", card_id, "project", "card-builder")
        return (
            "revised",
            MemoryCard(
                card_id,
                key.scope,
                existing["status"],
                existing["sensitivity"],
                MemoryCardVersion(
                    version_id,
                    card_id,
                    version,
                    title,
                    content,
                    datetime.fromisoformat(now),
                ),
            ),
        )

    def enqueue_card_projection(self, key: CardProjectionKey) -> None:
        with self._connection:
            self._enqueue_card_projection(key.scope, key.subject, key.card_kind)

    def _enqueue_card_projection(
        self, scope: MemoryScope, subject: str, card_kind: str
    ) -> None:
        key = CardProjectionKey(scope, subject, card_kind).value
        now = datetime.now(UTC).isoformat()
        payload = json.dumps(
            {
                "scope_kind": scope.kind,
                "scope_id": scope.identifier,
                "subject": subject,
                "card_kind": card_kind,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        self._connection.execute(
            """
            INSERT INTO memory_projection_jobs(
                projection_type, projection_key, payload_json, state, attempts,
                last_error, available_at, updated_at
            ) VALUES ('card', ?, ?, 'pending', 0, NULL, ?, ?)
            ON CONFLICT(projection_type, projection_key) DO UPDATE SET
                payload_json=excluded.payload_json, state='pending',
                last_error=NULL, available_at=excluded.available_at,
                updated_at=excluded.updated_at
            """,
            (key, payload, now, now),
        )

    def claim_projection_jobs(
        self, projection_type: str, limit: int
    ) -> list[dict[str, Any]]:
        now = datetime.now(UTC).isoformat()
        with self._connection:
            rows = self._connection.execute(
                "SELECT * FROM memory_projection_jobs WHERE projection_type=? "
                "AND state IN ('pending', 'retry') AND available_at<=? "
                "ORDER BY updated_at, projection_key LIMIT ?",
                (projection_type, now, max(1, limit)),
            ).fetchall()
            for row in rows:
                self._connection.execute(
                    "UPDATE memory_projection_jobs SET state='running', "
                    "attempts=attempts+1, updated_at=? WHERE projection_type=? "
                    "AND projection_key=?",
                    (now, projection_type, row["projection_key"]),
                )
        return [dict(row) for row in rows]

    def finish_projection_job(
        self, projection_type: str, projection_key: str, state: str = "ready"
    ) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE memory_projection_jobs SET state=?, last_error=NULL, "
                "updated_at=? WHERE projection_type=? AND projection_key=?",
                (
                    state,
                    datetime.now(UTC).isoformat(),
                    projection_type,
                    projection_key,
                ),
            )

    def fail_projection_job(
        self, projection_type: str, projection_key: str, error_type: str
    ) -> None:
        available = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
        with self._connection:
            self._connection.execute(
                "UPDATE memory_projection_jobs SET state='retry', last_error=?, "
                "available_at=?, updated_at=? WHERE projection_type=? "
                "AND projection_key=?",
                (
                    error_type[:120],
                    available,
                    datetime.now(UTC).isoformat(),
                    projection_type,
                    projection_key,
                ),
            )

    def index_diagnostics(self) -> dict[str, Any]:
        rows = self._connection.execute(
            "SELECT state, COUNT(*) AS count FROM memory_index_jobs GROUP BY state"
        ).fetchall()
        return {
            "schema_version": _SCHEMA_VERSION,
            "fts_available": self.fts_available,
            "index_jobs": {row["state"]: int(row["count"]) for row in rows},
            "semantic_entries": int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM semantic_index"
                ).fetchone()[0]
            ),
        }

    def _initialize(self) -> None:
        current = self._connection.execute("PRAGMA user_version").fetchone()[0]
        if current not in {0, 1, 2, _SCHEMA_VERSION}:
            raise RuntimeError(f"不支持的 memory schema 版本：{current}")
        if current == 0:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                _execute_sql_script(self._connection, _SCHEMA)
                self._connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        elif current == 1:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                _execute_sql_script(self._connection, _MIGRATION_1_TO_2)
                rows = self._connection.execute(
                    "SELECT segment_id, content FROM trajectory_segments"
                ).fetchall()
                for row in rows:
                    self._connection.execute(
                        "UPDATE trajectory_segments SET search_text=?, content_hash=? "
                        "WHERE segment_id=?",
                        (
                            row["content"],
                            _source_content_hash(row["content"]),
                            row["segment_id"],
                        ),
                    )
                self._connection.execute("PRAGMA user_version = 2")
                self._connection.commit()
                current = 2
            except Exception:
                self._connection.rollback()
                raise
        if current == 2:
            self._migrate_v2_to_v3()
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            _execute_sql_script(self._connection, _FTS_SCHEMA)
            self._connection.commit()
            self.fts_available = True
        except sqlite3.OperationalError:
            self._connection.rollback()
            self.fts_available = False

    def _migrate_v2_to_v3(self) -> None:
        """移除旧全局 UNIQUE，并建立 scope 内活动记录部分唯一索引。"""

        self._connection.execute("PRAGMA foreign_keys = OFF")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            _execute_sql_script(self._connection, _MIGRATION_2_TO_3)
            self._connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        finally:
            self._connection.execute("PRAGMA foreign_keys = ON")

    def _insert_evidence(
        self, claim_id: str, ref: EvidenceRef, created_at: str
    ) -> None:
        self._connection.execute(
            "INSERT INTO evidence(evidence_id, claim_id, kind, ref_id, quote, "
            "metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                f"ev_{uuid.uuid4().hex}",
                claim_id,
                ref.kind,
                ref.ref_id,
                ref.quote,
                json.dumps(ref.metadata, ensure_ascii=False),
                created_at,
            ),
        )

    def _insert_claim_search(self, claim_id: str, content: str) -> None:
        if self.fts_available:
            self._connection.execute(
                "INSERT INTO claim_search(claim_id, content, search_text) "
                "VALUES (?, ?, ?)",
                (claim_id, content, _search_text(content, self.max_cjk_ngram)),
            )

    def _insert_card_version(
        self, card_id: str, version: int, title: str, content: str, created_at: str
    ) -> str:
        version_id = f"cv_{uuid.uuid4().hex}"
        self._connection.execute(
            "INSERT INTO card_versions(version_id, card_id, version, title, content, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (version_id, card_id, version, title, content, created_at),
        )
        return version_id

    def _insert_card_search(self, card_id: str, title: str, content: str) -> None:
        if not self.fts_available:
            return
        self._connection.execute(
            "DELETE FROM card_search WHERE card_id = ?", (card_id,)
        )
        self._connection.execute(
            "INSERT INTO card_search(card_id, title, content, search_text) "
            "VALUES (?, ?, ?, ?)",
            (
                card_id,
                title,
                content,
                _search_text(f"{title} {content}", self.max_cjk_ngram),
            ),
        )

    def _record_revision(
        self, entity_type: str, entity_id: str, action: str, actor: str
    ) -> None:
        self._connection.execute(
            "INSERT INTO memory_revisions(revision_id, entity_type, entity_id, action, "
            "actor, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                f"rev_{uuid.uuid4().hex}",
                entity_type,
                entity_id,
                action,
                actor,
                datetime.now(UTC).isoformat(),
            ),
        )

    def _claim_item(self, row: sqlite3.Row, reason: str) -> MemoryItem:
        evidence_rows = self._connection.execute(
            "SELECT * FROM evidence WHERE claim_id = ? "
            "ORDER BY created_at, evidence_id",
            (row["claim_id"],),
        ).fetchall()
        evidence = tuple(
            EvidenceRef(
                item["kind"],
                item["ref_id"],
                item["quote"],
                json.loads(item["metadata_json"]),
            )
            for item in evidence_rows
        )
        return MemoryItem(
            content=row["content"],
            source=row["source"],
            timestamp=datetime.fromisoformat(row["created_at"]),
            metadata={
                "scope_kind": row["scope_kind"],
                "scope_id": row["scope_id"],
                "sensitivity": row["sensitivity"],
                "explicitness": row["explicitness"],
                **(
                    {"keyword_score": float(row["score"])}
                    if "score" in row.keys()
                    else {}
                ),
            },
            item_id=row["claim_id"],
            status=row["status"],
            evidence=evidence,
            recall_reason=reason,
            current=row["status"] in {"active", "approved", "frozen"},
        )

    def _like_claims(
        self, query: str, limit: int, scope: MemoryScope
    ) -> tuple[list[sqlite3.Row], bool]:
        terms = _terms(query)
        if not terms:
            return [], True
        clauses = " OR ".join("normalized_content LIKE ?" for _ in terms)
        params: list[Any] = [f"%{term}%" for term in terms]
        params.extend((scope.kind, scope.identifier, scope.identifier, limit))
        rows = self._connection.execute(
            f"SELECT * FROM claims WHERE ({clauses}) "  # noqa: S608
            "AND scope_kind=? AND (?='*' OR scope_id IN (?, '*')) "
            "ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return list(rows), True

    def _search_cards(
        self, request: MemoryQuery, allowed_sensitivity: int
    ) -> list[MemoryItem]:
        terms = _terms(request.query)
        if not terms:
            return []
        clauses = " OR ".join("(v.title LIKE ? OR v.content LIKE ?)" for _ in terms)
        params: list[Any] = []
        for term in terms:
            params.extend((f"%{term}%", f"%{term}%"))
        params.extend(
            (request.scope.kind, request.scope.identifier, request.card_limit)
        )
        rows = self._connection.execute(
            f"""
            SELECT c.*, v.title, v.content, v.created_at AS version_created_at
            FROM cards c JOIN card_versions v
              ON v.card_id=c.card_id AND v.version=c.current_version
            WHERE ({clauses}) AND c.scope_kind=? AND c.scope_id IN (?, '*')
            ORDER BY v.created_at DESC LIMIT ?
            """,  # noqa: S608
            params,
        ).fetchall()
        return [
            MemoryItem(
                content=f"{row['title']}：{row['content']}",
                source="card",
                timestamp=datetime.fromisoformat(row["version_created_at"]),
                item_id=row["card_id"],
                item_type="card",
                status=row["status"],
                recall_reason="card-keyword",
                metadata={
                    "scope_kind": row["scope_kind"],
                    "scope_id": row["scope_id"],
                    "sensitivity": row["sensitivity"],
                },
            )
            for row in rows
            if row["status"] in request.statuses
            and _SENSITIVITY.get(row["sensitivity"], 2) <= allowed_sensitivity
        ]

    def _search_segments(self, request: MemoryQuery) -> list[MemoryItem]:
        terms = _terms(request.query)
        if not terms:
            return []
        clauses = " OR ".join("search_text LIKE ?" for _ in terms)
        params: list[Any] = [f"%{term}%" for term in terms]
        params.extend(
            (request.scope.kind, request.scope.identifier, request.episode_limit)
        )
        rows = self._connection.execute(
            f"""
            SELECT * FROM trajectory_segments WHERE ({clauses})
              AND scope_kind=? AND scope_id IN (?, '*')
            ORDER BY occurred_at DESC, segment_id LIMIT ?
            """,  # noqa: S608
            params,
        ).fetchall()
        return [self._segment_item(row, "trajectory-segment-keyword") for row in rows]

    def _segment_item(self, row: sqlite3.Row, reason: str) -> MemoryItem:
        return MemoryItem(
            content=row["search_text"] or row["content"],
            source="trajectory",
            timestamp=datetime.fromisoformat(row["occurred_at"]),
            metadata={
                "trace_id": row["trace_id"],
                "start_event_id": row["start_event_id"],
                "end_event_id": row["end_event_id"],
                "scope_kind": row["scope_kind"],
                "scope_id": row["scope_id"],
                "context_prefix": row["context_prefix"],
                "segmenter_version": row["segmenter_version"],
                "source_refs_json": row["source_refs_json"],
            },
            item_id=row["segment_id"],
            item_type="episode",
            recall_reason=reason,
            evidence=(EvidenceRef("trace", row["trace_id"]),),
        )

    @staticmethod
    def _metadata_evidence(metadata: dict[str, Any]) -> tuple[EvidenceRef, ...]:
        ref_id = str(
            metadata.get("message_id")
            or metadata.get("approved_batch_id")
            or metadata.get("actor_id")
            or ""
        )
        if not ref_id:
            return ()
        kind = "message" if metadata.get("message_id") else "approval"
        return (EvidenceRef(kind, ref_id),)

    @staticmethod
    def _has_write_basis(request: MemoryMutation) -> bool:
        if request.evidence:
            return True
        return any(
            request.metadata.get(key)
            for key in (
                "message_id",
                "actor_id",
                "approved_batch_id",
                "legacy_manifest",
            )
        )

    @staticmethod
    def _entity_table(entity_type: str) -> tuple[str, str]:
        if entity_type == "claim":
            return "claims", "claim_id"
        if entity_type == "card":
            return "cards", "card_id"
        raise ValueError(f"不支持的实体类型：{entity_type}")


def _normalize(content: str) -> str:
    return " ".join(content.casefold().split())


def _scope_matches(source: MemoryScope, request: MemoryScope) -> bool:
    return source.kind == request.kind and (
        request.identifier == "*"
        or source.identifier == "*"
        or source.identifier == request.identifier
    )


def _source_content_hash(content: str) -> str:
    return hashlib.sha256(_normalize(content).encode("utf-8")).hexdigest()


def _terms(query: str) -> list[str]:
    normalized = _normalize(query.replace("，", " ").replace("。", " "))
    words = re.findall(r"[\w\u3400-\u9fff]+", normalized)
    return list(dict.fromkeys(words))[:12]


def _search_text(content: str, max_ngram: int) -> str:
    normalized = _normalize(content)
    cjk_runs = re.findall(r"[\u3400-\u9fff]+", normalized)
    grams: list[str] = []
    for run in cjk_runs:
        for size in range(1, max_ngram + 1):
            grams.extend(
                run[index : index + size] for index in range(len(run) - size + 1)
            )
    return " ".join([normalized, *grams])


def _fts_query(query: str, max_ngram: int) -> str:
    terms = _terms(query)
    expanded: list[str] = []
    for term in terms:
        expanded.append(term)
        if re.fullmatch(r"[\u3400-\u9fff]+", term):
            expanded.extend(
                term[index : index + max_ngram]
                for index in range(max(0, len(term) - max_ngram + 1))
            )
    safe = [
        f'"{term.replace(chr(34), "")}"' for term in dict.fromkeys(expanded) if term
    ]
    return " OR ".join(safe) or '"__empty__"'


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _is_current(valid_from: str | None, valid_to: str | None, now: datetime) -> bool:
    return (valid_from is None or datetime.fromisoformat(valid_from) <= now) and (
        valid_to is None or now < datetime.fromisoformat(valid_to)
    )


def _validate_status_transition(current: str, target: str, actor: str) -> None:
    if current == target:
        return
    if current in {"deleted", "rejected", "superseded"}:
        raise ValueError(f"历史状态 {current} 不可转移。")
    if current == "frozen" and target in {"active", "deleted"}:
        normalized_actor = actor.casefold()
        is_user = normalized_actor in {"human", "user"} or normalized_actor.startswith(
            "user:"
        )
        if not is_user:
            raise PermissionError("Frozen 记忆只能由用户或人工主体变更。")
        return
    allowed = {
        "candidate": {"active", "approved", "rejected", "deleted"},
        "active": {"approved", "frozen", "superseded", "rejected", "deleted"},
        "approved": {"frozen", "superseded", "rejected", "deleted"},
        "frozen": set(),
    }
    if target not in allowed.get(current, set()):
        raise ValueError(f"不允许的记忆状态转移：{current} -> {target}")


def _execute_sql_script(connection: sqlite3.Connection, script: str) -> None:
    buffer = ""
    for line in script.splitlines():
        buffer += line + "\n"
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                connection.execute(statement)
            buffer = ""
    if buffer.strip():
        connection.execute(buffer.strip())


_SCHEMA = """
CREATE TABLE claims (
    claim_id TEXT PRIMARY KEY, content TEXT NOT NULL, normalized_content TEXT NOT NULL,
    content_hash TEXT NOT NULL, source TEXT NOT NULL, explicitness TEXT NOT NULL,
    scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL, sensitivity TEXT NOT NULL,
    status TEXT NOT NULL, valid_from TEXT, valid_to TEXT, created_at TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT 'general',
    card_kind TEXT NOT NULL DEFAULT 'profile',
    importance REAL NOT NULL DEFAULT 0.5
);
CREATE INDEX claims_scope_status ON claims(scope_kind, scope_id, status, created_at);
CREATE UNIQUE INDEX claims_live_content
ON claims(scope_kind, scope_id, content_hash)
WHERE status IN ('candidate', 'active', 'approved', 'frozen');
CREATE TABLE evidence (
    evidence_id TEXT PRIMARY KEY, claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    kind TEXT NOT NULL, ref_id TEXT NOT NULL, quote TEXT NOT NULL,
    metadata_json TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(claim_id, kind, ref_id)
);
CREATE TABLE cards (
    card_id TEXT PRIMARY KEY, scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL,
    status TEXT NOT NULL, sensitivity TEXT NOT NULL, current_version INTEGER NOT NULL,
    created_at TEXT NOT NULL, projection_key TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX cards_projection_key
ON cards(projection_key) WHERE projection_key <> '';
CREATE TABLE card_versions (
    version_id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES cards(card_id),
    version INTEGER NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL,
    created_at TEXT NOT NULL, UNIQUE(card_id, version)
);
CREATE TABLE card_claim_relations (
    card_id TEXT NOT NULL REFERENCES cards(card_id),
    claim_id TEXT NOT NULL REFERENCES claims(claim_id), relation TEXT NOT NULL,
    created_at TEXT NOT NULL, PRIMARY KEY(card_id, claim_id, relation)
);
CREATE TABLE claim_relations (
    source_claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    target_claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    relation TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(source_claim_id, target_claim_id, relation)
);
CREATE TABLE memory_revisions (
    revision_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
    action TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE consolidation_runs (
    run_id TEXT PRIMARY KEY, batch_key TEXT NOT NULL UNIQUE, trace_start TEXT,
    trace_end TEXT, status TEXT NOT NULL, checkpoint TEXT, error TEXT,
    created_at TEXT NOT NULL, completed_at TEXT
);
CREATE TABLE trajectory_segments (
    segment_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL,
    start_event_id INTEGER NOT NULL,
    end_event_id INTEGER NOT NULL, content TEXT NOT NULL, scope_kind TEXT NOT NULL,
    scope_id TEXT NOT NULL, occurred_at TEXT NOT NULL,
    context_prefix TEXT NOT NULL DEFAULT '',
    search_text TEXT NOT NULL DEFAULT '',
    segmenter_version TEXT NOT NULL DEFAULT '1',
    content_hash TEXT NOT NULL DEFAULT '',
    source_refs_json TEXT NOT NULL DEFAULT '[]',
    UNIQUE(trace_id, start_event_id, end_event_id)
);
CREATE INDEX segments_scope_time
ON trajectory_segments(scope_kind, scope_id, occurred_at);
CREATE TABLE semantic_index (
    memory_type TEXT NOT NULL, memory_id TEXT NOT NULL, content_hash TEXT NOT NULL,
    embedding_model TEXT NOT NULL, embedding_version TEXT NOT NULL,
    dimensions INTEGER NOT NULL, vector_blob BLOB NOT NULL, indexed_at TEXT NOT NULL,
    PRIMARY KEY(memory_type, memory_id)
);
CREATE INDEX semantic_index_version
ON semantic_index(embedding_model, embedding_version, dimensions, memory_type);
CREATE TABLE memory_index_jobs (
    memory_type TEXT NOT NULL, memory_id TEXT NOT NULL, content_hash TEXT NOT NULL,
    state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
    available_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY(memory_type, memory_id)
);
CREATE INDEX memory_index_jobs_state
ON memory_index_jobs(state, available_at, updated_at);
CREATE TABLE memory_projection_jobs (
    projection_type TEXT NOT NULL, projection_key TEXT NOT NULL,
    payload_json TEXT NOT NULL, state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
    available_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY(projection_type, projection_key)
);
CREATE INDEX memory_projection_jobs_state
ON memory_projection_jobs(projection_type, state, available_at, updated_at);
"""

_MIGRATION_1_TO_2 = """
ALTER TABLE claims ADD COLUMN subject TEXT NOT NULL DEFAULT 'general';
ALTER TABLE claims ADD COLUMN card_kind TEXT NOT NULL DEFAULT 'profile';
ALTER TABLE claims ADD COLUMN importance REAL NOT NULL DEFAULT 0.5;
ALTER TABLE cards ADD COLUMN projection_key TEXT NOT NULL DEFAULT '';
CREATE UNIQUE INDEX cards_projection_key
ON cards(projection_key) WHERE projection_key <> '';
ALTER TABLE trajectory_segments
ADD COLUMN context_prefix TEXT NOT NULL DEFAULT '';
ALTER TABLE trajectory_segments
ADD COLUMN search_text TEXT NOT NULL DEFAULT '';
ALTER TABLE trajectory_segments
ADD COLUMN segmenter_version TEXT NOT NULL DEFAULT '1';
ALTER TABLE trajectory_segments
ADD COLUMN content_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE trajectory_segments
ADD COLUMN source_refs_json TEXT NOT NULL DEFAULT '[]';
CREATE TABLE semantic_index (
    memory_type TEXT NOT NULL, memory_id TEXT NOT NULL, content_hash TEXT NOT NULL,
    embedding_model TEXT NOT NULL, embedding_version TEXT NOT NULL,
    dimensions INTEGER NOT NULL, vector_blob BLOB NOT NULL, indexed_at TEXT NOT NULL,
    PRIMARY KEY(memory_type, memory_id)
);
CREATE INDEX semantic_index_version
ON semantic_index(embedding_model, embedding_version, dimensions, memory_type);
CREATE TABLE memory_index_jobs (
    memory_type TEXT NOT NULL, memory_id TEXT NOT NULL, content_hash TEXT NOT NULL,
    state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
    available_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY(memory_type, memory_id)
);
CREATE INDEX memory_index_jobs_state
ON memory_index_jobs(state, available_at, updated_at);
CREATE TABLE memory_projection_jobs (
    projection_type TEXT NOT NULL, projection_key TEXT NOT NULL,
    payload_json TEXT NOT NULL, state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
    available_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY(projection_type, projection_key)
);
CREATE INDEX memory_projection_jobs_state
ON memory_projection_jobs(projection_type, state, available_at, updated_at);
"""

_MIGRATION_2_TO_3 = """
CREATE TABLE claims_v3 (
    claim_id TEXT PRIMARY KEY, content TEXT NOT NULL, normalized_content TEXT NOT NULL,
    content_hash TEXT NOT NULL, source TEXT NOT NULL, explicitness TEXT NOT NULL,
    scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL, sensitivity TEXT NOT NULL,
    status TEXT NOT NULL, valid_from TEXT, valid_to TEXT, created_at TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT 'general',
    card_kind TEXT NOT NULL DEFAULT 'profile',
    importance REAL NOT NULL DEFAULT 0.5
);
INSERT INTO claims_v3 SELECT * FROM claims;
DROP TABLE claims;
ALTER TABLE claims_v3 RENAME TO claims;
CREATE INDEX claims_scope_status ON claims(scope_kind, scope_id, status, created_at);
CREATE UNIQUE INDEX claims_live_content
ON claims(scope_kind, scope_id, content_hash)
WHERE status IN ('candidate', 'active', 'approved', 'frozen');
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS claim_search USING fts5(
    claim_id UNINDEXED, content, search_text, tokenize='unicode61'
);
CREATE VIRTUAL TABLE IF NOT EXISTS card_search USING fts5(
    card_id UNINDEXED, title, content, search_text, tokenize='unicode61'
);
"""
