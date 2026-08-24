"""权威轨迹驱动的离线 Candidate consolidation。"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from typing import Any

from memoli_agent.agent.memory.extraction import extractor_batch_key
from memoli_agent.agent.memory.models import (
    CandidateDraft,
    ConsolidationCandidate,
    ExtractorFingerprint,
    LongTermUpdateRequest,
    MemoryMutation,
    MemoryScope,
    SourceSegment,
)
from memoli_agent.agent.memory.source import EvidenceVerifier, TrajectorySourceReader
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore


@dataclass(frozen=True, slots=True)
class ConsolidationInput:
    """旧测试/运维适配器；正式 Runtime 只调用 ``run_request``。"""

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


@dataclass(frozen=True, slots=True)
class MemoryConsolidator:
    store: SQLiteMemoryStore
    extractor: Any
    source_reader: TrajectorySourceReader | None = None
    verifier: EvidenceVerifier = EvidenceVerifier()
    governor_version: str = "1"
    governance_policy_version: str = "1"
    governance_prompt_version: str = "1"
    governance_max_attempts: int = 5

    async def run_request(
        self,
        request: LongTermUpdateRequest,
        *,
        worker_id: str,
    ) -> ConsolidationResult:
        """只从请求引用的已完成 trajectory 读取并原子提交候选。"""

        if self.source_reader is None:
            raise RuntimeError("authoritative-source-reader-required")
        sources = await self.source_reader.read_current_user_turns(
            request.trace_ids,
            request.scope,
            expected_session_id=request.session_id,
        )
        if not sources:
            raise ValueError("authoritative-source-empty")
        fingerprint = getattr(self.extractor, "fingerprint", None)
        if not isinstance(fingerprint, ExtractorFingerprint):
            raise TypeError("versioned-extractor-fingerprint-required")
        batch_key, input_hash = extractor_batch_key(
            scope_kind=request.scope.kind,
            scope_id=request.scope.identifier,
            sources=sources,
            fingerprint=fingerprint,
        )
        trace_ids = tuple(dict.fromkeys(item.trace_id for item in sources))
        run_id = self.store.begin_consolidation(
            batch_key,
            trace_ids[0],
            trace_ids[-1],
            request_id=request.request_id,
            version_metadata={
                "extractor_name": fingerprint.name,
                "extractor_version": fingerprint.version,
                "schema_version": fingerprint.schema_version,
                "prompt_version": fingerprint.prompt_version,
                "policy_version": fingerprint.policy_version,
                "provider": fingerprint.provider,
                "model": fingerprint.model,
                "segmenter_version": fingerprint.segmenter_version,
                "input_hash": input_hash,
                "version_fingerprint": fingerprint.value,
            },
            max_attempts=request.max_attempts,
        )
        if run_id is None:
            self.store.complete_long_term_update_request(
                request.request_id,
                worker_id=worker_id,
                candidate_count=0,
            )
            return ConsolidationResult(batch_key, "already-completed")
        try:
            pending = self.extractor.extract(sources)
            drafts = await pending if inspect.isawaitable(pending) else pending
            entries = [
                self._entry(draft, sources, request.scope, fingerprint, input_hash)
                for draft in drafts
            ]
            checkpoint = sources[-1].message_id
            candidate_ids = self.store.apply_consolidation_batch(
                run_id,
                checkpoint,
                entries,
                request_id=request.request_id,
                worker_id=worker_id,
                governor_version=self.governor_version,
                policy_version=self.governance_policy_version,
                prompt_version=self.governance_prompt_version,
                governance_max_attempts=self.governance_max_attempts,
            )
        except Exception as exc:
            self.store.fail_consolidation(run_id, type(exc).__name__)
            raise
        return ConsolidationResult(run_id, "completed", candidate_ids)

    def _entry(
        self,
        draft: CandidateDraft,
        sources: tuple[SourceSegment, ...],
        scope: MemoryScope,
        fingerprint: ExtractorFingerprint,
        input_hash: str,
    ) -> tuple[MemoryMutation, tuple[tuple[str, str], ...]]:
        evidence = self.verifier.verify(draft, sources, scope)
        relations = draft.relations or self._infer_relations(draft, scope)
        return (
            MemoryMutation(
                content=draft.content,
                source="offline-extractor",
                scope=scope,
                status="candidate",
                sensitivity=draft.sensitivity,
                explicitness=draft.explicitness,
                evidence=evidence,
                valid_from=draft.valid_from,
                valid_to=draft.valid_to,
                subject=draft.subject,
                card_kind=draft.card_kind,
                importance=draft.importance,
                metadata={
                    "fact_type": draft.fact_type,
                    "entity": draft.entity,
                    "predicate": draft.predicate,
                    "value": draft.value,
                    "confidence": draft.confidence,
                    "extractor_name": fingerprint.name,
                    "extractor_version": fingerprint.version,
                    "extractor_schema_version": fingerprint.schema_version,
                    "extractor_prompt_version": fingerprint.prompt_version,
                    "extractor_policy_version": fingerprint.policy_version,
                    "provider": fingerprint.provider,
                    "model": fingerprint.model,
                    "segmenter_version": fingerprint.segmenter_version,
                    "input_hash": input_hash,
                    "verification_status": "verified",
                    "prompt_allowed": all(
                        bool(ref.metadata.get("prompt_allowed", False))
                        for ref in evidence
                    ),
                    "embedding_allowed": all(
                        bool(ref.metadata.get("embedding_allowed", False))
                        for ref in evidence
                    ),
                },
            ),
            relations,
        )

    def _infer_relations(
        self, draft: CandidateDraft, scope: MemoryScope
    ) -> tuple[tuple[str, str], ...]:
        if not draft.entity or not draft.predicate:
            return ()
        rows = self.store.related_claim_rows(
            scope,
            subject=draft.subject,
            fact_type=draft.fact_type,
            entity=draft.entity,
            predicate=draft.predicate,
        )
        relations: list[tuple[str, str]] = []
        for row in rows:
            existing_value = str(row.get("value_json") or "null")
            relation = (
                "supports"
                if existing_value == _canonical_value(draft.value)
                else "contradicts"
            )
            relations.append((str(row["claim_id"]), relation))
        return tuple(relations)

    def run(self, input_data: ConsolidationInput) -> ConsolidationResult:
        """兼容旧确定性测试；不被正式 Runtime 或工具调用。"""

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
                    self._validate_legacy(candidate)
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
            self.store.fail_consolidation(run_id, type(exc).__name__)
            raise
        return ConsolidationResult(
            run_id,
            "completed",
            candidate_ids,
            tuple(dict.fromkeys(skipped)),
        )

    @staticmethod
    def _validate_legacy(candidate: ConsolidationCandidate) -> None:
        if not candidate.content.strip() or not candidate.evidence:
            raise ValueError("候选记忆必须包含内容和 evidence。")
        if candidate.category not in {
            "personal-memory",
            "skill-candidate",
            "evaluation-candidate",
            "training-candidate",
        }:
            raise ValueError("未知候选分类。")


def _canonical_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
