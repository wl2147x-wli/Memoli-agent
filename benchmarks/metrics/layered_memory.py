"""记忆学习分层评估指标。

按《ai-agent-book》第 8 章表 8-3，把记忆写入与离线整理闭环的评估拆成四层，
区分更新器能力（harness-updating）与受益能力（harness-benefit），避免仅以
端到端回答分数反推更新器好坏。所有函数只消费既有审计证据，不引入侵入式埋点；
任一信号缺失时对应指标返回 ``None``，而非失败。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any, Protocol

# 记忆写入合同的两种拒绝码：计为遵循失败而非规则错误。
ADHERENCE_FAILURE_OUTCOMES = frozenset(
    {"missing-explicit-basis", "basis-content-mismatch"}
)


@dataclass(slots=True)
class MemoryManageCall:
    """一次 ``memory_manage remember/correct`` 调用的结果。"""

    action: str
    # "success" | "missing-explicit-basis" | "basis-content-mismatch" | 其它拒绝/错误
    outcome: str


@dataclass(slots=True)
class GovernanceCandidate:
    """一条离线整理 Candidate 的治理结局。"""

    status: str  # "approved" | "projected" | "rejected" | "pending" | 其它


@dataclass(slots=True)
class RecallAttempt:
    """一次记忆召回是否命中。"""

    hit: bool


@dataclass(slots=True)
class LayeredMemoryAudit:
    """分层评估的原始审计证据。"""

    memory_manage_calls: list[MemoryManageCall] = field(default_factory=list)
    governance_candidates: list[GovernanceCandidate] = field(default_factory=list)
    recall_attempts: list[RecallAttempt] = field(default_factory=list)
    baseline_score: float | None = None
    treatment_score: float | None = None


def adherence_rate(audit: LayeredMemoryAudit) -> float | None:
    """遵循成功率：通过逐字证据合同的 ``remember/correct`` 调用比例。

    ``missing-explicit-basis`` 与 ``basis-content-mismatch`` 拒绝计为遵循失败，
    而非规则错误。
    """
    calls = audit.memory_manage_calls
    if not calls:
        return None
    successes = sum(1 for call in calls if call.outcome == "success")
    return successes / len(calls)


def candidate_validity_rate(audit: LayeredMemoryAudit) -> float | None:
    """候选修改有效率：经 Governance 批准并成功投影的 Candidate 比例。"""
    candidates = audit.governance_candidates
    if not candidates:
        return None
    valid = sum(
        1 for candidate in candidates if candidate.status in {"approved", "projected"}
    )
    return valid / len(candidates)


def activation_rate(audit: LayeredMemoryAudit) -> float | None:
    """产物激活率：被召回记忆在正确场景被命中的比例。"""
    attempts = audit.recall_attempts
    if not attempts:
        return None
    hits = sum(1 for attempt in attempts if attempt.hit)
    return hits / len(attempts)


def held_out_gain(audit: LayeredMemoryAudit) -> float | None:
    """留出任务增益：召回相关记忆后的回答质量相对基线的增益。"""
    if audit.baseline_score is None or audit.treatment_score is None:
        return None
    return audit.treatment_score - audit.baseline_score


def compute_layered_memory(audit: LayeredMemoryAudit) -> dict[str, object]:
    """聚合四项分层指标；信号缺失时对应值为 ``None``。"""
    return {
        "adherence_rate": adherence_rate(audit),
        "candidate_validity_rate": candidate_validity_rate(audit),
        "activation_rate": activation_rate(audit),
        "held_out_gain": held_out_gain(audit),
        "sample_counts": {
            "memory_manage_calls": len(audit.memory_manage_calls),
            "governance_candidates": len(audit.governance_candidates),
            "recall_attempts": len(audit.recall_attempts),
        },
    }


def mean_score(scores: list[float]) -> float | None:
    """留出任务增益的辅助：对一组分数取均值，空集返回 ``None``。"""
    return mean(scores) if scores else None


class _MemoryAuditable(Protocol):
    """适配器可选暴露的 ``memory_audit`` 钩子。"""

    def memory_audit(self) -> LayeredMemoryAudit: ...


def collect_layered_memory(
    agent: Any, records: list[dict[str, Any]]
) -> LayeredMemoryAudit | None:
    """从适配器可选钩子与预测记录收集分层审计证据。

    适配器不提供 ``memory_audit`` 时返回 ``None``，调用方应据此跳过分层指标，
    而不影响官方评分。所有读取均为既有审计证据，不引入侵入式埋点。
    """
    audit_method = getattr(agent, "memory_audit", None)
    if not callable(audit_method):
        return None
    try:
        audit = audit_method()
    except Exception:
        return None
    if not isinstance(audit, LayeredMemoryAudit):
        return None
    _augment_held_out_gain(audit, records)
    return audit


def _augment_held_out_gain(
    audit: LayeredMemoryAudit, records: list[dict[str, Any]]
) -> None:
    """若预测记录携带基线/处置分数，补充留出增益证据。"""
    if audit.baseline_score is not None and audit.treatment_score is not None:
        return
    baseline_scores: list[float] = []
    treatment_scores: list[float] = []
    for record in records:
        metadata = record.get("metadata") or {}
        baseline = metadata.get("baseline_score")
        treatment = metadata.get("treatment_score")
        if isinstance(baseline, int | float):
            baseline_scores.append(float(baseline))
        if isinstance(treatment, int | float):
            treatment_scores.append(float(treatment))
    if audit.baseline_score is None:
        audit.baseline_score = mean_score(baseline_scores)
    if audit.treatment_score is None:
        audit.treatment_score = mean_score(treatment_scores)


def scan_memory_manage_calls(trajectory_db: Path) -> list[MemoryManageCall]:
    """只读扫描轨迹库中 ``memory_manage`` 工具结果，判定 success 与拒绝。

    成功判定为 payload JSON 含 ``status == "success"``；其余（非 JSON 或无
    success）计为遵循失败。任何 schema 或解析异常均返回空列表，对应指标为
    ``None``，绝不抛出。
    """
    calls: list[MemoryManageCall] = []
    uri = f"file:{trajectory_db.as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except Exception:
        return calls
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT payload_id FROM events "
            "WHERE event_type = 'tool_result_payload_stored'"
        ).fetchall()
        payload_ids = [int(row["payload_id"]) for row in rows if row["payload_id"]]
        if not payload_ids:
            return calls
        placeholders = ",".join("?" for _ in payload_ids)
        query = (
            "SELECT inline_text, blob FROM payloads "
            f"WHERE payload_id IN ({placeholders})"  # noqa: S608
        )
        payload_rows = connection.execute(query, payload_ids).fetchall()
        for raw_row in payload_rows:
            raw_text = _decode_payload_text(raw_row)
            if raw_text is None:
                continue
            try:
                payload = json.loads(raw_text)
            except (ValueError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            if str(payload.get("name") or "") != "memory_manage":
                continue
            outcome = _classify_memory_manage_payload(payload.get("raw_content"))
            calls.append(MemoryManageCall(action="remember", outcome=outcome))
    except Exception:
        return calls
    finally:
        try:
            connection.close()
        except Exception:
            pass
    return calls


def _decode_payload_text(row: sqlite3.Row) -> str | None:
    inline = row["inline_text"]
    if inline is not None:
        return str(inline)
    blob = row["blob"]
    if blob is not None:
        try:
            return bytes(blob).decode("utf-8")
        except (UnicodeDecodeError, TypeError):
            return None
    return None


def _classify_memory_manage_payload(raw_content: Any) -> str:
    """从工具结果正文判定 outcome。"""
    if isinstance(raw_content, str):
        try:
            parsed = json.loads(raw_content)
        except (ValueError, TypeError):
            return "rejected"
        if isinstance(parsed, dict) and parsed.get("status") == "success":
            return "success"
        if (
            isinstance(parsed, dict)
            and parsed.get("error") in ADHERENCE_FAILURE_OUTCOMES
        ):
            return str(parsed.get("error"))
    if isinstance(raw_content, dict):
        if raw_content.get("status") == "success":
            return "success"
        if raw_content.get("error") in ADHERENCE_FAILURE_OUTCOMES:
            return str(raw_content.get("error"))
    return "rejected"
