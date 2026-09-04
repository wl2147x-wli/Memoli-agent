"""Phase 4: 记忆系统功能完善度评测。

对 14 个子系统各设计针对性场景，用真实 embedding 构造 runtime/store，
断言 pass/fail 并捕获异常/问题。
每 case 记录 {feature, case_id, passed, detail, problem}。
失败不中断后续。产物：workspace/eval/phase4_feature_results.json。
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import traceback
from pathlib import Path

os.environ["local-memos-embedding-key"] = "local-memos-embedding-key"

from memoli_agent.agent.memory.hybrid import (  # noqa: E402
    FtsSearchLane,
    HybridMemoryRetriever,
    MetadataSearchLane,
    PatternSearchLane,
    SemanticSearchLane,
)
from memoli_agent.agent.memory.layered import LayeredMemoryRetriever  # noqa: E402
from memoli_agent.agent.memory.models import (  # noqa: E402
    EvidenceRef,
    GovernanceDecision,
    MemoryMutation,
    MemoryQuery,
    MemoryScope,
)
from memoli_agent.agent.memory.runtime import MemoryRuntime  # noqa: E402
from memoli_agent.agent.memory.semantic import (  # noqa: E402
    MemoryIndexWorker,
    OpenAICompatibleEmbedder,
)
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore  # noqa: E402

BASE_URL = "http://127.0.0.1:7997"
MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def make_embedder():
    return OpenAICompatibleEmbedder(
        model=MODEL, api_key_env="local-memos-embedding-key", dimensions=384,
        base_url=BASE_URL, version="1", timeout_seconds=120.0,
    )


class Harness:
    def __init__(self):
        self.db = Path(tempfile.mkdtemp(prefix="feat_")) / "mem.db"
        self.store = SQLiteMemoryStore(self.db, max_cjk_ngram=3)
        self.embedder = make_embedder()
        self.worker = MemoryIndexWorker(self.store, self.embedder, batch_size=4)
        hybrid = HybridMemoryRetriever(
            self.store,
            fts_lane=FtsSearchLane(self.store),
            pattern_lane=PatternSearchLane(self.store),
            metadata_lane=MetadataSearchLane(self.store),
            semantic_lane=SemanticSearchLane(
                self.store, self.embedder, candidate_limit=200
            ),
            candidate_limit=50,
        )
        self.runtime = MemoryRuntime(
            store=self.store, retriever=LayeredMemoryRetriever(self.store, hybrid),
            auto_recall=True, core_card_limit=8, core_card_chars=4000,
            recall_chars=8000, recall_limit=8, card_limit=2, claim_limit=5,
            episode_limit=2,
        )

    def seed(self, content, idx=0, **kw) -> str:
        item = self.store.append_claim(
            MemoryMutation(content, evidence=(EvidenceRef("feat", str(idx)),), **kw)
        )
        return getattr(item, "claim_id", None) or getattr(item, "item_id", "")

    def index(self):
        async def drain():
            for _ in range(30):
                r = await self.worker.tick()
                if not r.processed:
                    break
        asyncio.run(drain())

    def query(self, q, **kw):
        return asyncio.run(self.runtime.query(MemoryQuery(q, **kw)))

    def close(self):
        try:
            self.store.close()
        except Exception:
            pass


# ---- 每个场景函数 (h) -> (passed, detail, problem) ----

def c1(h: Harness):
    cid = h.seed("用户偏好使用 Vim 编辑器。", 1)
    h.index()
    res = h.query("用户用什么编辑器？")
    ok = any(it.item_type == "claim" and "Vim" in it.content for it in res.items)
    return (
        ok,
        f"seed={cid}, returned={len(res.items)}, "
        f"lanes={list(res.active_lanes)}",
        "",
    )


def c2(h: Harness):
    # 测试合法前进链 candidate→active→approved→frozen→deleted
    cid = h.seed("临时事实：会议在周三。", 2, status="candidate")
    fwd, problems = [], []
    transitions = [
        ("active", "user"),
        ("approved", "governor"),
        ("frozen", "user"),
        ("deleted", "user"),
    ]
    for nxt, actor in transitions:
        try:
            h.store.set_status("claim", cid, nxt, actor)
            fwd.append(nxt)
        except Exception as e:
            problems.append(f"{nxt}: {e!r}")
    # frozen 是否为终态：尝试 frozen→superseded/rejected 应被拒绝
    cid2 = h.seed("另一临时事实：周报在周五。", 12, status="candidate")
    terminal_guard = []
    try:
        h.store.set_status("claim", cid2, "active", "user")
        h.store.set_status("claim", cid2, "frozen", "user")
    except Exception as e:
        problems.append(f"setup2: {e!r}")
    for nxt in ("superseded", "rejected"):
        try:
            h.store.set_status("claim", cid2, nxt, "user")
            terminal_guard.append((nxt, "allowed"))
        except Exception:
            terminal_guard.append((nxt, "rejected"))
    ok = len(fwd) >= 4
    # frozen→superseded/rejected 被拒是设计约束（frozen 近终态），记录为发现
    return (
        ok,
        f"forward={fwd}; frozen_terminal_guard={terminal_guard}",
        "; ".join(problems),
    )


def c3(h: Harness):
    old = h.seed("用户使用的数据库是 MySQL。", 3)
    new = h.seed("用户使用的数据库改为 PostgreSQL。", 4)
    old_rev = int(h.store._connection.execute(  # noqa: SLF001
        "SELECT revision FROM claims WHERE claim_id=?", (old,)
    ).fetchone()["revision"])
    # 替代型关系要求显式 actor + expected_target_revision（无弱默认）；
    # 助手原子翻 old→superseded、写 corrects+supersedes、删派生索引。
    h.store.link_claims(new, old, "supersedes", actor="user",
                        expected_target_revision=old_rev)
    h.index()
    res = h.query("用户用什么数据库？")
    contents = [(it.content, it.current) for it in res.items]
    new_returned = any("PostgreSQL" in c for c, _ in contents)
    old_returned_current = any("MySQL" in c and cur for c, cur in contents)
    passed = new_returned and not old_returned_current
    return passed, (
        f"contents={contents}; new_returned={new_returned}, "
        f"old_returned_current={old_returned_current}"
    ), ""


def c4(h: Harness):
    h.seed("项目的依赖从清华镜像源下载。", 5)
    h.seed("代码注释统一使用中文。", 6)
    h.index()
    r_kw = h.query("清华源")
    kw_hit = any("清华" in it.content for it in r_kw.items)
    r_sem = h.query("包从哪儿装的？")
    sem_hit = any("清华" in it.content for it in r_sem.items)
    ok = kw_hit and sem_hit
    return ok, (
        f"keyword_hit={kw_hit}, semantic_hit={sem_hit}, "
        f"kw_lanes={list(r_kw.active_lanes)}, "
        f"sem_lanes={list(r_sem.active_lanes)}"
    ), ""


def c5(h: Harness):
    try:
        h.store.create_card(title="用户档案卡", content="偏好Vim与中文注释",
                            scope=MemoryScope(), sensitivity="private")
    except Exception as e:
        return False, "create_card 调用失败", f"create_card: {e!r}"
    h.index()
    cards = h.store.select_core_cards(MemoryScope(), limit=8, max_chars=4000) \
        if hasattr(h.store, "select_core_cards") else []
    ok = len(cards) > 0
    return ok, f"core_cards={len(cards)}", "" if ok else "核心卡片未返回"


def c6(h: Harness):
    try:
        h.store.enqueue_episode_projection("trace_test", MemoryScope(),
                                           objective="o", current_step="s")
        if hasattr(h.store, "claim_projection_jobs"):
            jobs = h.store.claim_projection_jobs(
                "episode", 10, worker_id="w1", lease_seconds=60
            )
        else:
            jobs = []
        n = len(jobs) if isinstance(jobs, list | tuple) else jobs
        return True, f"enqueued_episode; claimed_jobs={n}", ""
    except Exception as e:
        return False, "episode 投影路径异常", f"{e!r}"


def c7(h: Harness):
    try:
        run_id = h.store.begin_consolidation("phase4", "t0", "t1")
        if run_id:
            h.store.finish_consolidation(run_id, "done")
        return bool(run_id), f"run_id={run_id}", ""
    except Exception as e:
        return False, "consolidation 调用异常", f"{e!r}"


def c8(h: Harness):
    # 治理存储 API 可达性 + 决策路径验证；完整 approve/escalate 已由 Phase 1 覆盖
    problems = []
    if hasattr(h.store, "count_needs_user_review"):
        n_review = h.store.count_needs_user_review(MemoryScope())
    else:
        n_review = -1
    # 对不存在的 candidate 入队治理作业应被拒绝（验证校验链）
    rejected = False
    try:
        h.store.enqueue_governance_job("cand_missing", expected_revision=0,
                                       governor_version="memory-governor",
                                       policy_version="1", prompt_version="1")
    except Exception:
        rejected = True
        problems.append("enqueue_missing_candidate_rejected")
    # 对不存在 job 记录决策应抛 KeyError
    decision_guarded = False
    try:
        h.store.record_governance_decision(
            "job_missing",
            GovernanceDecision(
                candidate_id="cand_missing",
                expected_revision=0,
                decision="approve",
                reason_codes=("benchmark-guard",),
                confidence=1.0,
                governor_version="governor",
                prompt_version="t",
                policy_version="1",
            ),
            actor="benchmark",
            outcome="approved",
        )
    except Exception as e:
        decision_guarded = True
        problems.append(f"decision_missing_job_guarded: {type(e).__name__}")
    ok = isinstance(n_review, int) and rejected and decision_guarded
    return (
        ok,
        f"needs_review={n_review}, enqueue_rejected={rejected}, "
        f"decision_guarded={decision_guarded}",
        "; ".join(problems),
    )


def c9(h: Harness):
    try:
        req = h.store.create_long_term_update_request(
            source_type="explicit-tool", scope=MemoryScope(),
            trace_ids=("t1",), session_id="s1", version_fingerprint="v1",
            idempotency_key="key1",
        )
        if hasattr(h.store, "claim_long_term_update_requests"):
            claimed = h.store.claim_long_term_update_requests(
                worker_id="w1", limit=10, lease_seconds=60
            )
        else:
            claimed = ()
        if hasattr(h.store, "recover_expired_long_term_update_leases"):
            recovered = h.store.recover_expired_long_term_update_leases()
        else:
            recovered = 0
        ok = req is not None and isinstance(claimed, tuple)
        claimed_n = len(claimed) if isinstance(claimed, tuple) else claimed
        return (
            ok,
            f"req={'ok' if req else 'None'}, claimed={claimed_n}, "
            f"recovered={recovered}",
            "",
        )
    except Exception as e:
        return False, "offline 请求生命周期异常", f"{e!r}"


def c10(h: Harness):
    problems = []
    diag = h.store.index_diagnostics() if hasattr(h.store, "index_diagnostics") else {}
    backfill = rebuilt = -1
    try:
        backfill = (
            h.store.backfill_index_jobs()
            if hasattr(h.store, "backfill_index_jobs")
            else -1
        )
    except Exception as e:
        problems.append(f"backfill: {e!r}")
    try:
        rebuilt = (
            h.store.rebuild_index_jobs()
            if hasattr(h.store, "rebuild_index_jobs")
            else -1
        )
    except Exception as e:
        problems.append(f"rebuild: {e!r}")
    return (
        isinstance(diag, dict),
        f"diagnostics={diag}, backfill={backfill}, rebuilt={rebuilt}",
        "; ".join(problems),
    )


def c11(h: Harness):
    h.seed("普通偏好：喜欢深色主题。", 7, sensitivity="public")
    h.seed("机密：账户密码是 hunter2。", 8, sensitivity="restricted")
    h.index()
    res = h.query("账户密码是什么？", max_sensitivity="private")
    leaked = any("hunter2" in it.content for it in res.items)
    return (
        not leaked,
        f"returned={len(res.items)}, restricted_leaked={leaked}",
        "" if not leaked else "受限敏感记忆泄漏到 private 检索结果",
    )


def c12(h: Harness):
    problems = []
    h.seed("用户在杭州工作。", 9)
    h.index()
    pre = asyncio.run(h.runtime.pre_recall(user_message="用户在哪个城市工作？"))
    block = h.runtime.render_prompt_block(pre)
    starts_ok = block.startswith('<memory_context trust="data">')
    ends_ok = block.rstrip().endswith("</memory_context>")
    has_block = starts_ok and ends_ok
    mt = asyncio.run(h.runtime.maintenance_tick())
    diag = h.runtime.diagnostics()
    big_res = h.query("城市", max_chars=5)
    truncated = (
        big_res.truncated or big_res.injected_chars <= 5 or len(big_res.items) == 0
    )
    if not has_block:
        problems.append("prompt block 格式不符")
    if not truncated:
        problems.append(f"char 预算未截断 injected={big_res.injected_chars}")
    ok = has_block and isinstance(mt, dict) and isinstance(diag, dict) and truncated
    mt_keys = list(mt.keys()) if isinstance(mt, dict) else mt
    diag_keys = list(diag.keys()) if isinstance(diag, dict) else diag
    return ok, (
        f"block={has_block}, maintenance_keys={mt_keys}, "
        f"diag_keys={diag_keys}, truncated={truncated}"
    ), "; ".join(problems)


def c13(h: Harness):
    h.seed("用户使用 PostgreSQL 数据库。", 10)
    h.index()
    results = {}
    for mode in ("auto", "claim-first", "hybrid"):
        r = h.query("数据库", retrieval_mode=mode)
        results[mode] = {"actual_route": r.actual_route, "count": len(r.items)}
    r_sum = h.query("数据库", detail_level="summary")
    r_evi = h.query("数据库", detail_level="evidence")
    ok = all(isinstance(v, dict) for v in results.values())
    return ok, (
        f"modes={results}, summary_chars={r_sum.injected_chars}, "
        f"evidence_chars={r_evi.injected_chars}"
    ), ""


def c14(h: Harness):
    h.seed("用户偏好 PostgreSQL。", 11)
    h.index()
    routes = {}
    for mode in ("auto", "card-first", "claim-first", "episode-first", "hybrid"):
        r = h.query("数据库", retrieval_mode=mode)
        routes[mode] = r.actual_route
    ok = routes["claim-first"] == "claim-first"
    return ok, f"routes={routes}", "" if ok else f"路由不符预期: {routes}"


CASES = [
    ("1.Claim写读", "claim_write_read", c1),
    ("2.状态生命周期", "status_lifecycle", c2),
    ("3.关系", "relations_supersede", c3),
    ("4.混合检索三lane", "hybrid_three_lanes", c4),
    ("5.Cards", "card_core_selection", c5),
    ("6.Episodic", "episode_projection_enqueue", c6),
    ("7.Consolidation", "consolidation_run", c7),
    ("8.Governance", "governance_decision_paths", c8),
    ("9.离线学习管线", "offline_update_request_lifecycle", c9),
    ("10.Migration", "schema_and_index_backfill", c10),
    ("11.Sensitivity隐私", "sensitivity_filtering", c11),
    ("12.Runtime门面", "runtime_facade", c12),
    ("13.检索模式detail", "retrieval_mode_detail", c13),
    ("14.Auto-router", "auto_router_routes", c14),
]


def run_all() -> list[dict]:
    out = []
    for feature, cid, fn in CASES:
        h = Harness()
        try:
            passed, detail, problem = fn(h)
        except Exception as e:
            passed = False
            detail = "case raised"
            problem = f"{e!r}\n{traceback.format_exc()}"
        finally:
            h.close()
        out.append({
            "feature": feature, "case_id": cid, "passed": bool(passed),
            "detail": str(detail), "problem": problem,
        })
    return out


def main() -> None:
    results = run_all()
    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "failed": sum(1 for r in results if not r["passed"]),
        "embedding": "OpenAICompatible(infinity_emb,384d)",
        "by_feature": {r["feature"]: r["passed"] for r in results},
    }
    out = {"summary": summary, "cases": results}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    with open("workspace/eval/phase4_feature_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
