"""Private context-state persistence, separate from memory and trajectory."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, replace
from pathlib import Path
from typing import Protocol

from memoli_agent.agent.context_management.models import (
    ContextArchive,
    ContextDiagnostic,
    ContextSnapshot,
    FrozenToolPreview,
    OutboxEvent,
    ToolDisclosure,
)

# §6.1：v2 增加 archives 的 epoch/level/status/coverage_hash/parent_archive_refs
# 列与 coverage/outbox 表；旧 v1 DB 经 _migrate_v1_to_v2 additive 升级，不删数据。
# §7.1：v3 把 snapshots 主键迁移到 (session_key, conversation_epoch)。
# §7.4：v4 给 previews 加 visible 列（派生索引 epoch 清理/不可见状态）。
SCHEMA_VERSION = 6


class ContextStateError(RuntimeError):
    """Context state is unavailable or incompatible."""


class ContextStateRepository(Protocol):
    def close(self) -> None: ...

    def get_snapshot(
        self, session_key: str, epoch: int = 0, revision: int | None = None
    ) -> ContextSnapshot | None: ...

    def save_snapshot(self, snapshot: ContextSnapshot) -> ContextSnapshot: ...

    def invalidate_snapshot(
        self, session_key: str, reason: str, epoch: int = 0,
        revision: int | None = None,
    ) -> None: ...

    def save_tool_disclosure(self, disclosure: ToolDisclosure) -> ToolDisclosure: ...

    def list_tool_disclosures(
        self, session_key: str, epoch: int, revision: int | None = None
    ) -> tuple[ToolDisclosure, ...]: ...

    def list_archives(self, session_key: str) -> tuple[ContextArchive, ...]: ...

    def list_frontier(self, session_key: str) -> tuple[ContextArchive, ...]:
        """§6.1 活动 frontier：status='active' 的 archive，按 generation 升序。"""
        ...

    def append_archive(self, archive: ContextArchive) -> None: ...

    def commit_archive(
        self,
        archive: ContextArchive,
        *,
        outbox: OutboxEvent | None = None,
        reset_failures: bool = True,
    ) -> tuple[ContextArchive, bool]:
        """§6.2 单事务内分配 ``(session,epoch)`` generation 并原子提交
        archive/coverage/失败计数重置/outbox 行。返回
        ``(已提交 archive, 是否本次新建)``：
        重试同 ``archive_id`` 幂等返回 ``(已提交, False)``，不重复分配 generation
        或写 coverage/outbox。coverage 活动非重叠或 generation 冲突抛
        ``ContextStateError``（§6.3 由协调器转为 fresh re-compile）。"""
        ...

    def merge_archives(
        self,
        parents: tuple[ContextArchive, ...],
        merged: ContextArchive,
        *,
        outbox: OutboxEvent | None = None,
        reset_failures: bool = False,
    ) -> tuple[ContextArchive, bool]:
        """§6.5 分层合并：把若干活动父 archive 原子合并为更高层 archive。

        事务顺序（correction 3，load-bearing）：先 supersede 父 archive 与父
        coverage 行（移出活动 partial-unique 范围），再 INSERT merged coverage 行
        （活动），再 INSERT merged archive（活动，事务内分配 generation），最后
        outbox。父 archive/coverage 行留存审计（status=superseded、
        superseded_by=merged_id，design line 104「保留原始 source coverage」）。
        重试同 ``merged.archive_id`` 幂等返回 ``(已提交, False)``。父非活动
        （已被并发合并）、coverage invariant 违反（``set(parents.refs) ⊄
        set(merged.refs)``，correction 4）或 merged coverage 与其他活动 archive
        重叠抛 ``ContextStateError``（事务回滚，父节点保持活动）。"""
        ...

    def mark_outbox_delivered(self, outbox_id: str, *, delivered_at: str) -> None: ...

    def mark_outbox_failed(self, outbox_id: str, *, error: str) -> None: ...

    def list_pending_outbox(self, session_key: str) -> tuple[OutboxEvent, ...]:
        """§6.6 列出 ``pending``/``failed`` 状态的 outbox 行（供重放）。

        返回的 ``OutboxEvent.payload`` 为 commit_archive/merge_archives 事务内
        填入的已提交 archive 完整 data JSON，``span_projection`` 为 completed
        SpanProjection JSON，重放时据此重建 archive 与 span 自洽投递。
        ``delivered`` 行不返回（已投递无需重放）。
        """
        ...

    def get_preview(self, preview_id: str) -> FrozenToolPreview | None: ...

    def save_preview(self, preview: FrozenToolPreview) -> None: ...

    def get_preview_by_ref(
        self, session_key: str, epoch: int, tool_call_id: str
    ) -> FrozenToolPreview | None: ...

    def clear_epoch_previews(
        self, session_key: str, *, before_epoch: int
    ) -> int:
        """§7.4 把早于 ``before_epoch`` 的冻结预览派生索引标记为不可见。

        ``/clear`` 推进到新 epoch 后调用，传入 ``before_epoch=new_epoch``：所有
        旧 epoch 的预览被标记不可见（不删除，保留审计/可重建的派生索引），新 epoch
        预览保持可见。原始受管 payload 的保留遵循 trajectory 策略，不受本操作影响
        （design §7 line 91「清理 epoch 只删除派生索引或将其标记不可见，原始受管
        payload 的保留仍遵循 trajectory 策略」）。返回被标记不可见的预览数。
        ``get_preview_by_ref`` 只返回可见预览，故不可见预览不再注入新 epoch 上下文。
        """
        ...

    def set_compaction_failures(self, session_key: str, failures: int) -> None: ...

    def get_compaction_failures(self, session_key: str) -> int: ...

    def save_diagnostics(
        self, session_key: str, diagnostics: tuple[ContextDiagnostic, ...]
    ) -> None: ...

    def diagnostic_summary(self, session_key: str) -> dict[str, object]: ...

    def reset_session(self, session_key: str) -> None: ...


class InMemoryContextStateRepository:
    """Non-persistent state; intentionally starts empty after process restart."""

    def __init__(self) -> None:
        self.snapshots: dict[tuple[str, int, int], ContextSnapshot] = {}
        self.archives: dict[str, list[ContextArchive]] = {}
        # §6.1 coverage 行：{archive_id, source_ref, superseded_by}（''=活动）。
        # superseded_by 非空 = 被该 archive 取代后留存审计（design §5 line 104）。
        self.coverage: dict[str, list[dict[str, str]]] = {}
        # §6.1 outbox 行（结构对等；投递由 §6.6 实现）。
        self.outbox: dict[str, list[dict[str, object]]] = {}
        self.previews: dict[str, FrozenToolPreview] = {}
        self.tool_disclosures: dict[tuple[str, int, int], list[ToolDisclosure]] = {}
        # §7.4 不可见预览派生索引：epoch 清理时把旧 epoch 预览标记不可见（不删，
        # 保留审计/可重建），get_preview_by_ref 据此过滤，不注入新 epoch 上下文。
        self.invisible_previews: set[str] = set()
        self.failures: dict[str, int] = {}
        self.diagnostics: dict[str, tuple[ContextDiagnostic, ...]] = {}
        self._lock = threading.RLock()

    def close(self) -> None:
        return None

    def get_snapshot(
        self, session_key: str, epoch: int = 0, revision: int | None = None
    ) -> ContextSnapshot | None:
        with self._lock:
            if revision is not None:
                return self.snapshots.get((session_key, epoch, revision))
            matches = [
                snapshot
                for (key, item_epoch, _), snapshot in self.snapshots.items()
                if key == session_key and item_epoch == epoch
            ]
            return max(matches, key=lambda item: item.capability_revision, default=None)

    def save_snapshot(self, snapshot: ContextSnapshot) -> ContextSnapshot:
        with self._lock:
            latest = self.get_snapshot(
                snapshot.session_key, snapshot.conversation_epoch
            )
            if (
                latest is not None
                and not latest.invalidated_reason
                and latest.stable_prefix_hash == snapshot.stable_prefix_hash
            ):
                return latest
            revision = latest.capability_revision + 1 if latest is not None else 1
            committed = replace(snapshot, capability_revision=revision)
            key = (committed.session_key, committed.conversation_epoch, revision)
            self.snapshots[key] = committed
            return committed

    def invalidate_snapshot(
        self, session_key: str, reason: str, epoch: int = 0,
        revision: int | None = None,
    ) -> None:
        with self._lock:
            current = self.get_snapshot(session_key, epoch, revision)
            if current is not None and not current.invalidated_reason:
                key = (session_key, epoch, current.capability_revision)
                self.snapshots[key] = replace(
                    current, invalidated_reason=reason[:512]
                )

    def save_tool_disclosure(self, disclosure: ToolDisclosure) -> ToolDisclosure:
        with self._lock:
            key = (
                disclosure.session_key,
                disclosure.conversation_epoch,
                disclosure.capability_revision,
            )
            items = self.tool_disclosures.setdefault(key, [])
            existing = next(
                (item for item in items if item.tool_name == disclosure.tool_name),
                None,
            )
            if existing is not None:
                if existing.schema_hash != disclosure.schema_hash:
                    raise ContextStateError(
                        "disclosed tool schema changed within capability revision"
                    )
                return existing
            committed = replace(disclosure, sequence=len(items) + 1)
            items.append(committed)
            return committed

    def list_tool_disclosures(
        self, session_key: str, epoch: int, revision: int | None = None
    ) -> tuple[ToolDisclosure, ...]:
        with self._lock:
            selected = revision
            if selected is None:
                snapshot = self.get_snapshot(session_key, epoch)
                selected = snapshot.capability_revision if snapshot is not None else 1
            return tuple(self.tool_disclosures.get((session_key, epoch, selected), ()))

    def list_archives(self, session_key: str) -> tuple[ContextArchive, ...]:
        with self._lock:
            return tuple(self.archives.get(session_key, ()))

    def list_frontier(self, session_key: str) -> tuple[ContextArchive, ...]:
        with self._lock:
            items = [
                item
                for item in self.archives.get(session_key, ())
                if item.status == "active"
            ]
            items.sort(key=lambda item: item.generation)
            return tuple(items)

    def append_archive(self, archive: ContextArchive) -> None:
        with self._lock:
            items = self.archives.setdefault(archive.session_key, [])
            if any(item.archive_id == archive.archive_id for item in items):
                return  # 重试幂等：同 archive_id 不重复写
            coverage = self.coverage.setdefault(archive.session_key, [])
            active_refs = {
                row["source_ref"]
                for row in coverage
                if row["superseded_by"] == ""
            }
            for source_ref in archive.source_refs:
                # 活动非重叠：已被其他活动 archive 覆盖的 ref 跳过（对等 SQLite
                # partial UNIQUE + INSERT OR IGNORE 的跳过语义；并发冲突显式报错
                # 由 §6.3 commit_archive 在事务内统一处理）。
                if source_ref in active_refs:
                    continue
                if not any(
                    row["archive_id"] == archive.archive_id
                    and row["source_ref"] == source_ref
                    for row in coverage
                ):
                    coverage.append(
                        {
                            "archive_id": archive.archive_id,
                            "source_ref": source_ref,
                            "superseded_by": "",
                        }
                    )
                    active_refs.add(source_ref)
            items.append(archive)

    def commit_archive(
        self,
        archive: ContextArchive,
        *,
        outbox: OutboxEvent | None = None,
        reset_failures: bool = True,
    ) -> tuple[ContextArchive, bool]:
        # §6.2 单事务（内存版用 _lock 串行对等）：先查 archive_id 幂等，再事务内
        # 分配 (session,epoch) generation=max+1，写 coverage（活动非重叠冲突报错）、
        # 重置失败计数、写 outbox 行（INSERT OR IGNORE 对等）。
        with self._lock:
            items = self.archives.setdefault(archive.session_key, [])
            existing = next(
                (
                    item
                    for item in items
                    if item.archive_id == archive.archive_id
                ),
                None,
            )
            if existing is not None:
                # 重试幂等：同 archive_id 已提交（事务原子，coverage/outbox 必同在）
                return existing, False
            generation = 1 + max(
                (item.generation for item in items if item.epoch == archive.epoch),
                default=0,
            )
            committed = replace(archive, generation=generation)
            coverage = self.coverage.setdefault(archive.session_key, [])
            active_refs = {
                row["source_ref"]
                for row in coverage
                if row["superseded_by"] == ""
                and row["archive_id"] != committed.archive_id
            }
            # §6.2 coverage 写入按 source_ref 去重：批次内可能含相同内容消息
            # （如重复 tool 结果），同一 ref 只覆盖一次。archive.source_refs 仍
            # 保留原序（§5.4 与批次 direct refs 完全一致合同），coverage 表为集合。
            for source_ref in dict.fromkeys(committed.source_refs):
                # 活动非重叠：已被其他活动 archive 覆盖的 ref → 真实重叠，报错
                # （对等 SQLite partial UNIQUE IntegrityError；§6.3
                # 转 fresh re-compile）
                if source_ref in active_refs:
                    raise ContextStateError("coverage overlap with active archive")
                if not any(
                    row["archive_id"] == committed.archive_id
                    and row["source_ref"] == source_ref
                    for row in coverage
                ):
                    coverage.append(
                        {
                            "archive_id": committed.archive_id,
                            "source_ref": source_ref,
                            "superseded_by": "",
                        }
                    )
                    active_refs.add(source_ref)
            items.append(committed)
            if reset_failures:
                # §6.2 成功提交重置熔断计数（correction 16：reset，非记录）
                self.failures[archive.session_key] = 0
            if outbox is not None:
                queue = self.outbox.setdefault(archive.session_key, [])
                if not any(
                    row["archive_id"] == outbox.archive_id
                    and row["event_type"] == outbox.event_type
                    for row in queue
                ):
                    # payload 由本事务填入已提交 archive 完整 data（含分配 generation）
                    filled = replace(outbox, payload=_json(asdict(committed)))
                    queue.append(asdict(filled))
            return committed, True

    def merge_archives(
        self,
        parents: tuple[ContextArchive, ...],
        merged: ContextArchive,
        *,
        outbox: OutboxEvent | None = None,
        reset_failures: bool = False,
    ) -> tuple[ContextArchive, bool]:
        # §6.5 分层合并（内存版用 _lock 串行对等）。validate-then-mutate：所有
        # 前置校验（父活动、invariant、merged coverage 不与其他活动 archive 重叠）
        # 先于任何变更，故校验失败时父节点保持活动、无部分 supersede（对等
        # SQLite 靠事务回滚 + partial UNIQUE 约束）。
        if len(parents) < 2:
            raise ValueError("merge requires at least two parents")
        with self._lock:
            items = self.archives.setdefault(merged.session_key, [])
            existing = next(
                (item for item in items if item.archive_id == merged.archive_id),
                None,
            )
            if existing is not None:
                # 重试幂等：同 merged.archive_id 已提交（事务原子，coverage 同在）
                return existing, False
            parent_ids = {p.archive_id for p in parents}
            active_ids = {
                item.archive_id for item in items if item.status == "active"
            }
            # 前置校验 1：父均为活动（correction 3；并发合并已取代某父 → 冲突）
            if not parent_ids <= active_ids:
                raise ContextStateError("merge parent not active (concurrent merge)")
            # 前置校验 2：invariant——父 refs ⊆ merged refs（correction 4）
            merged_refs_set = set(merged.source_refs)
            for parent in parents:
                if not set(parent.source_refs) <= merged_refs_set:
                    raise ContextStateError("merge violates coverage invariant")
            coverage = self.coverage.setdefault(merged.session_key, [])
            # 前置校验 3：merged coverage 不与其他（非父）活动 archive 重叠
            other_active_refs = {
                row["source_ref"]
                for row in coverage
                if row["superseded_by"] == "" and row["archive_id"] not in parent_ids
            }
            if merged_refs_set & other_active_refs:
                raise ContextStateError("merge coverage overlaps active archive")
            # (1) supersede 父 archive：status=superseded（不可变节点留存审计）
            for index, item in enumerate(items):
                if item.archive_id in parent_ids:
                    items[index] = replace(item, status="superseded")
            # (2) supersede 父 coverage 行：superseded_by=merged_id（行留存审计）
            for row in coverage:
                if row["archive_id"] in parent_ids and row["superseded_by"] == "":
                    row["superseded_by"] = merged.archive_id
            # (3) INSERT merged coverage 行（活动，已前置校验无重叠）
            for source_ref in dict.fromkeys(merged.source_refs):
                if not any(
                    row["archive_id"] == merged.archive_id
                    and row["source_ref"] == source_ref
                    for row in coverage
                ):
                    coverage.append(
                        {
                            "archive_id": merged.archive_id,
                            "source_ref": source_ref,
                            "superseded_by": "",
                        }
                    )
            # (4) INSERT merged archive（事务内分配 generation，monotonic per epoch）
            generation = 1 + max(
                (item.generation for item in items if item.epoch == merged.epoch),
                default=0,
            )
            committed = replace(merged, generation=generation)
            items.append(committed)
            if reset_failures:
                self.failures[merged.session_key] = 0
            # (5) outbox（INSERT OR IGNORE 对等）
            if outbox is not None:
                queue = self.outbox.setdefault(merged.session_key, [])
                if not any(
                    row["archive_id"] == outbox.archive_id
                    and row["event_type"] == outbox.event_type
                    for row in queue
                ):
                    filled = replace(outbox, payload=_json(asdict(committed)))
                    queue.append(asdict(filled))
            return committed, True

    def mark_outbox_delivered(self, outbox_id: str, *, delivered_at: str) -> None:
        with self._lock:
            row = self._find_outbox_row(outbox_id)
            if row is not None:
                row["status"] = "delivered"
                row["delivered_at"] = delivered_at

    def mark_outbox_failed(self, outbox_id: str, *, error: str) -> None:
        with self._lock:
            row = self._find_outbox_row(outbox_id)
            if row is not None:
                row["status"] = "failed"
                attempts = row.get("attempts", 0)
                if not isinstance(attempts, int):
                    attempts = 0
                row["attempts"] = attempts + 1
                row["last_error"] = error[:512]

    def list_pending_outbox(self, session_key: str) -> tuple[OutboxEvent, ...]:
        with self._lock:
            rows = [
                row
                for row in self.outbox.get(session_key, ())
                if row.get("status") in ("pending", "failed")
            ]
            return tuple(_outbox_from_mapping(row) for row in rows)

    def _find_outbox_row(self, outbox_id: str) -> dict[str, object] | None:
        for queue in self.outbox.values():
            for row in queue:
                if row.get("outbox_id") == outbox_id:
                    return row
        return None

    def get_preview(self, preview_id: str) -> FrozenToolPreview | None:
        with self._lock:
            return self.previews.get(preview_id)

    def save_preview(self, preview: FrozenToolPreview) -> None:
        with self._lock:
            self.previews.setdefault(preview.preview_id, preview)

    def get_preview_by_ref(
        self, session_key: str, epoch: int, tool_call_id: str
    ) -> FrozenToolPreview | None:
        # §7.3 恢复期按 (session_key, epoch, tool_call_id) 取冻结预览以校验引用
        # 完整性；旧预览无 epoch 字段时 dataclass 默认 0，仍可被 epoch=0 命中。
        # §7.4 不可见预览（epoch 清理后标记）不返回，避免注入新 epoch 上下文。
        with self._lock:
            for preview in self.previews.values():
                if (
                    preview.session_key == session_key
                    and preview.epoch == epoch
                    and preview.tool_call_id == tool_call_id
                    and preview.preview_id not in self.invisible_previews
                ):
                    return preview
        return None

    def clear_epoch_previews(
        self, session_key: str, *, before_epoch: int
    ) -> int:
        # §7.4 把早于 before_epoch 的预览标记不可见（不删，保留审计/可重建派生
        # 索引）。新 epoch 预览（epoch >= before_epoch）保持可见。幂等：已不可见
        # 的预览不重复计数。
        with self._lock:
            count = 0
            for preview in self.previews.values():
                if (
                    preview.session_key == session_key
                    and preview.epoch < before_epoch
                    and preview.preview_id not in self.invisible_previews
                ):
                    self.invisible_previews.add(preview.preview_id)
                    count += 1
            return count

    def set_compaction_failures(self, session_key: str, failures: int) -> None:
        with self._lock:
            self.failures[session_key] = max(0, failures)

    def get_compaction_failures(self, session_key: str) -> int:
        with self._lock:
            return self.failures.get(session_key, 0)

    def save_diagnostics(
        self, session_key: str, diagnostics: tuple[ContextDiagnostic, ...]
    ) -> None:
        with self._lock:
            self.diagnostics[session_key] = diagnostics

    def diagnostic_summary(self, session_key: str) -> dict[str, object]:
        with self._lock:
            archives = self.archives.get(session_key, ())
            frontier = [item for item in archives if item.status == "active"]
            diagnostics = self.diagnostics.get(session_key, ())
            # §6.6 outbox pending/failed 计数：诊断暴露未投递审计事件，供运维定位
            # 延迟投递（不暴露 payload/span——仅哈希/计数/稳定引用，§8.3 安全）
            outbox_rows = self.outbox.get(session_key, ())
            outbox_pending = sum(
                1 for row in outbox_rows if row.get("status") == "pending"
            )
            outbox_failed = sum(
                1 for row in outbox_rows if row.get("status") == "failed"
            )
            return {
                "archive_generation": archives[-1].generation if archives else 0,
                "archive_level": frontier[-1].level if frontier else 0,
                "frontier_active_count": len(frontier),
                "compaction_failures": self.failures.get(session_key, 0),
                "outbox_pending": outbox_pending,
                "outbox_failed": outbox_failed,
                "diagnostic_actions": tuple(item.action for item in diagnostics),
            }

    def reset_session(self, session_key: str) -> None:
        with self._lock:
            # §7.1 snapshots 以 (session_key, epoch) 为键；/clear 重置派生状态
            # 时清掉该会话全部 epoch 的快照（新 epoch 将重新冻结）。
            self.snapshots = {
                (sk, ep, revision): snap
                for (sk, ep, revision), snap in self.snapshots.items()
                if sk != session_key
            }
            self.archives.pop(session_key, None)
            self.coverage.pop(session_key, None)
            self.outbox.pop(session_key, None)
            self.failures.pop(session_key, None)
            self.diagnostics.pop(session_key, None)
            self.tool_disclosures = {
                key: value
                for key, value in self.tool_disclosures.items()
                if key[0] != session_key
            }
            # §7.4 预览派生索引不在此硬删：由 clear_epoch_previews 按 epoch 标记
            # 不可见（保留审计/可重建），原始 payload 由 trajectory 独立保留。
            # 预览行与不可见标记一并保留，不受本会话硬重置影响。


class SQLiteContextStateRepository:
    """Small transactional SQLite store for immutable context artifacts."""

    def __init__(self, database: str | Path) -> None:
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.database, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        try:
            self._initialize()
        except Exception:
            self._connection.close()
            raise

    def _initialize(self) -> None:
        with self._lock, self._connection:
            # SQLite DDL 在隐式事务开始前可能直接持久化；显式事务保证 clone-copy-
            # rename 迁移任一步失败时 schema 与版本整体回滚。
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_info "
                "(component TEXT PRIMARY KEY, version INTEGER NOT NULL)"
            )
            row = self._connection.execute(
                "SELECT version FROM schema_info WHERE component='context-state'"
            ).fetchone()
            current = int(row["version"]) if row is not None else None
            if current is None:
                # 全新 DB：直接建当前 schema
                self._create_v6_schema()
                self._connection.execute(
                    "INSERT OR IGNORE INTO schema_info VALUES ('context-state', ?)",
                    (SCHEMA_VERSION,),
                )
            elif current == 1:
                # §6.1 v1→v2 additive 迁移（事务内，崩溃回滚到 v1，旧代码仍可读）
                self._migrate_v1_to_v2()
                # §7.1 v2→v3 链式：snapshots 主键迁移到 (session_key, epoch)
                self._migrate_v2_to_v3()
                # §7.4 v3→v4 链式：previews 加 visible 列
                self._migrate_v3_to_v4()
                self._migrate_v4_to_v5()
                self._migrate_v5_to_v6()
                self._connection.execute(
                    "UPDATE schema_info SET version=? "
                    "WHERE component='context-state'",
                    (SCHEMA_VERSION,),
                )
            elif current == 2:
                # §7.1 v2→v3：snapshots 主键 (session_key) → (session_key, epoch)
                self._migrate_v2_to_v3()
                # §7.4 v3→v4 链式：previews 加 visible 列
                self._migrate_v3_to_v4()
                self._migrate_v4_to_v5()
                self._migrate_v5_to_v6()
                self._connection.execute(
                    "UPDATE schema_info SET version=? "
                    "WHERE component='context-state'",
                    (SCHEMA_VERSION,),
                )
            elif current == 3:
                # §7.4 v3→v4：previews 加 visible 列（派生索引 epoch 清理/不可见）
                self._migrate_v3_to_v4()
                self._migrate_v4_to_v5()
                self._migrate_v5_to_v6()
                self._connection.execute(
                    "UPDATE schema_info SET version=? "
                    "WHERE component='context-state'",
                    (SCHEMA_VERSION,),
                )
            elif current == 4:
                self._migrate_v4_to_v5()
                self._migrate_v5_to_v6()
                self._connection.execute(
                    "UPDATE schema_info SET version=? "
                    "WHERE component='context-state'",
                    (SCHEMA_VERSION,),
                )
            elif current == 5:
                self._migrate_v5_to_v6()
                self._connection.execute(
                    "UPDATE schema_info SET version=? "
                    "WHERE component='context-state'",
                    (SCHEMA_VERSION,),
                )
            elif current != SCHEMA_VERSION:
                raise ContextStateError(
                    f"context-state schema {current} is not supported"
                )

    def _create_v6_schema(self) -> None:
        # archives：epoch/level/status/coverage_hash/parent_archive_refs 为真实列
        # （供 list_frontier 索引与 coverage 活动非重叠 partial UNIQUE），data 仍存
        # 完整 ContextArchive JSON（重建权威，列为其查询镜像）。
        # previews：visible 列（§7.4）派生索引 epoch 清理时标记不可见，不删行
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                session_key TEXT NOT NULL,
                conversation_epoch INTEGER NOT NULL DEFAULT 0,
                capability_revision INTEGER NOT NULL DEFAULT 1,
                data TEXT NOT NULL,
                PRIMARY KEY(session_key, conversation_epoch, capability_revision)
            );
            CREATE TABLE IF NOT EXISTS archives (
                archive_id TEXT PRIMARY KEY, session_key TEXT NOT NULL,
                epoch INTEGER NOT NULL DEFAULT 0, generation INTEGER NOT NULL,
                level INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'active',
                coverage_hash TEXT NOT NULL DEFAULT '',
                parent_archive_refs TEXT NOT NULL DEFAULT '[]',
                data TEXT NOT NULL,
                UNIQUE(session_key, epoch, generation)
            );
            CREATE TABLE IF NOT EXISTS coverage (
                session_key TEXT NOT NULL, archive_id TEXT NOT NULL,
                source_ref TEXT NOT NULL, superseded_by TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(session_key, archive_id, source_ref)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS coverage_active_unique
                ON coverage(session_key, source_ref) WHERE superseded_by = '';
            CREATE TABLE IF NOT EXISTS previews (
                preview_id TEXT PRIMARY KEY, session_key TEXT NOT NULL,
                data TEXT NOT NULL,
                visible INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS tool_disclosures (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                session_key TEXT NOT NULL,
                conversation_epoch INTEGER NOT NULL,
                capability_revision INTEGER NOT NULL DEFAULT 1,
                tool_name TEXT NOT NULL,
                schema_json TEXT NOT NULL,
                schema_hash TEXT NOT NULL,
                tool_call_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(session_key, conversation_epoch, capability_revision, tool_name)
            );
            CREATE TABLE IF NOT EXISTS session_state (
                session_key TEXT PRIMARY KEY, compaction_failures INTEGER NOT NULL,
                diagnostics TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS outbox (
                outbox_id TEXT PRIMARY KEY, session_key TEXT NOT NULL,
                archive_id TEXT NOT NULL, event_type TEXT NOT NULL,
                span_id TEXT NOT NULL, trace_id TEXT NOT NULL,
                parent_span_id TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL,
                span_projection TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT '',
                delivered_at TEXT NOT NULL DEFAULT '',
                UNIQUE(archive_id, event_type)
            );
            """
        )

    def _migrate_v1_to_v2(self) -> None:
        """§6.1 v1→v2 additive 迁移：archives 加列并改 UNIQUE，新增 coverage/outbox。

        全程在 _initialize 的单个事务内执行（execute 逐条，非 executescript，以保
        事务原子性）。旧 v1 DB 的 epoch 仅在 JSON data 中，用 COALESCE 回填到列
        （legacy 全 epoch=0，符合 design「先加入 additive schema，旧数据不删」）。
        """
        conn = self._connection
        # 1. 加列（ALTER ADD COLUMN 保留数据，逐条原子）
        for stmt in (
            "ALTER TABLE archives ADD COLUMN epoch INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE archives ADD COLUMN level INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE archives ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
            "ALTER TABLE archives ADD COLUMN coverage_hash TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE archives ADD COLUMN parent_archive_refs "
            "TEXT NOT NULL DEFAULT '[]'",
        ):
            conn.execute(stmt)
        # 2. 从 data JSON 回填列（COALESCE 防缺失键，NULLIF 把空串当缺失）
        conn.execute(
            "UPDATE archives SET "
            "epoch=COALESCE(json_extract(data,'$.epoch'),0), "
            "level=COALESCE(json_extract(data,'$.level'),1), "
            "status=COALESCE(NULLIF(json_extract(data,'$.status'),''),'active'), "
            "coverage_hash=COALESCE("
            "NULLIF(json_extract(data,'$.coverage_hash'),''),''), "
            "parent_archive_refs=COALESCE("
            "json_extract(data,'$.parent_archive_refs'),'[]')"
        )
        # 3. UNIQUE(session_key,generation)→(session_key,epoch,generation)：
        # SQLite 不能就地改 UNIQUE，走 clone-copy-rename
        conn.execute(
            "CREATE TABLE archives_new ("
            "archive_id TEXT PRIMARY KEY, session_key TEXT NOT NULL, "
            "epoch INTEGER NOT NULL, generation INTEGER NOT NULL, "
            "level INTEGER NOT NULL, status TEXT NOT NULL, "
            "coverage_hash TEXT NOT NULL, parent_archive_refs TEXT NOT NULL, "
            "data TEXT NOT NULL, UNIQUE(session_key, epoch, generation))"
        )
        conn.execute(
            "INSERT INTO archives_new(archive_id, session_key, epoch, generation, "
            "level, status, coverage_hash, parent_archive_refs, data) "
            "SELECT archive_id, session_key, epoch, generation, level, status, "
            "coverage_hash, parent_archive_refs, data FROM archives"
        )
        conn.execute("DROP TABLE archives")
        conn.execute("ALTER TABLE archives_new RENAME TO archives")
        # 4. 既有 v1 表确保存在（IF NOT EXISTS：真实 v1 DB 已有则无操作，
        # 部分/损坏 v1 DB 则补齐 snapshots/previews/session_state）
        conn.execute(
            "CREATE TABLE IF NOT EXISTS snapshots ("
            "session_key TEXT PRIMARY KEY, data TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS previews ("
            "preview_id TEXT PRIMARY KEY, session_key TEXT NOT NULL, "
            "data TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS session_state ("
            "session_key TEXT PRIMARY KEY, compaction_failures INTEGER NOT NULL, "
            "diagnostics TEXT NOT NULL DEFAULT '[]')"
        )
        # 5. 新表：coverage（活动非重叠 partial UNIQUE）+ outbox（幂等投递）
        conn.execute(
            "CREATE TABLE IF NOT EXISTS coverage ("
            "session_key TEXT NOT NULL, archive_id TEXT NOT NULL, "
            "source_ref TEXT NOT NULL, superseded_by TEXT NOT NULL DEFAULT '', "
            "PRIMARY KEY(session_key, archive_id, source_ref))"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS coverage_active_unique "
            "ON coverage(session_key, source_ref) WHERE superseded_by = ''"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS outbox ("
            "outbox_id TEXT PRIMARY KEY, session_key TEXT NOT NULL, "
            "archive_id TEXT NOT NULL, event_type TEXT NOT NULL, "
            "span_id TEXT NOT NULL, trace_id TEXT NOT NULL, "
            "parent_span_id TEXT NOT NULL DEFAULT '', payload TEXT NOT NULL, "
            "span_projection TEXT NOT NULL DEFAULT '{}', "
            "status TEXT NOT NULL DEFAULT 'pending', "
            "attempts INTEGER NOT NULL DEFAULT 0, "
            "last_error TEXT NOT NULL DEFAULT '', "
            "created_at TEXT NOT NULL DEFAULT '', "
            "delivered_at TEXT NOT NULL DEFAULT '', "
            "UNIQUE(archive_id, event_type))"
        )

    def _migrate_v2_to_v3(self) -> None:
        """§7.1 v2→v3 迁移：snapshots 主键 (session_key)→(session_key, epoch)。

        旧 v2 snapshot 的 conversation_epoch 仅可能在 data JSON（多数缺失，
        视为 epoch=0）；COALESCE 回填列。SQLite 不能就地改 PRIMARY KEY，走
        clone-copy-rename，全程在 _initialize 单事务内（崩溃回滚到 v2）。
        """
        conn = self._connection
        conn.execute(
            "CREATE TABLE snapshots_new ("
            "session_key TEXT NOT NULL, "
            "conversation_epoch INTEGER NOT NULL DEFAULT 0, "
            "data TEXT NOT NULL, "
            "PRIMARY KEY(session_key, conversation_epoch))"
        )
        conn.execute(
            "INSERT INTO snapshots_new(session_key, conversation_epoch, data) "
            "SELECT session_key, "
            "COALESCE(json_extract(data, '$.conversation_epoch'), 0), "
            "data FROM snapshots"
        )
        conn.execute("DROP TABLE snapshots")
        conn.execute("ALTER TABLE snapshots_new RENAME TO snapshots")

    def _migrate_v3_to_v4(self) -> None:
        """§7.4 v3→v4 additive 迁移：previews 加 visible 列。

        visible=1（默认可见）。/clear 推进 epoch 时把早于新 epoch 的派生预览
        索引置 visible=0（标记不可见，不删行），原始 payload 在 trajectory 层
        独立保留（design line 91）。全程在 _initialize 单事务内执行，崩溃回滚到 v3。
        """
        # ADD COLUMN 保留数据，旧预览默认 visible=1（继续可见，直到被清理标记）
        self._connection.execute(
            "ALTER TABLE previews ADD COLUMN visible INTEGER NOT NULL DEFAULT 1"
        )

    def _migrate_v4_to_v5(self) -> None:
        """v4→v5 additive migration: epoch-scoped deferred-tool disclosures."""

        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS tool_disclosures ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_key TEXT NOT NULL, conversation_epoch INTEGER NOT NULL, "
            "tool_name TEXT NOT NULL, schema_json TEXT NOT NULL, "
            "schema_hash TEXT NOT NULL, tool_call_id TEXT NOT NULL, "
            "created_at TEXT NOT NULL, "
            "UNIQUE(session_key, conversation_epoch, tool_name))"
        )

    def _migrate_v5_to_v6(self) -> None:
        """v5→v6：快照与工具披露增加不可变 capability revision。"""

        conn = self._connection
        conn.execute(
            "CREATE TABLE IF NOT EXISTS snapshots ("
            "session_key TEXT NOT NULL, conversation_epoch INTEGER NOT NULL DEFAULT 0, "
            "data TEXT NOT NULL, PRIMARY KEY(session_key, conversation_epoch))"
        )
        conn.execute(
            "CREATE TABLE snapshots_v6 ("
            "session_key TEXT NOT NULL, conversation_epoch INTEGER NOT NULL, "
            "capability_revision INTEGER NOT NULL, data TEXT NOT NULL, "
            "PRIMARY KEY(session_key, conversation_epoch, capability_revision))"
        )
        conn.execute(
            "INSERT INTO snapshots_v6 "
            "(session_key, conversation_epoch, capability_revision, data) "
            "SELECT session_key, conversation_epoch, 1, "
            "json_set(data, '$.capability_revision', 1) FROM snapshots"
        )
        conn.execute("DROP TABLE snapshots")
        conn.execute("ALTER TABLE snapshots_v6 RENAME TO snapshots")
        conn.execute(
            "CREATE TABLE tool_disclosures_v6 ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_key TEXT NOT NULL, conversation_epoch INTEGER NOT NULL, "
            "capability_revision INTEGER NOT NULL, tool_name TEXT NOT NULL, "
            "schema_json TEXT NOT NULL, schema_hash TEXT NOT NULL, "
            "tool_call_id TEXT NOT NULL, created_at TEXT NOT NULL, "
            "UNIQUE(session_key, conversation_epoch, capability_revision, tool_name))"
        )
        conn.execute(
            "INSERT INTO tool_disclosures_v6 "
            "(sequence, session_key, conversation_epoch, capability_revision, "
            "tool_name, schema_json, schema_hash, tool_call_id, created_at) "
            "SELECT sequence, session_key, conversation_epoch, 1, tool_name, "
            "schema_json, schema_hash, tool_call_id, created_at "
            "FROM tool_disclosures"
        )
        conn.execute("DROP TABLE tool_disclosures")
        conn.execute(
            "ALTER TABLE tool_disclosures_v6 RENAME TO tool_disclosures"
        )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def get_snapshot(
        self, session_key: str, epoch: int = 0, revision: int | None = None
    ) -> ContextSnapshot | None:
        if revision is None:
            row = self._one(
                "SELECT data FROM snapshots WHERE session_key=? "
                "AND conversation_epoch=? ORDER BY capability_revision DESC LIMIT 1",
                session_key,
                epoch,
            )
        else:
            row = self._one(
                "SELECT data FROM snapshots WHERE session_key=? "
                "AND conversation_epoch=? AND capability_revision=?",
                session_key,
                epoch,
                revision,
            )
        return ContextSnapshot(**json.loads(row["data"])) if row else None

    def save_snapshot(self, snapshot: ContextSnapshot) -> ContextSnapshot:
        try:
            with self._lock, self._connection:
                row = self._connection.execute(
                    "SELECT data FROM snapshots WHERE session_key=? "
                    "AND conversation_epoch=? "
                    "ORDER BY capability_revision DESC LIMIT 1",
                    (snapshot.session_key, snapshot.conversation_epoch),
                ).fetchone()
                latest = ContextSnapshot(**json.loads(row["data"])) if row else None
                if (
                    latest is not None
                    and not latest.invalidated_reason
                    and latest.stable_prefix_hash == snapshot.stable_prefix_hash
                ):
                    return latest
                revision = latest.capability_revision + 1 if latest is not None else 1
                committed = replace(snapshot, capability_revision=revision)
                self._connection.execute(
                    "INSERT INTO snapshots "
                    "(session_key, conversation_epoch, capability_revision, data) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        committed.session_key,
                        committed.conversation_epoch,
                        revision,
                        _json(asdict(committed)),
                    ),
                )
                return committed
        except sqlite3.DatabaseError as exc:
            raise ContextStateError(type(exc).__name__) from exc

    def invalidate_snapshot(
        self, session_key: str, reason: str, epoch: int = 0,
        revision: int | None = None,
    ) -> None:
        with self._lock, self._connection:
            if revision is None:
                row = self._connection.execute(
                    "SELECT data FROM snapshots WHERE session_key=? "
                    "AND conversation_epoch=? "
                    "ORDER BY capability_revision DESC LIMIT 1",
                    (session_key, epoch),
                ).fetchone()
            else:
                row = self._connection.execute(
                    "SELECT data FROM snapshots WHERE session_key=? "
                    "AND conversation_epoch=? AND capability_revision=?",
                    (session_key, epoch, revision),
                ).fetchone()
            if row is None:
                return
            snapshot = ContextSnapshot(**json.loads(row["data"]))
            if snapshot.invalidated_reason:
                return
            invalidated = replace(snapshot, invalidated_reason=reason[:512])
            self._connection.execute(
                "UPDATE snapshots SET data=? "
                "WHERE session_key=? AND conversation_epoch=? "
                "AND capability_revision=?",
                (
                    _json(asdict(invalidated)),
                    session_key,
                    epoch,
                    snapshot.capability_revision,
                ),
            )

    def save_tool_disclosure(self, disclosure: ToolDisclosure) -> ToolDisclosure:
        try:
            with self._lock, self._connection:
                self._connection.execute(
                    "INSERT OR IGNORE INTO tool_disclosures "
                    "(session_key, conversation_epoch, capability_revision, "
                    "tool_name, schema_json, "
                    "schema_hash, tool_call_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        disclosure.session_key,
                        disclosure.conversation_epoch,
                        disclosure.capability_revision,
                        disclosure.tool_name,
                        disclosure.schema_json,
                        disclosure.schema_hash,
                        disclosure.tool_call_id,
                        disclosure.created_at,
                    ),
                )
                row = self._connection.execute(
                    "SELECT sequence, session_key, conversation_epoch, "
                    "capability_revision, tool_name, "
                    "schema_json, schema_hash, tool_call_id, created_at "
                    "FROM tool_disclosures WHERE session_key=? "
                    "AND conversation_epoch=? AND capability_revision=? "
                    "AND tool_name=?",
                    (
                        disclosure.session_key,
                        disclosure.conversation_epoch,
                        disclosure.capability_revision,
                        disclosure.tool_name,
                    ),
                ).fetchone()
                assert row is not None
                committed = _tool_disclosure_from_row(row)
                if committed.schema_hash != disclosure.schema_hash:
                    raise ContextStateError(
                        "disclosed tool schema changed within capability revision"
                    )
                return committed
        except sqlite3.DatabaseError as exc:
            raise ContextStateError(type(exc).__name__) from exc

    def list_tool_disclosures(
        self, session_key: str, epoch: int, revision: int | None = None
    ) -> tuple[ToolDisclosure, ...]:
        selected = revision
        if selected is None:
            snapshot = self.get_snapshot(session_key, epoch)
            selected = snapshot.capability_revision if snapshot is not None else 1
        with self._lock:
            rows = self._connection.execute(
                "SELECT sequence, session_key, conversation_epoch, "
                "capability_revision, tool_name, "
                "schema_json, schema_hash, tool_call_id, created_at "
                "FROM tool_disclosures WHERE session_key=? AND conversation_epoch=? "
                "AND capability_revision=? "
                "ORDER BY sequence, tool_name",
                (session_key, epoch, selected),
            ).fetchall()
        return tuple(_tool_disclosure_from_row(row) for row in rows)

    def list_archives(self, session_key: str) -> tuple[ContextArchive, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT data FROM archives WHERE session_key=? ORDER BY generation",
                (session_key,),
            ).fetchall()
        return tuple(_archive_from_json(row["data"]) for row in rows)

    def list_frontier(self, session_key: str) -> tuple[ContextArchive, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT data FROM archives "
                "WHERE session_key=? AND status='active' ORDER BY generation",
                (session_key,),
            ).fetchall()
        return tuple(_archive_from_json(row["data"]) for row in rows)

    def append_archive(self, archive: ContextArchive) -> None:
        # §6.1：写 archives 行（新列镜像）+ coverage 行（活动非重叠 partial UNIQUE
        # + INSERT OR IGNORE 重试幂等）。generation 分配与 outbox 由 §6.2 的
        # commit_archive 在单事务内统一；本方法保留为简单写入路径。
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO archives "
                "(archive_id, session_key, epoch, generation, level, status, "
                "coverage_hash, parent_archive_refs, data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                _archive_row(archive),
            )
            for source_ref in archive.source_refs:
                self._connection.execute(
                    "INSERT OR IGNORE INTO coverage "
                    "(session_key, archive_id, source_ref, superseded_by) "
                    "VALUES (?, ?, ?, '')",
                    (archive.session_key, archive.archive_id, source_ref),
                )

    def commit_archive(
        self,
        archive: ContextArchive,
        *,
        outbox: OutboxEvent | None = None,
        reset_failures: bool = True,
    ) -> tuple[ContextArchive, bool]:
        # §6.2 单事务：查 archive_id 幂等 → 分配 (session,epoch) generation=max+1 →
        # INSERT archive（UNIQUE(session,epoch,generation) 冲突回滚）→ INSERT coverage
        # （partial UNIQUE 活动非重叠冲突回滚）→ 重置 compaction_failures → INSERT
        # outbox。IntegrityError（并发 generation 或 coverage 重叠）转
        # ContextStateError，
        # 由协调器映射为 CompactionError → fresh re-compile（§6.3）。
        try:
            with self._lock, self._connection:
                existing = self._connection.execute(
                    "SELECT data FROM archives WHERE archive_id=?",
                    (archive.archive_id,),
                ).fetchone()
                if existing is not None:
                    # 重试幂等：同 archive_id 已提交（事务原子，coverage/outbox 必同在）
                    return _archive_from_json(existing["data"]), False
                row = self._connection.execute(
                    "SELECT COALESCE(MAX(generation), 0) + 1 FROM archives "
                    "WHERE session_key=? AND epoch=?",
                    (archive.session_key, archive.epoch),
                ).fetchone()
                generation = int(row[0])
                committed = replace(archive, generation=generation)
                self._connection.execute(
                    "INSERT INTO archives "
                    "(archive_id, session_key, epoch, generation, level, status, "
                    "coverage_hash, parent_archive_refs, data) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    _archive_row(committed),
                )
                # §6.2 coverage 去重：批次内重复内容消息只覆盖一次（对等 InMemory），
                # 否则 partial UNIQUE(session_key,source_ref) 自冲突回滚。
                for source_ref in dict.fromkeys(committed.source_refs):
                    self._connection.execute(
                        "INSERT INTO coverage "
                        "(session_key, archive_id, source_ref, superseded_by) "
                        "VALUES (?, ?, ?, '')",
                        (
                            committed.session_key,
                            committed.archive_id,
                            source_ref,
                        ),
                    )
                if reset_failures:
                    # §6.2 成功提交重置熔断计数（correction 16：reset，非记录）
                    self._connection.execute(
                        "INSERT INTO session_state"
                        "(session_key, compaction_failures) "
                        "VALUES (?, 0) ON CONFLICT(session_key) DO UPDATE SET "
                        "compaction_failures=0",
                        (committed.session_key,),
                    )
                if outbox is not None:
                    # payload 事务内填入已提交 archive 完整 data（含分配 generation）
                    filled = replace(outbox, payload=_json(asdict(committed)))
                    self._connection.execute(
                        "INSERT OR IGNORE INTO outbox "
                        "(outbox_id, session_key, archive_id, event_type, span_id, "
                        "trace_id, parent_span_id, payload, span_projection, status, "
                        "attempts, last_error, created_at, delivered_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        _outbox_row(filled),
                    )
                return committed, True
        except sqlite3.IntegrityError as exc:
            raise ContextStateError(f"commit conflict: {exc}") from exc
        except sqlite3.DatabaseError as exc:
            raise ContextStateError(type(exc).__name__) from exc

    def merge_archives(
        self,
        parents: tuple[ContextArchive, ...],
        merged: ContextArchive,
        *,
        outbox: OutboxEvent | None = None,
        reset_failures: bool = False,
    ) -> tuple[ContextArchive, bool]:
        # §6.5 单事务（correction 3 顺序）：supersede 父 archive + 父 coverage →
        # INSERT merged coverage（partial UNIQUE 活动非重叠冲突回滚）→ INSERT
        # merged archive（事务内分配 generation）→ outbox。父行留存审计。靠
        # ``with self._lock, self._connection:`` 事务回滚 + partial UNIQUE 约束
        # 保证失败时父节点不变（对等 InMemory validate-then-mutate）。
        if len(parents) < 2:
            raise ValueError("merge requires at least two parents")
        parent_ids = tuple(parent.archive_id for parent in parents)
        placeholders = ",".join("?" for _ in parent_ids)
        try:
            with self._lock, self._connection:
                existing = self._connection.execute(
                    "SELECT data FROM archives WHERE archive_id=?",
                    (merged.archive_id,),
                ).fetchone()
                if existing is not None:
                    # 重试幂等：同 merged.archive_id 已提交（事务原子同在）
                    return _archive_from_json(existing["data"]), False
                # invariant 校验（correction 4）：父 refs ⊆ merged refs
                merged_refs_set = set(merged.source_refs)
                for parent in parents:
                    if not set(parent.source_refs) <= merged_refs_set:
                        raise ContextStateError(
                            "merge violates coverage invariant"
                        )
                # (1) supersede 父 archive：status=superseded + data JSON 同步更新
                for parent in parents:
                    superseded = replace(parent, status="superseded")
                    self._connection.execute(
                        "UPDATE archives SET status='superseded', data=? "
                        "WHERE archive_id=?",
                        (_json(asdict(superseded)), parent.archive_id),
                    )
                # (2) supersede 父 coverage 行：superseded_by=merged_id（行留存审计）
                self._connection.execute(
                    f"UPDATE coverage SET superseded_by=? "
                    f"WHERE archive_id IN ({placeholders}) AND superseded_by=''",
                    (merged.archive_id, *parent_ids),
                )
                # (3) INSERT merged coverage 行（活动；partial UNIQUE 冲突 → 回滚）
                for source_ref in dict.fromkeys(merged.source_refs):
                    self._connection.execute(
                        "INSERT INTO coverage "
                        "(session_key, archive_id, source_ref, superseded_by) "
                        "VALUES (?, ?, ?, '')",
                        (
                            merged.session_key,
                            merged.archive_id,
                            source_ref,
                        ),
                    )
                # (4) INSERT merged archive（事务内分配 generation，per epoch 单调）
                row = self._connection.execute(
                    "SELECT COALESCE(MAX(generation), 0) + 1 FROM archives "
                    "WHERE session_key=? AND epoch=?",
                    (merged.session_key, merged.epoch),
                ).fetchone()
                generation = int(row[0])
                committed = replace(merged, generation=generation)
                self._connection.execute(
                    "INSERT INTO archives "
                    "(archive_id, session_key, epoch, generation, level, status, "
                    "coverage_hash, parent_archive_refs, data) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    _archive_row(committed),
                )
                if reset_failures:
                    self._connection.execute(
                        "INSERT INTO session_state"
                        "(session_key, compaction_failures) "
                        "VALUES (?, 0) ON CONFLICT(session_key) DO UPDATE SET "
                        "compaction_failures=0",
                        (committed.session_key,),
                    )
                # (5) outbox（INSERT OR IGNORE 幂等）
                if outbox is not None:
                    filled = replace(outbox, payload=_json(asdict(committed)))
                    self._connection.execute(
                        "INSERT OR IGNORE INTO outbox "
                        "(outbox_id, session_key, archive_id, event_type, span_id, "
                        "trace_id, parent_span_id, payload, span_projection, status, "
                        "attempts, last_error, created_at, delivered_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        _outbox_row(filled),
                    )
                return committed, True
        except sqlite3.IntegrityError as exc:
            raise ContextStateError(f"merge conflict: {exc}") from exc
        except sqlite3.DatabaseError as exc:
            raise ContextStateError(type(exc).__name__) from exc

    def mark_outbox_delivered(self, outbox_id: str, *, delivered_at: str) -> None:
        self._execute(
            "UPDATE outbox SET status='delivered', delivered_at=? WHERE outbox_id=?",
            delivered_at,
            outbox_id,
        )

    def mark_outbox_failed(self, outbox_id: str, *, error: str) -> None:
        self._execute(
            "UPDATE outbox SET status='failed', attempts=attempts+1, "
            "last_error=? WHERE outbox_id=?",
            error[:512],
            outbox_id,
        )

    def list_pending_outbox(self, session_key: str) -> tuple[OutboxEvent, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT outbox_id, session_key, archive_id, event_type, "
                "span_id, trace_id, parent_span_id, payload, span_projection, "
                "status, attempts, last_error, created_at, delivered_at "
                "FROM outbox WHERE session_key=? AND status IN ('pending','failed') "
                "ORDER BY created_at",
                (session_key,),
            ).fetchall()
        return tuple(_outbox_from_row(row) for row in rows)

    def get_preview(self, preview_id: str) -> FrozenToolPreview | None:
        row = self._one("SELECT data FROM previews WHERE preview_id=?", preview_id)
        return FrozenToolPreview(**json.loads(row["data"])) if row else None

    def save_preview(self, preview: FrozenToolPreview) -> None:
        # §7.4 表有 visible 列：显式列名插入（visible=1 可见），
        # 避免 VALUES(?,?,?) 列数不匹配。
        self._execute(
            "INSERT OR IGNORE INTO previews(preview_id, session_key, data, visible) "
            "VALUES (?, ?, ?, 1)",
            preview.preview_id,
            preview.session_key,
            _json(asdict(preview)),
        )

    def get_preview_by_ref(
        self, session_key: str, epoch: int, tool_call_id: str
    ) -> FrozenToolPreview | None:
        # §7.3 恢复期按 (session_key, epoch, tool_call_id) 取冻结预览以校验引用
        # 完整性。epoch/tool_call_id 存于 data JSON；COALESCE 把无 epoch 键的旧
        # 预览视作 epoch=0，使其在 epoch=0 恢复时仍可命中（旧预览 canonical hash
        # 为空→校验跳过 canonical 项，仍校验 epoch/tool_call_id/payload_ref）。
        # §7.4 visible=1 过滤：epoch 清理后标记不可见的派生索引不返回，避免
        # 把旧 epoch 预览注入新 epoch 上下文。
        row = self._one(
            "SELECT data FROM previews WHERE session_key=? "
            "AND visible=1 "
            "AND COALESCE(json_extract(data, '$.epoch'), 0)=? "
            "AND COALESCE(json_extract(data, '$.tool_call_id'), '')=?",
            session_key,
            epoch,
            tool_call_id,
        )
        return FrozenToolPreview(**json.loads(row["data"])) if row else None

    def clear_epoch_previews(
        self, session_key: str, *, before_epoch: int
    ) -> int:
        # §7.4 把早于 before_epoch 的派生预览索引标记不可见（visible=0，不删行）。
        # /clear 推进 epoch 后调用：旧 epoch 预览不再注入新 epoch 上下文。原始
        # payload 在 trajectory 层独立保留（design line 91），可审计/重建。
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE previews SET visible=0 WHERE session_key=? "
                "AND visible=1 "
                "AND COALESCE(json_extract(data, '$.epoch'), 0) < ?",
                (session_key, before_epoch),
            )
            return int(cursor.rowcount)

    def set_compaction_failures(self, session_key: str, failures: int) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO session_state(session_key, compaction_failures) "
                "VALUES (?, ?) ON CONFLICT(session_key) DO UPDATE SET "
                "compaction_failures=excluded.compaction_failures",
                (session_key, max(0, failures)),
            )

    def get_compaction_failures(self, session_key: str) -> int:
        row = self._one(
            "SELECT compaction_failures FROM session_state WHERE session_key=?",
            session_key,
        )
        return int(row["compaction_failures"]) if row else 0

    def save_diagnostics(
        self, session_key: str, diagnostics: tuple[ContextDiagnostic, ...]
    ) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                "INSERT INTO session_state"
                "(session_key, compaction_failures, diagnostics) "
                "VALUES (?, 0, ?) ON CONFLICT(session_key) DO UPDATE SET "
                "diagnostics=excluded.diagnostics",
                (session_key, _json([asdict(item) for item in diagnostics])),
            )

    def diagnostic_summary(self, session_key: str) -> dict[str, object]:
        archives = self.list_archives(session_key)
        frontier = [item for item in archives if item.status == "active"]
        row = self._one(
            "SELECT compaction_failures, diagnostics FROM session_state "
            "WHERE session_key=?",
            session_key,
        )
        values = json.loads(row["diagnostics"]) if row else []
        # §6.6 outbox pending/failed 计数（聚合查询，零行时 SUM 返回 NULL→0）
        outbox = self._one(
            "SELECT "
            "COALESCE(SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END),0) "
            "AS pending, "
            "COALESCE(SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END),0) "
            "AS failed FROM outbox WHERE session_key=?",
            session_key,
        )
        return {
            "archive_generation": archives[-1].generation if archives else 0,
            "archive_level": frontier[-1].level if frontier else 0,
            "frontier_active_count": len(frontier),
            "compaction_failures": int(row["compaction_failures"]) if row else 0,
            "outbox_pending": int(outbox["pending"]) if outbox else 0,
            "outbox_failed": int(outbox["failed"]) if outbox else 0,
            "diagnostic_actions": tuple(item["action"] for item in values),
        }

    def reset_session(self, session_key: str) -> None:
        # §7.4 不再删 previews：派生预览索引的 epoch 清理由
        # clear_epoch_previews 标记不可见（保留审计/可重建），原始 payload 在
        # trajectory 层独立保留。此处仅重置可重建派生状态（快照/frontier/
        # 覆盖/outbox/失败计数/诊断）。
        with self._lock, self._connection:
            for table in (
                "snapshots",
                "archives",
                "coverage",
                "outbox",
                "session_state",
                "tool_disclosures",
            ):
                self._connection.execute(
                    f"DELETE FROM {table} WHERE session_key=?", (session_key,)
                )

    def _one(self, query: str, *values: object) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(query, values).fetchone()

    def _execute(self, query: str, *values: object) -> None:
        try:
            with self._lock, self._connection:
                self._connection.execute(query, values)
        except sqlite3.DatabaseError as exc:
            raise ContextStateError(type(exc).__name__) from exc


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _archive_row(archive: ContextArchive) -> tuple[object, ...]:
    """§6.1 archives 行列值：查询镜像列 + 完整 data JSON（重建权威）。"""
    return (
        archive.archive_id,
        archive.session_key,
        archive.epoch,
        archive.generation,
        archive.level,
        archive.status,
        archive.coverage_hash,
        _json(list(archive.parent_archive_refs)),
        _json(asdict(archive)),
    )


def _outbox_row(event: OutboxEvent) -> tuple[object, ...]:
    """§6.2 outbox 行列值（顺序对齐 _create_v2_schema 的列定义）。"""
    return (
        event.outbox_id,
        event.session_key,
        event.archive_id,
        event.event_type,
        event.span_id,
        event.trace_id,
        event.parent_span_id,
        event.payload,
        event.span_projection,
        event.status,
        event.attempts,
        event.last_error,
        event.created_at,
        event.delivered_at,
    )


def _outbox_from_row(row: sqlite3.Row) -> OutboxEvent:
    """§6.6 从 outbox 行重建 OutboxEvent（供重放自洽投递）。

    ``payload`` 为 commit_archive/merge_archives 事务内填入的已提交 archive 完整
    data JSON；``span_projection`` 为 completed SpanProjection JSON，重放端据此
    复用 ``span_id`` 关闭 span、解析 archive 重建 ``_deliver_committed`` 入参。
    """

    return OutboxEvent(
        outbox_id=row["outbox_id"],
        session_key=row["session_key"],
        archive_id=row["archive_id"],
        event_type=row["event_type"],
        span_id=row["span_id"],
        trace_id=row["trace_id"],
        parent_span_id=row["parent_span_id"],
        payload=row["payload"],
        span_projection=row["span_projection"],
        status=row["status"],
        attempts=row["attempts"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        delivered_at=row["delivered_at"],
    )


def _tool_disclosure_from_row(row: sqlite3.Row) -> ToolDisclosure:
    return ToolDisclosure(
        session_key=str(row["session_key"]),
        conversation_epoch=int(row["conversation_epoch"]),
        tool_name=str(row["tool_name"]),
        schema_json=str(row["schema_json"]),
        schema_hash=str(row["schema_hash"]),
        tool_call_id=str(row["tool_call_id"]),
        created_at=str(row["created_at"]),
        sequence=int(row["sequence"]),
        capability_revision=int(row["capability_revision"]),
    )


def _outbox_from_mapping(row: dict[str, object]) -> OutboxEvent:
    """§6.6 从 InMemory outbox dict 重建 OutboxEvent（类型安全，避免 object→str/int）。

    内存 outbox 存 ``asdict(OutboxEvent)`` 的 dict（mutable，供 mark_outbox_*
    原地改 status）；读回需显式重建，因 ``**row`` 会把 object 值喂给 str/int 字段。
    """

    attempts = row.get("attempts", 0)
    return OutboxEvent(
        outbox_id=str(row["outbox_id"]),
        session_key=str(row["session_key"]),
        archive_id=str(row["archive_id"]),
        event_type=str(row["event_type"]),
        span_id=str(row["span_id"]),
        trace_id=str(row["trace_id"]),
        parent_span_id=str(row.get("parent_span_id", "")),
        payload=str(row.get("payload", "")),
        span_projection=str(row.get("span_projection", "{}")),
        status=str(row.get("status", "pending")),
        attempts=attempts if isinstance(attempts, int) else 0,
        last_error=str(row.get("last_error", "")),
        created_at=str(row.get("created_at", "")),
        delivered_at=str(row.get("delivered_at", "")),
    )


def _archive_from_json(value: str) -> ContextArchive:
    data = json.loads(value)
    data["source_refs"] = tuple(data.get("source_refs", ()))
    # §6.1 新增 tuple 字段从 JSON 数组还原（旧 v1 archive 缺该键时取默认 ()）
    data["parent_archive_refs"] = tuple(data.get("parent_archive_refs", ()))
    return ContextArchive(**data)
