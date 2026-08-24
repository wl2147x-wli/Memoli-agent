"""记忆系统装配模块。

第七阶段只支持 Markdown 文件记忆引擎。
"""

from __future__ import annotations

import os
from pathlib import Path

from memoli_agent.agent.memory.cards import CardBuilder
from memoli_agent.agent.memory.consolidator import MemoryConsolidator
from memoli_agent.agent.memory.episodic import TrajectorySegmentIndexer
from memoli_agent.agent.memory.extraction import (
    CandidateExtractor,
    DeterministicCandidateExtractor,
    OpenAICompatibleCandidateExtractor,
)
from memoli_agent.agent.memory.governance import (
    GovernancePolicy,
    GovernancePolicyGate,
    MemoryGovernanceService,
)
from memoli_agent.agent.memory.hybrid import (
    FtsSearchLane,
    HybridMemoryRetriever,
    MetadataSearchLane,
    PatternSearchLane,
    SemanticSearchLane,
)
from memoli_agent.agent.memory.layered import LayeredMemoryRetriever
from memoli_agent.agent.memory.migration import LegacyMemoryMigrator
from memoli_agent.agent.memory.models import ExtractorFingerprint
from memoli_agent.agent.memory.retriever import (
    KeywordMemoryRetriever,
    SQLiteMemoryRetriever,
)
from memoli_agent.agent.memory.runtime import MemoryRuntime
from memoli_agent.agent.memory.semantic import (
    DeterministicEmbedder,
    DisabledEmbedder,
    MemoryIndexWorker,
    OpenAICompatibleEmbedder,
)
from memoli_agent.agent.memory.source import MemoryContentPolicy, TrajectorySourceReader
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore
from memoli_agent.agent.memory.store import MarkdownMemoryStore
from memoli_agent.agent.memory.triggers import TriggerCoordinator
from memoli_agent.agent.memory.worker import OfflineMemoryWorker
from memoli_agent.agent.trajectory import SQLiteTrajectoryStore
from memoli_agent.bootstrap.config import AppConfig


def build_candidate_extractor(config: AppConfig) -> CandidateExtractor | None:
    """按独立配置创建版本化 Extractor；不复用聊天凭据。"""

    if not config.memory.consolidation_enabled:
        return None
    extractor = config.memory.offline.extractor
    if extractor.provider == "disabled":
        raise ValueError("memory consolidation 已启用，但 Extractor 为 disabled。")
    fingerprint = ExtractorFingerprint(
        name=extractor.provider,
        version=extractor.version,
        schema_version=extractor.schema_version,
        prompt_version=extractor.prompt_version,
        policy_version=extractor.policy_version,
        provider=extractor.provider,
        model=extractor.model,
        segmenter_version=extractor.segmenter_version,
    )
    if extractor.provider == "deterministic":
        return DeterministicCandidateExtractor(fingerprint)
    if not extractor.model.strip():
        raise ValueError("openai-compatible memory Extractor 必须配置 model。")
    if not os.environ.get(extractor.api_key_env, "").strip():
        raise ValueError(
            f"memory Extractor 凭据环境变量未配置：{extractor.api_key_env}"
        )
    return OpenAICompatibleCandidateExtractor(
        model=extractor.model,
        api_key_env=extractor.api_key_env,
        base_url=extractor.base_url,
        timeout_seconds=extractor.timeout_seconds,
        fingerprint=fingerprint,
    )


def build_memory_runtime(
    config: AppConfig,
    trajectory_store: SQLiteTrajectoryStore | None = None,
) -> MemoryRuntime | None:
    """根据配置创建记忆 runtime。"""

    if not config.memory.enabled:
        return None

    if config.memory.engine == "markdown":
        if config.memory.consolidation_enabled:
            raise ValueError("离线记忆学习要求 memory.engine='sqlite'。")
        store = MarkdownMemoryStore(Path(config.memory.path))
        store.ensure_files()
        return MemoryRuntime(store=store, retriever=KeywordMemoryRetriever(store))

    store = SQLiteMemoryStore(
        config.memory.database,
        max_cjk_ngram=config.memory.max_cjk_ngram,
    )
    if config.memory.legacy_import != "off":
        migrator = LegacyMemoryMigrator(Path(config.memory.path), store)
        if config.memory.legacy_import == "auto":
            migrator.import_memory()
        else:
            migrator.preview()
    store.backfill_index_jobs()
    embedding = config.memory.embedding
    if embedding.enabled and embedding.provider == "deterministic":
        embedder = DeterministicEmbedder(
            dimensions=embedding.dimensions,
            model=embedding.model or "deterministic",
            version=embedding.version,
        )
    elif embedding.enabled and embedding.provider == "openai-compatible":
        embedder = OpenAICompatibleEmbedder(
            model=embedding.model,
            api_key_env=embedding.api_key_env,
            dimensions=embedding.dimensions,
            base_url=embedding.base_url,
            version=embedding.version,
            timeout_seconds=embedding.timeout_seconds,
        )
    else:
        embedder = DisabledEmbedder()
    if config.memory.hybrid.enabled:
        semantic_lane = (
            SemanticSearchLane(
                store,
                embedder,
                candidate_limit=embedding.candidate_limit,
            )
            if embedder.enabled
            else None
        )
        hybrid = config.memory.hybrid
        retriever = HybridMemoryRetriever(
            store=store,
            fts_lane=FtsSearchLane(store),
            pattern_lane=PatternSearchLane(store),
            metadata_lane=MetadataSearchLane(store),
            semantic_lane=semantic_lane,
            rrf_k=hybrid.rrf_k,
            rrf_bonus_weight=hybrid.rrf_bonus_weight,
            lane_weights={
                "fts": hybrid.fts_weight,
                "pattern": hybrid.pattern_weight,
                "semantic": hybrid.semantic_weight,
                "metadata": hybrid.metadata_weight,
            },
            candidate_limit=hybrid.candidate_limit,
            fts_candidate_limit=hybrid.fts_candidate_limit,
            pattern_candidate_limit=hybrid.pattern_candidate_limit,
            relative_threshold=hybrid.relative_threshold,
            multi_lane_protection=hybrid.multi_lane_protection,
            smart_seed_ratio=hybrid.smart_seed_ratio,
            mmr_enabled=hybrid.mmr_enabled,
            mmr_lambda=hybrid.mmr_lambda,
        )
    else:
        retriever = SQLiteMemoryRetriever(store)
    retriever = LayeredMemoryRetriever(store, retriever)
    index_worker = (
        MemoryIndexWorker(store, embedder, batch_size=embedding.batch_size)
        if embedder.enabled
        else None
    )
    card_builder = (
        CardBuilder(store, batch_size=config.memory.maintenance_batch_size)
        if config.memory.card_builder_enabled
        else None
    )
    episode_projector = (
        TrajectorySegmentIndexer(trajectory_store, store)
        if config.memory.episode_projection_enabled and trajectory_store is not None
        else None
    )
    extractor = build_candidate_extractor(config)
    governance_config = config.memory.offline.governance
    governance_service = MemoryGovernanceService(
        store,
        GovernancePolicyGate(
            store,
            GovernancePolicy(
                version=governance_config.policy_version,
                low_risk_fact_types=tuple(governance_config.low_risk_fact_types),
                min_independent_evidence=(governance_config.min_independent_evidence),
            ),
        ),
    )
    offline_worker = None
    if extractor is not None:
        if trajectory_store is None:
            raise ValueError("离线记忆学习要求启用 SQLite trajectory。")
        offline = config.memory.offline
        governance = offline.governance
        source_reader = TrajectorySourceReader(
            trajectory_store,
            MemoryContentPolicy(
                prompt_max_sensitivity=offline.extractor.prompt_max_sensitivity,
                embedding_max_sensitivity="private",
            ),
        )
        consolidator = MemoryConsolidator(
            store,
            extractor,
            source_reader,
            governor_version=governance.profile,
            governance_policy_version=governance.policy_version,
            governance_prompt_version=governance.prompt_version,
            governance_max_attempts=governance.max_attempts,
        )
        offline_worker = OfflineMemoryWorker(
            store,
            consolidator,
            poll_seconds=offline.poll_seconds,
            batch_size=offline.batch_size,
            lease_seconds=offline.lease_seconds,
            retry_max_seconds=offline.retry_max_seconds,
            auto_scan_enabled=offline.auto_scan_enabled,
            trigger_coordinator=TriggerCoordinator(
                store,
                source_reader,
                extractor.fingerprint.value,
                chat_turn_threshold=offline.chat_turn_threshold,
                long_task_min_business_tool_calls=(
                    offline.long_task_min_business_tool_calls
                ),
                long_task_min_distinct_business_tools=(
                    offline.long_task_min_distinct_business_tools
                ),
                long_task_min_elapsed_seconds=offline.long_task_min_elapsed_seconds,
                max_attempts=offline.max_attempts,
            ),
            card_builder=card_builder,
            index_worker=index_worker,
            episode_projector=episode_projector,
            governance_batch_size=governance.batch_size,
            governance_lease_seconds=governance.lease_seconds,
            dead_letter_stale_after_seconds=offline.dead_letter_stale_after_seconds,
            chat_turn_threshold=offline.chat_turn_threshold,
        )
    return MemoryRuntime(
        store=store,
        retriever=retriever,
        auto_recall=config.memory.auto_recall,
        core_card_limit=config.memory.core_card_limit,
        core_card_chars=config.memory.core_card_chars,
        recall_chars=config.memory.recall_chars,
        recall_limit=config.memory.recall_limit,
        card_limit=config.memory.hybrid.card_limit,
        claim_limit=config.memory.hybrid.claim_limit,
        episode_limit=config.memory.hybrid.episode_limit,
        spillover_order=tuple(config.memory.hybrid.spillover_order),
        index_worker=index_worker,
        card_builder=card_builder,
        episode_projector=episode_projector,
        offline_worker=offline_worker,
        offline_enabled=offline_worker is not None,
        extractor_fingerprint=(
            extractor.fingerprint.value if extractor is not None else ""
        ),
        governance_service=governance_service,
        retrieval_mode=config.memory.retrieval.mode,
        detail_level=config.memory.retrieval.detail_level,
        card_statement_limit=config.memory.retrieval.card_statement_limit,
        claim_expansion_limit=config.memory.retrieval.claim_expansion_limit,
        evidence_expansion_limit=config.memory.retrieval.evidence_expansion_limit,
        direct_claim_fallback=config.memory.retrieval.direct_claim_fallback,
    )
