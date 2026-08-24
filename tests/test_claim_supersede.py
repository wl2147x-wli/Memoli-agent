"""BUG-1 修复回归测试：claim 替代关系（supersedes/corrects）的货币性解析。

覆盖共享助手 ``_supersede_existing_claim_tx`` 的全部不变量与三处调用方
（``correct_claim`` / governance 批准 / ``link_claims`` 替代分支）的统一行为：
状态翻转、双关系原子写入、scope/事实槽位隔离、乐观并发、幂等/冲突、
索引清理、Card 重投影、事务回滚、存量修复。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from memoli_agent.agent.memory.models import (
    EvidenceRef,
    MemoryMutation,
    MemoryQuery,
    MemoryScope,
)
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore


def _memory(content: str, **kwargs: object) -> MemoryMutation:
    return MemoryMutation(
        content=content,
        evidence=(EvidenceRef("message", "msg-1", content),),
        **kwargs,  # type: ignore[arg-type]
    )


def _claim(store: SQLiteMemoryStore, content: str, **kwargs: object) -> str:
    item = store.append_claim(_memory(content, **kwargs))
    return item.item_id


def _row(store: SQLiteMemoryStore, claim_id: str) -> sqlite3.Row:
    return store._connection.execute(  # noqa: SLF001
        "SELECT status, revision FROM claims WHERE claim_id=?", (claim_id,)
    ).fetchone()


def _status(store: SQLiteMemoryStore, claim_id: str) -> str:
    return str(_row(store, claim_id)["status"])


def _revision(store: SQLiteMemoryStore, claim_id: str) -> int:
    return int(_row(store, claim_id)["revision"])


def _relations_to(store: SQLiteMemoryStore, target_id: str) -> list[str]:
    rows = store._connection.execute(  # noqa: SLF001
        "SELECT relation FROM claim_relations WHERE target_claim_id=?",
        (target_id,),
    ).fetchall()
    return sorted(str(r["relation"]) for r in rows)


def _relations_from(store: SQLiteMemoryStore, source_id: str) -> list[str]:
    rows = store._connection.execute(  # noqa: SLF001
        "SELECT relation FROM claim_relations WHERE source_claim_id=?",
        (source_id,),
    ).fetchall()
    return sorted(str(r["relation"]) for r in rows)


# ---------------------------------------------------------------------------
# 1. 替代型关系翻状态 + 检索缺席
# ---------------------------------------------------------------------------


def test_supersedes_flips_status_and_excludes_from_default_search(
    tmp_path: Path,
) -> None:
    with SQLiteMemoryStore(tmp_path / "mem.db") as store:
        old = _claim(store, "用户使用的数据库是 MySQL。", status="active")
        new = _claim(store, "用户使用的数据库改为 PostgreSQL。", status="active")
        store.link_claims(new, old, "supersedes", actor="user",
                          expected_target_revision=0)
        assert _status(store, old) == "superseded"
        assert _status(store, new) == "active"
        # 默认检索（statuses=active/approved/frozen）旧 claim 缺席，仅 new 返回
        result = store.search(MemoryQuery("数据库", limit=8))
        ids = [it.item_id for it in result.items]
        assert new in ids
        assert old not in ids


def test_corrects_on_approved_writes_both_relations(tmp_path: Path) -> None:
    with SQLiteMemoryStore(tmp_path / "mem.db") as store:
        old = _claim(store, "旧事实 A。", status="active")
        store.set_status("claim", old, "approved", "user")
        new = _claim(store, "新事实 A 修正。", status="active")
        store.link_claims(new, old, "corrects", actor="user",
                          expected_target_revision=_revision(store, old))
        assert _status(store, old) == "superseded"
        # 无论传入 corrects 还是 supersedes，均原子写两条
        assert _relations_to(store, old) == ["corrects", "supersedes"]


# ---------------------------------------------------------------------------
# 3. 纯边关系不翻状态、仅一条边（仍校验 scope/存在/非自环）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("relation", ["supports", "contradicts", "derived-from"])
def test_pure_edge_does_not_change_status(tmp_path: Path, relation: str) -> None:
    with SQLiteMemoryStore(tmp_path / "mem.db") as store:
        a = _claim(store, "事实一。", status="active")
        b = _claim(store, "事实二。", status="active")
        store.link_claims(a, b, relation)
        assert _status(store, b) == "active"
        assert _relations_to(store, b) == [relation]


# ---------------------------------------------------------------------------
# 4. frozen/candidate target → 整事务失败，边也不落库
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_status", ["frozen", "candidate"])
def test_supersede_non_live_target_rolls_back(tmp_path: Path,
                                              bad_status: str) -> None:
    with SQLiteMemoryStore(tmp_path / "mem.db") as store:
        # active→candidate 非法迁移；candidate 直接以初始态创建。
        # frozen 经合法迁移 active→frozen 获得（active→frozen 允许）。
        if bad_status == "frozen":
            old = _claim(store, "将被冻结。", status="active")
            store.set_status("claim", old, "frozen", "user")
        else:
            old = _claim(store, "将为候选。", status="candidate")
        new = _claim(store, "新事实。", status="active")
        with pytest.raises(ValueError):
            store.link_claims(new, old, "supersedes", actor="user",
                              expected_target_revision=_revision(store, old))
        assert _status(store, old) == bad_status
        assert _relations_to(store, old) == []


# ---------------------------------------------------------------------------
# 5. source 为 rejected/deleted → 失败回滚
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dead", ["rejected", "deleted"])
def test_supersede_dead_source_rolls_back(tmp_path: Path, dead: str) -> None:
    with SQLiteMemoryStore(tmp_path / "mem.db") as store:
        new = _claim(store, "新事实。", status="active")
        store.set_status("claim", new, dead, "user")
        old = _claim(store, "旧事实。", status="active")
        with pytest.raises(ValueError):
            store.link_claims(new, old, "supersedes", actor="user",
                              expected_target_revision=0)
        assert _status(store, old) == "active"
        assert _relations_to(store, old) == []


# ---------------------------------------------------------------------------
# 6. 跨 scope → PermissionError 回滚
# ---------------------------------------------------------------------------


def test_supersede_cross_scope_rejected(tmp_path: Path) -> None:
    with SQLiteMemoryStore(tmp_path / "mem.db") as store:
        old = _claim(store, "session A 旧事实。",
                     scope=MemoryScope("session", "A"), status="active")
        new = _claim(store, "session B 新事实。",
                     scope=MemoryScope("session", "B"), status="active")
        with pytest.raises(PermissionError):
            store.link_claims(new, old, "supersedes", actor="user",
                              expected_target_revision=0)
        assert _status(store, old) == "active"
        assert _relations_to(store, old) == []


def test_pure_edge_cross_scope_rejected(tmp_path: Path) -> None:
    with SQLiteMemoryStore(tmp_path / "mem.db") as store:
        a = _claim(store, "session A。",
                   scope=MemoryScope("session", "A"), status="active")
        b = _claim(store, "session B.",
                   scope=MemoryScope("session", "B"), status="active")
        with pytest.raises(PermissionError):
            store.link_claims(a, b, "supports")
        assert _relations_to(store, b) == []


# ---------------------------------------------------------------------------
# 7. source == target → ValueError
# ---------------------------------------------------------------------------


def test_self_supersede_rejected(tmp_path: Path) -> None:
    with SQLiteMemoryStore(tmp_path / "mem.db") as store:
        claim = _claim(store, "自指事实。", status="active")
        with pytest.raises(ValueError):
            store.link_claims(claim, claim, "supersedes", actor="user",
                              expected_target_revision=0)


# ---------------------------------------------------------------------------
# 8. expected_target_revision 不匹配 → stale，无边、无状态变化
# ---------------------------------------------------------------------------


def test_stale_revision_rejected(tmp_path: Path) -> None:
    with SQLiteMemoryStore(tmp_path / "mem.db") as store:
        old = _claim(store, "旧事实。", status="active")
        new = _claim(store, "新事实。", status="active")
        with pytest.raises(RuntimeError, match="stale-claim-revision"):
            store.link_claims(new, old, "supersedes", actor="user",
                              expected_target_revision=999)
        assert _status(store, old) == "active"
        assert _revision(store, old) == 0
        assert _relations_to(store, old) == []


def test_replacement_requires_actor_and_revision(tmp_path: Path) -> None:
    with SQLiteMemoryStore(tmp_path / "mem.db") as store:
        old = _claim(store, "旧事实。", status="active")
        new = _claim(store, "新事实。", status="active")
        with pytest.raises(TypeError):
            store.link_claims(new, old, "supersedes")
        with pytest.raises(TypeError):
            store.link_claims(new, old, "supersedes", actor="user")
        assert _status(store, old) == "active"
        assert _relations_to(store, old) == []


# ---------------------------------------------------------------------------
# 9. 重复同一置替 → 幂等；不同 source 再替 → 冲突
# ---------------------------------------------------------------------------


def test_repeat_same_supersede_is_idempotent(tmp_path: Path) -> None:
    with SQLiteMemoryStore(tmp_path / "mem.db") as store:
        old = _claim(store, "旧事实。", status="active")
        new = _claim(store, "新事实。", status="active")
        store.link_claims(new, old, "supersedes", actor="user",
                          expected_target_revision=0)
        rev_after_first = _revision(store, old)
        # 再次用同一 source 置替 → 幂等，不重复写边、不二次递增 revision
        store.link_claims(new, old, "supersedes", actor="user",
                          expected_target_revision=rev_after_first)
        assert _status(store, old) == "superseded"
        assert _revision(store, old) == rev_after_first
        assert _relations_to(store, old) == ["corrects", "supersedes"]


def test_supersede_conflict_other_source_rejected(tmp_path: Path) -> None:
    with SQLiteMemoryStore(tmp_path / "mem.db") as store:
        old = _claim(store, "旧事实。", status="active")
        first = _claim(store, "第一次修正。", status="active")
        second = _claim(store, "第二次修正。", status="active")
        store.link_claims(first, old, "supersedes", actor="user",
                          expected_target_revision=0)
        # old 已被 first 置替；second 再替 → 冲突，不记录新边
        with pytest.raises(RuntimeError, match="supersede-conflict"):
            store.link_claims(second, old, "supersedes", actor="user",
                              expected_target_revision=_revision(store, old))
        assert _relations_from(store, second) == []


# ---------------------------------------------------------------------------
# 11. 管理查询含 superseded → 旧 claim 可取且 current=False
# ---------------------------------------------------------------------------


def test_management_query_returns_superseded_not_current(tmp_path: Path) -> None:
    with SQLiteMemoryStore(tmp_path / "mem.db") as store:
        old = _claim(store, "用户使用的数据库是 MySQL。", status="active")
        new = _claim(store, "用户使用的数据库改为 PostgreSQL。", status="active")
        store.link_claims(new, old, "supersedes", actor="user",
                          expected_target_revision=0)
        result = store.search(
            MemoryQuery("数据库", limit=8, statuses=("superseded",))
        )
        items = {it.item_id: it for it in result.items}
        assert old in items
        assert items[old].current is False
        assert items[old].status == "superseded"


# ---------------------------------------------------------------------------
# 12. 事务故障注入 → 状态/关系/审计全部回滚
# ---------------------------------------------------------------------------


def test_fault_in_audit_rolls_back_everything(tmp_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    with SQLiteMemoryStore(tmp_path / "mem.db") as store:
        old = _claim(store, "旧事实。", status="active")
        new = _claim(store, "新事实。", status="active")

        def _raise(*_args: object, **_kw: object) -> None:
            raise RuntimeError("injected-fault")

        monkeypatch.setattr(store, "_record_revision", _raise)
        with pytest.raises(RuntimeError, match="injected-fault"):
            store.link_claims(new, old, "supersedes", actor="user",
                              expected_target_revision=0)
        # CAS 翻状态与关系插入均应被回滚
        assert _status(store, old) == "active"
        assert _revision(store, old) == 0
        assert _relations_to(store, old) == []


# ---------------------------------------------------------------------------
# 13. correct_claim 路径与 link_claims 行为一致（双关系 + 旧缺席/current=False）
# ---------------------------------------------------------------------------


def test_correct_claim_consistent_with_link_claims(tmp_path: Path) -> None:
    with SQLiteMemoryStore(tmp_path / "mem.db") as store:
        old = _claim(store, "用户使用的数据库是 MySQL。", status="active")
        new_item = store.correct_claim(
            old, 0, _memory("用户使用的数据库改为 PostgreSQL。", status="active"),
            actor="user",
        )
        assert _status(store, old) == "superseded"
        assert _relations_to(store, old) == ["corrects", "supersedes"]
        # 默认检索旧缺席、new 在场
        result = store.search(MemoryQuery("数据库", limit=8))
        ids = [it.item_id for it in result.items]
        assert new_item.item_id in ids
        assert old not in ids
        # 管理查询旧可取且 current=False
        mgmt = store.search(MemoryQuery("数据库", limit=8, statuses=("superseded",)))
        old_item = next(it for it in mgmt.items if it.item_id == old)
        assert old_item.current is False


# ---------------------------------------------------------------------------
# 14. 存量一致性修复：安全修复 + 多源/跨 scope 只报告
# ---------------------------------------------------------------------------


def test_repair_supersede_consistency_fixes_and_reports(tmp_path: Path) -> None:
    with SQLiteMemoryStore(tmp_path / "mem.db") as store:
        # 先用 append_claim 建好全部 claim（各自显式提交事务），再造脏边。
        # (a) 可安全修复：同 scope、单 live source、target 仍 active
        old_a = _claim(store, "旧 A。", status="active")
        new_a = _claim(store, "新 A。", status="active")
        # (b) 跨 scope：只报告
        old_b = _claim(store, "旧 B。", scope=MemoryScope("session", "X"),
                       status="active")
        new_b = _claim(store, "新 B。", scope=MemoryScope("session", "Y"),
                       status="active")
        # (c) 多源竞争：只报告
        old_c = _claim(store, "旧 C。", status="active")
        src_c1 = _claim(store, "新 C1。", status="active")
        src_c2 = _claim(store, "新 C2。", status="active")

        # 手工造"边在、状态未翻"脏数据（绕过助手的状态翻转），完成后提交，
        # 否则 sqlite3 隐式事务会让后续 BEGIN IMMEDIATE 报 "within a transaction"。
        dirty_edges = [
            (new_a, old_a),
            (new_b, old_b),
            (src_c1, old_c),
            (src_c2, old_c),
        ]
        for source_id, target_id in dirty_edges:
            store._connection.execute(  # noqa: SLF001
                "INSERT OR IGNORE INTO claim_relations("
                "source_claim_id, target_claim_id, relation, created_at) "
                "VALUES (?, ?, ?, ?)",
                (source_id, target_id, "supersedes",
                 "2026-01-01T00:00:00+00:00"),
            )
        store._connection.commit()  # noqa: SLF001

        suspect_before = store.index_diagnostics()["suspect_supersede_relations"]
        report = store.repair_supersede_consistency()
        assert old_a in report["fixed"]
        assert _status(store, old_a) == "superseded"
        # 跨 scope 与多源不被翻状态
        assert _status(store, old_b) == "active"
        assert _status(store, old_c) == "active"
        report_targets = {r["target"] for r in report["report_only"]}
        assert old_b in report_targets
        assert old_c in {s["target"] for s in report["skipped"]}

        # diagnostics：仅 old_a（1 条边）被消解；跨 scope(old_b)/多源(old_c 2 边)
        # 仍残留为 suspect，故计数减 1 而非归零。
        suspect_after = store.index_diagnostics()["suspect_supersede_relations"]
        assert suspect_after == suspect_before - 1
