"""SubAgent 持久化任务图装配。"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import replace
from pathlib import Path

from memoli_agent.agent.memory.governance import MemoryGovernanceService
from memoli_agent.agent.plugins.hooks import HookBus
from memoli_agent.agent.provider import ProviderLike
from memoli_agent.agent.skills.runtime import SkillRuntime
from memoli_agent.agent.subagent.manager import SubAgentManager
from memoli_agent.agent.subagent.profiles import (
    ProfileToolRegistryFactory,
    default_subagent_profiles,
)
from memoli_agent.agent.subagent.repository import TaskGraphError, TaskGraphRepository
from memoli_agent.agent.subagent.runtime import SubAgentRuntime, SubAgentRuntimeFactory
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import TrajectoryStore
from memoli_agent.bootstrap.config import AppConfig
from memoli_agent.bus.queue import MessageBus

logger = logging.getLogger(__name__)


def build_subagent_manager(
    config: AppConfig,
    bus: MessageBus,
    provider: ProviderLike,
    fallback_provider: ProviderLike | None,
    source_registry: ToolRegistry,
    trajectory_store: TrajectoryStore,
    hook_bus: HookBus | None = None,
    skill_runtime: SkillRuntime | None = None,
    governance_service: MemoryGovernanceService | None = None,
) -> SubAgentManager | None:
    """按配置创建共享 provider、独立上下文和独立工具注册表的运行时。"""

    if not config.subagent.enabled:
        return None
    profiles = default_subagent_profiles()
    for name, profile in tuple(profiles.items()):
        iterations = config.subagent.profile_max_iterations.get(
            name, profile.max_iterations
        )
        elapsed = config.subagent.profile_max_elapsed_seconds.get(
            name, profile.max_elapsed_seconds
        )
        profiles[name] = replace(
            profile,
            max_iterations=iterations,
            max_elapsed_seconds=elapsed,
            max_depth=config.subagent.max_depth,
        )
    tool_factory = ProfileToolRegistryFactory(
        source_registry=source_registry,
        workspace=Path(config.runtime.workspace),
        hook_bus=hook_bus,
        governance_service=governance_service,
        code_timeout_seconds=config.tools.code_timeout_seconds,
        code_max_output_chars=config.tools.code_max_output_chars,
        file_read_max_lines=config.tools.file_read_max_lines,
        file_max_output_chars=config.tools.file_max_output_chars,
    )
    runtime = SubAgentRuntime(
        factory=SubAgentRuntimeFactory(
            provider=provider,
            fallback_provider=fallback_provider,
            tool_registry_factory=tool_factory,
            trajectory_store=trajectory_store,
            model_name=config.llm.primary_model,
            no_progress_limit=config.agent.no_progress_limit,
            hook_bus=hook_bus,
            skill_runtime=skill_runtime,
            stream_model=config.llm.stream,
        ),
        profiles=profiles,
    )
    try:
        repository = TaskGraphRepository(config.subagent.database)
        return SubAgentManager(
            runtime=runtime,
            repository=repository,
            bus=bus,
            root=Path(config.subagent.root),
            profiles=profiles,
            default_profile=config.subagent.default_profile,
            max_concurrent=config.subagent.max_concurrent,
            max_depth=config.subagent.max_depth,
        )
    except (OSError, sqlite3.Error, TaskGraphError) as exc:
        logger.error("SubAgent 任务图初始化失败，已禁用该能力：%s", exc)
        return None
