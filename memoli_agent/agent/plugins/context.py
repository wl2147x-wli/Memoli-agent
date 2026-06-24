"""插件上下文。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from memoli_agent.agent.memory.runtime import MemoryRuntime
from memoli_agent.agent.plugins.decorators import HookRegistry
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.bootstrap.config import AppConfig


@dataclass(frozen=True, slots=True)
class PluginContext:
    """传给插件的受控资源集合。"""

    config: AppConfig
    workspace: Path
    tool_registry: ToolRegistry
    memory_runtime: MemoryRuntime | None
    hook_registry: HookRegistry
