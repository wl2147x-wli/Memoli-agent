"""clarify-memory-write-contract 的行为契约测试。

覆盖：工具描述传达两阶段合同、拒绝信息稳定错误码与自纠正指引、单次证据接受、
逐字写入成功路径回归保护，以及记忆学习分层评估（合同拒绝计为遵循失败、与官方
分数分开呈现、未启用时不降级官方评分）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from benchmarks.config import (
    AgentBenchmarkConfig,
    BenchmarkConfig,
    DatasetConfig,
)
from benchmarks.metrics.layered_memory import (
    GovernanceCandidate,
    LayeredMemoryAudit,
    MemoryManageCall,
    RecallAttempt,
    adherence_rate,
    collect_layered_memory,
    compute_layered_memory,
    scan_memory_manage_calls,
)
from benchmarks.reports.writer import ReportWriter
from memoli_agent.agent.memory.retriever import SQLiteMemoryRetriever
from memoli_agent.agent.memory.runtime import MemoryRuntime
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore
from memoli_agent.agent.tools.builtin import MemoryManageTool
from memoli_agent.agent.tools.execution import ToolExecutionContext, tool_context


def _build_tool(tmp_path: Path) -> MemoryManageTool:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    return MemoryManageTool(MemoryRuntime(store, SQLiteMemoryRetriever(store)))


def test_tool_description_states_two_phase_contract() -> None:
    tool = MemoryManageTool(None)
    description = tool.description
    # 关键词：在线证据层、逐字、禁止改写、离线整理层
    assert "在线证据层" in description
    assert "逐字" in description
    assert "禁止改写" in description
    assert "离线整理层" in description
    # 不含用户正文样本或 embedding 字样
    assert "embedding" not in description.lower()
    assert "xky" not in description
    # basis_quote 参数描述也保留逐字语义
    basis_desc = tool.parameters["properties"]["basis_quote"]["description"]
    assert "逐字" in basis_desc
    assert "不得改写" in basis_desc


def test_rejection_messages_have_stable_codes_and_self_correction(
    tmp_path: Path,
) -> None:
    tool = _build_tool(tmp_path)
    context = ToolExecutionContext(
        "trace", "session", "call", "msg-1", "请记住我喜欢中文注释"
    )

    async def scenario() -> None:
        with tool_context(context):
            missing = await tool.run(
                {"action": "remember", "content": "x", "basis_quote": "不存在"}
            )
            assert missing.success is False
            assert missing.metadata["error"] == "missing-explicit-basis"
            assert "逐字" in missing.content
            assert "不得改写" in missing.content

            mismatch = await tool.run(
                {
                    "action": "remember",
                    "content": "用户喜欢中文注释",
                    "basis_quote": "我喜欢中文注释",
                }
            )
            assert mismatch.success is False
            assert mismatch.metadata["error"] == "basis-content-mismatch"
            assert "逐字" in mismatch.content
            assert "不得改写" in mismatch.content

    asyncio.run(scenario())


def test_single_explicit_statement_accepted_as_evidence(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    # 该事实此前从未出现，仅本次显式陈述一次。
    context = ToolExecutionContext(
        "trace", "session", "call", "msg-1", "remember my preferred language is Python"
    )

    async def scenario() -> None:
        with tool_context(context):
            accepted = await tool.run(
                {
                    "action": "remember",
                    "content": "my preferred language is Python",
                    "basis_quote": "my preferred language is Python",
                }
            )
            assert accepted.success is True
            payload = json.loads(accepted.content)
            assert payload["status"] == "success"
            assert payload["current_user_message_id"] == "msg-1"
            assert payload["basis_quote"] == "my preferred language is Python"

    asyncio.run(scenario())


def test_verbatim_write_success_path_unchanged(tmp_path: Path) -> None:
    tool = _build_tool(tmp_path)
    context = ToolExecutionContext(
        "trace", "session", "call", "msg-1", "请记住：我对花生过敏。"
    )

    async def scenario() -> None:
        with tool_context(context):
            result = await tool.run(
                {
                    "action": "remember",
                    "content": "我对花生过敏。",
                    "basis_quote": "请记住：我对花生过敏。",
                }
            )
            assert result.success is True
            payload = json.loads(result.content)
            # 成功路径返回结构保持不变
            assert set(payload) >= {
                "status",
                "id",
                "claim_id",
                "action",
                "current_user_message_id",
                "basis_quote",
            }
            assert payload["action"] == "remember"
            assert payload["basis_quote"] == "请记住：我对花生过敏。"

    asyncio.run(scenario())


def test_layered_metrics_classify_rejections_as_adherence_failures() -> None:
    audit = LayeredMemoryAudit(
        memory_manage_calls=[
            MemoryManageCall(action="remember", outcome="success"),
            MemoryManageCall(action="remember", outcome="basis-content-mismatch"),
            MemoryManageCall(action="remember", outcome="missing-explicit-basis"),
            MemoryManageCall(action="remember", outcome="success"),
        ],
        governance_candidates=[
            GovernanceCandidate(status="approved"),
            GovernanceCandidate(status="rejected"),
            GovernanceCandidate(status="pending"),
        ],
        recall_attempts=[
            RecallAttempt(hit=True),
            RecallAttempt(hit=False),
            RecallAttempt(hit=True),
        ],
        baseline_score=0.5,
        treatment_score=0.7,
    )
    metrics = compute_layered_memory(audit)
    # 4 次调用 2 次成功 → 0.5；两次合同拒绝计为遵循失败而非规则错误
    assert metrics["adherence_rate"] == pytest.approx(0.5)
    assert metrics["candidate_validity_rate"] == pytest.approx(1 / 3)
    assert metrics["activation_rate"] == pytest.approx(2 / 3)
    assert metrics["held_out_gain"] == pytest.approx(0.2)
    # 分层指标与官方分数分开呈现：键独立存在
    assert "adherence_rate" in metrics
    assert "overall" not in metrics


def test_adherence_rate_none_when_no_calls() -> None:
    assert adherence_rate(LayeredMemoryAudit()) is None


class _FakeAuditableAgent:
    def __init__(self, audit: LayeredMemoryAudit | None) -> None:
        self._audit = audit

    def memory_audit(self) -> LayeredMemoryAudit:
        if self._audit is None:
            raise RuntimeError("audit unavailable")
        return self._audit


def test_collect_layered_memory_skips_when_adapter_lacks_hook() -> None:
    class NoHookAgent:
        pass

    assert collect_layered_memory(NoHookAgent(), []) is None


def test_collect_layered_memory_skips_when_hook_raises() -> None:
    agent = _FakeAuditableAgent(None)
    assert collect_layered_memory(agent, []) is None


def test_collect_layered_memory_augments_held_out_gain_from_records() -> None:
    agent = _FakeAuditableAgent(LayeredMemoryAudit())
    records = [
        {"metadata": {"baseline_score": 0.4, "treatment_score": 0.6}},
        {"metadata": {"baseline_score": 0.6, "treatment_score": 0.8}},
    ]
    audit = collect_layered_memory(agent, records)
    assert audit is not None
    assert audit.baseline_score == pytest.approx(0.5)
    assert audit.treatment_score == pytest.approx(0.7)
    assert compute_layered_memory(audit)["held_out_gain"] == pytest.approx(0.2)


def test_run_collect_layered_disabled_returns_none() -> None:
    from benchmarks.run import _collect_layered

    class Cfg:
        class metrics:
            layered_memory = False

    assert _collect_layered(Cfg, _FakeAuditableAgent(LayeredMemoryAudit()), []) is None


def test_report_separates_layered_metrics_and_is_non_interfering(
    tmp_path: Path,
) -> None:
    writer = ReportWriter(tmp_path / "out")

    # 未启用分层指标时：报告不含分层章节，官方分数章节仍在
    metrics_off = {
        "dataset": "locomo",
        "split": "locomo10",
        "total_questions": 1,
        "overall": {"score": 0.8, "retrieval_recall": 0.5},
        "by_question_type": {},
        "layered_memory": None,
    }
    path_off = writer.write_report(_report_config(), metrics_off, [], False)
    text_off = path_off.read_text(encoding="utf-8")
    assert "记忆学习分层评估" not in text_off
    assert "总体指标" in text_off

    # 启用且有证据时：分层章节出现，且与官方分数分开
    metrics_on = {
        **metrics_off,
        "layered_memory": {
            "adherence_rate": 0.5,
            "candidate_validity_rate": 0.33,
            "activation_rate": 0.66,
            "held_out_gain": 0.2,
            "sample_counts": {
                "memory_manage_calls": 4,
                "governance_candidates": 3,
                "recall_attempts": 3,
            },
        },
    }
    path_on = writer.write_report(_report_config(), metrics_on, [], False)
    text_on = path_on.read_text(encoding="utf-8")
    assert "记忆学习分层评估" in text_on
    assert "遵循失败而非规则错误" in text_on
    # 官方分数章节仍然独立存在
    assert "总体指标" in text_on


def _report_config() -> BenchmarkConfig:
    return BenchmarkConfig(
        dataset=DatasetConfig(
            name="locomo",
            path="x",
            split="locomo10",
            sample_size=1,
            question_types=[],
        ),
        agent=AgentBenchmarkConfig(
            type="memoli", ingest_mode="memory_write", answer_mode="agent_turn"
        ),
    )


def test_scan_memory_manage_calls_reads_trajectory_outcomes(tmp_path: Path) -> None:
    # 构造最小轨迹库：events + payloads，存两条 memory_manage 工具结果。
    db = tmp_path / "trajectories.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE trajectory_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.execute(
        """
        CREATE TABLE payloads (
            payload_id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_type TEXT NOT NULL,
            encoding TEXT NOT NULL,
            compression TEXT NOT NULL,
            redaction_status TEXT NOT NULL,
            sha256 TEXT NOT NULL UNIQUE,
            original_size INTEGER NOT NULL,
            stored_size INTEGER NOT NULL,
            inline_text TEXT,
            blob BLOB,
            external_uri TEXT,
            transformed INTEGER NOT NULL DEFAULT 0,
            truncated INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL,
            span_id TEXT,
            sequence INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            payload_id INTEGER,
            schema_version INTEGER NOT NULL
        )
        """
    )
    success_payload = json.dumps(
        {"name": "memory_manage", "raw_content": '{"status":"success","id":"c1"}'}
    )
    rejected_payload = json.dumps(
        {"name": "memory_manage", "raw_content": "正式记忆写入被拒绝：content 不一致"}
    )
    other_payload = json.dumps({"name": "code_run", "raw_content": "{}"})
    for payload_text in (success_payload, rejected_payload, other_payload):
        digest = hashlib.sha256(payload_text.encode()).hexdigest()
        conn.execute(
            "INSERT INTO payloads(content_type, encoding, compression, "
            "redaction_status, sha256, original_size, stored_size, "
            "inline_text) VALUES('json','utf-8','none','none',?,?,?,?)",
            (digest, len(payload_text), len(payload_text), payload_text),
        )
    rows = conn.execute(
        "SELECT payload_id FROM payloads ORDER BY payload_id"
    ).fetchall()
    for seq, (pid,) in enumerate(rows, start=1):
        conn.execute(
            "INSERT INTO events(trace_id, span_id, sequence, event_type, "
            "occurred_at, payload_id, schema_version) VALUES('t', NULL, ?, "
            "'tool_result_payload_stored', '2026-08-16T00:00:00Z', ?, 1)",
            (seq, pid),
        )
    conn.commit()
    conn.close()

    calls = scan_memory_manage_calls(db)
    # code_run 被跳过；memory_manage 两次：一次成功，一次拒绝
    assert len(calls) == 2
    outcomes = {call.outcome for call in calls}
    assert "success" in outcomes
    assert "rejected" in outcomes


def test_scan_memory_manage_calls_missing_db_returns_empty(tmp_path: Path) -> None:
    assert scan_memory_manage_calls(tmp_path / "absent.db") == []
