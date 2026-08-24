"""证据化个人记忆的 SQLite 存储与检索。"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import struct
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from memoli_agent.agent.memory.models import (
    CardDraftStatement,
    CardProjectionKey,
    EvidenceRef,
    GovernanceAudit,
    GovernanceDecision,
    GovernanceJob,
    LongTermUpdateRequest,
    MemoryCard,
    MemoryCardVersion,
    MemoryIndexJob,
    MemoryIndexSource,
    MemoryItem,
    MemoryMutation,
    MemoryQuery,
    MemoryQueryResult,
    MemoryScope,
    QueryPlan,
    TraceConsumption,
    TurnClassification,
    UpdateIntent,
)
from memoli_agent.agent.memory.query_plan import build_query_plan

_SCHEMA_VERSION = 7
_LIVE_STATUSES = ("candidate", "active", "approved", "frozen")
_SENSITIVITY = {"public": 0, "private": 1, "sensitive": 2}


def _allowed_sensitivities(max_sensitivity: str) -> tuple[str, ...]:
    """返回敏感度等级不超过上限的敏感度标签，用于 SQL 下推。"""

    max_rank = _SENSITIVITY.get(max_sensitivity, 1)
    return tuple(name for name, rank in _SENSITIVITY.items() if rank <= max_rank)


def _escape_like(term: str) -> str:
    """转义 LIKE 模式中的 ``%``、``_`` 与 escape 字符。"""

    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
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
                created_at = datetime.now(UTC).isoformat()
                evidence = request.evidence or self._metadata_evidence(request.metadata)
                for ref in evidence:
                    self._insert_evidence(
                        str(existing["claim_id"]),
                        ref,
                        created_at,
                        ignore_duplicate=True,
                    )
                if existing["status"] in {"active", "approved", "frozen"}:
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
                    valid_from, valid_to, created_at, subject, card_kind, importance,
                    revision, fact_type, entity, predicate, value_json, confidence,
                    extractor_name, extractor_version, extractor_schema_version,
                    extractor_prompt_version, extractor_policy_version, provider, model,
                    segmenter_version, input_hash, verification_status,
                    prompt_allowed, embedding_allowed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    str(request.metadata.get("fact_type", "profile")),
                    str(request.metadata.get("entity", "")),
                    str(request.metadata.get("predicate", "")),
                    json.dumps(
                        request.metadata.get("value"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    max(
                        0.0,
                        min(float(request.metadata.get("confidence", 0.5)), 1.0),
                    ),
                    str(request.metadata.get("extractor_name", "")),
                    str(request.metadata.get("extractor_version", "")),
                    str(request.metadata.get("extractor_schema_version", "")),
                    str(request.metadata.get("extractor_prompt_version", "")),
                    str(request.metadata.get("extractor_policy_version", "")),
                    str(request.metadata.get("provider", "")),
                    str(request.metadata.get("model", "")),
                    str(request.metadata.get("segmenter_version", "")),
                    str(request.metadata.get("input_hash", "")),
                    str(request.metadata.get("verification_status", "unverified")),
                    int(
                        bool(
                            request.metadata.get(
                                "prompt_allowed",
                                request.sensitivity != "sensitive",
                            )
                        )
                    ),
                    int(
                        bool(
                            request.metadata.get(
                                "embedding_allowed",
                                request.sensitivity != "sensitive",
                            )
                        )
                    ),
                ),
            )
            evidence = request.evidence or self._metadata_evidence(request.metadata)
            for ref in evidence:
                self._insert_evidence(claim_id, ref, created_at.isoformat())
            self._insert_claim_search(claim_id, content)
            if request.status in {"active", "approved", "frozen"}:
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
                self._enqueue_card_projection(scope, "general", "profile")
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
        statements: tuple[CardDraftStatement, ...] = (),
    ) -> MemoryCard:
        scope = scope or MemoryScope()
        if status not in _VALID_STATUS:
            raise ValueError(f"无效记忆状态：{status}")
        card_id = f"card_{uuid.uuid4().hex}"
        now = datetime.now(UTC).isoformat()
        with self._connection:
            self._connection.execute(
                "INSERT INTO cards(card_id, scope_kind, scope_id, status, sensitivity, "
                "current_version, created_at, projection_key, prompt_allowed, "
                "embedding_allowed) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
                (
                    card_id,
                    scope.kind,
                    scope.identifier,
                    status,
                    sensitivity,
                    now,
                    projection_key,
                    int(sensitivity != "sensitive"),
                    int(sensitivity != "sensitive"),
                ),
            )
            version_id = self._insert_card_version(card_id, 1, title, content, now)
            self._replace_card_statements(
                card_id, version_id, statements, sensitivity, now
            )
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
        self,
        source_claim_id: str,
        target_claim_id: str,
        relation: str,
        *,
        actor: str | None = None,
        expected_target_revision: int | None = None,
    ) -> None:
        """记录 claim 间关系。

        纯边关系（supports/contradicts/derived-from）仅插入一条边，仍校验
        存在/非自环/scope 隔离。替代型关系（supersedes/corrects）要求显式
        ``actor`` 与 ``expected_target_revision``（无弱默认），委托
        ``_supersede_existing_claim_tx`` 原子翻状态、写 corrects+supersedes
        两条关系、清理派生索引并重排 Card 投影。
        """
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
            if relation in {"supersedes", "corrects"}:
                if actor is None or expected_target_revision is None:
                    raise TypeError(
                        "替代关系 (supersedes/corrects) 要求显式提供 actor 与 "
                        "expected_target_revision，不接受弱默认"
                    )
                self._supersede_existing_claim_tx(
                    source_claim_id,
                    target_claim_id,
                    expected_target_revision,
                    actor,
                )
            else:
                src = self._connection.execute(
                    "SELECT scope_kind, scope_id FROM claims WHERE claim_id=?",
                    (source_claim_id,),
                ).fetchone()
                tgt = self._connection.execute(
                    "SELECT scope_kind, scope_id FROM claims WHERE claim_id=?",
                    (target_claim_id,),
                ).fetchone()
                if src is None:
                    raise KeyError(source_claim_id)
                if tgt is None:
                    raise KeyError(target_claim_id)
                if source_claim_id == target_claim_id:
                    raise ValueError("self-link: source 与 target 不能相同")
                if (str(src["scope_kind"]), str(src["scope_id"])) != (
                    str(tgt["scope_kind"]),
                    str(tgt["scope_id"]),
                ):
                    raise PermissionError("relation-scope-mismatch")
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

    def _supersede_existing_claim_tx(
        self,
        source_claim_id: str,
        target_claim_id: str,
        expected_target_revision: int | None,
        actor: str,
    ) -> None:
        """统一替代不变量。

        correct_claim / governance 批准 / link_claims 替代分支共享。

        必须在调用方已开启的事务内执行；本方法不管理 BEGIN/commit/rollback。
        校验：存在、非自环、scope 隔离、事实槽位一致、源存活、target 迁移合法。
        幂等：同一 source 已置替过 target → 直接返回；target 已被其他 source
        置替 → 抛冲突、不记录新边。``expected_target_revision`` 非 None 走乐观并发
        CAS（correct_claim/link_claims）；为 None 走 status 守卫 CAS（governance，
        保留 governance-target-cas-stale 契约）。无论传入 corrects 还是 supersedes，
        均原子写 corrects+supersedes 两条关系，翻 target 为 superseded、删其派生
        索引、幂等重排 source 索引，并对 source/target 各自重排 Card 投影。
        """
        src = self._connection.execute(
            "SELECT status, scope_kind, scope_id, subject, card_kind, "
            "fact_type, entity, predicate, content_hash FROM claims "
            "WHERE claim_id=?",
            (source_claim_id,),
        ).fetchone()
        tgt = self._connection.execute(
            "SELECT status, revision, scope_kind, scope_id, subject, card_kind, "
            "fact_type, entity, predicate FROM claims WHERE claim_id=?",
            (target_claim_id,),
        ).fetchone()
        if src is None:
            raise KeyError(source_claim_id)
        if tgt is None:
            raise KeyError(target_claim_id)
        if source_claim_id == target_claim_id:
            raise ValueError("self-supersede: source 与 target 不能相同")
        if (str(src["scope_kind"]), str(src["scope_id"])) != (
            str(tgt["scope_kind"]),
            str(tgt["scope_id"]),
        ):
            raise PermissionError("supersede-scope-mismatch: source 与 target 跨 scope")
        src_slot = (str(src["fact_type"]), str(src["entity"]), str(src["predicate"]))
        tgt_slot = (str(tgt["fact_type"]), str(tgt["entity"]), str(tgt["predicate"]))
        if all(src_slot) and all(tgt_slot) and src_slot != tgt_slot:
            raise PermissionError("supersede-fact-slot-mismatch: 事实槽位不一致")
        if str(src["status"]) not in _LIVE_STATUSES:
            raise ValueError(
                f"supersede-source-not-live: 源 claim 状态 {src['status']} 不可用于替代"
            )
        now = datetime.now(UTC).isoformat()
        if str(tgt["status"]) == "superseded":
            already = self._connection.execute(
                "SELECT 1 FROM claim_relations WHERE source_claim_id=? "
                "AND target_claim_id=? AND relation IN ('corrects','supersedes')",
                (source_claim_id, target_claim_id),
            ).fetchone()
            if already is not None:
                return
            raise RuntimeError(
                "supersede-conflict: target 已被其他 claim 置替，无法再次替代"
            )
        if expected_target_revision is not None:
            if str(tgt["status"]) not in {"active", "approved"}:
                raise ValueError(
                    f"supersede-target-not-live: target 状态 {tgt['status']} 不可置替"
                )
            _validate_status_transition(str(tgt["status"]), "superseded", actor)
            if int(tgt["revision"]) != int(expected_target_revision):
                raise RuntimeError("stale-claim-revision")
            changed = self._connection.execute(
                "UPDATE claims SET status='superseded', revision=revision+1 "
                "WHERE claim_id=? AND revision=?",
                (target_claim_id, int(expected_target_revision)),
            )
            if changed.rowcount != 1:
                raise RuntimeError("stale-claim-revision")
        else:
            changed = self._connection.execute(
                "UPDATE claims SET status='superseded', revision=revision+1 "
                "WHERE claim_id=? AND status IN ('active','approved')",
                (target_claim_id,),
            )
            if changed.rowcount != 1:
                raise RuntimeError("governance-target-cas-stale")
        for relation in ("corrects", "supersedes"):
            self._connection.execute(
                "INSERT OR IGNORE INTO claim_relations("
                "source_claim_id, target_claim_id, relation, created_at) "
                "VALUES (?, ?, ?, ?)",
                (source_claim_id, target_claim_id, relation, now),
            )
        self._record_revision("claim", target_claim_id, "status:superseded", actor)
        self._delete_derived_index("claim", target_claim_id)
        src_source = self.get_index_source("claim", source_claim_id)
        if src_source is not None:
            self._enqueue_index_job("claim", source_claim_id, src_source.content_hash)
        for claim_id in (source_claim_id, target_claim_id):
            row = self._connection.execute(
                "SELECT scope_kind, scope_id, subject, card_kind FROM claims "
                "WHERE claim_id=?",
                (claim_id,),
            ).fetchone()
            if row is not None:
                self._enqueue_card_projection(
                    MemoryScope(str(row["scope_kind"]), str(row["scope_id"])),
                    str(row["subject"]),
                    str(row["card_kind"]),
                )

    def correct_claim(
        self,
        target_claim_id: str,
        expected_revision: int,
        mutation: MemoryMutation,
        *,
        actor: str,
    ) -> MemoryItem:
        """Atomically create the corrected fact and supersede one expected revision."""

        self._connection.execute("BEGIN IMMEDIATE")
        try:
            target = self._connection.execute(
                "SELECT scope_kind, scope_id, status, revision FROM claims "
                "WHERE claim_id=?",
                (target_claim_id,),
            ).fetchone()
            if target is None:
                raise KeyError(target_claim_id)
            if (
                str(target["scope_kind"]) != mutation.scope.kind
                or str(target["scope_id"]) != mutation.scope.identifier
            ):
                raise PermissionError("correction-scope-mismatch")
            if int(target["revision"]) != expected_revision:
                raise RuntimeError("stale-claim-revision")
            _validate_status_transition(str(target["status"]), "superseded", actor)
            item = self.append_claim(mutation, _manage_transaction=False)
            self._supersede_existing_claim_tx(
                item.item_id, target_claim_id, expected_revision, actor
            )
            self._connection.commit()
            return item
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

    def related_claim_rows(
        self,
        scope: MemoryScope,
        *,
        subject: str,
        fact_type: str,
        entity: str,
        predicate: str,
    ) -> list[dict[str, Any]]:
        """只在同 scope/事实槽位内返回当前正式 Claim。"""

        rows = self._connection.execute(
            "SELECT * FROM claims WHERE scope_kind=? AND scope_id=? AND subject=? "
            "AND fact_type=? AND entity=? AND predicate=? AND status IN "
            "('active','approved','frozen') ORDER BY created_at, claim_id",
            (
                scope.kind,
                scope.identifier,
                subject,
                fact_type,
                entity,
                predicate,
            ),
        ).fetchall()
        now = datetime.now(UTC)
        return [
            dict(row)
            for row in rows
            if _is_current(row["valid_from"], row["valid_to"], now)
        ]

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
            assignment = (
                "status = ?, revision = revision + 1"
                if entity_type == "claim"
                else "status = ?"
            )
            cursor = self._connection.execute(
                f"UPDATE {table} SET {assignment} WHERE {key} = ?",  # noqa: S608
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
        plan = build_query_plan(request)
        rows: list[sqlite3.Row]
        degraded = not self.fts_available
        if "claim" not in request.item_types:
            rows = []
        elif self.fts_available and plan.fts_term_count > 0:
            try:
                rows = list(
                    self._connection.execute(
                        """
                        SELECT c.*, bm25(memory_search) AS score
                        FROM memory_search JOIN claims c
                          ON c.claim_id = memory_search.memory_id
                        WHERE memory_search MATCH ?
                          AND memory_search.memory_type='claim'
                          AND c.scope_kind=?
                          AND (?='*' OR c.scope_id IN (?, '*'))
                        ORDER BY score, c.created_at DESC LIMIT ?
                        """,
                        (
                            plan.fts_match,
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
            # 严格 FTS 无 term (短于 trigram 窗口) 或 FTS 不可用：走有界 Pattern。
            rows, _ = self._like_claims(
                query, request.claim_limit * 4, request.scope
            )
            degraded = not self.fts_available

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
        # FTS 索引仅含 active/approved/frozen 的可检索行；管理查询
        # (含 superseded/deleted 等状态) 或索引未覆盖的权威行用 LIKE 补足。
        if "claim" in request.item_types and len(items) < request.claim_limit:
            seen = {item.item_id for item in items}
            like_rows, _ = self._like_claims(
                query, request.claim_limit * 4, request.scope
            )
            for row in like_rows:
                if row["claim_id"] in seen:
                    continue
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
                items.append(self._claim_item(row, "keyword-like"))
                seen.add(row["claim_id"])
                candidate_count += 1
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
                if _SENSITIVITY.get(str(item.metadata.get("sensitivity")), 2) <= allowed
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
        sensitivity: str = "private",
        prompt_allowed: bool = True,
        embedding_allowed: bool = True,
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
                    segmenter_version, content_hash, source_refs_json, sensitivity,
                    prompt_allowed, embedding_allowed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    sensitivity,
                    int(prompt_allowed),
                    int(embedding_allowed),
                ),
            )
            self._upsert_sparse("episode", segment_id, searchable)
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
                        segmenter_version, content_hash, source_refs_json, sensitivity,
                        prompt_allowed, embedding_allowed
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        segment.get("sensitivity", "private"),
                        int(bool(segment.get("prompt_allowed", True))),
                        int(bool(segment.get("embedding_allowed", True))),
                    ),
                )
                self._upsert_sparse(
                    "episode", segment["segment_id"], segment["search_text"]
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

    def create_long_term_update_request(
        self,
        *,
        source_type: str,
        scope: MemoryScope,
        trace_ids: tuple[str, ...] = (),
        session_id: str = "",
        trace_cursor: str = "",
        version_fingerprint: str = "",
        idempotency_key: str = "",
        priority: int = 0,
        max_attempts: int = 5,
    ) -> LongTermUpdateRequest:
        """幂等创建持久长期整理请求；请求表不保存轨迹正文。"""

        traces = tuple(dict.fromkeys(item for item in trace_ids if item))
        key = (
            idempotency_key
            or hashlib.sha256(
                json.dumps(
                    {
                        "source": source_type,
                        "scope": [scope.kind, scope.identifier],
                        "traces": traces,
                        "session": session_id,
                        "cursor": trace_cursor,
                        "version": version_fingerprint,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
        )
        now = datetime.now(UTC).isoformat()
        request_id = f"ltu_{uuid.uuid4().hex}"
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO long_term_update_requests(
                    request_id, idempotency_key, source_type, session_id,
                    scope_kind, scope_id, trace_ids_json, trace_cursor, state,
                    priority, attempts, max_attempts, worker_id, lease_until,
                    available_at, version_fingerprint, last_error_type,
                    candidate_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, 0, ?, '', NULL,
                          ?, ?, '', 0, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    request_id,
                    key,
                    source_type,
                    session_id,
                    scope.kind,
                    scope.identifier,
                    json.dumps(traces),
                    trace_cursor,
                    priority,
                    max(1, max_attempts),
                    now,
                    version_fingerprint,
                    now,
                    now,
                ),
            )
        row = self._connection.execute(
            "SELECT * FROM long_term_update_requests WHERE idempotency_key=?", (key,)
        ).fetchone()
        assert row is not None
        return self._request_from_row(row)

    def get_long_term_update_request(
        self, request_id: str, scope: MemoryScope | None = None
    ) -> LongTermUpdateRequest | None:
        params: list[Any] = [request_id]
        sql = "SELECT * FROM long_term_update_requests WHERE request_id=?"
        if scope is not None:
            sql += " AND scope_kind=? AND scope_id=?"
            params.extend((scope.kind, scope.identifier))
        row = self._connection.execute(sql, params).fetchone()
        return self._request_from_row(row) if row is not None else None

    def list_long_term_update_requests(
        self, scope: MemoryScope, *, limit: int = 50
    ) -> tuple[LongTermUpdateRequest, ...]:
        rows = self._connection.execute(
            "SELECT * FROM long_term_update_requests WHERE scope_kind=? AND scope_id=? "
            "ORDER BY created_at DESC, request_id LIMIT ?",
            (scope.kind, scope.identifier, max(1, limit)),
        ).fetchall()
        return tuple(self._request_from_row(row) for row in rows)

    def claim_long_term_update_requests(
        self, *, worker_id: str, limit: int, lease_seconds: int
    ) -> tuple[LongTermUpdateRequest, ...]:
        """事务条件领取，避免多个 Worker 双消费。"""

        now = datetime.now(UTC)
        lease_until = (now + timedelta(seconds=max(1, lease_seconds))).isoformat()
        claimed: list[LongTermUpdateRequest] = []
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            rows = self._connection.execute(
                "SELECT request_id FROM long_term_update_requests "
                "WHERE state IN ('pending','retry') AND available_at<=? "
                "ORDER BY priority DESC, created_at, request_id LIMIT ?",
                (now.isoformat(), max(1, limit)),
            ).fetchall()
            for row in rows:
                cursor = self._connection.execute(
                    "UPDATE long_term_update_requests SET state='running', "
                    "attempts=attempts+1, worker_id=?, lease_until=?, updated_at=? "
                    "WHERE request_id=? AND state IN ('pending','retry')",
                    (worker_id, lease_until, now.isoformat(), row["request_id"]),
                )
                if cursor.rowcount:
                    claimed_row = self._connection.execute(
                        "SELECT * FROM long_term_update_requests WHERE request_id=?",
                        (row["request_id"],),
                    ).fetchone()
                    assert claimed_row is not None
                    claimed.append(self._request_from_row(claimed_row))
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return tuple(claimed)

    def renew_long_term_update_lease(
        self, request_id: str, *, worker_id: str, lease_seconds: int
    ) -> bool:
        now = datetime.now(UTC)
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE long_term_update_requests SET lease_until=?, updated_at=? "
                "WHERE request_id=? AND state='running' AND worker_id=?",
                (
                    (now + timedelta(seconds=max(1, lease_seconds))).isoformat(),
                    now.isoformat(),
                    request_id,
                    worker_id,
                ),
            )
        return cursor.rowcount == 1

    def complete_long_term_update_request(
        self, request_id: str, *, worker_id: str, candidate_count: int
    ) -> bool:
        now = datetime.now(UTC).isoformat()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            request = self._connection.execute(
                "SELECT source_type, scope_kind, scope_id, trace_cursor FROM "
                "long_term_update_requests WHERE request_id=? AND state='running' "
                "AND worker_id=?",
                (request_id, worker_id),
            ).fetchone()
            if request is None:
                self._connection.rollback()
                return False
            cursor = self._connection.execute(
                "UPDATE long_term_update_requests SET state='completed', "
                "candidate_count=?, worker_id='', lease_until=NULL, completed_at=?, "
                "last_error_type='', updated_at=? WHERE request_id=? AND "
                "state='running' AND worker_id=?",
                (max(0, candidate_count), now, now, request_id, worker_id),
            )
            if cursor.rowcount == 1:
                self._advance_offline_checkpoint_for_request(request, now)
                self._mark_request_consumptions(
                    request_id, "consumed", now=now, actor="offline-worker"
                )
            self._connection.commit()
            return cursor.rowcount == 1
        except Exception:
            self._connection.rollback()
            raise

    def get_offline_checkpoint(
        self, scope: MemoryScope, *, consumer: str = "trajectory-auto-scan"
    ) -> str:
        row = self._connection.execute(
            "SELECT cursor FROM offline_memory_checkpoints WHERE scope_kind=? "
            "AND scope_id=? AND consumer=?",
            (scope.kind, scope.identifier, consumer),
        ).fetchone()
        return str(row["cursor"]) if row is not None else ""

    def observe_completed_trace(
        self,
        classification: TurnClassification,
        scope: MemoryScope,
        *,
        trace_started_at: datetime,
        consumer: str = "offline-memory-v2",
    ) -> TraceConsumption | None:
        """Persist a completed user trace without changing an existing state."""

        if not classification.completed or classification.kind == "ineligible":
            return None
        now = datetime.now(UTC).isoformat()
        with self._connection:
            self._connection.execute(
                "INSERT INTO memory_trace_consumptions(consumer, scope_kind, scope_id, "
                "session_id, trace_id, trace_started_at, state, turn_kind, "
                "successful_business_tool_calls, distinct_business_tool_kinds, "
                "elapsed_seconds, observed_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'observed', ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(consumer, trace_id) DO NOTHING",
                (
                    consumer,
                    scope.kind,
                    scope.identifier,
                    classification.session_id,
                    classification.trace_id,
                    trace_started_at.isoformat(),
                    classification.kind,
                    classification.successful_business_tool_calls,
                    classification.distinct_business_tool_kinds,
                    classification.elapsed_seconds,
                    now,
                    now,
                    now,
                ),
            )
        return self.get_trace_consumption(classification.trace_id, consumer=consumer)

    def get_trace_consumption(
        self, trace_id: str, *, consumer: str = "offline-memory-v2"
    ) -> TraceConsumption | None:
        row = self._connection.execute(
            "SELECT * FROM memory_trace_consumptions WHERE consumer=? AND trace_id=?",
            (consumer, trace_id),
        ).fetchone()
        return self._consumption_from_row(row) if row is not None else None

    def pending_chat_consumptions(
        self,
        scope: MemoryScope,
        session_id: str,
        *,
        limit: int | None = None,
        consumer: str = "offline-memory-v2",
    ) -> tuple[TraceConsumption, ...]:
        sql = (
            "SELECT * FROM memory_trace_consumptions WHERE consumer=? AND "
            "scope_kind=? AND scope_id=? AND session_id=? AND state='observed' "
            "AND turn_kind='chat' ORDER BY trace_started_at, trace_id"
        )
        params: list[Any] = [consumer, scope.kind, scope.identifier, session_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(max(1, limit))
        rows = self._connection.execute(sql, params).fetchall()
        return tuple(self._consumption_from_row(row) for row in rows)

    def pending_chat_count(
        self,
        scope: MemoryScope,
        session_id: str,
        *,
        consumer: str = "offline-memory-v2",
    ) -> int:
        return len(self.pending_chat_consumptions(scope, session_id, consumer=consumer))

    def reserve_trigger_request(
        self,
        *,
        trigger_kind: str,
        scope: MemoryScope,
        session_id: str,
        trace_ids: tuple[str, ...],
        version_fingerprint: str,
        idempotency_key: str,
        priority: int = 0,
        max_attempts: int = 5,
        consumer: str = "offline-memory-v2",
    ) -> LongTermUpdateRequest | None:
        """Atomically reserve a stable trace set and create exactly one request."""

        traces = tuple(dict.fromkeys(item for item in trace_ids if item))
        if not traces or trigger_kind not in {"chat-window", "long-task"}:
            raise ValueError("invalid-trigger-reservation")
        now = datetime.now(UTC).isoformat()
        request_id = f"ltu_{uuid.uuid4().hex}"
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._connection.execute(
                "SELECT * FROM long_term_update_requests WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                self._connection.commit()
                return self._request_from_row(existing)
            placeholders = ",".join("?" for _ in traces)
            rows = self._connection.execute(
                f"SELECT trace_id, state FROM memory_trace_consumptions "  # noqa: S608
                f"WHERE consumer=? AND trace_id IN ({placeholders})",
                (consumer, *traces),
            ).fetchall()
            if len(rows) != len(traces) or any(
                str(row["state"]) not in {"observed", "released"} for row in rows
            ):
                self._connection.rollback()
                return None
            cursor = max(
                str(
                    self._connection.execute(
                        "SELECT trace_started_at || '|' || trace_id FROM "
                        "memory_trace_consumptions WHERE consumer=? AND trace_id=?",
                        (consumer, trace_id),
                    ).fetchone()[0]
                )
                for trace_id in traces
            )
            self._connection.execute(
                "INSERT INTO long_term_update_requests(request_id, idempotency_key, "
                "source_type, session_id, scope_kind, scope_id, trace_ids_json, "
                "trace_cursor, state, priority, attempts, max_attempts, worker_id, "
                "lease_until, available_at, version_fingerprint, last_error_type, "
                "candidate_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, "
                "?, 'pending', ?, 0, ?, '', NULL, ?, ?, '', 0, ?, ?)",
                (
                    request_id,
                    idempotency_key,
                    trigger_kind,
                    session_id,
                    scope.kind,
                    scope.identifier,
                    json.dumps(traces),
                    cursor,
                    priority,
                    max(1, max_attempts),
                    now,
                    version_fingerprint,
                    now,
                    now,
                ),
            )
            for trace_id in traces:
                changed = self._connection.execute(
                    "UPDATE memory_trace_consumptions SET state='reserved', "
                    "trigger_kind=?, request_id=?, reserved_at=?, released_at=NULL, "
                    "actor='', reason='', updated_at=? WHERE consumer=? AND trace_id=? "
                    "AND state IN ('observed','released')",
                    (
                        trigger_kind,
                        request_id,
                        now,
                        now,
                        consumer,
                        trace_id,
                    ),
                )
                if changed.rowcount != 1:
                    raise RuntimeError("trace-reservation-raced")
            row = self._connection.execute(
                "SELECT * FROM long_term_update_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            self._connection.commit()
            assert row is not None
            return self._request_from_row(row)
        except Exception:
            self._connection.rollback()
            raise

    def create_update_intent(
        self,
        scope: MemoryScope,
        session_id: str,
        boundary_key: str,
    ) -> UpdateIntent:
        key = hashlib.sha256(
            f"{scope.kind}:{scope.identifier}:{session_id}:{boundary_key}".encode()
        ).hexdigest()
        hint_id = f"hint_{key[:24]}"
        now = datetime.now(UTC).isoformat()
        with self._connection:
            self._connection.execute(
                "INSERT INTO memory_update_intents(hint_id, idempotency_key, "
                "scope_kind, "
                "scope_id, session_id, boundary_key, state, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'waiting-for-trigger', ?, ?) "
                "ON CONFLICT(idempotency_key) DO NOTHING",
                (
                    hint_id,
                    key,
                    scope.kind,
                    scope.identifier,
                    session_id,
                    boundary_key,
                    now,
                    now,
                ),
            )
        row = self._connection.execute(
            "SELECT * FROM memory_update_intents WHERE idempotency_key=?", (key,)
        ).fetchone()
        assert row is not None
        return self._intent_from_row(row)

    def satisfy_update_intents(self, scope: MemoryScope, session_id: str) -> int:
        now = datetime.now(UTC).isoformat()
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE memory_update_intents SET state='satisfied', updated_at=? "
                "WHERE scope_kind=? AND scope_id=? AND session_id=? "
                "AND state='waiting-for-trigger'",
                (now, scope.kind, scope.identifier, session_id),
            )
        return int(cursor.rowcount)

    def has_unfinished_auto_scan(self, scope: MemoryScope) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM long_term_update_requests WHERE source_type='auto-scan' "
            "AND scope_kind=? AND scope_id=? AND state NOT IN "
            "('completed','cancelled') LIMIT 1",
            (scope.kind, scope.identifier),
        ).fetchone()
        return row is not None

    def _advance_offline_checkpoint_for_request(
        self, request: sqlite3.Row, now: str
    ) -> None:
        cursor = str(request["trace_cursor"] or "")
        if str(request["source_type"]) != "auto-scan" or not cursor:
            return
        self._connection.execute(
            "INSERT INTO offline_memory_checkpoints(scope_kind, scope_id, consumer, "
            "cursor, updated_at) VALUES (?, ?, 'trajectory-auto-scan', ?, ?) "
            "ON CONFLICT(scope_kind, scope_id, consumer) DO UPDATE SET "
            "cursor=CASE WHEN excluded.cursor>offline_memory_checkpoints.cursor "
            "THEN excluded.cursor ELSE offline_memory_checkpoints.cursor END, "
            "updated_at=excluded.updated_at",
            (request["scope_kind"], request["scope_id"], cursor, now),
        )

    def fail_long_term_update_request(
        self,
        request_id: str,
        *,
        worker_id: str,
        error_type: str,
        permanent: bool = False,
        retry_seconds: float = 5.0,
    ) -> str:
        row = self._connection.execute(
            "SELECT attempts, max_attempts FROM long_term_update_requests "
            "WHERE request_id=? AND state='running' AND worker_id=?",
            (request_id, worker_id),
        ).fetchone()
        if row is None:
            return "stale"
        state = (
            "quarantined"
            if permanent or int(row["attempts"]) >= int(row["max_attempts"])
            else "retry"
        )
        now = datetime.now(UTC)
        available = now + timedelta(seconds=max(0.0, retry_seconds))
        with self._connection:
            self._connection.execute(
                "UPDATE long_term_update_requests SET state=?, worker_id='', "
                "lease_until=NULL, available_at=?, last_error_type=?, updated_at=? "
                "WHERE request_id=? AND state='running' AND worker_id=?",
                (
                    state,
                    available.isoformat(),
                    error_type[:120],
                    now.isoformat(),
                    request_id,
                    worker_id,
                ),
            )
            if state == "quarantined":
                self._mark_request_consumptions(
                    request_id,
                    "quarantined",
                    now=now.isoformat(),
                    actor="offline-worker",
                    reason=error_type[:120],
                )
        return state

    def cancel_long_term_update_request(
        self, request_id: str, scope: MemoryScope
    ) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE long_term_update_requests SET state='suppressed', "
                "worker_id='', "
                "lease_until=NULL, updated_at=? WHERE request_id=? AND scope_kind=? "
                "AND scope_id=? AND state IN ('pending','retry','quarantined') "
                "AND candidate_count=0",
                (now, request_id, scope.kind, scope.identifier),
            )
            if cursor.rowcount == 1:
                self._mark_request_consumptions(
                    request_id,
                    "suppressed",
                    now=now,
                    actor="operator",
                    reason="request-cancelled",
                )
        return cursor.rowcount == 1

    def retry_long_term_update_request(
        self, request_id: str, scope: MemoryScope
    ) -> bool:
        now = datetime.now(UTC).isoformat()
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE long_term_update_requests SET state='retry', attempts=0, "
                "worker_id='', lease_until=NULL, available_at=?, last_error_type='', "
                "updated_at=? WHERE request_id=? AND scope_kind=? AND scope_id=? "
                "AND state='quarantined' AND candidate_count=0",
                (now, now, request_id, scope.kind, scope.identifier),
            )
            if cursor.rowcount == 1:
                self._mark_request_consumptions(
                    request_id, "reserved", now=now, actor="operator", reason="retry"
                )
        return cursor.rowcount == 1

    def force_release_long_term_update_request(
        self,
        request_id: str,
        scope: MemoryScope,
        *,
        actor: str,
        reason: str,
    ) -> bool:
        if not actor.strip() or not reason.strip():
            raise ValueError("force-release-requires-actor-and-reason")
        now = datetime.now(UTC).isoformat()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            request = self._connection.execute(
                "SELECT state, candidate_count FROM long_term_update_requests "
                "WHERE request_id=? AND scope_kind=? AND scope_id=?",
                (request_id, scope.kind, scope.identifier),
            ).fetchone()
            if (
                request is None
                or str(request["state"]) not in {"quarantined", "suppressed"}
                or int(request["candidate_count"]) != 0
            ):
                self._connection.rollback()
                return False
            self._mark_request_consumptions(
                request_id,
                "released",
                now=now,
                actor=actor,
                reason=reason,
            )
            self._connection.execute(
                "UPDATE long_term_update_requests SET updated_at=? WHERE request_id=?",
                (now, request_id),
            )
            self._record_revision(
                "consolidation-request", request_id, "force-release", actor
            )
            self._connection.commit()
            return True
        except Exception:
            self._connection.rollback()
            raise

    def _mark_request_consumptions(
        self,
        request_id: str,
        state: str,
        *,
        now: str,
        actor: str,
        reason: str = "",
    ) -> int:
        fields = {
            "consumed": "consumed_at=?",
            "released": "released_at=?",
        }
        extra = fields.get(state)
        sql = (
            "UPDATE memory_trace_consumptions SET state=?, actor=?, reason=?, "
            "updated_at=?"
        )
        params: list[Any] = [state, actor, reason, now]
        if extra:
            sql += f", {extra}"  # noqa: S608
            params.append(now)
        sql += " WHERE request_id=?"
        params.append(request_id)
        cursor = self._connection.execute(sql, params)
        return int(cursor.rowcount)

    def recover_expired_long_term_update_leases(self) -> int:
        now = datetime.now(UTC).isoformat()
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE long_term_update_requests SET state='retry', worker_id='', "
                "lease_until=NULL, available_at=?, last_error_type='lease-expired', "
                "updated_at=? WHERE state='running' AND lease_until IS NOT NULL "
                "AND lease_until<=?",
                (now, now, now),
            )
        return int(cursor.rowcount)

    def enqueue_governance_job(
        self,
        candidate_id: str,
        *,
        expected_revision: int,
        governor_version: str,
        policy_version: str,
        prompt_version: str,
        max_attempts: int = 5,
        initial_state: str = "pending",
        escalation_reason: str = "",
        _manage_transaction: bool = True,
    ) -> GovernanceJob:
        if initial_state not in {"pending", "needs-user-review"}:
            raise ValueError("治理任务初始状态无效。")
        key = hashlib.sha256(
            f"{candidate_id}:{expected_revision}:{governor_version}:"
            f"{policy_version}:{prompt_version}".encode()
        ).hexdigest()
        now = datetime.now(UTC).isoformat()
        job_id = f"gov_{uuid.uuid4().hex}"
        if _manage_transaction:
            self._connection.execute("BEGIN IMMEDIATE")
        try:
            candidate = self._connection.execute(
                "SELECT status, revision FROM claims WHERE claim_id=?",
                (candidate_id,),
            ).fetchone()
            if candidate is None or candidate["status"] != "candidate":
                raise ValueError("治理任务只能绑定 candidate Claim。")
            self._connection.execute(
                """
                INSERT INTO governance_jobs(
                    job_id, idempotency_key, candidate_id, expected_revision, state,
                    governor_version, policy_version, prompt_version, attempts,
                    max_attempts, worker_id, lease_until, available_at,
                    last_error_type, task_id, escalation_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, '', NULL, ?, '', '', ?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    job_id,
                    key,
                    candidate_id,
                    expected_revision,
                    initial_state,
                    governor_version,
                    policy_version,
                    prompt_version,
                    max(1, max_attempts),
                    now,
                    escalation_reason[:240],
                    now,
                    now,
                ),
            )
            row = self._connection.execute(
                "SELECT * FROM governance_jobs WHERE idempotency_key=?", (key,)
            ).fetchone()
            assert row is not None
            if _manage_transaction:
                self._connection.commit()
        except Exception:
            if _manage_transaction:
                self._connection.rollback()
            raise
        return self._governance_job_from_row(row)

    def get_governance_job(self, job_id: str) -> GovernanceJob | None:
        row = self._connection.execute(
            "SELECT * FROM governance_jobs WHERE job_id=?", (job_id,)
        ).fetchone()
        return self._governance_job_from_row(row) if row is not None else None

    def list_governance_jobs(
        self,
        scope: MemoryScope,
        *,
        state: str | None = None,
        limit: int = 50,
    ) -> tuple[GovernanceJob, ...]:
        sql = (
            "SELECT g.* FROM governance_jobs g JOIN claims c "
            "ON c.claim_id=g.candidate_id WHERE c.scope_kind=? AND c.scope_id=?"
        )
        params: list[Any] = [scope.kind, scope.identifier]
        if state is not None:
            sql += " AND g.state=?"
            params.append(state)
        sql += " ORDER BY g.created_at DESC, g.job_id LIMIT ?"
        params.append(max(1, limit))
        rows = self._connection.execute(sql, params).fetchall()
        return tuple(self._governance_job_from_row(row) for row in rows)

    def latest_governance_job(self, candidate_id: str) -> GovernanceJob | None:
        row = self._connection.execute(
            "SELECT * FROM governance_jobs WHERE candidate_id=? "
            "ORDER BY created_at DESC, job_id DESC LIMIT 1",
            (candidate_id,),
        ).fetchone()
        return self._governance_job_from_row(row) if row is not None else None

    def attach_governance_task(
        self, job_id: str, task_id: str, *, worker_id: str
    ) -> bool:
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE governance_jobs SET task_id=?, updated_at=? WHERE job_id=? "
                "AND state='running' AND worker_id=?",
                (task_id, datetime.now(UTC).isoformat(), job_id, worker_id),
            )
        return cursor.rowcount == 1

    def latest_governance_audit(self, job_id: str) -> GovernanceAudit | None:
        row = self._connection.execute(
            "SELECT * FROM governance_decisions WHERE job_id=? "
            "ORDER BY created_at DESC, decision_id DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        return self._governance_audit_from_row(row) if row is not None else None

    def claim_governance_jobs(
        self, *, worker_id: str, limit: int, lease_seconds: int
    ) -> tuple[GovernanceJob, ...]:
        now = datetime.now(UTC)
        lease_until = (now + timedelta(seconds=max(1, lease_seconds))).isoformat()
        jobs: list[GovernanceJob] = []
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            rows = self._connection.execute(
                "SELECT job_id FROM governance_jobs WHERE state IN ('pending','retry') "
                "AND available_at<=? ORDER BY created_at, job_id LIMIT ?",
                (now.isoformat(), max(1, limit)),
            ).fetchall()
            for row in rows:
                cursor = self._connection.execute(
                    "UPDATE governance_jobs SET state='running', attempts=attempts+1, "
                    "worker_id=?, lease_until=?, updated_at=? WHERE job_id=? "
                    "AND state IN ('pending','retry')",
                    (worker_id, lease_until, now.isoformat(), row["job_id"]),
                )
                if cursor.rowcount:
                    claimed = self._connection.execute(
                        "SELECT * FROM governance_jobs WHERE job_id=?", (row["job_id"],)
                    ).fetchone()
                    assert claimed is not None
                    jobs.append(self._governance_job_from_row(claimed))
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return tuple(jobs)

    def renew_governance_lease(
        self, job_id: str, *, worker_id: str, lease_seconds: int
    ) -> bool:
        now = datetime.now(UTC)
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE governance_jobs SET lease_until=?, updated_at=? WHERE job_id=? "
                "AND state='running' AND worker_id=?",
                (
                    (now + timedelta(seconds=max(1, lease_seconds))).isoformat(),
                    now.isoformat(),
                    job_id,
                    worker_id,
                ),
            )
        return cursor.rowcount == 1

    def fail_governance_job(
        self,
        job_id: str,
        *,
        worker_id: str,
        error_type: str,
        permanent: bool = False,
        needs_user_review: bool = False,
        retry_seconds: float = 5.0,
    ) -> str:
        row = self._connection.execute(
            "SELECT attempts, max_attempts FROM governance_jobs WHERE job_id=? "
            "AND state='running' AND worker_id=?",
            (job_id, worker_id),
        ).fetchone()
        if row is None:
            return "stale"
        if needs_user_review:
            state = "needs-user-review"
        elif permanent or int(row["attempts"]) >= int(row["max_attempts"]):
            state = "dead-letter"
        else:
            state = "retry"
        now = datetime.now(UTC)
        with self._connection:
            self._connection.execute(
                "UPDATE governance_jobs SET state=?, worker_id='', lease_until=NULL, "
                "available_at=?, last_error_type=?, escalation_reason=?, updated_at=? "
                "WHERE job_id=? AND state='running' AND worker_id=?",
                (
                    state,
                    (now + timedelta(seconds=max(0.0, retry_seconds))).isoformat(),
                    error_type[:120],
                    error_type[:240] if needs_user_review else "",
                    now.isoformat(),
                    job_id,
                    worker_id,
                ),
            )
        return state

    def recover_expired_governance_leases(self) -> int:
        now = datetime.now(UTC).isoformat()
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE governance_jobs SET state='retry', worker_id='', "
                "lease_until=NULL, available_at=?, last_error_type='lease-expired', "
                "updated_at=? WHERE state='running' AND lease_until IS NOT NULL "
                "AND lease_until<=?",
                (now, now, now),
            )
        return int(cursor.rowcount)

    def retry_governance_job(
        self, job_id: str, scope: MemoryScope
    ) -> tuple[GovernanceJob | None, GovernanceJob | None]:
        """Conditionally requeue a dead-letter job and retain audit fields."""

        self._connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._connection.execute(
                "SELECT g.*, c.scope_kind AS candidate_scope_kind, "
                "c.scope_id AS candidate_scope_id, c.status AS candidate_status, "
                "c.revision AS candidate_revision FROM governance_jobs g "
                "JOIN claims c ON c.claim_id=g.candidate_id WHERE g.job_id=?",
                (job_id,),
            ).fetchone()
            if row is None:
                self._connection.rollback()
                return None, None
            before = self._governance_job_from_row(row)
            if (
                before.state != "dead-letter"
                or str(row["candidate_scope_kind"]) != scope.kind
                or str(row["candidate_scope_id"]) != scope.identifier
                or str(row["candidate_status"]) != "candidate"
                or int(row["candidate_revision"]) != before.expected_revision
            ):
                self._connection.rollback()
                return before, None
            now = datetime.now(UTC).isoformat()
            changed = self._connection.execute(
                "UPDATE governance_jobs SET state='retry', attempts=0, worker_id='', "
                "lease_until=NULL, available_at=?, updated_at=? WHERE job_id=? "
                "AND state='dead-letter' AND expected_revision=?",
                (now, now, job_id, before.expected_revision),
            )
            if changed.rowcount != 1:
                self._connection.rollback()
                return before, None
            after_row = self._connection.execute(
                "SELECT * FROM governance_jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            self._record_revision("governance-job", job_id, "retry", "operator")
            self._connection.commit()
            assert after_row is not None
            return before, self._governance_job_from_row(after_row)
        except Exception:
            self._connection.rollback()
            raise

    def list_candidate_rows(
        self,
        scope: MemoryScope,
        *,
        states: tuple[str, ...] = ("candidate",),
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        placeholders = ",".join("?" for _ in states)
        rows = self._connection.execute(
            "SELECT c.*, g.job_id, g.state AS governance_state, "
            "g.escalation_reason FROM claims c LEFT JOIN governance_jobs g ON "
            "g.candidate_id=c.claim_id AND g.expected_revision=c.revision "
            f"WHERE c.scope_kind=? AND c.scope_id=? AND c.status IN ({placeholders}) "
            "ORDER BY c.created_at DESC, c.claim_id LIMIT ?",  # noqa: S608
            (scope.kind, scope.identifier, *states, max(1, limit)),
        ).fetchall()
        return [dict(row) for row in rows]

    def candidate_detail(
        self, candidate_id: str, scope: MemoryScope
    ) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM claims WHERE claim_id=? AND scope_kind=? AND scope_id=?",
            (candidate_id, scope.kind, scope.identifier),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["evidence"] = [
            dict(item)
            for item in self._connection.execute(
                "SELECT evidence_id, kind, ref_id, quote, metadata_json, locator_json, "
                "content_hash, verified FROM evidence WHERE claim_id=? "
                "ORDER BY created_at, evidence_id",
                (candidate_id,),
            ).fetchall()
        ]
        result["relations"] = [
            dict(item)
            for item in self._connection.execute(
                "SELECT * FROM candidate_relations WHERE candidate_id=? "
                "ORDER BY relation, target_claim_id",
                (candidate_id,),
            ).fetchall()
        ]
        result["governance"] = [
            dict(item)
            for item in self._connection.execute(
                "SELECT * FROM governance_jobs WHERE candidate_id=? "
                "ORDER BY created_at, job_id",
                (candidate_id,),
            ).fetchall()
        ]
        return result

    def claim_row(self, claim_id: str) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM claims WHERE claim_id=?", (claim_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def record_governance_decision(
        self,
        job_id: str,
        decision: GovernanceDecision,
        *,
        actor: str,
        outcome: str,
        worker_id: str = "",
    ) -> GovernanceAudit:
        """以 Candidate revision 做 CAS，并原子保存不可变治理审计。"""

        if outcome not in {
            "approved",
            "rejected",
            "escalated",
            "deferred",
            "stale",
            "denied",
        }:
            raise ValueError("治理结果无效。")
        decision_key = hashlib.sha256(
            json.dumps(
                {
                    "candidate": decision.candidate_id,
                    "revision": decision.expected_revision,
                    "decision": decision.decision,
                    "governor": decision.governor_version,
                    "policy": decision.policy_version,
                    "actor": actor,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            existing = self._connection.execute(
                "SELECT * FROM governance_decisions WHERE decision_key=?",
                (decision_key,),
            ).fetchone()
            if existing is not None:
                self._connection.commit()
                return self._governance_audit_from_row(existing)
            job = self._connection.execute(
                "SELECT * FROM governance_jobs WHERE job_id=? AND candidate_id=?",
                (job_id, decision.candidate_id),
            ).fetchone()
            if job is None:
                raise KeyError(job_id)
            if worker_id and (
                job["state"] != "running" or str(job["worker_id"]) != worker_id
            ):
                outcome = "stale"
            candidate = self._connection.execute(
                "SELECT * FROM claims WHERE claim_id=?",
                (decision.candidate_id,),
            ).fetchone()
            if candidate is None:
                raise KeyError(decision.candidate_id)
            actual_revision = int(candidate["revision"])
            if (
                actual_revision != decision.expected_revision
                or candidate["status"] != "candidate"
            ):
                outcome = "stale"
            now = datetime.now(UTC).isoformat()
            if outcome in {"approved", "rejected"}:
                relation = decision.relation
                target_id = decision.target_claim_id
                proposed = self._connection.execute(
                    "SELECT * FROM candidate_relations WHERE candidate_id=? "
                    "AND status='proposed' ORDER BY relation, target_claim_id",
                    (decision.candidate_id,),
                ).fetchall()
                if outcome == "approved" and not relation and len(proposed) == 1:
                    relation = str(proposed[0]["relation"])
                    target_id = str(proposed[0]["target_claim_id"])
                target = None
                if outcome == "approved" and relation in {
                    "supports",
                    "corrects",
                    "supersedes",
                }:
                    target = next(
                        (
                            row
                            for row in proposed
                            if row["relation"] == relation
                            and row["target_claim_id"] == target_id
                        ),
                        None,
                    )
                    target_claim = self._connection.execute(
                        "SELECT * FROM claims WHERE claim_id=?",
                        (target_id,),
                    ).fetchone()
                    if (
                        target is None
                        or target_claim is None
                        or target_claim["scope_kind"] != candidate["scope_kind"]
                        or target_claim["scope_id"] != candidate["scope_id"]
                        or int(target_claim["revision"])
                        != int(target["expected_target_revision"])
                        or target_claim["status"] == "frozen"
                    ):
                        outcome = "stale"
                new_status = (
                    "superseded"
                    if outcome == "approved" and relation == "supports"
                    else "approved"
                    if outcome == "approved"
                    else "rejected"
                )
                cursor = self._connection.execute(
                    "UPDATE claims SET status=?, revision=revision+1 WHERE claim_id=? "
                    "AND status='candidate' AND revision=?",
                    (
                        new_status,
                        decision.candidate_id,
                        decision.expected_revision if outcome != "stale" else -1,
                    ),
                )
                if cursor.rowcount != 1:
                    outcome = "stale"
                else:
                    actual_revision += 1
                    self._record_revision(
                        "claim", decision.candidate_id, f"status:{new_status}", actor
                    )
                    if outcome == "approved":
                        projection_claim_id = decision.candidate_id
                        projection_hash = str(candidate["content_hash"])
                        if relation == "supports" and target_id:
                            self._merge_candidate_evidence(
                                decision.candidate_id, target_id, now
                            )
                            projection_claim_id = target_id
                            target_claim = self._connection.execute(
                                "SELECT content_hash FROM claims WHERE claim_id=?",
                                (target_id,),
                            ).fetchone()
                            assert target_claim is not None
                            projection_hash = str(target_claim["content_hash"])
                        elif relation in {"corrects", "supersedes"} and target_id:
                            self._supersede_existing_claim_tx(
                                decision.candidate_id, target_id, None, actor
                            )
                            self._connection.execute(
                                "UPDATE candidate_relations SET status='accepted' "
                                "WHERE candidate_id=? AND target_claim_id=? "
                                "AND relation=?",
                                (decision.candidate_id, target_id, relation),
                            )
                        self._enqueue_index_job(
                            "claim", projection_claim_id, projection_hash
                        )
                        self._enqueue_card_projection(
                            MemoryScope(
                                str(candidate["scope_kind"]),
                                str(candidate["scope_id"]),
                            ),
                            str(candidate["subject"]),
                            str(candidate["card_kind"]),
                        )
            job_state = {
                "approved": "completed",
                "rejected": "completed",
                "escalated": "needs-user-review",
                "deferred": "retry",
                "stale": "completed",
                "denied": "completed",
            }[outcome]
            decision_id = f"gdec_{uuid.uuid4().hex}"
            self._connection.execute(
                """
                INSERT INTO governance_decisions(
                    decision_id, decision_key, job_id, candidate_id,
                    expected_revision, actual_revision, decision, outcome, actor,
                    confidence, reason_codes_json, governor_version, prompt_version,
                    policy_version, relation, target_claim_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    decision_key,
                    job_id,
                    decision.candidate_id,
                    decision.expected_revision,
                    actual_revision,
                    decision.decision,
                    outcome,
                    actor,
                    max(0.0, min(decision.confidence, 1.0)),
                    json.dumps(decision.reason_codes),
                    decision.governor_version,
                    decision.prompt_version,
                    decision.policy_version,
                    decision.relation,
                    decision.target_claim_id,
                    now,
                ),
            )
            self._connection.execute(
                "UPDATE governance_jobs SET state=?, worker_id='', lease_until=NULL, "
                "last_error_type='', escalation_reason=?, updated_at=?, completed_at=? "
                "WHERE job_id=?",
                (
                    job_state,
                    ",".join(decision.reason_codes)[:240]
                    if job_state == "needs-user-review"
                    else "",
                    now,
                    now if job_state == "completed" else None,
                    job_id,
                ),
            )
            row = self._connection.execute(
                "SELECT * FROM governance_decisions WHERE decision_id=?",
                (decision_id,),
            ).fetchone()
            assert row is not None
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return self._governance_audit_from_row(row)

    def _merge_candidate_evidence(
        self, candidate_id: str, target_id: str, now: str
    ) -> None:
        rows = self._connection.execute(
            "SELECT * FROM evidence WHERE claim_id=?", (candidate_id,)
        ).fetchall()
        for row in rows:
            identity = hashlib.sha256(
                f"{target_id}:{row['kind']}:{row['ref_id']}:"
                f"{row['content_hash']}:{row['locator_json']}".encode()
            ).hexdigest()
            self._connection.execute(
                "INSERT OR IGNORE INTO evidence(evidence_id, claim_id, kind, ref_id, "
                "quote, metadata_json, created_at, locator_json, content_hash, "
                "verified, prompt_allowed, embedding_allowed) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"ev_{identity}",
                    target_id,
                    row["kind"],
                    row["ref_id"],
                    row["quote"],
                    row["metadata_json"],
                    now,
                    row["locator_json"],
                    row["content_hash"],
                    row["verified"],
                    row["prompt_allowed"],
                    row["embedding_allowed"],
                ),
            )

    def count_needs_user_review(self, scope: MemoryScope) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM governance_jobs g JOIN claims c "
            "ON c.claim_id=g.candidate_id WHERE g.state='needs-user-review' "
            "AND c.scope_kind=? AND c.scope_id=? AND c.status='candidate'",
            (scope.kind, scope.identifier),
        ).fetchone()
        return int(row[0]) if row else 0

    def begin_consolidation(
        self,
        batch_key: str,
        trace_start: str,
        trace_end: str,
        *,
        request_id: str = "",
        version_metadata: dict[str, str] | None = None,
        max_attempts: int = 5,
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
            metadata = version_metadata or {}
            now = datetime.now(UTC).isoformat()
            self._connection.execute(
                """
                INSERT INTO consolidation_runs(
                    run_id, batch_key, trace_start, trace_end, status, created_at,
                    request_id, extractor_name, extractor_version, schema_version,
                    prompt_version, policy_version, provider, model,
                    segmenter_version, input_hash, version_fingerprint, attempts,
                    max_attempts, available_at, updated_at
                ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, 1, ?, ?, ?)
                ON CONFLICT(batch_key) DO UPDATE SET
                    status='running', error=NULL, last_error_type='',
                    completed_at=NULL, attempts=consolidation_runs.attempts+1,
                    updated_at=excluded.updated_at
                """,
                (
                    run_id,
                    batch_key,
                    trace_start,
                    trace_end,
                    now,
                    request_id,
                    metadata.get("extractor_name", ""),
                    metadata.get("extractor_version", ""),
                    metadata.get("schema_version", ""),
                    metadata.get("prompt_version", ""),
                    metadata.get("policy_version", ""),
                    metadata.get("provider", ""),
                    metadata.get("model", ""),
                    metadata.get("segmenter_version", ""),
                    metadata.get("input_hash", ""),
                    metadata.get("version_fingerprint", ""),
                    max(1, max_attempts),
                    now,
                    now,
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
                "UPDATE consolidation_runs SET status='failed', error=?, "
                "last_error_type=?, updated_at=? WHERE run_id=?",
                (error[:2_000], error[:120], datetime.now(UTC).isoformat(), run_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(run_id)

    def apply_consolidation_batch(
        self,
        run_id: str,
        checkpoint: str,
        entries: list[tuple[MemoryMutation, tuple[tuple[str, str], ...]]],
        *,
        request_id: str = "",
        worker_id: str = "",
        governor_version: str = "",
        policy_version: str = "",
        prompt_version: str = "",
        governance_max_attempts: int = 5,
    ) -> tuple[str, ...]:
        """在一个事务内写入候选、关系、治理任务、请求和 checkpoint。"""

        self._connection.execute("BEGIN IMMEDIATE")
        candidate_ids: list[str] = []
        try:
            for mutation, relations in entries:
                formal_claim_id = self._find_formal_duplicate(mutation)
                if formal_claim_id:
                    evidence = mutation.evidence or self._metadata_evidence(
                        mutation.metadata
                    )
                    for ref in evidence:
                        self._insert_evidence(
                            formal_claim_id,
                            ref,
                            datetime.now(UTC).isoformat(),
                            ignore_duplicate=True,
                        )
                    continue
                item = self.append_claim(mutation, _manage_transaction=False)
                is_duplicate = item.recall_reason == "exact-hash"
                if not is_duplicate:
                    candidate_ids.append(item.item_id)
                else:
                    continue
                for target_id, relation in relations:
                    target = self._connection.execute(
                        "SELECT scope_kind, scope_id, revision FROM claims "
                        "WHERE claim_id=?",
                        (target_id,),
                    ).fetchone()
                    if target is None:
                        raise ValueError("候选关系目标不存在。")
                    if (
                        target["scope_kind"] != mutation.scope.kind
                        or target["scope_id"] != mutation.scope.identifier
                    ):
                        raise PermissionError("候选关系目标跨 scope。")
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
                    self._connection.execute(
                        "INSERT OR IGNORE INTO candidate_relations("
                        "candidate_id, target_claim_id, relation, "
                        "expected_target_revision, confidence, status, created_at) "
                        "VALUES (?, ?, ?, ?, 1.0, 'proposed', ?)",
                        (
                            item.item_id,
                            target_id,
                            relation,
                            int(target["revision"]),
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                if (
                    not is_duplicate
                    and mutation.status == "candidate"
                    and governor_version
                    and policy_version
                    and prompt_version
                ):
                    has_conflict = any(
                        relation == "contradicts" for _, relation in relations
                    )
                    self.enqueue_governance_job(
                        item.item_id,
                        expected_revision=0,
                        governor_version=governor_version,
                        policy_version=policy_version,
                        prompt_version=prompt_version,
                        max_attempts=governance_max_attempts,
                        initial_state=(
                            "needs-user-review" if has_conflict else "pending"
                        ),
                        escalation_reason=(
                            "unresolved-conflict" if has_conflict else ""
                        ),
                        _manage_transaction=False,
                    )
            now = datetime.now(UTC).isoformat()
            cursor = self._connection.execute(
                "UPDATE consolidation_runs SET status='completed', checkpoint=?, "
                "completed_at=?, updated_at=? WHERE run_id=?",
                (checkpoint, now, now, run_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(run_id)
            if request_id:
                request = self._connection.execute(
                    "SELECT source_type, scope_kind, scope_id, trace_cursor, "
                    "trace_ids_json FROM "
                    "long_term_update_requests WHERE request_id=? AND state='running' "
                    "AND (?='' OR worker_id=?)",
                    (request_id, worker_id, worker_id),
                ).fetchone()
                if request is None:
                    raise RuntimeError("long-term-update-request-lease-stale")
                request_cursor = self._connection.execute(
                    "UPDATE long_term_update_requests SET state='completed', "
                    "candidate_count=?, worker_id='', lease_until=NULL, "
                    "completed_at=?, "
                    "last_error_type='', updated_at=? WHERE request_id=? AND "
                    "state='running' AND (?='' OR worker_id=?)",
                    (
                        len(candidate_ids),
                        now,
                        now,
                        request_id,
                        worker_id,
                        worker_id,
                    ),
                )
                if request_cursor.rowcount != 1:
                    raise RuntimeError("long-term-update-request-lease-stale")
                self._advance_offline_checkpoint_for_request(request, now)
                consumed_count = self._mark_request_consumptions(
                    request_id, "consumed", now=now, actor="offline-worker"
                )
                if str(request["source_type"]) in {"chat-window", "long-task"} and (
                    consumed_count != len(json.loads(str(request["trace_ids_json"])))
                ):
                    raise RuntimeError("trace-consumption-reservation-stale")
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return tuple(dict.fromkeys(candidate_ids))

    def _find_formal_duplicate(self, mutation: MemoryMutation) -> str | None:
        """Reuse an authoritative claim before creating an offline candidate."""

        for ref in mutation.evidence:
            row = self._connection.execute(
                "SELECT c.claim_id FROM evidence e JOIN claims c "
                "ON c.claim_id=e.claim_id "
                "WHERE c.scope_kind=? AND c.scope_id=? AND c.status IN "
                "('active','approved','frozen') AND e.ref_id=? AND e.quote=? "
                "ORDER BY c.created_at, c.claim_id LIMIT 1",
                (
                    mutation.scope.kind,
                    mutation.scope.identifier,
                    ref.ref_id,
                    ref.quote,
                ),
            ).fetchone()
            if row is not None:
                return str(row["claim_id"])
        fact_type = str(mutation.metadata.get("fact_type") or "")
        entity = str(mutation.metadata.get("entity") or "")
        predicate = str(mutation.metadata.get("predicate") or "")
        if fact_type and entity and predicate and "value" in mutation.metadata:
            value_json = json.dumps(
                mutation.metadata.get("value"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            row = self._connection.execute(
                "SELECT claim_id FROM claims WHERE scope_kind=? AND scope_id=? "
                "AND status IN ('active','approved','frozen') AND fact_type=? "
                "AND entity=? AND predicate=? AND value_json=? "
                "ORDER BY created_at, claim_id LIMIT 1",
                (
                    mutation.scope.kind,
                    mutation.scope.identifier,
                    fact_type,
                    entity,
                    predicate,
                    value_json,
                ),
            ).fetchone()
            if row is not None:
                return str(row["claim_id"])
        return None

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

    def claim_index_jobs(
        self,
        limit: int,
        *,
        worker_id: str = "index-worker",
        lease_seconds: int = 120,
    ) -> list[MemoryIndexJob]:
        now_value = datetime.now(UTC)
        now = now_value.isoformat()
        lease_until = (now_value + timedelta(seconds=max(1, lease_seconds))).isoformat()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
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
                    "attempts=attempts+1, worker_id=?, lease_until=?, "
                    "updated_at=? WHERE memory_type=? AND memory_id=?",
                    (
                        worker_id,
                        lease_until,
                        now,
                        row["memory_type"],
                        row["memory_id"],
                    ),
                )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return [
            MemoryIndexJob(
                row["memory_type"],
                row["memory_id"],
                row["content_hash"],
                int(row["attempts"]) + 1,
                worker_id,
                datetime.fromisoformat(lease_until),
                int(row["max_attempts"]),
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
                "WHERE memory_type=? AND memory_id=? AND state='running' "
                "AND (?='' OR worker_id=?)",
                (job.memory_type, job.memory_id, job.worker_id, job.worker_id),
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
                "last_error_type='', worker_id='', lease_until=NULL, updated_at=? "
                "WHERE memory_type=? AND memory_id=?",
                (now, job.memory_type, job.memory_id),
            )

    def fail_index_job(
        self, job: MemoryIndexJob, error_type: str, *, permanent: bool = False
    ) -> None:
        delay = min(300, 2 ** min(job.attempts, 8))
        state = (
            "dead-letter" if permanent or job.attempts >= job.max_attempts else "retry"
        )
        available = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
        with self._connection:
            self._connection.execute(
                "UPDATE memory_index_jobs SET state=?, last_error=?, "
                "last_error_type=?, worker_id='', lease_until=NULL, available_at=?, "
                "updated_at=? WHERE memory_type=? AND memory_id=? AND content_hash=? "
                "AND (?='' OR worker_id=?)",
                (
                    state,
                    error_type[:120],
                    error_type[:120],
                    available,
                    datetime.now(UTC).isoformat(),
                    job.memory_type,
                    job.memory_id,
                    job.content_hash,
                    job.worker_id,
                    job.worker_id,
                ),
            )

    def recover_expired_derived_leases(self) -> dict[str, int]:
        now = datetime.now(UTC).isoformat()
        recovered: dict[str, int] = {}
        with self._connection:
            for table in ("memory_index_jobs", "memory_projection_jobs"):
                cursor = self._connection.execute(
                    f"UPDATE {table} SET state='retry', worker_id='', "  # noqa: S608
                    "lease_until=NULL, available_at=?, "
                    "last_error_type='lease-expired', "
                    "updated_at=? WHERE state='running' AND lease_until IS NOT NULL "
                    "AND lease_until<=?",
                    (now, now, now),
                )
                recovered[table] = int(cursor.rowcount)
        return recovered

    def retry_index_job(self, memory_type: str, memory_id: str) -> bool:
        """Explicitly requeue a dead-letter index job for operators."""

        now = datetime.now(UTC).isoformat()
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE memory_index_jobs SET state='retry', attempts=0, "
                "last_error=NULL, last_error_type='', worker_id='', lease_until=NULL, "
                "available_at=?, updated_at=? WHERE memory_type=? AND memory_id=? "
                "AND state='dead-letter'",
                (now, now, memory_type, memory_id),
            )
        return cursor.rowcount == 1

    def renew_index_lease(
        self, job: MemoryIndexJob, *, lease_seconds: int = 120
    ) -> bool:
        now = datetime.now(UTC)
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE memory_index_jobs SET lease_until=?, updated_at=? "
                "WHERE memory_type=? AND memory_id=? AND state='running' "
                "AND worker_id=? AND content_hash=?",
                (
                    (now + timedelta(seconds=max(1, lease_seconds))).isoformat(),
                    now.isoformat(),
                    job.memory_type,
                    job.memory_id,
                    job.worker_id,
                    job.content_hash,
                ),
            )
        return cursor.rowcount == 1

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
        self._delete_sparse(memory_type, memory_id)

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
                bool(row["prompt_allowed"]),
                bool(row["embedding_allowed"]),
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
                bool(row["prompt_allowed"]),
                bool(row["embedding_allowed"]),
            )
        if memory_type == "card-statement":
            row = self._connection.execute(
                "SELECT s.*, c.scope_kind, c.scope_id, c.status, "
                "c.embedding_allowed, c.prompt_allowed FROM card_statements s "
                "JOIN cards c ON c.card_id=s.card_id WHERE s.statement_id=? "
                "AND s.is_current=1 AND c.status IN ('active','approved','frozen')",
                (memory_id,),
            ).fetchone()
            if row is None:
                return None
            return MemoryIndexSource(
                "card-statement",
                str(row["statement_id"]),
                str(row["content"]),
                str(row["content_hash"]),
                MemoryScope(str(row["scope_kind"]), str(row["scope_id"])),
                str(row["status"]),
                str(row["sensitivity"]),
                str(row["created_at"]),
                bool(row["prompt_allowed"]),
                bool(row["embedding_allowed"]),
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
                row["sensitivity"],
                row["occurred_at"],
                bool(row["prompt_allowed"]),
                bool(row["embedding_allowed"]),
            )
        return None

    def rebuild_index_jobs(self, memory_type: str | None = None) -> int:
        types = (
            (memory_type,)
            if memory_type
            else ("claim", "card", "card-statement", "episode")
        )
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
            for memory_type in ("claim", "card", "card-statement", "episode"):
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
                    self._enqueue_index_job(memory_type, memory_id, source.content_hash)
                    count += 1
        return count

    def _source_ids(self, memory_type: str) -> list[str]:
        table, key = {
            "claim": ("claims", "claim_id"),
            "card": ("cards", "card_id"),
            "card-statement": ("card_statements", "statement_id"),
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
        if source.memory_type == "card-statement":
            row = self._connection.execute(
                "SELECT s.*, c.status, c.scope_kind, c.scope_id, "
                "v.version FROM card_statements s JOIN cards c ON c.card_id=s.card_id "
                "JOIN card_versions v ON v.version_id=s.version_id "
                "WHERE s.statement_id=?",
                (source.memory_id,),
            ).fetchone()
            assert row is not None
            return self._statement_item(row, reason)
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

    def fts_recall(
        self, request: MemoryQuery, plan: QueryPlan, *, limit: int
    ) -> tuple[list[tuple[MemoryItem, float]], bool, int, str]:
        """严格 FTS 召回。

        经 ``memory_search`` + ``bm25()`` 跨 claim/card-statement/episode。

        硬过滤 (scope/status/sensitivity/时间) 尽量 SQL 下推到候选限制之前；无法
        下推的留作有界窗口内 Python 过滤并计入 filtered。返回按 bm25 升序
        (越负越相关) 排列的 ``(item, raw_bm25)``，``raw_bm25`` 仅用于安全诊断。
        """

        if not self.fts_available:
            return [], True, 0, "fts:unavailable"
        if plan.fts_term_count == 0:
            return [], False, 0, "fts:no-term"
        window = max(limit * 4, limit)
        now = request.at_time or datetime.now(UTC)
        statuses = request.statuses or ("active", "approved", "frozen")
        sens = _allowed_sensitivities(request.max_sensitivity)
        status_ph = ",".join("?" for _ in statuses)
        sens_ph = ",".join("?" for _ in sens)
        hits: list[tuple[MemoryItem, float]] = []
        scanned = 0
        truncated_window = False
        if "claim" in request.item_types:
            rows = self._connection.execute(
                f"""
                SELECT c.*, bm25(memory_search) AS score
                FROM memory_search JOIN claims c
                  ON c.claim_id = memory_search.memory_id
                WHERE memory_search MATCH ? AND memory_search.memory_type='claim'
                  AND c.scope_kind=? AND (?='*' OR c.scope_id IN (?, '*'))
                  AND c.status IN ({status_ph})
                  AND c.sensitivity IN ({sens_ph})
                  AND (c.valid_from IS NULL OR c.valid_from <= ?)
                  AND (c.valid_to IS NULL OR ? < c.valid_to)
                ORDER BY score, c.created_at DESC LIMIT ?
                """,  # noqa: S608
                (
                    plan.fts_match,
                    request.scope.kind,
                    request.scope.identifier,
                    request.scope.identifier,
                    *statuses,
                    *sens,
                    now,
                    now,
                    window,
                ),
            ).fetchall()
            scanned += len(rows)
            truncated_window = truncated_window or len(rows) >= window
            for row in rows:
                hits.append((self._claim_item(row, "fts"), float(row["score"])))
        if "card" in request.item_types:
            rows = self._connection.execute(
                f"""
                SELECT s.statement_id, s.content, s.created_at, s.card_id,
                       s.version_id, s.ordinal, c.status, c.scope_kind, c.scope_id,
                       c.sensitivity, v.version, bm25(memory_search) AS score
                FROM memory_search
                JOIN card_statements s ON s.statement_id = memory_search.memory_id
                JOIN cards c ON c.card_id = s.card_id
                JOIN card_versions v ON v.version_id = s.version_id
                WHERE memory_search MATCH ? AND memory_search.memory_type='card'
                  AND s.is_current=1 AND c.current_version=v.version
                  AND c.scope_kind=? AND (?='*' OR c.scope_id IN (?, '*'))
                  AND c.status IN ({status_ph})
                  AND c.sensitivity IN ({sens_ph})
                ORDER BY score, s.card_id, s.ordinal LIMIT ?
                """,  # noqa: S608
                (
                    plan.fts_match,
                    request.scope.kind,
                    request.scope.identifier,
                    request.scope.identifier,
                    *statuses,
                    *sens,
                    window,
                ),
            ).fetchall()
            scanned += len(rows)
            truncated_window = truncated_window or len(rows) >= window
            for row in rows:
                hits.append((self._statement_item(row, "fts"), float(row["score"])))
        if "episode" in request.item_types:
            rows = self._connection.execute(
                f"""
                SELECT t.*, bm25(memory_search) AS score
                FROM memory_search JOIN trajectory_segments t
                  ON t.segment_id = memory_search.memory_id
                WHERE memory_search MATCH ? AND memory_search.memory_type='episode'
                  AND t.scope_kind=? AND (?='*' OR t.scope_id IN (?, '*'))
                  AND t.sensitivity IN ({sens_ph})
                ORDER BY score, t.occurred_at DESC LIMIT ?
                """,  # noqa: S608
                (
                    plan.fts_match,
                    request.scope.kind,
                    request.scope.identifier,
                    request.scope.identifier,
                    *sens,
                    window,
                ),
            ).fetchall()
            scanned += len(rows)
            truncated_window = truncated_window or len(rows) >= window
            for row in rows:
                hits.append((self._segment_item(row, "fts"), float(row["score"])))
        # bm25 越小(更负)越相关；跨类型同表可比，按 score 升序合并。
        hits.sort(key=lambda pair: (pair[1], pair[0].item_type, pair[0].item_id))
        filtered = max(0, scanned - len(hits))
        if truncated_window:
            reason = "fts:bounded-window"
        elif hits:
            reason = "fts"
        else:
            reason = "fts:no-match"
        return hits[:limit], False, filtered, reason

    def pattern_recall(
        self, request: MemoryQuery, plan: QueryPlan, *, limit: int
    ) -> tuple[list[MemoryItem], int, str]:
        """宽松 Pattern 召回：转义后的有界 LIKE OR，最多 16 个 term。

        所有类型先按 scope/status/sensitivity/时间 SQL 下推，再应用有界预过滤窗口；
        窗口内按命中 term 数、最新时间、stable ID 排序。``raw_score`` 由 lane
        从命中数推导，不进入跨 lane 加法。
        """

        terms = tuple(plan.pattern_terms)[: max(plan.pattern_term_count, 1)]
        if not terms:
            return [], 0, "pattern:no-terms"
        escaped = [_escape_like(term) for term in terms]
        like_params = [f"%{esc}%" for esc in escaped]
        window = max(limit * 4, limit)
        now = request.at_time or datetime.now(UTC)
        statuses = request.statuses or ("active", "approved", "frozen")
        sens = _allowed_sensitivities(request.max_sensitivity)
        status_ph = ",".join("?" for _ in statuses)
        sens_ph = ",".join("?" for _ in sens)
        like_clause = "normalized_content LIKE ? ESCAPE '\\'"
        claim_clause = " OR ".join(like_clause for _ in escaped)
        card_clause = " OR ".join("s.content LIKE ? ESCAPE '\\'" for _ in escaped)
        episode_clause = " OR ".join("search_text LIKE ? ESCAPE '\\'" for _ in escaped)
        scored: list[tuple[int, MemoryItem]] = []

        def _hit_count(text: str) -> int:
            lowered = text.casefold()
            return sum(1 for esc in escaped if esc in lowered)

        if "claim" in request.item_types:
            rows = self._connection.execute(
                f"""
                SELECT * FROM claims
                WHERE ({claim_clause})
                  AND scope_kind=? AND (?='*' OR scope_id IN (?, '*'))
                  AND status IN ({status_ph})
                  AND sensitivity IN ({sens_ph})
                  AND (valid_from IS NULL OR valid_from <= ?)
                  AND (valid_to IS NULL OR ? < valid_to)
                ORDER BY created_at DESC LIMIT ?
                """,  # noqa: S608
                (
                    *like_params,
                    request.scope.kind,
                    request.scope.identifier,
                    request.scope.identifier,
                    *statuses,
                    *sens,
                    now,
                    now,
                    window,
                ),
            ).fetchall()
            for row in rows:
                item = self._claim_item(row, "pattern")
                scored.append((_hit_count(item.content), item))
        if "card" in request.item_types:
            rows = self._connection.execute(
                f"""
                SELECT s.statement_id, s.content, s.created_at, s.card_id,
                       s.version_id, s.ordinal, c.status, c.scope_kind, c.scope_id,
                       c.sensitivity, v.version
                FROM card_statements s JOIN cards c ON c.card_id=s.card_id
                JOIN card_versions v ON v.version_id=s.version_id
                WHERE s.is_current=1 AND c.current_version=v.version
                  AND ({card_clause})
                  AND c.scope_kind=? AND (?='*' OR c.scope_id IN (?, '*'))
                  AND c.status IN ({status_ph})
                  AND c.sensitivity IN ({sens_ph})
                ORDER BY s.created_at DESC LIMIT ?
                """,  # noqa: S608
                (
                    *like_params,
                    request.scope.kind,
                    request.scope.identifier,
                    request.scope.identifier,
                    *statuses,
                    *sens,
                    window,
                ),
            ).fetchall()
            for row in rows:
                item = self._statement_item(row, "pattern")
                scored.append((_hit_count(item.content), item))
        if "episode" in request.item_types:
            rows = self._connection.execute(
                f"""
                SELECT * FROM trajectory_segments
                WHERE ({episode_clause})
                  AND scope_kind=? AND (?='*' OR scope_id IN (?, '*'))
                  AND sensitivity IN ({sens_ph})
                ORDER BY occurred_at DESC, segment_id LIMIT ?
                """,  # noqa: S608
                (
                    *like_params,
                    request.scope.kind,
                    request.scope.identifier,
                    request.scope.identifier,
                    *sens,
                    window,
                ),
            ).fetchall()
            for row in rows:
                item = self._segment_item(row, "pattern")
                scored.append((_hit_count(row["search_text"] or row["content"]), item))
        scored.sort(
            key=lambda pair: (
                -pair[0],
                -(pair[1].timestamp.timestamp() if pair[1].timestamp else 0),
                pair[1].item_type,
                pair[1].item_id,
            )
        )
        items = [item for _, item in scored[:limit]]
        return items, len(scored), "pattern" if items else "pattern:no-match"

    def cached_vectors(
        self,
        identities: tuple[tuple[str, str], ...],
        *,
        model: str,
        version: str,
        dimensions: int,
    ) -> dict[tuple[str, str], list[float]]:
        """读取已就绪且同版本的缓存向量，用于 MMR；不发起在线 embedding。"""

        if not identities:
            return {}
        result: dict[tuple[str, str], list[float]] = {}
        for memory_type, memory_id in identities:
            row = self._connection.execute(
                "SELECT vector_blob, content_hash FROM semantic_index "
                "WHERE memory_type=? AND memory_id=? AND embedding_model=? "
                "AND embedding_version=? AND dimensions=?",
                (memory_type, memory_id, model, version, dimensions),
            ).fetchone()
            if row is None:
                continue
            source = self.get_index_source(memory_type, memory_id)
            if source is None or source.content_hash != row["content_hash"]:
                continue
            try:
                blob = bytes(row["vector_blob"])
                vec = [
                    float(x)
                    for x in struct.unpack(f"<{dimensions}f", blob)
                ]
            except (struct.error, ValueError):
                continue
            result[(memory_type, memory_id)] = vec
        return result

    def search_card_statements(self, request: MemoryQuery) -> list[MemoryItem]:
        """Card-first 语句召回：复用共享 Query Plan 的严格 FTS + Pattern fallback。

        不再使用 substring term-count 排名旁路；FTS 经 ``memory_search`` 类型 ``card``
        以 ``bm25()`` 排序，无 FTS term 或 FTS 不可用时回退到有界 Pattern LIKE。
        """

        plan = build_query_plan(request)
        allowed = _SENSITIVITY.get(request.max_sensitivity, 1)
        params: list[Any] = [request.scope.kind, request.scope.identifier]
        sql = (
            "SELECT s.*, c.status, c.scope_kind, c.scope_id, v.version "
            "FROM card_statements s JOIN cards c ON c.card_id=s.card_id "
            "JOIN card_versions v ON v.version_id=s.version_id "
            "WHERE s.is_current=1 AND c.current_version=v.version "
            "AND c.scope_kind=? AND c.scope_id IN (?, '*') "
            "AND c.status IN ('active','approved','frozen')"
        )
        if request.statement_ids:
            placeholders = ",".join("?" for _ in request.statement_ids)
            sql += f" AND s.statement_id IN ({placeholders})"  # noqa: S608
            params.extend(request.statement_ids)
        sql += " ORDER BY s.card_id, s.ordinal, s.statement_id"
        rows = self._connection.execute(sql, params).fetchall()
        fts_ids: set[str] = set()
        if self.fts_available and plan.fts_term_count > 0:
            fts_rows = self._connection.execute(
                """
                SELECT memory_search.memory_id, bm25(memory_search) AS score
                FROM memory_search
                WHERE memory_search MATCH ? AND memory_search.memory_type='card'
                ORDER BY score LIMIT ?
                """,
                (
                    plan.fts_match,
                    max(
                        request.card_statement_limit * 4,
                        request.card_statement_limit,
                    ),
                ),
            ).fetchall()
            fts_ids = {str(r["memory_id"]) for r in fts_rows}
        pattern_terms = tuple(plan.pattern_terms)
        scored: list[tuple[int, bool, sqlite3.Row]] = []
        for row in rows:
            if _SENSITIVITY.get(str(row["sensitivity"]), 2) > allowed:
                continue
            if request.statement_ids or not pattern_terms:
                scored.append((0, row["statement_id"] in fts_ids, row))
                continue
            normalized = _normalize(str(row["content"]))
            hit_count = sum(
                1 for term in pattern_terms if term in normalized
            )
            if hit_count or row["statement_id"] in fts_ids:
                scored.append((hit_count, row["statement_id"] in fts_ids, row))
        scored.sort(
            key=lambda triple: (
                -triple[0],
                not triple[1],
                triple[2]["card_id"],
                triple[2]["ordinal"],
            )
        )
        return [
            self._statement_item(
                row,
                "card-statement-fts" if in_fts else "card-statement-pattern",
            )
            for _, in_fts, row in scored[: request.card_statement_limit]
        ]

    def expand_card_statement_claims(
        self, statement_ids: tuple[str, ...], request: MemoryQuery
    ) -> list[MemoryItem]:
        if not statement_ids:
            return []
        placeholders = ",".join("?" for _ in statement_ids)
        rows = self._connection.execute(
            "SELECT DISTINCT c.* FROM card_statement_claims link JOIN claims c "
            "ON c.claim_id=link.claim_id JOIN card_statements s "
            "ON s.statement_id=link.statement_id WHERE s.is_current=1 "
            f"AND link.statement_id IN ({placeholders}) "  # noqa: S608
            "ORDER BY c.claim_id",
            statement_ids,
        ).fetchall()
        now = request.at_time or datetime.now(UTC)
        items: list[MemoryItem] = []
        for row in rows:
            if row["scope_kind"] != request.scope.kind or row["scope_id"] not in {
                request.scope.identifier,
                "*",
            }:
                continue
            if row["status"] not in request.statuses or not _is_current(
                row["valid_from"], row["valid_to"], now
            ):
                continue
            if _SENSITIVITY.get(row["sensitivity"], 2) > _SENSITIVITY.get(
                request.max_sensitivity, 1
            ):
                continue
            items.append(self._claim_item(row, "card-statement-expand"))
        return items[: request.claim_expansion_limit]

    def _statement_item(self, row: sqlite3.Row, reason: str) -> MemoryItem:
        claim_rows = self._connection.execute(
            "SELECT claim_id FROM card_statement_claims WHERE statement_id=? "
            "ORDER BY ordinal, claim_id",
            (row["statement_id"],),
        ).fetchall()
        return MemoryItem(
            str(row["content"]),
            "card-statement",
            datetime.fromisoformat(str(row["created_at"])),
            metadata={
                "card_id": str(row["card_id"]),
                "version_id": str(row["version_id"]),
                "version": int(row["version"]),
                "claim_ids": tuple(str(item["claim_id"]) for item in claim_rows),
                "scope_kind": str(row["scope_kind"]),
                "scope_id": str(row["scope_id"]),
                "sensitivity": str(row["sensitivity"]),
            },
            item_id=str(row["statement_id"]),
            item_type="card-statement",
            status=str(row["status"]),
            recall_reason=reason,
        )

    def eligible_card_claims(self, key: CardProjectionKey) -> list[sqlite3.Row]:
        now = datetime.now(UTC)
        rows = self._connection.execute(
            """
            SELECT c.* FROM claims c
            WHERE c.scope_kind=? AND c.scope_id=? AND c.subject=? AND c.card_kind=?
              AND c.status IN ('active', 'approved')
              AND EXISTS(SELECT 1 FROM evidence e WHERE e.claim_id=c.claim_id)
              AND NOT EXISTS(
                SELECT 1 FROM claim_relations r JOIN claims newer
                  ON newer.claim_id=r.source_claim_id
                WHERE r.target_claim_id=c.claim_id
                  AND r.relation IN ('corrects','supersedes')
                  AND newer.status IN ('active','approved','frozen')
              )
            ORDER BY c.valid_from, c.created_at, c.claim_id
            """,
            (key.scope.kind, key.scope.identifier, key.subject, key.card_kind),
        ).fetchall()
        return [
            row for row in rows if _is_current(row["valid_from"], row["valid_to"], now)
        ]

    def has_unresolved_card_conflict(self, key: CardProjectionKey) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM candidate_relations r JOIN claims candidate "
            "ON candidate.claim_id=r.candidate_id JOIN claims target "
            "ON target.claim_id=r.target_claim_id WHERE r.relation='contradicts' "
            "AND r.status='proposed' AND candidate.status='candidate' "
            "AND target.scope_kind=? AND target.scope_id=? AND target.subject=? "
            "AND target.card_kind=? LIMIT 1",
            (key.scope.kind, key.scope.identifier, key.subject, key.card_kind),
        ).fetchone()
        return row is not None

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
        statements: tuple[CardDraftStatement, ...] = (),
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
                statements=statements,
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
            self._replace_card_statements(
                card_id,
                version_id,
                statements,
                str(existing["sensitivity"]),
                now,
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

    def _replace_card_statements(
        self,
        card_id: str,
        version_id: str,
        statements: tuple[CardDraftStatement, ...],
        sensitivity: str,
        now: str,
    ) -> None:
        self._connection.execute(
            "UPDATE card_statements SET is_current=0 WHERE card_id=?", (card_id,)
        )
        for ordinal, statement in enumerate(statements):
            content_hash = _source_content_hash(statement.content)
            statement_id = (
                "stmt_"
                + hashlib.sha256(
                    f"{version_id}:{ordinal}:{content_hash}".encode()
                ).hexdigest()
            )
            self._connection.execute(
                "INSERT INTO card_statements(statement_id, card_id, version_id, "
                "ordinal, content, content_hash, sensitivity, is_current, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (
                    statement_id,
                    card_id,
                    version_id,
                    ordinal,
                    statement.content,
                    content_hash,
                    sensitivity,
                    now,
                ),
            )
            for claim_ordinal, claim_id in enumerate(statement.claim_ids):
                self._connection.execute(
                    "INSERT INTO card_statement_claims("
                    "statement_id, claim_id, ordinal) "
                    "VALUES (?, ?, ?)",
                    (statement_id, claim_id, claim_ordinal),
                )
            self._upsert_sparse("card", statement_id, statement.content)
            self._enqueue_index_job("card-statement", statement_id, content_hash)

    def enqueue_card_projection(self, key: CardProjectionKey) -> None:
        with self._connection:
            self._enqueue_card_projection(key.scope, key.subject, key.card_kind)

    def enqueue_episode_projection(
        self,
        trace_id: str,
        scope: MemoryScope,
        *,
        objective: str = "",
        current_step: str = "",
    ) -> None:
        """只登记派生任务，不在在线消息泵读取 trajectory。"""

        now = datetime.now(UTC).isoformat()
        payload = json.dumps(
            {
                "trace_id": trace_id,
                "scope_kind": scope.kind,
                "scope_id": scope.identifier,
                "objective": objective[:2_000],
                "current_step": current_step[:2_000],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO memory_projection_jobs(
                    projection_type, projection_key, payload_json, state, attempts,
                    last_error, available_at, updated_at
                ) VALUES ('episode', ?, ?, 'pending', 0, NULL, ?, ?)
                ON CONFLICT(projection_type, projection_key) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    state=CASE WHEN memory_projection_jobs.state='ready'
                               THEN 'ready' ELSE 'pending' END,
                    last_error=NULL, available_at=excluded.available_at,
                    updated_at=excluded.updated_at
                """,
                (trace_id, payload, now, now),
            )

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
        self,
        projection_type: str,
        limit: int,
        *,
        worker_id: str = "projection-worker",
        lease_seconds: int = 120,
    ) -> list[dict[str, Any]]:
        now_value = datetime.now(UTC)
        now = now_value.isoformat()
        lease_until = (now_value + timedelta(seconds=max(1, lease_seconds))).isoformat()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            rows = self._connection.execute(
                "SELECT * FROM memory_projection_jobs WHERE projection_type=? "
                "AND state IN ('pending', 'retry') AND available_at<=? "
                "ORDER BY updated_at, projection_key LIMIT ?",
                (projection_type, now, max(1, limit)),
            ).fetchall()
            for row in rows:
                self._connection.execute(
                    "UPDATE memory_projection_jobs SET state='running', "
                    "attempts=attempts+1, worker_id=?, lease_until=?, updated_at=? "
                    "WHERE projection_type=? "
                    "AND projection_key=?",
                    (
                        worker_id,
                        lease_until,
                        now,
                        projection_type,
                        row["projection_key"],
                    ),
                )
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return [
            {**dict(row), "worker_id": worker_id, "lease_until": lease_until}
            for row in rows
        ]

    def finish_projection_job(
        self,
        projection_type: str,
        projection_key: str,
        state: str = "ready",
        *,
        worker_id: str = "",
    ) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE memory_projection_jobs SET state=?, last_error=NULL, "
                "last_error_type='', worker_id='', lease_until=NULL, updated_at=? "
                "WHERE projection_type=? AND projection_key=? "
                "AND (?='' OR worker_id=?)",
                (
                    state,
                    datetime.now(UTC).isoformat(),
                    projection_type,
                    projection_key,
                    worker_id,
                    worker_id,
                ),
            )

    def renew_projection_lease(
        self,
        projection_type: str,
        projection_key: str,
        *,
        worker_id: str,
        lease_seconds: int = 120,
    ) -> bool:
        now = datetime.now(UTC)
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE memory_projection_jobs SET lease_until=?, updated_at=? "
                "WHERE projection_type=? AND projection_key=? AND state='running' "
                "AND worker_id=?",
                (
                    (now + timedelta(seconds=max(1, lease_seconds))).isoformat(),
                    now.isoformat(),
                    projection_type,
                    projection_key,
                    worker_id,
                ),
            )
        return cursor.rowcount == 1

    def fail_projection_job(
        self,
        projection_type: str,
        projection_key: str,
        error_type: str,
        *,
        worker_id: str = "",
        permanent: bool = False,
    ) -> None:
        row = self._connection.execute(
            "SELECT attempts, max_attempts FROM memory_projection_jobs "
            "WHERE projection_type=? AND projection_key=?",
            (projection_type, projection_key),
        ).fetchone()
        attempts = int(row["attempts"]) if row is not None else 0
        max_attempts = int(row["max_attempts"]) if row is not None else 1
        state = "dead-letter" if permanent or attempts >= max_attempts else "retry"
        available = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
        with self._connection:
            self._connection.execute(
                "UPDATE memory_projection_jobs SET state=?, last_error=?, "
                "last_error_type=?, worker_id='', lease_until=NULL, available_at=?, "
                "updated_at=? WHERE projection_type=? AND projection_key=? "
                "AND (?='' OR worker_id=?)",
                (
                    state,
                    error_type[:120],
                    error_type[:120],
                    available,
                    datetime.now(UTC).isoformat(),
                    projection_type,
                    projection_key,
                    worker_id,
                    worker_id,
                ),
            )

    def retry_projection_job(self, projection_type: str, projection_key: str) -> bool:
        """Explicitly requeue a dead-letter Card or Episode projection."""

        now = datetime.now(UTC).isoformat()
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE memory_projection_jobs SET state='retry', attempts=0, "
                "last_error=NULL, last_error_type='', worker_id='', lease_until=NULL, "
                "available_at=?, updated_at=? WHERE projection_type=? "
                "AND projection_key=? AND state='dead-letter'",
                (now, now, projection_type, projection_key),
            )
        return cursor.rowcount == 1

    def repair_supersede_consistency(
        self, *, actor: str = "migration"
    ) -> dict[str, Any]:
        """一次性修复既有"边在、状态未翻"的替代关系数据。

        安全自动修复：同 scope、单 live source、target 仍 active/approved 且无
        多源竞争 → 翻 superseded、记审计、删派生索引、重排 target Card。
        frozen/candidate target、跨 scope、死 source、多源竞争 → 只报告不处理。
        """
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            rows = self._connection.execute(
                """
                SELECT DISTINCT r.source_claim_id, r.target_claim_id
                FROM claim_relations r
                JOIN claims src ON src.claim_id = r.source_claim_id
                JOIN claims tgt ON tgt.claim_id = r.target_claim_id
                WHERE r.relation IN ('corrects', 'supersedes')
                  AND tgt.status IN ('active', 'approved')
                  AND src.status IN ('active', 'approved', 'frozen')
                  AND src.scope_kind = tgt.scope_kind
                  AND src.scope_id = tgt.scope_id
                """
            ).fetchall()
            fixed: list[str] = []
            skipped: list[dict[str, str]] = []
            for row in rows:
                target_id = str(row["target_claim_id"])
                source_id = str(row["source_claim_id"])
                competitor = self._connection.execute(
                    "SELECT 1 FROM claim_relations r2 "
                    "JOIN claims s2 ON s2.claim_id = r2.source_claim_id "
                    "WHERE r2.target_claim_id = ? "
                    "AND r2.relation IN ('corrects','supersedes') "
                    "AND r2.source_claim_id != ? "
                    "AND s2.status IN ('active','approved','frozen')",
                    (target_id, source_id),
                ).fetchone()
                if competitor is not None:
                    skipped.append(
                        {"target": target_id, "reason": "multi-source-competition"}
                    )
                    continue
                changed = self._connection.execute(
                    "UPDATE claims SET status='superseded', revision=revision+1 "
                    "WHERE claim_id=? AND status IN ('active','approved')",
                    (target_id,),
                )
                if changed.rowcount != 1:
                    skipped.append({"target": target_id, "reason": "cas-stale"})
                    continue
                self._record_revision(
                    "claim", target_id, "status:superseded(auto-repair)", actor
                )
                self._delete_derived_index("claim", target_id)
                prow = self._connection.execute(
                    "SELECT scope_kind, scope_id, subject, card_kind "
                    "FROM claims WHERE claim_id=?",
                    (target_id,),
                ).fetchone()
                if prow is not None:
                    self._enqueue_card_projection(
                        MemoryScope(str(prow["scope_kind"]), str(prow["scope_id"])),
                        str(prow["subject"]),
                        str(prow["card_kind"]),
                    )
                fixed.append(target_id)
            report_rows = self._connection.execute(
                """
                SELECT DISTINCT r.target_claim_id, r.source_claim_id,
                       tgt.status AS target_status, src.status AS source_status,
                       CASE WHEN src.scope_kind = tgt.scope_kind
                                 AND src.scope_id = tgt.scope_id
                            THEN 0 ELSE 1 END AS cross_scope
                FROM claim_relations r
                JOIN claims src ON src.claim_id = r.source_claim_id
                JOIN claims tgt ON tgt.claim_id = r.target_claim_id
                WHERE r.relation IN ('corrects', 'supersedes')
                  AND (
                    tgt.status IN ('frozen', 'candidate')
                    OR src.status NOT IN ('active', 'approved', 'frozen')
                    OR src.scope_kind != tgt.scope_kind
                    OR src.scope_id != tgt.scope_id
                  )
                """
            ).fetchall()
            report_only: list[dict[str, str]] = []
            for row in report_rows:
                report_only.append(
                    {
                        "target": str(row["target_claim_id"]),
                        "source": str(row["source_claim_id"]),
                        "target_status": str(row["target_status"]),
                        "source_status": str(row["source_status"]),
                        "cross_scope": str(bool(int(row["cross_scope"]))),
                    }
                )
            self._connection.commit()
            return {"fixed": fixed, "skipped": skipped, "report_only": report_only}
        except Exception:
            self._connection.rollback()
            raise

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
            "suspect_supersede_relations": int(
                self._connection.execute(
                    "SELECT COUNT(*) FROM claim_relations r "
                    "JOIN claims tgt ON tgt.claim_id = r.target_claim_id "
                    "WHERE r.relation IN ('corrects','supersedes') "
                    "AND tgt.status IN ('active','approved')"
                ).fetchone()[0]
            ),
        }

    def offline_diagnostics(
        self, *, dead_letter_stale_after_seconds: int = 86_400
    ) -> dict[str, Any]:
        def counts(table: str) -> dict[str, int]:
            rows = self._connection.execute(
                f"SELECT state, COUNT(*) AS count FROM {table} "  # noqa: S608
                "GROUP BY state"
            ).fetchall()
            return {str(row["state"]): int(row["count"]) for row in rows}

        def job_health(table: str, time_column: str) -> dict[str, Any]:
            row = self._connection.execute(
                f"SELECT MIN({time_column}) AS oldest, "  # noqa: S608
                "SUM(CASE WHEN state='running' THEN 1 ELSE 0 END) AS leased, "
                "MAX(last_error_type) AS last_error_type "
                f"FROM {table} WHERE state IN "  # noqa: S608
                "('pending','retry','running','dead-letter')"
            ).fetchone()
            return {
                "oldest_at": str(row["oldest"] or ""),
                "leased": int(row["leased"] or 0),
                "last_error_type": str(row["last_error_type"] or ""),
            }

        request_health = job_health("long_term_update_requests", "created_at")
        cutoff = (
            datetime.now(UTC)
            - timedelta(seconds=max(1, dead_letter_stale_after_seconds))
        ).isoformat()
        stale_dead_letters = int(
            self._connection.execute(
                "SELECT COUNT(*) FROM long_term_update_requests "
                "WHERE state='quarantined' AND updated_at<=?",
                (cutoff,),
            ).fetchone()[0]
        )
        consumption_rows = self._connection.execute(
            "SELECT state, COUNT(*) AS count FROM memory_trace_consumptions "
            "GROUP BY state"
        ).fetchall()
        pending_rows = self._connection.execute(
            "SELECT session_id, COUNT(*) AS count FROM memory_trace_consumptions "
            "WHERE state='observed' AND turn_kind='chat' GROUP BY session_id"
        ).fetchall()
        recent = self._connection.execute(
            "SELECT trigger_kind FROM memory_trace_consumptions WHERE trigger_kind "
            "IS NOT NULL ORDER BY updated_at DESC, trace_id DESC LIMIT 1"
        ).fetchone()
        projection_counts = counts("memory_projection_jobs")
        index_counts = counts("memory_index_jobs")
        return {
            "requests": counts("long_term_update_requests"),
            "governance": counts("governance_jobs"),
            "projections": projection_counts,
            "index_jobs": index_counts,
            "projection_ready_output": projection_counts.get("ready", 0),
            "index_ready_output": index_counts.get("ready", 0),
            "projection_backlog": sum(
                projection_counts.get(state, 0)
                for state in ("pending", "retry", "running")
            ),
            "index_backlog": sum(
                index_counts.get(state, 0) for state in ("pending", "retry", "running")
            ),
            "stale_dead_letter": stale_dead_letters,
            "consumptions": {
                str(row["state"]): int(row["count"]) for row in consumption_rows
            },
            "pending_chat_by_session": {
                str(row["session_id"]): int(row["count"]) for row in pending_rows
            },
            "recent_trigger_kind": str(recent["trigger_kind"]) if recent else "",
            "request_health": request_health,
            "governance_health": job_health("governance_jobs", "created_at"),
            "projection_health": job_health("memory_projection_jobs", "updated_at"),
            "index_health": job_health("memory_index_jobs", "updated_at"),
            "oldest_request_at": request_health["oldest_at"],
        }

    def _probe_trigram_bm25(self) -> bool:
        """启动能力探测：FTS5 trigram tokenizer 与 ``bm25()`` 是否可用。

        在临时表上创建 trigram FTS5、写入一行并执行 ``bm25()`` 排序查询；
        ``sqlite3.OperationalError`` 视为能力不可用，其他异常向上抛出以区分
        普通失败与能力缺失。探测表在 finally 中清理，不污染真实索引。
        """

        try:
            self._connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS __probe_trigram "
                "USING fts5(content, tokenize='trigram')"
            )
            self._connection.execute(
                "INSERT INTO __probe_trigram(content) VALUES ('memory trigram probe')"
            )
            row = self._connection.execute(
                "SELECT bm25(__probe_trigram) AS score FROM __probe_trigram "
                "WHERE __probe_trigram MATCH 'trigram' LIMIT 1"
            ).fetchone()
            return row is not None
        except sqlite3.OperationalError:
            return False
        finally:
            self._connection.execute("DROP TABLE IF EXISTS __probe_trigram")

    def _set_meta(self, key: str, value: str) -> None:
        self._connection.execute(
            "INSERT INTO memory_index_meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def _setup_sparse_index(self) -> None:
        """新数据库或迁移后建立 sparse 索引与元数据。

        trigram/bm25 可用时创建 ``memory_search`` 并标记 ``trigram-v1``；不可用时
        数据库仍可打开，标记为 ``unavailable``，运行时只依赖 Pattern/semantic/metadata。
        """

        self._connection.execute("BEGIN IMMEDIATE")
        try:
            _execute_sql_script(self._connection, _INDEX_META_SCHEMA)
            available = self._probe_trigram_bm25()
            if available:
                _execute_sql_script(self._connection, _SPARSE_FTS_SCHEMA)
                existing = self._connection.execute(
                    "SELECT COUNT(*) FROM memory_search"
                ).fetchone()[0]
                if existing == 0:
                    # trigram 此前不可用或为新库：从权威表回填，保证索引不空。
                    self._backfill_memory_search()
                self._set_meta("sparse_format", "trigram-v1")
            else:
                self._set_meta("sparse_format", "unavailable")
            self._connection.commit()
            self.fts_available = available
        except sqlite3.OperationalError:
            self._connection.rollback()
            self.fts_available = False
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                _execute_sql_script(self._connection, _INDEX_META_SCHEMA)
                self._set_meta("sparse_format", "unavailable")
                self._connection.commit()
            except sqlite3.OperationalError:
                self._connection.rollback()

    def _upsert_sparse(self, memory_type: str, memory_id: str, content: str) -> None:
        """写入/更新一条 sparse 索引行，按 stable identity (memory_type, memory_id)。"""

        if not self.fts_available:
            return
        self._connection.execute(
            "DELETE FROM memory_search WHERE memory_type=? AND memory_id=?",
            (memory_type, memory_id),
        )
        self._connection.execute(
            "INSERT INTO memory_search(memory_type, memory_id, content) "
            "VALUES (?, ?, ?)",
            (memory_type, memory_id, content),
        )

    def _delete_sparse(self, memory_type: str, memory_id: str) -> None:
        if not self.fts_available:
            return
        self._connection.execute(
            "DELETE FROM memory_search WHERE memory_type=? AND memory_id=?",
            (memory_type, memory_id),
        )

    def _backfill_memory_search(self) -> None:
        """从权威表回填 Claim、当前 Card statement、Episode 到 sparse 索引。

        Claim 与当前 Card statement 的 stable identity 分别为 claim_id、statement_id；
        Episode 为 segment_id，索引内容使用其 searchable ``search_text`` 列。状态/版本/
        有效性过滤在召回 SQL 中下推，回填不据此剔除，以保证迁移后与写入路径一致。
        """

        self._connection.execute(
            "INSERT INTO memory_search(memory_type, memory_id, content) "
            "SELECT 'claim', claim_id, content FROM claims"
        )
        self._connection.execute(
            "INSERT INTO memory_search(memory_type, memory_id, content) "
            "SELECT 'card', s.statement_id, s.content "
            "FROM card_statements s "
            "JOIN card_versions v ON v.version_id=s.version_id "
            "JOIN cards c ON c.card_id=s.card_id "
            "WHERE s.is_current=1 AND v.version=c.current_version"
        )
        self._connection.execute(
            "INSERT INTO memory_search(memory_type, memory_id, content) "
            "SELECT 'episode', segment_id, search_text FROM trajectory_segments"
        )

    def _validate_sparse_backfill(self) -> None:
        """验证 sparse 索引 stable identity/记录计数与权威表一致，否则抛出回滚迁移。"""

        checks = [
            (
                "claim",
                "SELECT COUNT(*) FROM claims",
                "SELECT COUNT(*) FROM memory_search WHERE memory_type='claim'",
            ),
            (
                "card",
                "SELECT COUNT(*) FROM card_statements s "
                "JOIN card_versions v ON v.version_id=s.version_id "
                "JOIN cards c ON c.card_id=s.card_id "
                "WHERE s.is_current=1 AND v.version=c.current_version",
                "SELECT COUNT(*) FROM memory_search WHERE memory_type='card'",
            ),
            (
                "episode",
                "SELECT COUNT(*) FROM trajectory_segments",
                "SELECT COUNT(*) FROM memory_search WHERE memory_type='episode'",
            ),
        ]
        for label, authority_sql, index_sql in checks:
            authority = self._connection.execute(authority_sql).fetchone()[0]
            indexed = self._connection.execute(index_sql).fetchone()[0]
            if authority != indexed:
                raise RuntimeError(
                    f"sparse 索引校验失败：{label} "
                    f"权威 {authority} != 索引 {indexed}"
                )

    def _migrate_v6_to_v7(self) -> None:
        """schema 6→7：事务内创建并回填 sparse 索引、校验、发布版本后移除旧派生表。

        trigram 不可用时仍发布 v7 并标记 ``unavailable``（降级而非失败）；任何创建、
        回填或校验失败均回滚，不改写权威记忆、不发布版本、不移除旧表。
        """

        try:
            self._connection.execute("BEGIN IMMEDIATE")
            _execute_sql_script(self._connection, _INDEX_META_SCHEMA)
            trigram = self._probe_trigram_bm25()
            if trigram:
                _execute_sql_script(self._connection, _SPARSE_FTS_SCHEMA)
                # 清空旧派生行再从权威表回填，保证迁移是 sparse 索引的干净重建
                # （DB 可能从更高版本降级而来，memory_search 已有写入路径留下的行）。
                self._connection.execute("DELETE FROM memory_search")
                self._backfill_memory_search()
                self._validate_sparse_backfill()
                self._set_meta("sparse_format", "trigram-v1")
            else:
                self._set_meta("sparse_format", "unavailable")
            # 新索引已发布成功后才移除旧派生搜索表。
            self._connection.execute("DROP TABLE IF EXISTS claim_search")
            self._connection.execute("DROP TABLE IF EXISTS card_search")
            self._connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            self._connection.commit()
            self.fts_available = trigram
        except Exception:
            self._connection.rollback()
            raise

    def rebuild_sparse_index(self) -> None:
        """幂等重建 sparse 派生索引。

        tokenizer/index format 变化时从当前权威记录重新生成同一 stable identity 集合；
        只重建派生索引，不触发治理或事实写入。
        """

        if not self._probe_trigram_bm25():
            raise RuntimeError("trigram FTS5 不可用，无法重建 sparse 索引")
        _execute_sql_script(self._connection, _SPARSE_FTS_SCHEMA)
        with self._connection:
            self._connection.execute("DELETE FROM memory_search")
            self._backfill_memory_search()
            self._set_meta("sparse_format", "trigram-v1")
            self._set_meta("sparse_rebuilt_at", datetime.now(UTC).isoformat())
        self.fts_available = True

    def _initialize(self) -> None:
        current = self._connection.execute("PRAGMA user_version").fetchone()[0]
        if current not in {0, 1, 2, 3, 4, 5, 6, _SCHEMA_VERSION}:
            raise RuntimeError(f"不支持的 memory schema 版本：{current}")
        if current == 5:
            self._migrate_v5_to_v4()
            current = 4
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
            current = 3
        if current == 3:
            self._migrate_v3_to_v4()
            current = 4
        if current == 4:
            self._migrate_v4_to_v6()
            current = 6
        if current == 6:
            self._migrate_v6_to_v7()
            current = 7
        self._setup_sparse_index()

    def _migrate_v2_to_v3(self) -> None:
        """移除旧全局 UNIQUE，并建立 scope 内活动记录部分唯一索引。"""

        self._connection.execute("PRAGMA foreign_keys = OFF")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            _execute_sql_script(self._connection, _MIGRATION_2_TO_3)
            self._connection.execute("PRAGMA user_version = 3")
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        finally:
            self._connection.execute("PRAGMA foreign_keys = ON")

    def _migrate_v3_to_v4(self) -> None:
        """增加离线请求、治理、租约、候选结构和 Card statement。"""

        self._connection.execute("PRAGMA foreign_keys = OFF")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS consolidation_runs ("
                "run_id TEXT PRIMARY KEY, batch_key TEXT NOT NULL UNIQUE, "
                "trace_start TEXT, trace_end TEXT, status TEXT NOT NULL, "
                "checkpoint TEXT, error TEXT, created_at TEXT NOT NULL, "
                "completed_at TEXT)"
            )
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS memory_index_jobs ("
                "memory_type TEXT NOT NULL, memory_id TEXT NOT NULL, "
                "content_hash TEXT NOT NULL, state TEXT NOT NULL, "
                "attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, "
                "available_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
                "PRIMARY KEY(memory_type, memory_id))"
            )
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS memory_projection_jobs ("
                "projection_type TEXT NOT NULL, projection_key TEXT NOT NULL, "
                "payload_json TEXT NOT NULL, state TEXT NOT NULL, "
                "attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, "
                "available_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
                "PRIMARY KEY(projection_type, projection_key))"
            )
            self._ensure_v4_columns()
            create_and_rebuild = "\n".join(
                line
                for line in _MIGRATION_3_TO_4.splitlines()
                if not (line.startswith("ALTER TABLE") and " ADD COLUMN " in line)
            )
            _execute_sql_script(self._connection, create_and_rebuild)
            now = datetime.now(UTC).isoformat()
            self._connection.execute(
                "UPDATE consolidation_runs SET "
                "updated_at=COALESCE(updated_at, created_at), "
                "available_at=COALESCE(available_at, created_at)"
            )
            self._connection.execute(
                "UPDATE memory_index_jobs SET updated_at=COALESCE(updated_at, ?), "
                "available_at=COALESCE(available_at, ?)",
                (now, now),
            )
            self._connection.execute(
                "UPDATE memory_projection_jobs SET updated_at=COALESCE(updated_at, ?), "
                "available_at=COALESCE(available_at, ?)",
                (now, now),
            )
            self._connection.execute("PRAGMA user_version = 4")
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        finally:
            self._connection.execute("PRAGMA foreign_keys = ON")

    def _migrate_v4_to_v6(self) -> None:
        """Add the triggered-learning ledger without replaying old checkpoints."""

        try:
            self._connection.execute("BEGIN IMMEDIATE")
            _execute_sql_script(self._connection, _MIGRATION_4_TO_6)
            now = datetime.now(UTC).isoformat()
            self._connection.execute(
                "INSERT INTO offline_memory_checkpoints(scope_kind, scope_id, "
                "consumer, "
                "cursor, updated_at) SELECT scope_kind, scope_id, "
                "'trace-consumption-baseline', cursor, ? "
                "FROM offline_memory_checkpoints "
                "WHERE consumer='trajectory-auto-scan' "
                "ON CONFLICT(scope_kind, scope_id, consumer) DO UPDATE SET "
                "cursor=CASE WHEN excluded.cursor>offline_memory_checkpoints.cursor "
                "THEN excluded.cursor ELSE offline_memory_checkpoints.cursor END, "
                "updated_at=excluded.updated_at",
                (now,),
            )
            self._connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def _migrate_v5_to_v4(self) -> None:
        """Collapse an experimental multi-version index to its newest entry."""

        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                "CREATE TABLE semantic_index_v4 ("
                "memory_type TEXT NOT NULL, memory_id TEXT NOT NULL, "
                "content_hash TEXT NOT NULL, embedding_model TEXT NOT NULL, "
                "embedding_version TEXT NOT NULL, dimensions INTEGER NOT NULL, "
                "vector_blob BLOB NOT NULL, indexed_at TEXT NOT NULL, "
                "PRIMARY KEY(memory_type, memory_id))"
            )
            self._connection.execute(
                "INSERT INTO semantic_index_v4("
                "memory_type, memory_id, content_hash, embedding_model, "
                "embedding_version, dimensions, vector_blob, indexed_at) "
                "SELECT memory_type, memory_id, content_hash, embedding_model, "
                "embedding_version, dimensions, vector_blob, indexed_at "
                "FROM semantic_index AS current WHERE rowid=("
                "SELECT rowid FROM semantic_index AS candidate "
                "WHERE candidate.memory_type=current.memory_type "
                "AND candidate.memory_id=current.memory_id "
                "ORDER BY candidate.indexed_at DESC, candidate.rowid DESC LIMIT 1)"
            )
            self._connection.execute("DROP TABLE semantic_index")
            self._connection.execute(
                "ALTER TABLE semantic_index_v4 RENAME TO semantic_index"
            )
            self._connection.execute(
                "CREATE INDEX semantic_index_version ON semantic_index("
                "embedding_model, embedding_version, dimensions, memory_type)"
            )
            self._connection.execute("PRAGMA user_version = 4")
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise

    def _ensure_v4_columns(self) -> None:
        columns: dict[str, dict[str, str]] = {
            "claims": {
                "revision": "INTEGER NOT NULL DEFAULT 0",
                "fact_type": "TEXT NOT NULL DEFAULT 'profile'",
                "entity": "TEXT NOT NULL DEFAULT ''",
                "predicate": "TEXT NOT NULL DEFAULT ''",
                "value_json": "TEXT NOT NULL DEFAULT 'null'",
                "confidence": "REAL NOT NULL DEFAULT 0.5",
                "extractor_name": "TEXT NOT NULL DEFAULT ''",
                "extractor_version": "TEXT NOT NULL DEFAULT ''",
                "extractor_schema_version": "TEXT NOT NULL DEFAULT ''",
                "extractor_prompt_version": "TEXT NOT NULL DEFAULT ''",
                "extractor_policy_version": "TEXT NOT NULL DEFAULT ''",
                "provider": "TEXT NOT NULL DEFAULT ''",
                "model": "TEXT NOT NULL DEFAULT ''",
                "segmenter_version": "TEXT NOT NULL DEFAULT ''",
                "input_hash": "TEXT NOT NULL DEFAULT ''",
                "verification_status": "TEXT NOT NULL DEFAULT 'unverified'",
                "prompt_allowed": "INTEGER NOT NULL DEFAULT 1",
                "embedding_allowed": "INTEGER NOT NULL DEFAULT 1",
            },
            "cards": {
                "prompt_allowed": "INTEGER NOT NULL DEFAULT 1",
                "embedding_allowed": "INTEGER NOT NULL DEFAULT 1",
            },
            "trajectory_segments": {
                "sensitivity": "TEXT NOT NULL DEFAULT 'private'",
                "prompt_allowed": "INTEGER NOT NULL DEFAULT 1",
                "embedding_allowed": "INTEGER NOT NULL DEFAULT 1",
            },
            "consolidation_runs": {
                "request_id": "TEXT NOT NULL DEFAULT ''",
                "extractor_name": "TEXT NOT NULL DEFAULT ''",
                "extractor_version": "TEXT NOT NULL DEFAULT ''",
                "schema_version": "TEXT NOT NULL DEFAULT ''",
                "prompt_version": "TEXT NOT NULL DEFAULT ''",
                "policy_version": "TEXT NOT NULL DEFAULT ''",
                "provider": "TEXT NOT NULL DEFAULT ''",
                "model": "TEXT NOT NULL DEFAULT ''",
                "segmenter_version": "TEXT NOT NULL DEFAULT ''",
                "input_hash": "TEXT NOT NULL DEFAULT ''",
                "version_fingerprint": "TEXT NOT NULL DEFAULT ''",
                "attempts": "INTEGER NOT NULL DEFAULT 0",
                "max_attempts": "INTEGER NOT NULL DEFAULT 5",
                "worker_id": "TEXT NOT NULL DEFAULT ''",
                "lease_until": "TEXT",
                "last_error_type": "TEXT NOT NULL DEFAULT ''",
                "available_at": "TEXT",
                "updated_at": "TEXT",
            },
            "memory_index_jobs": {
                "last_error_type": "TEXT NOT NULL DEFAULT ''",
                "worker_id": "TEXT NOT NULL DEFAULT ''",
                "lease_until": "TEXT",
                "max_attempts": "INTEGER NOT NULL DEFAULT 5",
            },
            "memory_projection_jobs": {
                "last_error_type": "TEXT NOT NULL DEFAULT ''",
                "worker_id": "TEXT NOT NULL DEFAULT ''",
                "lease_until": "TEXT",
                "max_attempts": "INTEGER NOT NULL DEFAULT 5",
            },
        }
        for table, definitions in columns.items():
            existing = {
                str(row["name"])
                for row in self._connection.execute(
                    f"PRAGMA table_info({table})"  # noqa: S608
                ).fetchall()
            }
            for name, definition in definitions.items():
                if name not in existing:
                    self._connection.execute(
                        f"ALTER TABLE {table} ADD COLUMN {name} {definition}"  # noqa: S608
                    )

    def _insert_evidence(
        self,
        claim_id: str,
        ref: EvidenceRef,
        created_at: str,
        *,
        ignore_duplicate: bool = False,
    ) -> None:
        locator = ref.metadata.get("locator", {})
        content_hash = str(ref.metadata.get("content_hash", ""))
        insert = "INSERT OR IGNORE" if ignore_duplicate else "INSERT"
        self._connection.execute(
            f"{insert} INTO evidence(evidence_id, claim_id, kind, ref_id, quote, "
            "metadata_json, created_at, locator_json, content_hash, verified, "
            "prompt_allowed, embedding_allowed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"ev_{uuid.uuid4().hex}",
                claim_id,
                ref.kind,
                ref.ref_id,
                ref.quote,
                json.dumps(ref.metadata, ensure_ascii=False),
                created_at,
                json.dumps(locator, ensure_ascii=False, sort_keys=True),
                content_hash,
                int(bool(ref.metadata.get("verified", False))),
                int(bool(ref.metadata.get("prompt_allowed", True))),
                int(bool(ref.metadata.get("embedding_allowed", True))),
            ),
        )

    def _insert_claim_search(self, claim_id: str, content: str) -> None:
        self._upsert_sparse("claim", claim_id, content)

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
        # Card 级 FTS 已由 statement 级 sparse 索引替代（见
        # _replace_card_statements）。保留空实现兼容旧调用点，不写派生表。
        return

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

    @staticmethod
    def _request_from_row(row: sqlite3.Row) -> LongTermUpdateRequest:
        return LongTermUpdateRequest(
            request_id=str(row["request_id"]),
            source_type=str(row["source_type"]),
            scope=MemoryScope(str(row["scope_kind"]), str(row["scope_id"])),
            trace_ids=tuple(json.loads(str(row["trace_ids_json"]))),
            state=str(row["state"]),  # type: ignore[arg-type]
            version_fingerprint=str(row["version_fingerprint"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            session_id=str(row["session_id"]),
            trace_cursor=str(row["trace_cursor"]),
            priority=int(row["priority"]),
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            worker_id=str(row["worker_id"]),
            lease_until=_parse_optional_datetime(row["lease_until"]),
            available_at=_parse_optional_datetime(row["available_at"]),
            last_error_type=str(row["last_error_type"]),
            candidate_count=int(row["candidate_count"]),
        )

    @staticmethod
    def _consumption_from_row(row: sqlite3.Row) -> TraceConsumption:
        return TraceConsumption(
            consumer=str(row["consumer"]),
            scope=MemoryScope(str(row["scope_kind"]), str(row["scope_id"])),
            session_id=str(row["session_id"]),
            trace_id=str(row["trace_id"]),
            trace_started_at=datetime.fromisoformat(str(row["trace_started_at"])),
            trigger_kind=(
                str(row["trigger_kind"]) if row["trigger_kind"] is not None else None
            ),  # type: ignore[arg-type]
            state=str(row["state"]),  # type: ignore[arg-type]
            observed_at=datetime.fromisoformat(str(row["observed_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            request_id=str(row["request_id"]),
            reserved_at=_parse_optional_datetime(row["reserved_at"]),
            consumed_at=_parse_optional_datetime(row["consumed_at"]),
            released_at=_parse_optional_datetime(row["released_at"]),
            actor=str(row["actor"]),
            reason=str(row["reason"]),
        )

    @staticmethod
    def _intent_from_row(row: sqlite3.Row) -> UpdateIntent:
        return UpdateIntent(
            hint_id=str(row["hint_id"]),
            scope=MemoryScope(str(row["scope_kind"]), str(row["scope_id"])),
            session_id=str(row["session_id"]),
            boundary_key=str(row["boundary_key"]),
            state=str(row["state"]),  # type: ignore[arg-type]
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _governance_job_from_row(row: sqlite3.Row) -> GovernanceJob:
        return GovernanceJob(
            job_id=str(row["job_id"]),
            candidate_id=str(row["candidate_id"]),
            expected_revision=int(row["expected_revision"]),
            state=str(row["state"]),  # type: ignore[arg-type]
            governor_version=str(row["governor_version"]),
            policy_version=str(row["policy_version"]),
            prompt_version=str(row["prompt_version"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
            worker_id=str(row["worker_id"]),
            lease_until=_parse_optional_datetime(row["lease_until"]),
            available_at=_parse_optional_datetime(row["available_at"]),
            last_error_type=str(row["last_error_type"]),
            task_id=str(row["task_id"]),
            escalation_reason=str(row["escalation_reason"]),
        )

    @staticmethod
    def _governance_audit_from_row(row: sqlite3.Row) -> GovernanceAudit:
        return GovernanceAudit(
            decision_id=str(row["decision_id"]),
            job_id=str(row["job_id"]),
            candidate_id=str(row["candidate_id"]),
            expected_revision=int(row["expected_revision"]),
            actual_revision=(
                int(row["actual_revision"])
                if row["actual_revision"] is not None
                else None
            ),
            decision=str(row["decision"]),  # type: ignore[arg-type]
            outcome=str(row["outcome"]),  # type: ignore[arg-type]
            actor=str(row["actor"]),
            reason_codes=tuple(json.loads(str(row["reason_codes_json"]))),
            created_at=datetime.fromisoformat(str(row["created_at"])),
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


def _parse_optional_datetime(value: Any) -> datetime | None:
    return datetime.fromisoformat(str(value)) if value else None


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
    importance REAL NOT NULL DEFAULT 0.5,
    revision INTEGER NOT NULL DEFAULT 0, fact_type TEXT NOT NULL DEFAULT 'profile',
    entity TEXT NOT NULL DEFAULT '', predicate TEXT NOT NULL DEFAULT '',
    value_json TEXT NOT NULL DEFAULT 'null', confidence REAL NOT NULL DEFAULT 0.5,
    extractor_name TEXT NOT NULL DEFAULT '', extractor_version TEXT NOT NULL DEFAULT '',
    extractor_schema_version TEXT NOT NULL DEFAULT '',
    extractor_prompt_version TEXT NOT NULL DEFAULT '',
    extractor_policy_version TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '', segmenter_version TEXT NOT NULL DEFAULT '',
    input_hash TEXT NOT NULL DEFAULT '',
    verification_status TEXT NOT NULL DEFAULT 'unverified',
    prompt_allowed INTEGER NOT NULL DEFAULT 1,
    embedding_allowed INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX claims_scope_status ON claims(scope_kind, scope_id, status, created_at);
CREATE UNIQUE INDEX claims_live_content
ON claims(scope_kind, scope_id, content_hash)
WHERE status IN ('candidate', 'active', 'approved', 'frozen');
CREATE TABLE evidence (
    evidence_id TEXT PRIMARY KEY, claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    kind TEXT NOT NULL, ref_id TEXT NOT NULL, quote TEXT NOT NULL,
    metadata_json TEXT NOT NULL, created_at TEXT NOT NULL,
    locator_json TEXT NOT NULL DEFAULT '{}', content_hash TEXT NOT NULL DEFAULT '',
    verified INTEGER NOT NULL DEFAULT 0, prompt_allowed INTEGER NOT NULL DEFAULT 1,
    embedding_allowed INTEGER NOT NULL DEFAULT 1,
    UNIQUE(claim_id, kind, ref_id, content_hash, locator_json)
);
CREATE TABLE cards (
    card_id TEXT PRIMARY KEY, scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL,
    status TEXT NOT NULL, sensitivity TEXT NOT NULL, current_version INTEGER NOT NULL,
    created_at TEXT NOT NULL, projection_key TEXT NOT NULL DEFAULT '',
    prompt_allowed INTEGER NOT NULL DEFAULT 1,
    embedding_allowed INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX cards_projection_key
ON cards(projection_key) WHERE projection_key <> '';
CREATE TABLE card_versions (
    version_id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES cards(card_id),
    version INTEGER NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL,
    created_at TEXT NOT NULL, UNIQUE(card_id, version)
);
CREATE TABLE IF NOT EXISTS card_statements (
    statement_id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES cards(card_id),
    version_id TEXT NOT NULL REFERENCES card_versions(version_id),
    ordinal INTEGER NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'private', is_current INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL, UNIQUE(version_id, ordinal)
);
CREATE INDEX IF NOT EXISTS card_statements_current
ON card_statements(is_current, card_id, ordinal);
CREATE TABLE IF NOT EXISTS card_statement_claims (
    statement_id TEXT NOT NULL REFERENCES card_statements(statement_id),
    claim_id TEXT NOT NULL REFERENCES claims(claim_id), ordinal INTEGER NOT NULL,
    PRIMARY KEY(statement_id, claim_id)
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
    created_at TEXT NOT NULL, completed_at TEXT,
    request_id TEXT NOT NULL DEFAULT '', extractor_name TEXT NOT NULL DEFAULT '',
    extractor_version TEXT NOT NULL DEFAULT '', schema_version TEXT NOT NULL DEFAULT '',
    prompt_version TEXT NOT NULL DEFAULT '', policy_version TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '',
    segmenter_version TEXT NOT NULL DEFAULT '', input_hash TEXT NOT NULL DEFAULT '',
    version_fingerprint TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5, worker_id TEXT NOT NULL DEFAULT '',
    lease_until TEXT, last_error_type TEXT NOT NULL DEFAULT '',
    available_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS long_term_update_requests (
    request_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '',
    scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL,
    trace_ids_json TEXT NOT NULL DEFAULT '[]', trace_cursor TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 5,
    worker_id TEXT NOT NULL DEFAULT '', lease_until TEXT, available_at TEXT NOT NULL,
    version_fingerprint TEXT NOT NULL DEFAULT '',
    last_error_type TEXT NOT NULL DEFAULT '',
    candidate_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT
);
CREATE INDEX IF NOT EXISTS long_term_update_requests_ready
ON long_term_update_requests(state, available_at, priority, created_at);
CREATE TABLE IF NOT EXISTS offline_memory_checkpoints (
    scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL, consumer TEXT NOT NULL,
    cursor TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY(scope_kind, scope_id, consumer)
);
CREATE TABLE IF NOT EXISTS memory_trace_consumptions (
    consumer TEXT NOT NULL, scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL,
    session_id TEXT NOT NULL, trace_id TEXT NOT NULL,
    trace_started_at TEXT NOT NULL, trigger_kind TEXT,
    request_id TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL, turn_kind TEXT NOT NULL DEFAULT 'chat',
    successful_business_tool_calls INTEGER NOT NULL DEFAULT 0,
    distinct_business_tool_kinds INTEGER NOT NULL DEFAULT 0,
    elapsed_seconds REAL NOT NULL DEFAULT 0,
    observed_at TEXT NOT NULL, reserved_at TEXT,
    consumed_at TEXT, released_at TEXT, actor TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY(consumer, trace_id)
);
CREATE INDEX IF NOT EXISTS memory_trace_consumptions_session_state
ON memory_trace_consumptions(consumer, scope_kind, scope_id, session_id, state,
                             trace_started_at, trace_id);
CREATE INDEX IF NOT EXISTS memory_trace_consumptions_request
ON memory_trace_consumptions(request_id, state);
CREATE TABLE IF NOT EXISTS memory_update_intents (
    hint_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
    scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL, session_id TEXT NOT NULL,
    boundary_key TEXT NOT NULL, state TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS memory_update_intents_session_state
ON memory_update_intents(scope_kind, scope_id, session_id, state, created_at);
CREATE TABLE IF NOT EXISTS governance_jobs (
    job_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
    candidate_id TEXT NOT NULL REFERENCES claims(claim_id),
    expected_revision INTEGER NOT NULL, state TEXT NOT NULL,
    governor_version TEXT NOT NULL, policy_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5, worker_id TEXT NOT NULL DEFAULT '',
    lease_until TEXT, available_at TEXT NOT NULL,
    last_error_type TEXT NOT NULL DEFAULT '', task_id TEXT NOT NULL DEFAULT '',
    escalation_reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, completed_at TEXT
);
CREATE INDEX IF NOT EXISTS governance_jobs_ready
ON governance_jobs(state, available_at, created_at);
CREATE TABLE IF NOT EXISTS governance_decisions (
    decision_id TEXT PRIMARY KEY, decision_key TEXT NOT NULL UNIQUE,
    job_id TEXT NOT NULL REFERENCES governance_jobs(job_id),
    candidate_id TEXT NOT NULL REFERENCES claims(claim_id),
    expected_revision INTEGER NOT NULL, actual_revision INTEGER,
    decision TEXT NOT NULL, outcome TEXT NOT NULL, actor TEXT NOT NULL,
    confidence REAL NOT NULL, reason_codes_json TEXT NOT NULL,
    governor_version TEXT NOT NULL, prompt_version TEXT NOT NULL,
    policy_version TEXT NOT NULL, relation TEXT NOT NULL DEFAULT '',
    target_claim_id TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidate_relations (
    candidate_id TEXT NOT NULL REFERENCES claims(claim_id),
    target_claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    relation TEXT NOT NULL, expected_target_revision INTEGER,
    confidence REAL NOT NULL DEFAULT 1.0, status TEXT NOT NULL DEFAULT 'proposed',
    created_at TEXT NOT NULL,
    PRIMARY KEY(candidate_id, target_claim_id, relation)
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
    sensitivity TEXT NOT NULL DEFAULT 'private',
    prompt_allowed INTEGER NOT NULL DEFAULT 1,
    embedding_allowed INTEGER NOT NULL DEFAULT 1,
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
    last_error_type TEXT NOT NULL DEFAULT '', worker_id TEXT NOT NULL DEFAULT '',
    lease_until TEXT, max_attempts INTEGER NOT NULL DEFAULT 5,
    PRIMARY KEY(memory_type, memory_id)
);
CREATE INDEX memory_index_jobs_state
ON memory_index_jobs(state, available_at, updated_at);
CREATE TABLE memory_projection_jobs (
    projection_type TEXT NOT NULL, projection_key TEXT NOT NULL,
    payload_json TEXT NOT NULL, state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
    available_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    last_error_type TEXT NOT NULL DEFAULT '', worker_id TEXT NOT NULL DEFAULT '',
    lease_until TEXT, max_attempts INTEGER NOT NULL DEFAULT 5,
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
INSERT INTO claims_v3(
    claim_id, content, normalized_content, content_hash, source, explicitness,
    scope_kind, scope_id, sensitivity, status, valid_from, valid_to, created_at,
    subject, card_kind, importance
) SELECT
    claim_id, content, normalized_content, content_hash, source, explicitness,
    scope_kind, scope_id, sensitivity, status, valid_from, valid_to, created_at,
    subject, card_kind, importance
FROM claims;
DROP TABLE claims;
ALTER TABLE claims_v3 RENAME TO claims;
CREATE INDEX claims_scope_status ON claims(scope_kind, scope_id, status, created_at);
CREATE UNIQUE INDEX claims_live_content
ON claims(scope_kind, scope_id, content_hash)
WHERE status IN ('candidate', 'active', 'approved', 'frozen');
"""

_MIGRATION_3_TO_4 = """
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY, claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    kind TEXT NOT NULL, ref_id TEXT NOT NULL, quote TEXT NOT NULL,
    metadata_json TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(claim_id, kind, ref_id)
);
CREATE TABLE IF NOT EXISTS card_versions (
    version_id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES cards(card_id),
    version INTEGER NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL,
    created_at TEXT NOT NULL, UNIQUE(card_id, version)
);
CREATE TABLE IF NOT EXISTS card_claim_relations (
    card_id TEXT NOT NULL REFERENCES cards(card_id),
    claim_id TEXT NOT NULL REFERENCES claims(claim_id), relation TEXT NOT NULL,
    created_at TEXT NOT NULL, PRIMARY KEY(card_id, claim_id, relation)
);
CREATE TABLE IF NOT EXISTS claim_relations (
    source_claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    target_claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    relation TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(source_claim_id, target_claim_id, relation)
);
CREATE TABLE IF NOT EXISTS memory_revisions (
    revision_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
    action TEXT NOT NULL, actor TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS consolidation_runs (
    run_id TEXT PRIMARY KEY, batch_key TEXT NOT NULL UNIQUE, trace_start TEXT,
    trace_end TEXT, status TEXT NOT NULL, checkpoint TEXT, error TEXT,
    created_at TEXT NOT NULL, completed_at TEXT
);
ALTER TABLE claims ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE claims ADD COLUMN fact_type TEXT NOT NULL DEFAULT 'profile';
ALTER TABLE claims ADD COLUMN entity TEXT NOT NULL DEFAULT '';
ALTER TABLE claims ADD COLUMN predicate TEXT NOT NULL DEFAULT '';
ALTER TABLE claims ADD COLUMN value_json TEXT NOT NULL DEFAULT 'null';
ALTER TABLE claims ADD COLUMN confidence REAL NOT NULL DEFAULT 0.5;
ALTER TABLE claims ADD COLUMN extractor_name TEXT NOT NULL DEFAULT '';
ALTER TABLE claims ADD COLUMN extractor_version TEXT NOT NULL DEFAULT '';
ALTER TABLE claims ADD COLUMN extractor_schema_version TEXT NOT NULL DEFAULT '';
ALTER TABLE claims ADD COLUMN extractor_prompt_version TEXT NOT NULL DEFAULT '';
ALTER TABLE claims ADD COLUMN extractor_policy_version TEXT NOT NULL DEFAULT '';
ALTER TABLE claims ADD COLUMN provider TEXT NOT NULL DEFAULT '';
ALTER TABLE claims ADD COLUMN model TEXT NOT NULL DEFAULT '';
ALTER TABLE claims ADD COLUMN segmenter_version TEXT NOT NULL DEFAULT '';
ALTER TABLE claims ADD COLUMN input_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE claims ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'unverified';
ALTER TABLE claims ADD COLUMN prompt_allowed INTEGER NOT NULL DEFAULT 1;
ALTER TABLE claims ADD COLUMN embedding_allowed INTEGER NOT NULL DEFAULT 1;
CREATE TABLE evidence_v4 (
    evidence_id TEXT PRIMARY KEY, claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    kind TEXT NOT NULL, ref_id TEXT NOT NULL, quote TEXT NOT NULL,
    metadata_json TEXT NOT NULL, created_at TEXT NOT NULL,
    locator_json TEXT NOT NULL DEFAULT '{}', content_hash TEXT NOT NULL DEFAULT '',
    verified INTEGER NOT NULL DEFAULT 0, prompt_allowed INTEGER NOT NULL DEFAULT 1,
    embedding_allowed INTEGER NOT NULL DEFAULT 1,
    UNIQUE(claim_id, kind, ref_id, content_hash, locator_json)
);
INSERT INTO evidence_v4(
    evidence_id, claim_id, kind, ref_id, quote, metadata_json, created_at
) SELECT evidence_id, claim_id, kind, ref_id, quote, metadata_json, created_at
FROM evidence;
DROP TABLE evidence;
ALTER TABLE evidence_v4 RENAME TO evidence;
ALTER TABLE consolidation_runs ADD COLUMN request_id TEXT NOT NULL DEFAULT '';
ALTER TABLE consolidation_runs ADD COLUMN extractor_name TEXT NOT NULL DEFAULT '';
ALTER TABLE consolidation_runs ADD COLUMN extractor_version TEXT NOT NULL DEFAULT '';
ALTER TABLE consolidation_runs ADD COLUMN schema_version TEXT NOT NULL DEFAULT '';
ALTER TABLE consolidation_runs ADD COLUMN prompt_version TEXT NOT NULL DEFAULT '';
ALTER TABLE consolidation_runs ADD COLUMN policy_version TEXT NOT NULL DEFAULT '';
ALTER TABLE consolidation_runs ADD COLUMN provider TEXT NOT NULL DEFAULT '';
ALTER TABLE consolidation_runs ADD COLUMN model TEXT NOT NULL DEFAULT '';
ALTER TABLE consolidation_runs ADD COLUMN segmenter_version TEXT NOT NULL DEFAULT '';
ALTER TABLE consolidation_runs ADD COLUMN input_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE consolidation_runs ADD COLUMN version_fingerprint TEXT NOT NULL DEFAULT '';
ALTER TABLE consolidation_runs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE consolidation_runs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 5;
ALTER TABLE consolidation_runs ADD COLUMN worker_id TEXT NOT NULL DEFAULT '';
ALTER TABLE consolidation_runs ADD COLUMN lease_until TEXT;
ALTER TABLE consolidation_runs ADD COLUMN last_error_type TEXT NOT NULL DEFAULT '';
ALTER TABLE consolidation_runs ADD COLUMN available_at TEXT;
ALTER TABLE consolidation_runs ADD COLUMN updated_at TEXT;
ALTER TABLE memory_index_jobs ADD COLUMN last_error_type TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_index_jobs ADD COLUMN worker_id TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_index_jobs ADD COLUMN lease_until TEXT;
ALTER TABLE memory_index_jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 5;
ALTER TABLE memory_projection_jobs ADD COLUMN last_error_type TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_projection_jobs ADD COLUMN worker_id TEXT NOT NULL DEFAULT '';
ALTER TABLE memory_projection_jobs ADD COLUMN lease_until TEXT;
ALTER TABLE memory_projection_jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 5;
CREATE TABLE IF NOT EXISTS long_term_update_requests (
    request_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '',
    scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL,
    trace_ids_json TEXT NOT NULL DEFAULT '[]', trace_cursor TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 5,
    worker_id TEXT NOT NULL DEFAULT '', lease_until TEXT, available_at TEXT NOT NULL,
    version_fingerprint TEXT NOT NULL DEFAULT '',
    last_error_type TEXT NOT NULL DEFAULT '',
    candidate_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT
);
CREATE INDEX IF NOT EXISTS long_term_update_requests_ready
ON long_term_update_requests(state, available_at, priority, created_at);
CREATE TABLE IF NOT EXISTS offline_memory_checkpoints (
    scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL, consumer TEXT NOT NULL,
    cursor TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY(scope_kind, scope_id, consumer)
);
CREATE TABLE IF NOT EXISTS governance_jobs (
    job_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
    candidate_id TEXT NOT NULL REFERENCES claims(claim_id),
    expected_revision INTEGER NOT NULL, state TEXT NOT NULL,
    governor_version TEXT NOT NULL, policy_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5, worker_id TEXT NOT NULL DEFAULT '',
    lease_until TEXT, available_at TEXT NOT NULL,
    last_error_type TEXT NOT NULL DEFAULT '', task_id TEXT NOT NULL DEFAULT '',
    escalation_reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, completed_at TEXT
);
CREATE INDEX IF NOT EXISTS governance_jobs_ready
ON governance_jobs(state, available_at, created_at);
CREATE TABLE IF NOT EXISTS governance_decisions (
    decision_id TEXT PRIMARY KEY, decision_key TEXT NOT NULL UNIQUE,
    job_id TEXT NOT NULL REFERENCES governance_jobs(job_id),
    candidate_id TEXT NOT NULL REFERENCES claims(claim_id),
    expected_revision INTEGER NOT NULL, actual_revision INTEGER,
    decision TEXT NOT NULL, outcome TEXT NOT NULL, actor TEXT NOT NULL,
    confidence REAL NOT NULL, reason_codes_json TEXT NOT NULL,
    governor_version TEXT NOT NULL, prompt_version TEXT NOT NULL,
    policy_version TEXT NOT NULL, relation TEXT NOT NULL DEFAULT '',
    target_claim_id TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidate_relations (
    candidate_id TEXT NOT NULL REFERENCES claims(claim_id),
    target_claim_id TEXT NOT NULL REFERENCES claims(claim_id),
    relation TEXT NOT NULL, expected_target_revision INTEGER,
    confidence REAL NOT NULL DEFAULT 1.0, status TEXT NOT NULL DEFAULT 'proposed',
    created_at TEXT NOT NULL,
    PRIMARY KEY(candidate_id, target_claim_id, relation)
);
CREATE TABLE IF NOT EXISTS card_statements (
    statement_id TEXT PRIMARY KEY, card_id TEXT NOT NULL REFERENCES cards(card_id),
    version_id TEXT NOT NULL REFERENCES card_versions(version_id),
    ordinal INTEGER NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL,
    sensitivity TEXT NOT NULL DEFAULT 'private', is_current INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL, UNIQUE(version_id, ordinal)
);
CREATE INDEX IF NOT EXISTS card_statements_current
ON card_statements(is_current, card_id, ordinal);
CREATE TABLE IF NOT EXISTS card_statement_claims (
    statement_id TEXT NOT NULL REFERENCES card_statements(statement_id),
    claim_id TEXT NOT NULL REFERENCES claims(claim_id), ordinal INTEGER NOT NULL,
    PRIMARY KEY(statement_id, claim_id)
);
"""

_MIGRATION_4_TO_6 = """
CREATE TABLE IF NOT EXISTS memory_trace_consumptions (
    consumer TEXT NOT NULL, scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL,
    session_id TEXT NOT NULL, trace_id TEXT NOT NULL,
    trace_started_at TEXT NOT NULL, trigger_kind TEXT,
    request_id TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL, turn_kind TEXT NOT NULL DEFAULT 'chat',
    successful_business_tool_calls INTEGER NOT NULL DEFAULT 0,
    distinct_business_tool_kinds INTEGER NOT NULL DEFAULT 0,
    elapsed_seconds REAL NOT NULL DEFAULT 0,
    observed_at TEXT NOT NULL, reserved_at TEXT,
    consumed_at TEXT, released_at TEXT, actor TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY(consumer, trace_id)
);
CREATE INDEX IF NOT EXISTS memory_trace_consumptions_session_state
ON memory_trace_consumptions(consumer, scope_kind, scope_id, session_id, state,
                             trace_started_at, trace_id);
CREATE INDEX IF NOT EXISTS memory_trace_consumptions_request
ON memory_trace_consumptions(request_id, state);
CREATE TABLE IF NOT EXISTS memory_update_intents (
    hint_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
    scope_kind TEXT NOT NULL, scope_id TEXT NOT NULL, session_id TEXT NOT NULL,
    boundary_key TEXT NOT NULL, state TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS memory_update_intents_session_state
ON memory_update_intents(scope_kind, scope_id, session_id, state, created_at);
"""

_INDEX_META_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_index_meta(
    key TEXT PRIMARY KEY, value TEXT NOT NULL
);
"""

_SPARSE_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS memory_search USING fts5(
    memory_type UNINDEXED, memory_id UNINDEXED, content,
    tokenize='trigram'
);
"""
