from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from memoli_agent.agent.memory.cards import CardBuilder
from memoli_agent.agent.memory.consolidator import MemoryConsolidator
from memoli_agent.agent.memory.extraction import (
    DeterministicCandidateExtractor,
    ExtractorPermanentError,
    parse_candidate_drafts,
)
from memoli_agent.agent.memory.governance import (
    DeterministicGovernor,
    GovernancePolicy,
    GovernancePolicyGate,
    MemoryGovernanceService,
)
from memoli_agent.agent.memory.layered import LayeredMemoryRetriever
from memoli_agent.agent.memory.models import (
    CandidateDraft,
    CardProjectionKey,
    EvidenceLocator,
    EvidenceRef,
    ExtractorFingerprint,
    GovernanceDecision,
    MemoryMutation,
    MemoryQuery,
    MemoryScope,
)
from memoli_agent.agent.memory.retriever import SQLiteMemoryRetriever
from memoli_agent.agent.memory.source import (
    EvidenceVerificationError,
    EvidenceVerifier,
    MemoryContentPolicy,
    TrajectorySourceError,
    TrajectorySourceReader,
)
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore
from memoli_agent.agent.memory.worker import OfflineMemoryWorker
from memoli_agent.agent.subagent.profiles import (
    ProfileToolRegistryFactory,
    default_subagent_profiles,
)
from memoli_agent.agent.trajectory import (
    NewTrajectoryEvent,
    SpanKind,
    SpanProjection,
    SQLiteTrajectoryStore,
    TraceProjection,
    utc_now_iso,
)
from memoli_agent.bootstrap.config import (
    AppConfig,
    MemoryConfig,
    RuntimeConfig,
    load_config,
)
from memoli_agent.bootstrap.memory import (
    build_candidate_extractor,
    build_memory_runtime,
)
from memoli_agent.bootstrap.tools import build_tool_registry


def _candidate(store: SQLiteMemoryStore, content: str = "Alice 喜欢乌龙茶") -> str:
    item = store.append_claim(
        MemoryMutation(
            content=content,
            source="offline-extractor",
            status="candidate",
            explicitness="explicit-user",
            evidence=(
                EvidenceRef(
                    "message",
                    "msg-1",
                    content,
                    {
                        "verified": True,
                        "content_hash": "source-hash",
                        "locator": {"trace_id": "trace-1", "role": "user"},
                    },
                ),
            ),
            metadata={
                "fact_type": "preference",
                "confidence": 0.9,
                "extractor_name": "deterministic",
                "extractor_version": "1",
                "verification_status": "verified",
            },
        )
    )
    return item.item_id


async def _trajectory(
    tmp_path: Path, *, complete: bool = True, session_id: str = "default"
) -> tuple[SQLiteTrajectoryStore, str]:
    store = SQLiteTrajectoryStore(
        tmp_path / "trajectories.db",
        payload_directory=tmp_path / "payloads",
        capture_content="redacted",
    )
    await store.start()
    trace_id = "a" * 32
    started = utc_now_iso()
    span_id = "b" * 16
    await store.record(
        NewTrajectoryEvent(
            trace_id,
            "trace_started",
            {"content": "记住：Alice 喜欢乌龙茶"},
            span_id=span_id,
            trace=TraceProjection(trace_id, session_id, started),
            span=SpanProjection(
                span_id,
                trace_id,
                None,
                SpanKind.AGENT,
                "turn",
                started,
                input_data={
                    "messages": [{"role": "user", "content": "记住：Alice 喜欢乌龙茶"}]
                },
            ),
        )
    )
    if complete:
        ended = utc_now_iso()
        await store.record(
            NewTrajectoryEvent(
                trace_id,
                "trace_finished",
                {"final_output": "好的"},
                span_id=span_id,
                trace=TraceProjection(
                    trace_id,
                    "default",
                    started,
                    status="completed",
                    ended_at=ended,
                    termination_reason="completed",
                    final_output="好的",
                ),
                span=SpanProjection(
                    span_id,
                    trace_id,
                    None,
                    SpanKind.AGENT,
                    "turn",
                    started,
                    status="completed",
                    ended_at=ended,
                ),
            )
        )
    return store, trace_id


def test_offline_memory_config_is_nested_and_disabled_by_default(
    tmp_path: Path,
) -> None:
    assert not load_config(tmp_path / "missing.toml").memory.consolidation_enabled
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[memory]
engine = "sqlite"
consolidation_enabled = true

[memory.offline]
lease_seconds = 42

[memory.offline.extractor]
provider = "deterministic"

[memory.offline.governance]
min_independent_evidence = 3

[memory.retrieval]
mode = "card-first"
detail_level = "fact"
""",
        encoding="utf-8",
    )
    config = load_config(config_file)
    assert config.memory.offline.lease_seconds == 42
    assert config.memory.offline.extractor.provider == "deterministic"
    assert config.memory.offline.governance.min_independent_evidence == 3
    assert config.memory.retrieval.mode == "card-first"


def test_inline_extractor_key_is_accepted_and_redacted(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[memory]
engine = "sqlite"
consolidation_enabled = true

[memory.offline.extractor]
provider = "openai-compatible"
model = "local-extractor"
api_key = "inline-secret"
api_key_env = ""
base_url = "http://127.0.0.1:8000/v1"
""",
        encoding="utf-8",
    )

    config = load_config(config_file)
    extractor = build_candidate_extractor(config)

    assert extractor is not None
    assert "inline-secret" not in repr(config.memory.offline.extractor)
    assert "inline-secret" not in repr(extractor)


def test_memory_provider_key_sources_are_mutually_exclusive(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        """
[memory]
engine = "sqlite"
consolidation_enabled = true

[memory.offline.extractor]
provider = "openai-compatible"
model = "local-extractor"
api_key = "inline-secret"
api_key_env = "MEMOLI_TEST_EXTRACTOR_KEY"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="不能同时配置"):
        build_candidate_extractor(load_config(config_file))


def test_request_repository_is_idempotent_leased_and_recoverable(
    tmp_path: Path,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    scope = MemoryScope()
    first = store.create_long_term_update_request(
        source_type="explicit-tool",
        scope=scope,
        trace_ids=("trace-1",),
        version_fingerprint="extractor-v1",
    )
    repeated = store.create_long_term_update_request(
        source_type="explicit-tool",
        scope=scope,
        trace_ids=("trace-1",),
        version_fingerprint="extractor-v1",
    )
    assert repeated.request_id == first.request_id

    claimed = store.claim_long_term_update_requests(
        worker_id="worker-a", limit=1, lease_seconds=30
    )
    assert len(claimed) == 1 and claimed[0].attempts == 1
    assert not store.claim_long_term_update_requests(
        worker_id="worker-b", limit=1, lease_seconds=30
    )
    store._connection.execute(  # noqa: SLF001 - fault-injection assertion
        "UPDATE long_term_update_requests SET lease_until=? WHERE request_id=?",
        ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), first.request_id),
    )
    store._connection.commit()  # noqa: SLF001
    assert store.recover_expired_long_term_update_leases() == 1
    recovered = store.claim_long_term_update_requests(
        worker_id="worker-b", limit=1, lease_seconds=30
    )
    assert recovered[0].request_id == first.request_id
    assert store.complete_long_term_update_request(
        first.request_id, worker_id="worker-b", candidate_count=2
    )
    store.close()


def test_governance_job_uses_revision_cas_and_idempotent_audit(
    tmp_path: Path,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    candidate_id = _candidate(store)
    job = store.enqueue_governance_job(
        candidate_id,
        expected_revision=0,
        governor_version="governor-1",
        policy_version="policy-1",
        prompt_version="prompt-1",
    )
    claimed = store.claim_governance_jobs(
        worker_id="governor-worker", limit=1, lease_seconds=30
    )[0]
    decision = GovernanceDecision(
        candidate_id=candidate_id,
        expected_revision=0,
        decision="approve",
        reason_codes=("explicit-low-risk",),
        confidence=0.9,
        governor_version="governor-1",
        prompt_version="prompt-1",
        policy_version="policy-1",
    )
    audit = store.record_governance_decision(
        claimed.job_id,
        decision,
        actor="memory-governor:1:task-1",
        outcome="approved",
        worker_id="governor-worker",
    )
    repeated = store.record_governance_decision(
        claimed.job_id,
        decision,
        actor="memory-governor:1:task-1",
        outcome="approved",
        worker_id="governor-worker",
    )
    assert repeated.decision_id == audit.decision_id
    detail = store.candidate_detail(candidate_id, MemoryScope())
    assert detail is not None and detail["status"] == "approved"
    assert detail["revision"] == 1
    assert store.get_governance_job(job.job_id).state == "completed"  # type: ignore[union-attr]
    store.close()


def test_unknown_memory_schema_version_fails_closed(tmp_path: Path) -> None:
    database = tmp_path / "future.db"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA user_version = 999")
    connection.close()
    with pytest.raises(RuntimeError, match="不支持的 memory schema"):
        SQLiteMemoryStore(database)


def test_authoritative_source_rejects_incomplete_trace(tmp_path: Path) -> None:
    async def scenario() -> None:
        trajectory, trace_id = await _trajectory(tmp_path, complete=False)
        try:
            with pytest.raises(TrajectorySourceError, match="trajectory-incomplete"):
                await TrajectorySourceReader(trajectory).read_trace(
                    trace_id, MemoryScope()
                )
        finally:
            await trajectory.close()

    asyncio.run(scenario())


def test_evidence_verifier_rejects_forged_quote_and_assistant_user_fact(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        trajectory, trace_id = await _trajectory(tmp_path)
        try:
            sources = await TrajectorySourceReader(trajectory).read_trace(
                trace_id, MemoryScope()
            )
            user = next(item for item in sources if item.role == "user")
            forged = CandidateDraft(
                content="Alice 喜欢咖啡",
                fact_type="preference",
                subject="general",
                card_kind="profile",
                sensitivity="private",
                explicitness="explicit-user",
                confidence=1,
                importance=0.5,
                evidence=(
                    EvidenceLocator(
                        user.trace_id,
                        user.message_id,
                        "user",
                        "Alice 喜欢咖啡",
                        user.content_hash,
                    ),
                ),
            )
            with pytest.raises(EvidenceVerificationError, match="quote-mismatch"):
                EvidenceVerifier().verify(forged, sources, MemoryScope())

            assistant = next(item for item in sources if item.role == "assistant")
            assistant_only = replace(
                forged,
                evidence=(
                    EvidenceLocator(
                        assistant.trace_id,
                        assistant.message_id,
                        assistant.role,
                        assistant.content,
                        assistant.content_hash,
                    ),
                ),
            )
            with pytest.raises(
                EvidenceVerificationError, match="explicit-user-evidence-required"
            ):
                EvidenceVerifier().verify(assistant_only, sources, MemoryScope())
        finally:
            await trajectory.close()

    asyncio.run(scenario())


def test_source_scope_offsets_and_sensitive_policy_are_enforced(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        trajectory, trace_id = await _trajectory(tmp_path)
        try:
            reader = TrajectorySourceReader(trajectory)
            with pytest.raises(TrajectorySourceError, match="scope-forbidden"):
                await reader.read_trace(trace_id, MemoryScope("user", "another"))
            sources = await reader.read_trace(trace_id, MemoryScope())
            user = next(item for item in sources if item.role == "user")
            invalid_offset = CandidateDraft(
                content="Alice 喜欢乌龙茶",
                fact_type="preference",
                subject="general",
                card_kind="profile",
                sensitivity="private",
                explicitness="explicit-user",
                confidence=1,
                importance=0.5,
                evidence=(
                    EvidenceLocator(
                        user.trace_id,
                        user.message_id,
                        user.role,
                        "Alice",
                        user.content_hash,
                        0,
                        5,
                    ),
                ),
            )
            with pytest.raises(EvidenceVerificationError, match="offset-mismatch"):
                EvidenceVerifier().verify(invalid_offset, sources, MemoryScope())
            policy = MemoryContentPolicy()
            sensitivity = policy.classify("我的 API key 是 REDACTED")
            assert sensitivity == "sensitive"
            assert not policy.prompt_allowed(sensitivity)
            assert not policy.embedding_allowed(sensitivity)
        finally:
            await trajectory.close()

    asyncio.run(scenario())


def test_versioned_extractor_parser_rejects_unknown_fields() -> None:
    with pytest.raises(ExtractorPermanentError, match="fields-invalid"):
        parse_candidate_drafts(
            {
                "candidates": [
                    {
                        "content": "x",
                        "fact_type": "profile",
                        "subject": "general",
                        "card_kind": "profile",
                        "sensitivity": "private",
                        "explicitness": "inferred",
                        "confidence": 0.5,
                        "importance": 0.5,
                        "evidence": [],
                        "unexpected": True,
                    }
                ]
            }
        )


def test_authoritative_consolidation_commits_candidate_job_and_request_atomically(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        trajectory, trace_id = await _trajectory(tmp_path)
        memory = SQLiteMemoryStore(tmp_path / "memory.db")
        try:
            extractor = DeterministicCandidateExtractor()
            request = memory.create_long_term_update_request(
                source_type="explicit-tool",
                scope=MemoryScope(),
                trace_ids=(trace_id,),
                session_id="default",
                version_fingerprint=extractor.fingerprint.value,
            )
            claimed = memory.claim_long_term_update_requests(
                worker_id="offline-worker", limit=1, lease_seconds=30
            )[0]
            result = await MemoryConsolidator(
                memory,
                extractor,
                TrajectorySourceReader(trajectory),
            ).run_request(claimed, worker_id="offline-worker")
            assert result.status == "completed" and len(result.candidate_ids) == 1
            persisted = memory.get_long_term_update_request(request.request_id)
            assert persisted is not None and persisted.state == "completed"
            detail = memory.candidate_detail(result.candidate_ids[0], MemoryScope())
            assert detail is not None
            assert detail["verification_status"] == "verified"
            assert detail["extractor_name"] == "deterministic"
            assert detail["governance"][0]["state"] == "pending"
            assert not memory._connection.execute(  # noqa: SLF001
                "SELECT 1 FROM memory_projection_jobs"
            ).fetchone()
        finally:
            memory.close()
            await trajectory.close()

    asyncio.run(scenario())


def test_extractor_version_rerun_deduplicates_current_candidate(tmp_path: Path) -> None:
    async def scenario() -> None:
        trajectory, trace_id = await _trajectory(tmp_path)
        memory = SQLiteMemoryStore(tmp_path / "memory.db")
        try:
            first_extractor = DeterministicCandidateExtractor()
            first = memory.create_long_term_update_request(
                source_type="explicit-tool",
                scope=MemoryScope(),
                trace_ids=(trace_id,),
                session_id="default",
                version_fingerprint=first_extractor.fingerprint.value,
            )
            first_claimed = memory.claim_long_term_update_requests(
                worker_id="w1", limit=1, lease_seconds=30
            )[0]
            await MemoryConsolidator(
                memory, first_extractor, TrajectorySourceReader(trajectory)
            ).run_request(first_claimed, worker_id="w1")
            second_extractor = DeterministicCandidateExtractor(
                ExtractorFingerprint(
                    "deterministic", "2", "1", "1", "1", "local", "", "1"
                )
            )
            second = memory.create_long_term_update_request(
                source_type="explicit-tool",
                scope=MemoryScope(),
                trace_ids=(trace_id,),
                session_id="default",
                version_fingerprint=second_extractor.fingerprint.value,
            )
            assert second.request_id != first.request_id
            second_claimed = memory.claim_long_term_update_requests(
                worker_id="w2", limit=1, lease_seconds=30
            )[0]
            rerun = await MemoryConsolidator(
                memory, second_extractor, TrajectorySourceReader(trajectory)
            ).run_request(second_claimed, worker_id="w2")
            assert rerun.candidate_ids == ()
            assert len(memory.list_candidate_rows(MemoryScope())) == 1
            assert (
                memory._connection.execute(  # noqa: SLF001
                    "SELECT COUNT(*) FROM governance_jobs"
                ).fetchone()[0]
                == 1
            )
        finally:
            memory.close()
            await trajectory.close()

    asyncio.run(scenario())


def test_policy_gate_and_governor_approve_explicit_low_risk_candidate(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        try:
            candidate_id = _candidate(store)
            store.enqueue_governance_job(
                candidate_id,
                expected_revision=0,
                governor_version="deterministic",
                policy_version="1",
                prompt_version="1",
            )
            job = store.claim_governance_jobs(
                worker_id="worker", limit=1, lease_seconds=30
            )[0]
            gate = GovernancePolicyGate(store, GovernancePolicy())
            audit = await DeterministicGovernor(gate).review(job, worker_id="worker")
            assert audit.outcome == "approved"
            assert store.claim_row(candidate_id)["status"] == "approved"  # type: ignore[index]
            assert (
                store._connection.execute(  # noqa: SLF001
                    "SELECT COUNT(*) FROM memory_projection_jobs "
                    "WHERE projection_type='card'"
                ).fetchone()[0]
                == 1
            )
        finally:
            store.close()

    asyncio.run(scenario())


def test_policy_gate_escalates_sensitive_and_user_can_resolve(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        try:
            candidate_id = _candidate(store, "Alice has a medical diagnosis")
            store._connection.execute(  # noqa: SLF001
                "UPDATE claims SET sensitivity='sensitive' WHERE claim_id=?",
                (candidate_id,),
            )
            store._connection.commit()  # noqa: SLF001
            store.enqueue_governance_job(
                candidate_id,
                expected_revision=0,
                governor_version="deterministic",
                policy_version="1",
                prompt_version="1",
            )
            job = store.claim_governance_jobs(
                worker_id="worker", limit=1, lease_seconds=30
            )[0]
            gate = GovernancePolicyGate(store)
            audit = await DeterministicGovernor(gate).review(job, worker_id="worker")
            assert audit.outcome == "escalated"
            service = MemoryGovernanceService(store, gate)
            resolved = service.decide_user(
                candidate_id,
                MemoryScope(),
                decision_kind="approve",
                expected_revision=0,
                actor="user:test",
            )
            assert resolved.outcome == "approved"
        finally:
            store.close()

    asyncio.run(scenario())


def test_memory_governor_profile_is_strictly_least_privilege() -> None:
    profile = default_subagent_profiles()["memory-governor"]
    assert set(profile.allowed_tools) == {
        "governance_candidate_read",
        "governance_evidence_read",
        "governance_related_claims",
        "governance_decide",
    }
    assert not profile.can_write_files
    assert not profile.can_use_network
    assert not profile.can_delegate


def test_governance_tools_are_internal_and_bound_only_for_governor(
    tmp_path: Path,
) -> None:
    config = AppConfig(
        runtime=RuntimeConfig(workspace=str(tmp_path)),
        memory=MemoryConfig(database=str(tmp_path / "memory.db")),
    )
    runtime = build_memory_runtime(config)
    assert runtime is not None
    try:
        main_registry = build_tool_registry(config, runtime)
        main_names = {tool.name for tool in main_registry.list_tools()}
        assert not any(name.startswith("governance_") for name in main_names)

        candidate_id = _candidate(runtime.store)
        job = runtime.store.enqueue_governance_job(
            candidate_id,
            expected_revision=0,
            governor_version="memory-governor",
            policy_version="1",
            prompt_version="1",
        )
        governor_registry = ProfileToolRegistryFactory(
            main_registry,
            tmp_path,
            governance_service=runtime.governance_service,
        ).build(
            default_subagent_profiles()["memory-governor"],
            tmp_path,
            (f"governance-job:{job.job_id}",),
        )
        assert {tool.name for tool in governor_registry.list_tools()} == {
            "governance_candidate_read",
            "governance_evidence_read",
            "governance_related_claims",
            "governance_decide",
        }
        result = asyncio.run(governor_registry.execute("governance_candidate_read", {}))
        assert result.success and candidate_id in result.content
        evidence = asyncio.run(
            governor_registry.execute("governance_evidence_read", {})
        )
        related = asyncio.run(
            governor_registry.execute("governance_related_claims", {})
        )
        decided = asyncio.run(
            governor_registry.execute(
                "governance_decide",
                {
                    "decision": "approve",
                    "reason_codes": ["low-risk-evidence-backed"],
                    "confidence": 1.0,
                },
            )
        )
        assert evidence.success and related.success and decided.success
        assert json.loads(decided.content)["outcome"] == "approved"
        assert runtime.store.get_governance_job(job.job_id).state == "completed"  # type: ignore[union-attr]
    finally:
        runtime.close()


def test_card_projection_persists_current_statement_claim_mapping_and_routes(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        try:
            claim = store.append_claim(
                MemoryMutation(
                    "Alice prefers oolong tea",
                    evidence=(EvidenceRef("message", "m1", "oolong"),),
                    subject="Alice",
                    card_kind="profile",
                )
            )
            result = CardBuilder(store).build(
                CardProjectionKey(MemoryScope(), "Alice", "profile")
            )
            assert result.status == "created"
            statement = store._connection.execute(  # noqa: SLF001
                "SELECT * FROM card_statements WHERE is_current=1"
            ).fetchone()
            assert statement is not None
            assert (
                store._connection.execute(  # noqa: SLF001
                    "SELECT claim_id FROM card_statement_claims WHERE statement_id=?",
                    (statement["statement_id"],),
                ).fetchone()[0]
                == claim.item_id
            )
            retriever = LayeredMemoryRetriever(store, SQLiteMemoryRetriever(store))
            recalled = await retriever.query(
                MemoryQuery(
                    "Alice preference overview",
                    retrieval_mode="card-first",
                    detail_level="fact",
                )
            )
            assert recalled.actual_route == "card-first"
            assert [item.item_type for item in recalled.items] == ["card-statement"]
            assert recalled.items[0].metadata["expanded_claim_ids"] == (claim.item_id,)
        finally:
            store.close()

    asyncio.run(scenario())


def test_worker_without_trigger_coordinator_never_uses_legacy_per_turn_scan(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        trajectory, _ = await _trajectory(tmp_path, session_id="cli:local")
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        worker = OfflineMemoryWorker(
            store,
            MemoryConsolidator(
                store,
                DeterministicCandidateExtractor(),
                TrajectorySourceReader(trajectory),
            ),
            auto_scan_enabled=True,
        )
        try:
            diagnostics = await worker.maintenance_tick()
            assert diagnostics["auto_scan_enqueued"] == 0
            assert store.list_long_term_update_requests(MemoryScope()) == ()
        finally:
            store.close()
            await trajectory.close()

    asyncio.run(scenario())


def test_auto_scan_ignores_internal_subagent_trajectory(tmp_path: Path) -> None:
    async def scenario() -> None:
        trajectory, _ = await _trajectory(
            tmp_path,
            session_id="subagent:memory-governor-1",
        )
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        worker = OfflineMemoryWorker(
            store,
            MemoryConsolidator(
                store,
                DeterministicCandidateExtractor(),
                TrajectorySourceReader(trajectory),
            ),
            auto_scan_enabled=True,
        )
        try:
            diagnostics = await worker.maintenance_tick()
            assert diagnostics["auto_scan_enqueued"] == 0
            assert store.list_long_term_update_requests(MemoryScope()) == ()
        finally:
            store.close()
            await trajectory.close()

    asyncio.run(scenario())


def test_legacy_internal_auto_scan_request_is_skipped(tmp_path: Path) -> None:
    async def scenario() -> None:
        trajectory, trace_id = await _trajectory(
            tmp_path,
            session_id="subagent:memory-governor-1",
        )
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        store.create_long_term_update_request(
            source_type="auto-scan",
            scope=MemoryScope(),
            trace_ids=(trace_id,),
            session_id="subagent:memory-governor-1",
            trace_cursor="cursor-1",
        )
        worker = OfflineMemoryWorker(
            store,
            MemoryConsolidator(
                store,
                DeterministicCandidateExtractor(),
                TrajectorySourceReader(trajectory),
            ),
        )
        try:
            diagnostics = await worker.maintenance_tick()
            request = store.list_long_term_update_requests(MemoryScope())[0]
            assert diagnostics["requests"]["skipped"] == 1
            assert request.state == "completed"
            assert request.candidate_count == 0
        finally:
            store.close()
            await trajectory.close()

    asyncio.run(scenario())


def test_governance_support_merge_and_correction_are_atomic(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    try:
        target = store.append_claim(
            MemoryMutation(
                "Alice prefers oolong tea",
                evidence=(EvidenceRef("message", "old", "oolong"),),
                metadata={
                    "fact_type": "preference",
                    "entity": "Alice",
                    "predicate": "prefers",
                    "value": "oolong",
                },
            )
        )
        candidate_id = _candidate(store, "Alice likes oolong tea")
        store._connection.execute(  # noqa: SLF001
            "INSERT INTO candidate_relations(candidate_id, target_claim_id, relation, "
            "expected_target_revision, confidence, status, created_at) "
            "VALUES (?, ?, 'supports', 0, 1, 'proposed', ?)",
            (candidate_id, target.item_id, datetime.now(UTC).isoformat()),
        )
        store._connection.commit()  # noqa: SLF001
        store.enqueue_governance_job(
            candidate_id,
            expected_revision=0,
            governor_version="g",
            policy_version="1",
            prompt_version="1",
            initial_state="needs-user-review",
        )
        service = MemoryGovernanceService(store, GovernancePolicyGate(store))
        audit = service.decide_user(
            candidate_id,
            MemoryScope(),
            decision_kind="approve",
            expected_revision=0,
            actor="user:test",
        )
        assert audit.outcome == "approved"
        assert store.claim_row(candidate_id)["status"] == "superseded"  # type: ignore[index]
        assert (
            store._connection.execute(  # noqa: SLF001
                "SELECT COUNT(*) FROM evidence WHERE claim_id=?", (target.item_id,)
            ).fetchone()[0]
            == 2
        )

        correction = _candidate(store, "Alice now prefers green tea")
        store._connection.execute(  # noqa: SLF001
            "INSERT INTO candidate_relations(candidate_id, target_claim_id, relation, "
            "expected_target_revision, confidence, status, created_at) "
            "VALUES (?, ?, 'corrects', 0, 1, 'proposed', ?)",
            (correction, target.item_id, datetime.now(UTC).isoformat()),
        )
        store._connection.commit()  # noqa: SLF001
        store.enqueue_governance_job(
            correction,
            expected_revision=0,
            governor_version="g",
            policy_version="1",
            prompt_version="1",
            initial_state="needs-user-review",
        )
        corrected = service.decide_user(
            correction,
            MemoryScope(),
            decision_kind="approve",
            expected_revision=0,
            actor="user:test",
        )
        assert corrected.outcome == "approved"
        assert store.claim_row(target.item_id)["status"] == "superseded"  # type: ignore[index]
        assert store._connection.execute(  # noqa: SLF001
            "SELECT 1 FROM claim_relations WHERE source_claim_id=? "
            "AND target_claim_id=? AND relation='corrects'",
            (correction, target.item_id),
        ).fetchone()
    finally:
        store.close()


def test_governance_dead_letter_retry_is_conditional_and_preserves_audit(
    tmp_path: Path,
) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    try:
        candidate_id = _candidate(store)
        job = store.enqueue_governance_job(
            candidate_id,
            expected_revision=0,
            governor_version="memory-governor",
            policy_version="1",
            prompt_version="1",
            max_attempts=1,
        )
        claimed = store.claim_governance_jobs(
            worker_id="governor", limit=1, lease_seconds=30
        )[0]
        store.attach_governance_task(
            claimed.job_id, "task-original", worker_id="governor"
        )
        assert (
            store.fail_governance_job(
                claimed.job_id,
                worker_id="governor",
                error_type="ProviderProtocolError",
                retry_seconds=0,
            )
            == "dead-letter"
        )
        before, after = store.retry_governance_job(job.job_id, MemoryScope())
        assert before is not None and after is not None
        assert (before.state, after.state) == ("dead-letter", "retry")
        assert after.task_id == "task-original"
        assert after.last_error_type == "ProviderProtocolError"
        repeated_before, repeated_after = store.retry_governance_job(
            job.job_id, MemoryScope()
        )
        assert repeated_before is not None and repeated_after is None
        store._connection.execute(  # noqa: SLF001
            "UPDATE governance_jobs SET state='completed' WHERE job_id=?",
            (job.job_id,),
        )
        store._connection.commit()  # noqa: SLF001

        stale_id = _candidate(store, "Alice 喜欢红茶")
        stale_job = store.enqueue_governance_job(
            stale_id,
            expected_revision=0,
            governor_version="memory-governor",
            policy_version="1",
            prompt_version="1",
            max_attempts=1,
        )
        stale_claimed = store.claim_governance_jobs(
            worker_id="governor", limit=1, lease_seconds=30
        )[0]
        store.fail_governance_job(
            stale_claimed.job_id,
            worker_id="governor",
            error_type="ProviderProtocolError",
            retry_seconds=0,
        )
        store.set_status("claim", stale_id, "active", "user:test")
        stale_before, stale_after = store.retry_governance_job(
            stale_job.job_id, MemoryScope()
        )
        assert stale_before is not None and stale_after is None
    finally:
        store.close()


def test_derived_job_leases_recover_and_dead_letter(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    try:
        claim = store.append_claim(
            MemoryMutation(
                "lease test",
                evidence=(EvidenceRef("message", "m", "lease"),),
            )
        )
        job = store.claim_index_jobs(1, worker_id="index-a", lease_seconds=30)[0]
        store._connection.execute(  # noqa: SLF001
            "UPDATE memory_index_jobs SET lease_until=? WHERE memory_id=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), claim.item_id),
        )
        store._connection.commit()  # noqa: SLF001
        assert store.recover_expired_derived_leases()["memory_index_jobs"] == 1
        reclaimed = store.claim_index_jobs(1, worker_id="index-b", lease_seconds=30)[0]
        store.fail_index_job(reclaimed, "InvalidSchema", permanent=True)
        assert store.index_diagnostics()["index_jobs"]["dead-letter"] == 1
        assert store.retry_index_job("claim", claim.item_id)
        retried = store._connection.execute(  # noqa: SLF001
            "SELECT state, attempts FROM memory_index_jobs WHERE memory_id=?",
            (claim.item_id,),
        ).fetchone()
        assert tuple(retried) == ("retry", 0)

        store.enqueue_episode_projection("trace-dead", MemoryScope())
        store.fail_projection_job(
            "episode", "trace-dead", "InvalidProjection", permanent=True
        )
        assert store.retry_projection_job("episode", "trace-dead")
        assert job.worker_id == "index-a"
    finally:
        store.close()


def test_worker_drains_without_new_turn_and_stops_cleanly(tmp_path: Path) -> None:
    async def scenario() -> None:
        trajectory, trace_id = await _trajectory(tmp_path)
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        extractor = DeterministicCandidateExtractor()
        store.create_long_term_update_request(
            source_type="explicit-tool",
            scope=MemoryScope(),
            trace_ids=(trace_id,),
            session_id="default",
            version_fingerprint=extractor.fingerprint.value,
        )
        worker = OfflineMemoryWorker(
            store,
            MemoryConsolidator(store, extractor, TrajectorySourceReader(trajectory)),
            poll_seconds=0.01,
        )
        try:
            await worker.start()
            for _ in range(100):
                if (
                    store.list_long_term_update_requests(MemoryScope())[0].state
                    == "completed"
                ):
                    break
                await asyncio.sleep(0.01)
            assert (
                store.list_long_term_update_requests(MemoryScope())[0].state
                == "completed"
            )
            await worker.stop()
            assert not worker.diagnostics()["running"]
        finally:
            await worker.stop()
            store.close()
            await trajectory.close()

    asyncio.run(scenario())


def test_auto_router_selects_claim_episode_and_hybrid(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = SQLiteMemoryStore(tmp_path / "memory.db")
        retriever = LayeredMemoryRetriever(store, SQLiteMemoryRetriever(store))
        try:
            assert (
                await retriever.query(MemoryQuery("latest exact evidence"))
            ).actual_route == "claim-first"
            assert (
                await retriever.query(MemoryQuery("what happened in that process"))
            ).actual_route == "episode-first"
            assert (
                await retriever.query(MemoryQuery("an uncertain question"))
            ).actual_route == "hybrid"
        finally:
            store.close()

    asyncio.run(scenario())
