"""SubAgent 装配模块。

这里集中创建 SubAgentManager，避免把子 agent 的任务目录、profile 和
MessageBus 回流细节散落到 AppRuntime 之外。
"""

from __future__ import annotations

from pathlib import Path

from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.subagent.manager import SubAgentManager
from memoli_agent.agent.subagent.profiles import default_subagent_profiles
from memoli_agent.agent.subagent.runtime import SubAgentRuntime
from memoli_agent.bootstrap.config import AppConfig
from memoli_agent.bus.queue import MessageBus


def build_subagent_manager(
    config: AppConfig,
    bus: MessageBus,
    reasoner: Reasoner,
) -> SubAgentManager | None:
    """根据配置创建子 agent 管理器。"""

    if not config.subagent.enabled:
        return None

    profiles = default_subagent_profiles()
    runtime = SubAgentRuntime(reasoner=reasoner, profiles=profiles)
    return SubAgentManager(
        runtime=runtime,
        bus=bus,
        root=Path(config.subagent.root),
        profiles=profiles,
        default_profile=config.subagent.default_profile,
        max_concurrent=config.subagent.max_concurrent,
    )
