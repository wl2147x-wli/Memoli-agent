"""工具装配模块。

第六阶段负责创建 ToolRegistry 并注册内置工具。插件工具、MCP 工具和
peer agent 工具会在后续阶段继续接入。
"""

from __future__ import annotations

from pathlib import Path

from memoli_agent.agent.memory.runtime import MemoryRuntime
from memoli_agent.agent.plugins.decorators import HookRegistry
from memoli_agent.agent.subagent.manager import SubAgentManager
from memoli_agent.agent.tools.builtin import (
    CalculatorTool,
    FilesystemReadTool,
    MemoryRecallTool,
    MemoryWriteTool,
    SpawnSubAgentTool,
    TimeTool,
)
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.bootstrap.config import AppConfig


def build_tool_registry(
    config: AppConfig,
    memory_runtime: MemoryRuntime | None = None,
    hook_registry: HookRegistry | None = None,
    subagent_manager: SubAgentManager | None = None,
) -> ToolRegistry:
    """创建并注册内置工具。"""

    registry = ToolRegistry(hook_registry=hook_registry)
    workspace = Path(config.runtime.workspace)

    registry.register(TimeTool())
    registry.register(CalculatorTool())
    registry.register(MemoryWriteTool(memory_runtime))
    registry.register(MemoryRecallTool(memory_runtime))
    registry.register(FilesystemReadTool(workspace))
    if subagent_manager is not None:
        registry.register(SpawnSubAgentTool(subagent_manager))

    return registry
