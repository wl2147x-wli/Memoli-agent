"""离线记忆整理：只生成候选，不在在线 turn 中修改长期记忆。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

from memoli_agent.agent.memory.models import (
    ConsolidationCandidate,
    MemoryMutation,
)
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore


@dataclass(frozen=True, slots=True)
class ConsolidationInput:
    trace_start: str
    trace_end: str
    segments: tuple[str, ...]
    request_id: str = ""


@dataclass(frozen=True, slots=True)
class ConsolidationResult:
    run_id: str
    status: str
    candidate_ids: tuple[str, ...] = ()
    skipped_categories: tuple[str, ...] = ()


class CandidateExtractor(Protocol):
    def extract(self, segment: str) -> list[ConsolidationCandidate]: ...


@dataclass(frozen=True, slots=True)
class MemoryConsolidator:
    store: SQLiteMemoryStore
    extractor: CandidateExtractor

    def run(self, input_data: ConsolidationInput) -> ConsolidationResult:
        batch_key = hashlib.sha256(
            (
                f"{input_data.trace_start}:{input_data.trace_end}:"
                f"{input_data.request_id}"
            ).encode()
        ).hexdigest()
        run_id = self.store.begin_consolidation(
            batch_key, input_data.trace_start, input_data.trace_end
        )
        if run_id is None:
            return ConsolidationResult(batch_key, "already-completed")

        entries: list[tuple[MemoryMutation, tuple[tuple[str, str], ...]]] = []
        skipped: list[str] = []
        try:
            for segment in input_data.segments:
                for candidate in self.extractor.extract(segment):
                    self._validate(candidate)
                    if candidate.category != "personal-memory":
                        skipped.append(candidate.category)
                        continue
                    entries.append(
                        (
                            MemoryMutation(
                            content=candidate.content,
                            source=candidate.source,
                            scope=candidate.scope,
                            status="candidate",
                            sensitivity=candidate.sensitivity,
                            explicitness=candidate.explicitness,
                            evidence=candidate.evidence,
                            metadata={"consolidation_run": run_id},
                            ),
                            candidate.relations,
                        )
                    )
            candidate_ids = self.store.apply_consolidation_batch(
                run_id, input_data.trace_end, entries
            )
        except Exception as exc:
            # 失败只记录错误，不推进消费 checkpoint。
            self.store.fail_consolidation(run_id, type(exc).__name__)
            raise
        return ConsolidationResult(
            run_id,
            "completed",
            candidate_ids,
            tuple(dict.fromkeys(skipped)),
        )

    @staticmethod
    def _validate(candidate: ConsolidationCandidate) -> None:
        if not candidate.content.strip():
            raise ValueError("候选记忆内容不能为空。")
        if not candidate.evidence:
            raise ValueError("候选记忆必须携带 evidence。")
        if candidate.explicitness == "explicit-user" and not all(
            ref.kind == "message" for ref in candidate.evidence
        ):
            raise ValueError("用户偏好/关系事实只能来自用户消息证据。")
        if candidate.category not in {
            "personal-memory",
            "skill-candidate",
            "evaluation-candidate",
            "training-candidate",
        }:
            raise ValueError("未知候选分类。")
        for target_id, relation in candidate.relations:
            if not target_id or relation not in {
                "supports",
                "corrects",
                "contradicts",
                "supersedes",
                "derived-from",
            }:
                raise ValueError("候选冲突关系无效。")
