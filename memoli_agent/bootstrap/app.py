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
from memoli_agent.agent.mcp.registry import MCPClientManager
from memoli_agent.agent.memory.consolidator import MemoryConsolidator
from memoli_agent.agent.memory.runtime import MemoryRuntime
from memoli_agent.agent.loop import AgentLoop
from memoli_agent.agent.plugins.context import PluginContext
from memoli_agent.agent.plugins.decorators import HookRegistry
from memoli_agent.agent.plugins.manager import PluginManager
from memoli_agent.agent.proactive.loop import ProactiveLoop
from memoli_agent.agent.provider import EchoProvider, OpenAICompatibleProvider
from memoli_agent.agent.runner import AgentRunner
from memoli_agent.agent.session import SessionManager
from memoli_agent.bootstrap.channels import run_configured_channels
from memoli_agent.bootstrap.config import AppConfig
from memoli_agent.bootstrap.memory import build_memory_runtime
from memoli_agent.bootstrap.mcp import build_mcp_manager
from memoli_agent.bootstrap.proactive import build_proactive_loop
from memoli_agent.bootstrap.subagent import build_subagent_manager
from memoli_agent.bootstrap.tools import build_tool_registry
from memoli_agent.agent.tools.registry import ToolRegistry
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

    async def start(self) -> None:
        """启动后台服务。"""

        if self.plugin_manager is not None:
            await self.plugin_manager.initialize_plugins()
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
        if self.mcp_manager is not None:
            await self.mcp_manager.close_all()
        if self.plugin_manager is not None:
            await self.plugin_manager.terminate_plugins()


def build_app_runtime(config: AppConfig) -> AppRuntime:
    """根据配置创建应用运行时。"""

    bus = MessageBus()
    memory_runtime = build_memory_runtime(config)
    memory_consolidator = (
        MemoryConsolidator(memory_runtime.store) if memory_runtime is not None else None
    )
    hook_registry = HookRegistry()
    provider = _build_provider(config)
    fallback_provider = _build_fallback_provider(config)
    subagent_reasoner = Reasoner(
        provider=provider,
        fallback_provider=fallback_provider,
        tool_registry=None,
        max_tool_rounds=0,
    )
    subagent_manager = build_subagent_manager(config, bus, subagent_reasoner)
    tool_registry = build_tool_registry(
        config,
        memory_runtime,
        hook_registry,
        subagent_manager,
    )
    plugin_context = PluginContext(
        config=config,
        workspace=Path(config.runtime.workspace),
        tool_registry=tool_registry,
        memory_runtime=memory_runtime,
        hook_registry=hook_registry,
    )
    plugin_manager = PluginManager(
        enabled_plugins=config.plugins.enabled,
        context=plugin_context,
    )
    plugin_manager.load_enabled_plugins()
    plugin_manager.register_plugins()
    reasoner = Reasoner(
        provider=provider,
        fallback_provider=fallback_provider,
        tool_registry=tool_registry,
        max_tool_rounds=1,
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
        memory_consolidator=memory_consolidator,
        hook_registry=hook_registry,
    )
    runner = AgentRunner(passive_turn_pipeline=passive_turn_pipeline)
    agent_loop = AgentLoop(
        bus=bus,
        runner=runner,
    )
    proactive_loop = build_proactive_loop(config, bus, memory_runtime)
    mcp_manager = build_mcp_manager(config)
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
    )


def _build_provider(config: AppConfig) -> EchoProvider | OpenAICompatibleProvider:
    """根据配置创建主 provider。"""

    provider_name = config.llm.provider.strip().lower()
    if provider_name == "echo":
        return EchoProvider()

    if provider_name == "openai-compatible" and config.llm.api_key:
        return OpenAICompatibleProvider(
            model=config.llm.model,
            api_key=config.llm.api_key,
            base_url=config.llm.base_url or "https://api.openai.com/v1",
        )

    return EchoProvider()


def _build_fallback_provider(config: AppConfig) -> EchoProvider | None:
    """为真实模型配置 fallback provider。"""

    provider_name = config.llm.provider.strip().lower()
    if provider_name == "openai-compatible" and config.llm.api_key:
        return EchoProvider()
    return None
