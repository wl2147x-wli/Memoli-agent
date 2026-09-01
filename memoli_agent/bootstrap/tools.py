"""工具装配模块。

第六阶段负责创建 ToolRegistry 并注册内置工具。插件工具、MCP 工具和
peer agent 工具会在后续阶段继续接入。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from memoli_agent.agent.context_management.repository import (
    ContextStateRepository,
    InMemoryContextStateRepository,
)
from memoli_agent.agent.memory.runtime import MemoryRuntime
from memoli_agent.agent.plugins.hooks import HookBus
from memoli_agent.agent.skills.runtime import SkillRuntime
from memoli_agent.agent.skills.tool import SkillLoadTool
from memoli_agent.agent.subagent.manager import SubAgentManager
from memoli_agent.agent.tools.browser import (
    BrowserAdapter,
    WebExecuteJSTool,
    WebScanTool,
)
from memoli_agent.agent.tools.builtin import (
    ManageSubAgentTool,
    MemoryManageTool,
    MemoryRecallTool,
    SpawnSubAgentTool,
    TimeTool,
)
from memoli_agent.agent.tools.control import (
    AskUserTool,
    StartLongTermUpdateTool,
    UpdateWorkingCheckpointTool,
    WorkingStateStore,
)
from memoli_agent.agent.tools.generic import (
    CodeRunTool,
    FilePatchTool,
    FileReadTool,
    FileWriteTool,
)
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.tools.tool_search import ToolSearchTool
from memoli_agent.agent.trajectory import TrajectoryStore
from memoli_agent.bootstrap.config import AppConfig


def build_tool_registry(
    config: AppConfig,
    memory_runtime: MemoryRuntime | None = None,
    hook_registry: HookBus | None = None,
    subagent_manager: SubAgentManager | None = None,
    working_state: WorkingStateStore | None = None,
    browser_adapter: BrowserAdapter | None = None,
    skill_runtime: SkillRuntime | None = None,
    trajectory_store: TrajectoryStore | None = None,
    mcp_names_provider: Callable[[], set[str]] | None = None,
    context_repository: ContextStateRepository | None = None,
) -> ToolRegistry:
    """创建并注册内置工具。"""

    disclosure_repository = context_repository
    if config.tools.tool_search_enabled and disclosure_repository is None:
        disclosure_repository = InMemoryContextStateRepository()
    registry = ToolRegistry(
        hook_bus=hook_registry,
        disclosure_repository=disclosure_repository,
    )
    workspace = Path(config.runtime.workspace)
    state = working_state or WorkingStateStore()

    if config.tools.code_runner != "disabled":
        registry.register(
            CodeRunTool(
            workspace,
            default_timeout_seconds=config.tools.code_timeout_seconds,
            max_output_chars=config.tools.code_max_output_chars,
            runner=config.tools.code_runner,
            container_cli=config.tools.code_container_cli,
            container_image=config.tools.code_container_image,
            python_executable=config.tools.code_python_executable,
            allow_network=config.tools.code_allow_network,
            memory_mb=config.tools.code_memory_mb,
            cpus=config.tools.code_cpus,
            pids_limit=config.tools.code_pids,
            )
        )
    registry.register(
        FileReadTool(
            workspace,
            max_lines=config.tools.file_read_max_lines,
            max_output_chars=config.tools.file_max_output_chars,
        )
    )
    registry.register(FilePatchTool(workspace))
    registry.register(FileWriteTool(workspace))
    registry.register(UpdateWorkingCheckpointTool(state))
    registry.register(AskUserTool())
    registry.register(StartLongTermUpdateTool(state, memory_runtime))
    registry.register(TimeTool())
    registry.register(MemoryRecallTool(memory_runtime))
    if config.tools.memory_manage_enabled:
        registry.register(MemoryManageTool(memory_runtime))
    if config.tools.browser_enabled and browser_adapter is not None:
        registry.register(WebScanTool(browser_adapter))
        registry.register(WebExecuteJSTool(browser_adapter, workspace))
    if config.tools.subagent_tool_enabled and subagent_manager is not None:
        register_subagent_tools(registry, subagent_manager)
    if config.skills.enabled and skill_runtime is not None:
        registry.register(
            SkillLoadTool(
                runtime=skill_runtime,
                tool_names_provider=lambda: {
                    tool.name for tool in registry.list_tools()
                },
                mcp_names_provider=mcp_names_provider or (lambda: set()),
                trajectory_store=trajectory_store,
            )
        )
    if config.tools.tool_search_enabled:
        registry.register(ToolSearchTool(registry))
        registry.enable_progressive_disclosure()

    return registry


def register_subagent_tools(
    registry: ToolRegistry, subagent_manager: SubAgentManager
) -> None:
    """在 manager 完成装配后注册委派与管理工具。"""

    registry.register(SpawnSubAgentTool(subagent_manager))
    registry.register(ManageSubAgentTool(subagent_manager))
