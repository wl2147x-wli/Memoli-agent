"""应用级 runtime 装配模块。

AppRuntime 是 main.py 和内部组件之间的边界：

- main.py 只负责加载配置、创建 runtime、运行 runtime。
- AppRuntime 负责创建并管理 MessageBus、AgentLoop 和通道。
- 后续加入 memory、tools、plugins、subagent 时，也优先在这里集中装配。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from memoli_agent.agent.context import ContextBuilder
from memoli_agent.agent.core.passive_turn import PassiveTurnPipeline
from memoli_agent.agent.core.prompt_blocks import build_system_prompt
from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.llm.contracts import LLMProvider
from memoli_agent.agent.loop import AgentLoop
from memoli_agent.agent.mcp.registry import MCPClientManager
from memoli_agent.agent.memory.runtime import MemoryRuntime
from memoli_agent.agent.plugins.events import HookName, RuntimeEvent
from memoli_agent.agent.plugins.hooks import HookBus
from memoli_agent.agent.plugins.manager import PluginManager
from memoli_agent.agent.plugins.manifest import RUNTIME_VERSION
from memoli_agent.agent.proactive.loop import ProactiveLoop
from memoli_agent.agent.runner import AgentRunner
from memoli_agent.agent.session import SessionManager
from memoli_agent.agent.subagent.manager import SubAgentManager
from memoli_agent.agent.tools.control import WorkingStateStore
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.trajectory import SQLiteTrajectoryStore, TrajectoryStore
from memoli_agent.agent.working.repository import WorkingStateRepository
from memoli_agent.bootstrap.channels import run_configured_channels
from memoli_agent.bootstrap.config import AppConfig
from memoli_agent.bootstrap.mcp import build_mcp_manager
from memoli_agent.bootstrap.memory import build_memory_runtime
from memoli_agent.bootstrap.proactive import build_proactive_loop
from memoli_agent.bootstrap.providers import build_model_provider
from memoli_agent.bootstrap.skills import SkillComponents, build_skill_components
from memoli_agent.bootstrap.subagent import build_subagent_manager
from memoli_agent.bootstrap.tools import build_tool_registry, register_subagent_tools
from memoli_agent.bootstrap.trajectory import build_trajectory_store
from memoli_agent.bus.queue import MessageBus


@dataclass(slots=True)
class AppRuntime:
    """应用运行时容器。

    当前管理配置、消息总线、AgentLoop，以及 AgentLoop 需要的内部组件。
    """

    config: AppConfig
    bus: MessageBus
    agent_loop: AgentLoop
    tool_registry: ToolRegistry
    runner: AgentRunner
    memory_runtime: MemoryRuntime | None = None
    plugin_manager: PluginManager | None = None
    proactive_loop: ProactiveLoop | None = None
    mcp_manager: MCPClientManager | None = None
    trajectory_store: TrajectoryStore | None = None
    working_state: WorkingStateStore | None = None
    hook_bus: HookBus | None = None
    subagent_manager: SubAgentManager | None = None
    skill_components: SkillComponents | None = None
    model_provider: LLMProvider | None = None

    async def start(self) -> None:
        """启动后台服务。"""

        if self.trajectory_store is not None:
            await self.trajectory_store.start()
        if self.subagent_manager is not None:
            await self.subagent_manager.start()
        if self.memory_runtime is not None:
            await self.memory_runtime.maintenance_tick()
        if self.plugin_manager is not None:
            await self.plugin_manager.activate_plugins()
        if self.hook_bus is not None:
            await self.hook_bus.observe(
                HookName.RUNTIME_START,
                RuntimeEvent(
                    trace_id=(
                        self.plugin_manager.runtime_trace_id
                        if self.plugin_manager is not None
                        else ""
                    ),
                    runtime_version=RUNTIME_VERSION,
                ),
            )
        if self.mcp_manager is not None:
            await self.mcp_manager.connect_all()
            self.mcp_manager.register_tools(self.tool_registry)
        await self.agent_loop.start()
        if self.proactive_loop is not None:
            await self.proactive_loop.start()

    async def run(self) -> None:
        """运行已启用的输入通道。"""

        await run_configured_channels(self.config, self.bus)

    async def shutdown(self) -> None:
        """关闭后台服务并清理资源。"""

        if self.proactive_loop is not None:
            await self.proactive_loop.stop()
        await self.agent_loop.stop()
        if self.hook_bus is not None:
            await self.hook_bus.observe(
                HookName.RUNTIME_STOP,
                RuntimeEvent(
                    trace_id=(
                        self.plugin_manager.runtime_trace_id
                        if self.plugin_manager is not None
                        else ""
                    ),
                    runtime_version=RUNTIME_VERSION,
                ),
            )
        if self.plugin_manager is not None:
            await self.plugin_manager.terminate_plugins()
        if self.subagent_manager is not None:
            await self.subagent_manager.stop()
        if self.model_provider is not None:
            await self.model_provider.aclose()
        if self.trajectory_store is not None:
            await self.trajectory_store.close()
        if self.memory_runtime is not None:
            self.memory_runtime.close()
        if self.working_state is not None:
            self.working_state.close()
        if self.mcp_manager is not None:
            await self.mcp_manager.close_all()
        if self.skill_components is not None:
            self.skill_components.close()


def build_app_runtime(config: AppConfig) -> AppRuntime:
    """根据配置创建应用运行时。"""

    bus = MessageBus()
    trajectory_store = build_trajectory_store(config)
    memory_runtime = build_memory_runtime(
        config,
        trajectory_store
        if isinstance(trajectory_store, SQLiteTrajectoryStore)
        else None,
    )
    provider_bundle = build_model_provider(config.llm)
    provider = provider_bundle.provider
    fallback_provider = None
    mcp_manager = build_mcp_manager(config)
    skill_components = build_skill_components(config)
    hook_registry = HookBus(
        trajectory_store=trajectory_store,
        default_deadline_seconds=config.plugins.hook_deadline_seconds,
    )
    working_state = (
        WorkingStateStore(
            repository=WorkingStateRepository(config.working_memory.database),
            max_chars=config.working_memory.max_chars,
        )
        if config.working_memory.enabled
        else WorkingStateStore()
    )
    tool_registry = build_tool_registry(
        config,
        memory_runtime,
        hook_registry,
        None,
        working_state,
        skill_runtime=(skill_components.runtime if skill_components else None),
        trajectory_store=trajectory_store,
        mcp_names_provider=lambda: (
            set(mcp_manager.clients) if mcp_manager is not None else set()
        ),
    )
    subagent_manager = build_subagent_manager(
        config,
        bus,
        provider,
        fallback_provider,
        tool_registry,
        trajectory_store,
        hook_registry,
        skill_components.runtime if skill_components is not None else None,
    )
    if config.tools.subagent_tool_enabled and subagent_manager is not None:
        register_subagent_tools(tool_registry, subagent_manager)
    plugin_manager = PluginManager(
        config=config.plugins,
        workspace=Path(config.runtime.workspace),
        hook_bus=hook_registry,
        tool_registry=tool_registry,
        trajectory_store=trajectory_store,
    )
    reasoner = Reasoner(
        provider=provider,
        fallback_provider=fallback_provider,
        tool_registry=tool_registry,
        trajectory_store=trajectory_store,
        max_iterations=config.agent.max_iterations,
        max_elapsed_seconds=config.agent.max_elapsed_seconds,
        no_progress_limit=config.agent.no_progress_limit,
        model_name=provider_bundle.model_name,
        working_state=working_state if config.working_memory.enabled else None,
        hook_bus=hook_registry,
        stream_model=config.llm.stream,
    )
    session_manager = SessionManager(history_window=config.agent.history_window)
    context_builder = ContextBuilder(
        agent_name=config.agent.name,
        system_prompt=build_system_prompt(config.agent.name),
    )
    passive_turn_pipeline = PassiveTurnPipeline(
        session_manager=session_manager,
        context_builder=context_builder,
        reasoner=reasoner,
        memory_runtime=memory_runtime,
        memory_consolidator=None,
        hook_registry=hook_registry,
        working_state=working_state,
        trajectory_store=trajectory_store,
        skill_runtime=(skill_components.runtime if skill_components else None),
        tool_registry=tool_registry,
        mcp_names_provider=lambda: (
            set(mcp_manager.clients) if mcp_manager is not None else set()
        ),
    )
    runner = AgentRunner(passive_turn_pipeline=passive_turn_pipeline)
    agent_loop = AgentLoop(
        bus=bus,
        runner=runner,
        maintenance=(
            memory_runtime.maintenance_tick if memory_runtime is not None else None
        ),
    )
    proactive_loop = build_proactive_loop(config, bus, memory_runtime)
    return AppRuntime(
        config=config,
        bus=bus,
        agent_loop=agent_loop,
        tool_registry=tool_registry,
        runner=runner,
        memory_runtime=memory_runtime,
        plugin_manager=plugin_manager,
        proactive_loop=proactive_loop,
        mcp_manager=mcp_manager,
        trajectory_store=trajectory_store,
        working_state=working_state,
        hook_bus=hook_registry,
        subagent_manager=subagent_manager,
        skill_components=skill_components,
        model_provider=provider,
    )
