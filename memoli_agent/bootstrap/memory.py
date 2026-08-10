"""记忆系统装配模块。

第七阶段只支持 Markdown 文件记忆引擎。
"""

from __future__ import annotations

from pathlib import Path

from memoli_agent.agent.memory.cards import CardBuilder
from memoli_agent.agent.memory.episodic import TrajectorySegmentIndexer
from memoli_agent.agent.memory.hybrid import (
    HybridMemoryRetriever,
    KeywordSearchLane,
    MetadataSearchLane,
    SemanticSearchLane,
)
from memoli_agent.agent.memory.migration import LegacyMemoryMigrator
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
from memoli_agent.agent.memory.sqlite_store import SQLiteMemoryStore
from memoli_agent.agent.memory.store import MarkdownMemoryStore
from memoli_agent.agent.trajectory import SQLiteTrajectoryStore
from memoli_agent.bootstrap.config import AppConfig


def build_memory_runtime(
    config: AppConfig,
    trajectory_store: SQLiteTrajectoryStore | None = None,
) -> MemoryRuntime | None:
    """根据配置创建记忆 runtime。"""

    if not config.memory.enabled:
        return None

    if config.memory.engine == "markdown":
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
            keyword_lane=KeywordSearchLane(store),
            metadata_lane=MetadataSearchLane(store),
            semantic_lane=semantic_lane,
            rrf_k=hybrid.rrf_k,
            lane_weights={
                "keyword": hybrid.keyword_weight,
                "semantic": hybrid.semantic_weight,
                "metadata": hybrid.metadata_weight,
            },
            candidate_limit=hybrid.candidate_limit,
        )
    else:
        retriever = SQLiteMemoryRetriever(store)
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
        if config.memory.episode_projection_enabled
        and trajectory_store is not None
        else None
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
    )
