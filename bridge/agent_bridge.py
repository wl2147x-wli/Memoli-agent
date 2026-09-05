"""
Agent Bridge - Integrates Agent system with existing COW bridge
"""

import os
import re
import threading
import uuid
from typing import Dict, Iterator, Optional, List, Tuple

from agent.protocol import (
    Agent,
    LLMModel,
    LLMRequest,
    get_cancel_registry,
    get_steer_registry,
)
from bridge.agent_event_handler import AgentEventHandler
from bridge.agent_initializer import AgentInitializer
from bridge.bridge import Bridge
from bridge.context import Context
from bridge.reply import Reply, ReplyType
from common import const
from common.log import logger
from common.utils import expand_path
from config import conf
from models.openai_compatible_bot import OpenAICompatibleBot


def add_openai_compatible_support(bot_instance):
    """
    Dynamically add OpenAI-compatible tool calling support to a bot instance.
    
    This allows any bot to gain tool calling capability without modifying its code,
    as long as it uses OpenAI-compatible API format.
    
    Note: Some bots like ZHIPUAIBot have native tool calling support and don't need enhancement.
    """
    if hasattr(bot_instance, 'call_with_tools'):
        # Bot 已经具备工具调用支持（例如 ZHIPUAIBot）
        logger.debug(f"[AgentBridge] {type(bot_instance).__name__} already has native tool calling support")
        return bot_instance

    # 创建一个临时 mixin 类，将机器人与 OpenAI 兼容性相结合
    class EnhancedBot(bot_instance.__class__, OpenAICompatibleBot):
        """Dynamically enhanced bot with OpenAI-compatible tool calling"""

        def get_api_config(self):
            """
            Infer API config from common configuration patterns.
            Most OpenAI-compatible bots use similar configuration.
            """
            from config import conf

            return {
                'api_key': conf().get("open_ai_api_key"),
                'api_base': conf().get("open_ai_api_base"),
                'model': conf().get("model") or const.DEFAULT_MODEL,
                'default_temperature': conf().get("temperature", 0.9),
                'default_top_p': conf().get("top_p", 1.0),
                'default_frequency_penalty': conf().get("frequency_penalty", 0.0),
                'default_presence_penalty': conf().get("presence_penalty", 0.0),
            }

    # 将机器人的类别更改为增强版本
    bot_instance.__class__ = EnhancedBot
    logger.info(
        f"[AgentBridge] Enhanced {bot_instance.__class__.__bases__[0].__name__} with OpenAI-compatible tool calling")

    return bot_instance


class AgentLLMModel(LLMModel):
    """
    LLM Model adapter that uses COW's existing bot infrastructure
    """

    _MODEL_BOT_TYPE_MAP = {
        "wenxin": const.BAIDU, "wenxin-4": const.BAIDU,
        "xunfei": const.XUNFEI, const.QWEN: const.QWEN_DASHSCOPE,
        const.QIANFAN: const.QIANFAN,
        const.MODELSCOPE: const.MODELSCOPE,
    }
    _MODEL_PREFIX_MAP = [
        ("qwen", const.QWEN_DASHSCOPE), ("qwq", const.QWEN_DASHSCOPE), ("qvq", const.QWEN_DASHSCOPE),
        ("gemini", const.GEMINI), ("glm", const.ZHIPU_AI), ("claude", const.CLAUDEAPI),
        ("moonshot", const.MOONSHOT), ("kimi", const.MOONSHOT),
        ("doubao", const.DOUBAO), ("deepseek", const.DEEPSEEK),
        ("ernie", const.QIANFAN),
        ("mimo-", const.MIMO),
    ]

    # 由哪个模型作答：按特异性从高到低依次取用。全部默认为 None，
    # 意思是“沿用下一级”，最终落到全局配置。声明在类上而不是
    # __init__ 里，这样解析模型永远不依赖 __init__ 是否运行过：
    # 每次调用都会重新读取这些字段，包括经 __new__ 构建的实例。
    #
    # 会话级：用户在单次对话中选择的模型。
    _session_model = None
    _session_provider = None
    # 代理级：来自该代理的档案。优先级低于会话选择、高于全局：
    # 按判断选定的代理，不应被控制台最后的设置喧宾夺主。
    # 默认代理没有代理级选择——它本身就是全局选择。
    _agent_model = None
    _agent_provider = None
    # 回退路由：主模型彻底失败后，由 use_fallback() 启用。
    # 在这里（而非 __init__ 中）声明，原因同上：`model` 每次调用
    # 都会重新读取，包括经 __new__ 构建的实例。
    _fallback_model = None
    _fallback_provider = None
    _fallback_depth = 0

    def __init__(self, bridge: Bridge, bot_type: str = "chat"):
        super().__init__(model=conf().get("model") or const.DEFAULT_MODEL)
        self.bridge = bridge
        self.bot_type = bot_type
        self._bot = None
        self._bot_model = None

    @property
    def model(self):
        # 已启用的回退优先于所有常规选择：一旦主模型失败，
        # 首要任务是继续给出回答，其它都靠后。
        if self._fallback_model:
            return self._fallback_model
        return (
            self._session_model
            or self._agent_model
            or conf().get("model")
            or const.DEFAULT_MODEL
        )

    @model.setter
    def model(self, value):
        pass

    def fallback_config(self) -> dict:
        """Return the configured chat fallback, normalized.

        A non-dict or disabled entry yields empty provider/model so callers can
        treat "not usable" as a single check.
        """
        raw = conf().get("chat_fallback")
        if not isinstance(raw, dict) or not raw.get("enabled"):
            return {"provider": "", "model": "", "max_switches": 0}
        try:
            max_switches = int(raw.get("max_switches") or 0)
        except (TypeError, ValueError):
            max_switches = 0
        return {
            "provider": (raw.get("provider") or "").strip(),
            "model": (raw.get("model") or "").strip(),
            "max_switches": max(0, max_switches),
        }

    def fallback_available(self) -> bool:
        """Whether this run can still switch to the fallback model."""
        if self._fallback_model:
            return False  # 已经在用后备了：后备对本次运行是“粘性”的
        cfg = self.fallback_config()
        if not cfg["provider"] or not cfg["model"]:
            return False  # 只配置了一半等同于“关闭”
        return self._fallback_depth < max(1, cfg["max_switches"])

    def use_fallback(self) -> bool:
        """Switch the rest of this run onto the configured fallback model.

        Returns True when the switch happened. Called after the primary model
        has failed a turn for good (retries exhausted), never mid-retry. The
        switch is sticky: once engaged, every remaining step of the run runs on
        the backup (``model`` returns ``_fallback_model``), so a sustained
        outage isn't re-probed on the primary once per step. reset_fallback()
        clears it at the start of the next run.
        """
        if not self.fallback_available():
            return False
        cfg = self.fallback_config()
        self._fallback_provider = cfg["provider"]
        self._fallback_model = cfg["model"]
        self._fallback_depth += 1
        # 丢弃缓存的主机器人；`bot` 会为新路由重新构建。
        self._bot = None
        self._bot_model = None
        self._bot_type = None
        logger.warning(
            "[AgentLLMModel] primary model failed; falling back to "
            f"{cfg['provider']}/{cfg['model']} (switch {self._fallback_depth})"
        )
        return True

    def reset_fallback(self) -> None:
        """Return to the primary model — call once at the start of a run.

        A new user message always starts fresh on the primary; within a run the
        fallback stays engaged (see use_fallback). Clearing the switch counter
        here — not mid-run — is what lets the *next* run fall back again, while
        bounding the current run to ``max_switches`` switches total.
        """
        if self._fallback_model is None:
            return
        self._fallback_model = None
        self._fallback_provider = None
        # 归零：下一次运行重新从主模型开始；若它再次失败，
        # 那是一次全新的失败，需要一次全新的切换。
        self._fallback_depth = 0
        self._bot = None
        self._bot_model = None
        self._bot_type = None

    def set_agent_default(self, provider: Optional[str], model: Optional[str]) -> None:
        """Pin the Agent's own model, under any per-conversation choice."""
        provider = (provider or "").strip() or None
        model = (model or "").strip() or None
        if provider == self._agent_provider and model == self._agent_model:
            return
        self._agent_provider = provider
        self._agent_model = model
        self._bot = None
        self._bot_model = None
        self._bot_type = None

    def set_session_override(self, provider: Optional[str], model: Optional[str]) -> None:
        """Pin this session to one model/provider, or clear it with None/None.

        The provider matters as much as the model: without it a session that
        switches from DeepSeek to Claude would keep routing through the globally
        configured bot type and ask DeepSeek for a Claude model.
        """
        provider = (provider or "").strip() or None
        model = (model or "").strip() or None
        if provider == self._session_provider and model == self._session_model:
            return
        self._session_provider = provider
        self._session_model = model
        # 强制在下次调用时为新路由重建惰性机器人。
        self._bot = None
        self._bot_model = None
        self._bot_type = None

    @staticmethod
    def provider_to_bot_type(provider_id: str) -> str:
        """Map a UI provider id onto a bot type, as the models console does."""
        if not provider_id:
            return ""
        # 模型控制台仍然保留相同的映射：“openai”通过
        # 与 OpenAI 兼容的机器人，而不是传统的完成机器人。
        if provider_id == "openai":
            return const.CHATGPT
        return provider_id

    def _resolve_bot_type(self, model_name: str) -> str:
        """Resolve bot type from model name, matching Bridge.__init__ logic."""
        # 会话覆盖胜过每个全局路由交换机，包括
        # use_linkai：用户为本次对话选择了该提供商。
        #
        # 回退的优先级甚至比会话选择还高：回退的目的就是
        # 离开刚失败的提供商，而且此时请求的模型
        # （`self.model`）本来就是后备自己的。
        if self._fallback_provider:
            return self.provider_to_bot_type(self._fallback_provider)
        if self._session_provider:
            return self.provider_to_bot_type(self._session_provider)
        if self._agent_provider:
            return self.provider_to_bot_type(self._agent_provider)

        if conf().get("use_linkai", False) and conf().get("linkai_api_key"):
            return const.LINKAI
        # 支持自定义机器人类型配置
        configured_bot_type = conf().get("bot_type")
        if configured_bot_type:
            return configured_bot_type
       
        if not model_name or not isinstance(model_name, str):
            return const.OPENAI
        if model_name in self._MODEL_BOT_TYPE_MAP:
            return self._MODEL_BOT_TYPE_MAP[model_name]
        if model_name.lower().startswith("minimax") or model_name in ["abab6.5-chat"]:
            return const.MiniMax
        if model_name in [const.QWEN_TURBO, const.QWEN_PLUS, const.QWEN_MAX]:
            return const.QWEN_DASHSCOPE
        if model_name in [const.MOONSHOT, "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"]:
            return const.MOONSHOT
        if conf().get("bot_type") == "modelscope":
            return const.MODELSCOPE
        lowered_model = model_name.lower()
        for prefix, btype in self._MODEL_PREFIX_MAP:
            if lowered_model.startswith(prefix):
                return btype
        return const.OPENAI

    def _normalized_reasoning_effort(self):
        """Return the active model's effort value after config resolution."""
        from models.reasoning_capabilities import resolve_reasoning_effort

        return resolve_reasoning_effort(
            self._resolve_bot_type(self.model),
            self.model,
            conf().get("reasoning_effort_by_model", {}),
            conf().get("reasoning_effort", "high"),
        )

    def _is_thinking_only_model(self) -> bool:
        """Return True for models that require reasoning to stay enabled."""
        from models.reasoning_capabilities import get_reasoning_capability

        capability = get_reasoning_capability(
            self._resolve_bot_type(self.model),
            self.model,
        )
        return bool(capability.get("thinking_only"))

    @property
    def bot(self):
        """Lazy load the bot, re-create when model or bot_type changes"""
        from models.bot_factory import create_bot
        cur_model = self.model
        cur_bot_type = self._resolve_bot_type(cur_model)
        if self._bot is None or self._bot_model != cur_model or getattr(self, '_bot_type', None) != cur_bot_type:
            self._bot = create_bot(cur_bot_type)
            self._bot = add_openai_compatible_support(self._bot)
            self._bot_model = cur_model
            self._bot_type = cur_bot_type
        return self._bot

    def call(self, request: LLMRequest):
        """
        Call the model using COW's bot infrastructure
        """
        try:
            # 对于非流式调用，我们将使用现有的回复方法
            # 这是一个简化的实现
            if hasattr(self.bot, 'call_with_tools'):
                # 如果可用，请使用支持工具的调用
                kwargs = {
                    'messages': request.messages,
                    'tools': getattr(request, 'tools', None),
                    'stream': False,
                    'model': self.model  # 传递模型参数
                }
                # 仅在显式设置时传递 max_tokens
                if request.max_tokens is not None:
                    kwargs['max_tokens'] = request.max_tokens

                # 提取系统提示（如果存在）
                system_prompt = getattr(request, 'system', None)
                if system_prompt:
                    kwargs['system'] = system_prompt

                # 将上下文元数据传递给机器人
                channel_type = getattr(self, 'channel_type', None) or ''
                if channel_type:
                    kwargs['channel_type'] = channel_type
                session_id = getattr(self, 'session_id', None)
                if session_id:
                    kwargs['session_id'] = session_id

                # 思维模式是独立于通道的全局开关。
                # IM 渠道（微信/企业微信/钉钉/飞书）虽不渲染
                # 推理过程，但答案质量仍会因思考而提升。
                from config import conf
                thinking_enabled = bool(conf().get("enable_thinking", False))
                # 一些原生推理模型不支持关闭思考，或只认
                # reasoning_effort 这一种控制手段，因此 UI 开关
                # 对它们不能照字面生效。
                if self._is_thinking_only_model():
                    thinking_enabled = True
                kwargs['thinking'] = (
                    {"type": "enabled"} if thinking_enabled
                    else {"type": "disabled"}
                )
                # reasoning_effort 只影响“怎么想”，不影响“想不想”。
                # 仅思考型模型仍会收到它，因为上面已强制 thinking_enabled。
                if thinking_enabled:
                    effort = self._normalized_reasoning_effort()
                    if effort:
                        kwargs['reasoning_effort'] = effort

                response = self.bot.call_with_tools(**kwargs)
                return self._format_response(response)
            else:
                # 回退到常规通话
                # 这需要根据您的具体需求来实施
                raise NotImplementedError("Regular call not implemented yet")
                
        except Exception as e:
            logger.error(f"AgentLLMModel call error: {e}")
            raise
    
    def call_stream(self, request: LLMRequest):
        """
        Call the model with streaming using COW's bot infrastructure
        """
        try:
            if hasattr(self.bot, 'call_with_tools'):
                # 如果可用，请使用支持工具的流式调用
                # 提取系统提示（如果存在）
                system_prompt = getattr(request, 'system', None)

                # 为 call_with_tools 构建 kwargs
                kwargs = {
                    'messages': request.messages,
                    'tools': getattr(request, 'tools', None),
                    'stream': True,
                    'model': self.model  # 传递模型参数
                }

                # 仅在显式设置时传递 max_tokens，让机器人使用其默认值
                if request.max_tokens is not None:
                    kwargs['max_tokens'] = request.max_tokens

                # 添加系统提示（如果有）
                if system_prompt:
                    kwargs['system'] = system_prompt

                # 将上下文元数据传递给机器人
                channel_type = getattr(self, 'channel_type', None) or ''
                if channel_type:
                    kwargs['channel_type'] = channel_type
                session_id = getattr(self, 'session_id', None)
                if session_id:
                    kwargs['session_id'] = session_id

                # 思维模式是独立于通道的全局开关。
                # IM 渠道（微信/企业微信/钉钉/飞书）虽不渲染
                # 推理过程，但答案质量仍会因思考而提升。
                from config import conf
                thinking_enabled = bool(conf().get("enable_thinking", False))
                # 流式与非流式调用要落在同一个提供商上：
                # 始终遵守思考型模型的这一约定。
                if self._is_thinking_only_model():
                    thinking_enabled = True
                kwargs['thinking'] = (
                    {"type": "enabled"} if thinking_enabled
                    else {"type": "disabled"}
                )
                # reasoning_effort 只影响“怎么想”，不影响“想不想”。
                # 仅思考型模型仍会收到它，因为上面已强制 thinking_enabled。
                if thinking_enabled:
                    effort = self._normalized_reasoning_effort()
                    if effort:
                        kwargs['reasoning_effort'] = effort

                stream = self.bot.call_with_tools(**kwargs)
                
                # 将流格式转换为我们期望的格式
                for chunk in stream:
                    yield self._format_stream_chunk(chunk)
            else:
                bot_type = type(self.bot).__name__
                raise NotImplementedError(f"Bot {bot_type} does not support call_with_tools. Please add the method.")
                
        except Exception as e:
            logger.error(f"AgentLLMModel call_stream error: {e}", exc_info=True)
            raise
    
    def _format_response(self, response):
        """Format Claude response to our expected format"""
        # 具体实现需按 Claude 的响应格式编写
        return response
    
    def _format_stream_chunk(self, chunk):
        """Format Claude stream chunk to our expected format"""
        # 这需要根据Claude的流格式来实现
        return chunk


class AgentBridge:
    """
    Bridge class that integrates super Agent with COW
    Manages multiple agent instances per session for conversation isolation
    """
    
    def __init__(self, bridge: Bridge):
        self.bridge = bridge
        from agent.registry import get_agent_registry
        from agent.routing import get_agent_router

        self.agent_registry = get_agent_registry()
        self.agent_router = get_agent_router(self.agent_registry)
        # 规范运行时映射。会话标识符仅在一个会话内是唯一的
        # 代理工作区，因此代理 ID 是每个实时密钥的一部分。
        self._agent_instances: Dict[Tuple[str, str], Agent] = {}
        self._default_agents: Dict[str, Agent] = {}
        self._agents_lock = threading.RLock()
        # 用于检查会话的集成的向后兼容视图
        # 直接配置的默认代理。
        self.agents: Dict[str, Agent] = {}
        self.default_agent = None
        self.agent: Optional[Agent] = None
        self.scheduler_initialized = False
        self.scheduler_agent_ids = set()
        
        # 创建辅助实例
        self.initializer = AgentInitializer(bridge, self)

        # 立即启动调度程序，以便 cron 任务无需等待即可触发
        # 对于第一条用户消息。 init_scheduler 是幂等的。
        try:
            from agent.tools.scheduler.integration import init_scheduler
            for profile in self.agent_registry.list(include_disabled=False):
                if init_scheduler(self, profile.workspace, profile.id):
                    self.scheduler_agent_ids.add(profile.id)
            self.scheduler_initialized = bool(self.scheduler_agent_ids)
        except Exception as e:
            logger.warning(f"[AgentBridge] Eager scheduler init failed: {e}")

        # 启动自演化空闲触发器（幂等、守护线程）。
        try:
            from agent.evolution.trigger import start_evolution_trigger
            start_evolution_trigger(self)
        except Exception as e:
            logger.warning(f"[AgentBridge] Evolution trigger init failed: {e}")

    def create_agent(self, system_prompt: str, tools: List = None, **kwargs) -> Agent:
        """
        Create the super agent with COW integration
        
        Args:
            system_prompt: System prompt
            tools: List of tools (optional)
            **kwargs: Additional agent parameters
            
        Returns:
            Agent instance
        """
        # 创建使用 COW 机器人基础设施的 LLM 模型
        model = AgentLLMModel(self.bridge)
        
        # 如果没有提供默认工具
        if tools is None:
            # 使用 ToolManager 加载所有可用工具
            from agent.tools import ToolManager
            tool_manager = ToolManager()
            tool_manager.load_tools()
            
            tools = []
            workspace_dir = kwargs.get("workspace_dir")
            for tool_name in tool_manager.tool_classes.keys():
                try:
                    tool = tool_manager.create_tool(tool_name)
                    if tool:
                        if workspace_dir:
                            tool.cwd = workspace_dir
                        tools.append(tool)
                except Exception as e:
                    logger.warning(f"[AgentBridge] Failed to load tool {tool_name}: {e}")
        
        # 创建代理实例
        agent = Agent(
            system_prompt=system_prompt,
            description=kwargs.get("description", "AI Super Agent"),
            model=model,
            tools=tools,
            max_steps=kwargs.get("max_steps", 15),
            output_mode=kwargs.get("output_mode", "logger"),
            workspace_dir=kwargs.get("workspace_dir"),
            skill_manager=kwargs.get("skill_manager"),
            enable_skills=kwargs.get("enable_skills", True),
            memory_manager=kwargs.get("memory_manager"),
            max_context_tokens=kwargs.get("max_context_tokens"),
            context_reserve_tokens=kwargs.get("context_reserve_tokens"),
            runtime_info=kwargs.get("runtime_info"),
        )

        # 记录技能加载详细信息
        if agent.skill_manager:
            logger.debug(f"[AgentBridge] SkillManager initialized with {len(agent.skill_manager.skills)} skills")

        return agent
    
    def steer_session(self, session_id: str, instruction: str, agent_id: str = None):
        """Inject an explicit instruction into one active session."""
        logger.info(f"[AgentBridge] steer new instruction: session={session_id}, content={instruction}")
        return get_steer_registry().submit(
            self.scoped_session_key(session_id, agent_id), instruction
        )

    def _resolve_agent_id(self, agent_id: str = None) -> str:
        return self.agent_registry.get(agent_id).id

    def scoped_session_key(self, session_id: str, agent_id: str = None) -> str:
        """Namespace a session id by its agent.

        Session ids are only unique within one Agent, so cancel and steer
        lookups must be scoped or a /cancel in one Agent's chat would abort a
        different Agent's run that happens to share the id.
        """
        return self._cancel_key(
            self._resolve_agent_id(agent_id),
            session_id,
            self.agent_registry.default_agent_id,
        )

    def route_context(self, context: Context) -> str:
        """Resolve and attach the workspace selected for an inbound context."""
        return self.agent_router.resolve_context(context)

    def get_conversation_store(self, agent_id: str = None):
        """Return the session store owned by one agent workspace."""
        profile = self.agent_registry.get(agent_id)
        from agent.memory import get_conversation_store
        return get_conversation_store(profile.workspace)

    def _seed_team_members(self, session_id: str, host_agent_id: str, context: Context = None) -> None:
        """Project a team bot's fixed roster onto the session, once.

        A channel instance configured with ``members`` is a fixed team: its
        owner (``host_agent_id``) plus teammates it may delegate to. The rest of
        the stack learns a conversation is a team from
        ``session_prefs.members``, so the instance roster is copied there the
        first time a message arrives on a session that has none yet.

        Only seeds when the session has no roster of its own, so a per-session
        edit (Web) is never clobbered; and only for enabled teammates other than
        the owner, matching how a Web team is stored.

        A delegated turn runs in its own private session that carries no roster;
        the original team travels with it as ``delegation_members`` instead, so
        seeding from that lets a teammate delegate onward to the same team.
        """
        if not session_id or not context:
            return
        members = (
            context.get("members")
            or context.kwargs.get("members")
            or context.get("delegation_members")
            or context.kwargs.get("delegation_members")
        )
        if not members:
            return
        try:
            from agent.workspace import session_prefs

            if session_prefs.get_prefs(session_id, host_agent_id).get("members"):
                return  # 群聊已有自己的名册；保持不变即可
            cleaned = []
            for mid in members:
                mid = str(mid or "").strip()
                if not mid or mid == host_agent_id or mid in cleaned:
                    continue
                try:
                    self.agent_registry.get(mid, require_enabled=True)
                except Exception:
                    continue  # 跳过未知/已停用的队友
                cleaned.append(mid)
            if cleaned:
                session_prefs.set_prefs(session_id, host_agent_id, members=cleaned)
                logger.info(
                    f"[AgentBridge] Seeded team roster {cleaned} onto session "
                    f"'{session_id}' owned by {host_agent_id}"
                )
        except Exception as e:
            logger.debug(f"[AgentBridge] _seed_team_members failed: {e}")

    def _resolve_speaker(self, host_agent_id: str, context: Context = None) -> str:
        """Pick who answers this turn: the conversation's owner, or a teammate
        the user addressed by name.

        Naming someone is an instruction about who should answer, so it is
        honoured literally. Anything unrecognised, disabled, or already the
        owner falls back to the owner, which is the single-Agent behaviour.
        """
        named = (context.get("speaker_agent_id") if context else "") or ""
        if not named or named == host_agent_id:
            return host_agent_id
        try:
            profile = self.agent_registry.get(named, require_enabled=True)
        except Exception:
            logger.warning(
                f"[AgentBridge] Ignoring unknown addressee '{named}', "
                f"answering as {host_agent_id}"
            )
            return host_agent_id
        logger.info(
            f"[AgentBridge] Turn addressed to {profile.id}; "
            f"answering in {host_agent_id}'s conversation"
        )
        return profile.id

    def _strip_address(self, query: str, speaker_agent_id: str) -> str:
        """Drop the leading "@name" now that it has been acted on.

        Routing already answered the question the mention was asking, so
        leaving it in makes the Agent read its own name as someone else's and
        reply about that person instead of as itself. It only ever comes off
        the front, and only for the Agent it named.

        The transcript keeps the original: the mention is what the user wrote,
        and it records who the turn was aimed at.
        """
        if not query:
            return query
        try:
            profile = self.agent_registry.get(speaker_agent_id, require_enabled=False)
        except Exception:
            return query
        labels = [label for label in (profile.name, profile.id) if label]
        pattern = (
            r"^\s*@(?:"
            + "|".join(re.escape(label) for label in sorted(labels, key=len, reverse=True))
            + r")[\s,，:：、]*"
        )
        stripped = re.sub(pattern, "", query, count=1, flags=re.IGNORECASE)
        # 只有一个称呼、后面再无内容时（例如仅“@Ops”），
        # 表达的其实是“你来说话”——因此保留原文返回，
        # 而不是把称呼剥掉后让代理空转。
        return stripped if stripped.strip() else query

    @staticmethod
    def _attribute_to_speaker(messages: list, speaker_agent_id: str) -> list:
        """Tag a guest's turns with who wrote them, for the transcript.

        A shared conversation that records no author replays as one voice, so a
        reload loses track of who said what.

        Returns copies. The dicts handed in are the Agent's live context, and
        ``extras`` is a column of ours: annotating them in place would put an
        unknown key on every later request and the model rejects the call.
        """
        return [
            {
                **message,
                "extras": {
                    **(message.get("extras") or {}),
                    "agent_id": speaker_agent_id,
                },
            }
            for message in messages or []
        ]

    def _begin_run(self, session_id: str, agent_id: str, context: Context = None):
        """Open a run for this turn and make its id the ambient one.

        Returns ``(run_id, token, store)``; every element is None when the run
        could not be recorded. Bookkeeping must never break a reply, so any
        failure here degrades to "no run row" rather than raising: the turn
        still runs, it just is not addressable afterwards.

        A run id already in scope means this turn was started by another run
        (a delegation or a spawn), so that one becomes the parent and the tree
        stays walkable from either end. A caller that hands work to another
        thread cannot rely on that ambient id, since context variables do not
        cross threads, so it may instead name the run and its parent through
        the context and keep the tree intact.
        """
        from common.utils import current_agent_run_id, set_agent_run_id

        try:
            parent_run_id = str(
                (context.get("parent_run_id") if context else "")
                or current_agent_run_id()
                or ""
            )
            run_id = str((context.get("run_id") if context else "") or "") or uuid.uuid4().hex
            store = self.get_conversation_store(agent_id)
            # 驱动本次运行的外部系统（调度器/推送）通过上下文
            # 传入自己的标识；本地对话轮次则两者皆为空。
            task_id = str((context.get("task_id") if context else "") or "")
            task_source = str((context.get("task_source") if context else "") or "")
            store.create_run(
                run_id,
                agent_id=agent_id or "",
                session_id=session_id or "",
                parent_run_id=parent_run_id,
                task_id=task_id,
                task_source=task_source,
            )
            # 最后设置：一旦环境 ID 发生变化，调用者就需要重置。
            token = set_agent_run_id(run_id)
            return run_id, token, store
        except Exception as e:
            logger.warning(f"[AgentBridge] Could not open run: {e}")
            return None, None, None

    def _end_run(self, store, run_id: str, token, status: str, error: str = "") -> None:
        """Close a run and restore the previous ambient run id.

        The reset happens even when the status update fails, or the ambient id
        would leak into whatever this thread handles next.
        """
        from common.utils import clear_agent_run_id

        try:
            if store is not None and run_id:
                store.finish_run(run_id, status=status, error=error)
        except Exception as e:
            logger.warning(f"[AgentBridge] Could not close run {run_id}: {e}")
        finally:
            if token is not None:
                clear_agent_run_id(token)

    @staticmethod
    def _runtime_key(agent_id: str, session_id: str) -> Tuple[str, str]:
        return agent_id, session_id

    @staticmethod
    def _cancel_key(agent_id: str, token: str, default_agent_id: str) -> str:
        """Keep legacy token keys for the default agent, namespace the rest."""
        return token if agent_id == default_agent_id else f"{agent_id}::{token}"

    def get_agent(
        self,
        session_id: str = None,
        agent_id: str = None,
        host_agent_id: str = None,
    ) -> Optional[Agent]:
        """
        Get agent instance for the given session
        
        Args:
            session_id: Session identifier (e.g., user_id). If None, returns
                the workspace's default runtime instance.
            agent_id: Agent profile identifier. Omit for the configured default.
            host_agent_id: Agent that owns this conversation, when it is not
                ``agent_id``. Set when the user addressed a teammate directly:
                the teammate answers as itself, but reads and continues the
                host's transcript instead of starting a private one.
        
        Returns:
            Agent instance for this session
        """
        resolved_agent_id = self._resolve_agent_id(agent_id)
        with self._agents_lock:
            if session_id is None:
                agent = self._default_agents.get(resolved_agent_id)
                if agent is None:
                    agent = self.initializer.initialize_agent(
                        session_id=None, agent_id=resolved_agent_id
                    )
                    self._default_agents[resolved_agent_id] = agent
                if resolved_agent_id == self.agent_registry.default_agent_id:
                    self.default_agent = agent
                return agent

            host_id = self._resolve_agent_id(host_agent_id or resolved_agent_id)
            key = self._runtime_key(resolved_agent_id, session_id)
            agent = self._agent_instances.get(key)
            if agent is None:
                agent = self.initializer.initialize_agent(
                    session_id=session_id,
                    agent_id=resolved_agent_id,
                    host_agent_id=host_id,
                )
                self._agent_instances[key] = agent
                if resolved_agent_id == self.agent_registry.default_agent_id:
                    self.agents[session_id] = agent
            # 将工作目录指向会话的项目（如果有）。
            # 应用于每次获取，因此切换项目 - 或返回到
            # default — 对下一条消息生效而不重建
            # 代理。无论如何，记忆/技能都会固定在工作空间上。
            # 项目和每会话设置都属于对话：访客跟随对话主人，
            # 而不会带入自己名下无关的设置。
            self._apply_session_project(agent, session_id, host_id)
            # 会话的权限模式的想法相同，每个对话
            # 覆盖回落到全局配置。型号不是
            # 与访客共享 — 请参阅 apply_session_prefs。
            self.apply_session_prefs(
                agent,
                session_id,
                host_id,
                owns_conversation=resolved_agent_id == host_id,
            )
            return agent

    def _apply_session_project(self, agent, session_id: str, agent_id: str) -> None:
        """Retarget the agent's working directory to the session's project dir.

        A no-op when the session has no project selected (clears any previous
        override). Failures are swallowed: a bad project setting must not break
        the chat, it just falls back to the default workspace.
        """
        try:
            from agent.workspace import project_store
            project_dir = project_store.get_project_dir(session_id, agent_id)
            if getattr(agent, "apply_project_dir", None):
                agent.apply_project_dir(project_dir)
        except Exception as e:
            logger.debug(f"[AgentBridge] apply_session_project failed: {e}")

    def apply_session_prefs(
        self, agent, session_id: str, agent_id: str = None, owns_conversation: bool = True
    ) -> None:
        """Apply a session's model / permission overrides to its agent.

        Called on every agent fetch and right after the user changes a setting,
        so a switch takes effect on the next message without rebuilding the
        agent. An empty override resets the agent to the global config, which is
        what makes "follow global" work after a session had pinned something.

        The model is the exception on two counts. A conversation's pinned model
        belongs to the Agent that owns it, so an invited teammate is never
        forced onto it — that would throw away the model it was configured with,
        often the reason it was invited. And in a group chat nobody follows the
        pin, the owner included: a team is a set of Agents each answering on its
        own model, so the pinned model (a single-chat notion) is ignored and
        every speaker uses its own default. Permission stays shared either way,
        because it bounds what this conversation may change regardless of who is
        speaking.
        """
        if agent is None or not session_id:
            return
        try:
            from agent.workspace import session_prefs

            prefs = session_prefs.get_prefs(session_id, agent_id)
            model = getattr(agent, "model", None)
            if model is not None and hasattr(model, "set_session_override"):
                # 有成员参与的对话就是群聊：每个代理都用
                # 自己配置的模型作答，因此会话级模型覆盖不生效。
                is_group = bool(prefs.get("members"))
                if owns_conversation and not is_group:
                    model.set_session_override(prefs.get("provider"), prefs.get("model"))
                else:
                    model.set_session_override(None, None)
            if hasattr(agent, "apply_permission_mode"):
                agent.apply_permission_mode(prefs.get("permission"))
        except Exception as e:
            logger.debug(f"[AgentBridge] apply_session_prefs failed: {e}")

    def get_cached_agent(self, session_id: str, agent_id: str = None) -> Optional[Agent]:
        """Return an existing session agent without creating one."""
        resolved_agent_id = self._resolve_agent_id(agent_id)
        with self._agents_lock:
            return self._agent_instances.get(
                self._runtime_key(resolved_agent_id, session_id)
            )

    def iter_agent_instances(
        self, include_defaults: bool = True
    ) -> Iterator[Tuple[str, Optional[str], Agent]]:
        """Snapshot all live instances as ``(agent_id, session_id, agent)``."""
        with self._agents_lock:
            defaults = list(self._default_agents.items()) if include_defaults else []
            sessions = list(self._agent_instances.items())
        for agent_id, agent in defaults:
            yield agent_id, None, agent
        for (agent_id, session_id), agent in sessions:
            yield agent_id, session_id, agent

    def sync_session_messages_from_store(
        self, session_id: str, agent_id: str = None
    ) -> int:
        """Reload an agent's in-memory ``messages`` list from the persistent
        conversation store.

        Used after an external mutation (e.g. user edits / deletes a message
        via the web console) so the agent's next turn sees the same history
        as the database. The operation is a no-op when the agent has not been
        instantiated yet for the session.

        Tool blocks are stripped exactly as on session restore. Deleting a
        message can orphan a tool_use from its tool_result, and replaying that
        pair would make the provider reject the next request.

        Returns:
            Number of messages now held in the agent's memory. Returns -1 if
            the agent does not exist or has no compatible ``messages`` attr.
        """
        if not session_id:
            return -1
        agent = self.get_cached_agent(session_id, agent_id=agent_id)
        if agent is None:
            return -1
        if not (hasattr(agent, "messages") and hasattr(agent, "messages_lock")):
            return -1
        try:
            store = self.get_conversation_store(agent_id)
            # 这里刻意不设上限：要如实镜像删除发生后，
            # 存储里该会话的剩余内容。
            remaining = store.load_messages(session_id, max_turns=10**6)
        except Exception as e:
            logger.warning(
                f"[AgentBridge] Failed to load messages for sync (session={session_id}): {e}"
            )
            return -1
        remaining = AgentInitializer._filter_text_only_messages(remaining)
        with agent.messages_lock:
            agent.messages.clear()
            for msg in remaining:
                agent.messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })
            count = len(agent.messages)
        logger.info(
            f"[AgentBridge] Synced agent memory for session={session_id}, messages={count}"
        )
        return count

    def agent_reply(self, query: str, context: Context = None, 
                   on_event=None, clear_history: bool = False) -> Reply:
        """
        Use super agent to reply to a query
        
        Args:
            query: User query
            context: COW context (optional, contains session_id for user isolation)
            on_event: Event callback (optional)
            clear_history: Whether to clear conversation history
            
        Returns:
            Reply object
        """
        session_id = None
        agent_id = None
        agent = None
        request_id = None
        cancel_event = None
        token_key = None
        steer_inbox = None
        run_id = None
        run_token = None
        run_store = None
        run_status = "done"
        run_error = ""
        try:
            # 从上下文中提取 session_id 以进行用户隔离
            if context:
                session_id = context.kwargs.get("session_id") or context.get("session_id")
                request_id = context.kwargs.get("request_id") or context.get("request_id")

            resolved_agent_id = (
                self.route_context(context)
                if context is not None
                else self.agent_registry.default_agent_id
            )

            # 团队频道机器人（例如配置了成员的飞书实例）会在
            # 每条入站消息上携带名册。第一次见到该对话时把它
            # 落成会话偏好，这样共享的委托/@提及机制
            # （读取 session_prefs.members）就能把它当作
            # 一个团队处理，与 Web 团队对话一致。
            self._seed_team_members(session_id, resolved_agent_id, context)

            # 点名队友会把本轮直接交给该队友作答。
            # 对话仍归属 `resolved_agent_id`，因此转录、运行
            # 和队列都留在同一处——只是这一轮换了个声音回答。
            speaker_agent_id = self._resolve_speaker(resolved_agent_id, context)
            # 代理一多（尤其是绑定了多个通道实例时），仅凭日志
            # 看不出消息被路由给了谁。这里输出一行，写明目标代理，
            # 以及（如果有的话）消息到达的通道实例。单代理配置
            # 直接跳过，避免日志噪音。
            try:
                if len(self.agent_registry.list()) > 1:
                    instance_id = (
                        context.get("instance_id")
                        or context.kwargs.get("instance_id")
                        if context is not None else ""
                    )
                    via = f" | {instance_id}" if instance_id else ""
                    # 真正作答这一轮的代理是“说话者”：用户点名
                    # 队友时，它与对话所有者不同。记录说话者，
                    # 让日志与实际回复者对应；当它与所有者不同时
                    # 也一并记下对话所有者，保证路由+称呼两条
                    # 日志口径一致。
                    speaker = self.agent_registry.get(speaker_agent_id)
                    if speaker_agent_id != resolved_agent_id:
                        owner = self.agent_registry.get(resolved_agent_id)
                        logger.info(
                            f"[Routing] → 🤖 {speaker.name}({speaker.id}) "
                            f"in {owner.name}({owner.id})'s conversation{via}"
                        )
                    else:
                        logger.info(
                            f"[Routing] → 🤖 {speaker.name}({speaker.id}){via}"
                        )
            except Exception:
                pass
            # 一旦地址被执行，代理将被询问什么。
            # 与 `query` 分开，逐字保留转录本。
            model_query = (
                self._strip_address(query, speaker_agent_id)
                if speaker_agent_id != resolved_agent_id
                else query
            )

            # 注册取消令牌：优先用每轮独立的 request_id（Web），
            # 否则退回 session_id（IM 渠道）。取消事件由
            # AgentStreamExecutor 位于安全检查点。
            registry = get_cancel_registry()
            token_key = request_id or session_id
            if token_key:
                token_key = self._cancel_key(
                    resolved_agent_id,
                    token_key,
                    self.agent_registry.default_agent_id,
                )
                scoped_session_id = self._cancel_key(
                    resolved_agent_id,
                    session_id,
                    self.agent_registry.default_agent_id,
                )
                cancel_event = registry.register(
                    token_key, session_id=scoped_session_id
                )

            # 获取此会话的代理（如果需要，将自动初始化）
            agent = self.get_agent(
                session_id=session_id,
                agent_id=speaker_agent_id,
                host_agent_id=resolved_agent_id,
            )
            if not agent:
                return Reply(ReplyType.ERROR, "Failed to initialize super agent")
            
            # 创建用于日志记录和通道通信的事件处理程序
            event_handler = AgentEventHandler(context=context, original_callback=on_event)
            
            # 根据上下文过滤工具
            original_tools = agent.tools
            filtered_tools = original_tools
            
            # 如果这是计划任务执行，请排除计划程序工具以防止递归
            if context and context.get("is_scheduled_task"):
                filtered_tools = [tool for tool in agent.tools if tool.name != "scheduler"]
                agent.tools = filtered_tools
                logger.info(f"[AgentBridge] Scheduled task execution: excluded scheduler tool ({len(filtered_tools)}/{len(original_tools)} tools)")

            if context and agent.tools:
                for tool in agent.tools:
                    if tool.name == "scheduler" and not context.get("is_scheduled_task"):
                        try:
                            from agent.tools.scheduler.integration import attach_scheduler_to_tool
                            attach_scheduler_to_tool(tool, context)
                        except Exception as e:
                            logger.warning(f"[AgentBridge] Failed to attach context to scheduler: {e}")
                    elif tool.name == "agent_delegate":
                        try:
                            from agent.tools.agent_delegate.agent_delegate import attach_agent_delegate_to_tool
                            attach_agent_delegate_to_tool(tool, self, context)
                        except Exception as e:
                            logger.warning(f"[AgentBridge] Failed to attach delegation context: {e}")
            
            # 将上下文元数据传递给下游 API 请求的模型
            if context and hasattr(agent, 'model'):
                agent.model.channel_type = context.get("channel_type", "")
                agent.model.session_id = session_id or ""
                agent.model.agent_id = speaker_agent_id

            # 将 session_id 存储在代理上，以便执行器可以在发生致命错误时清除数据库。
            # 对话所有者决定记录归属：这样即使由嘉宾代答，
            # 读写的仍是同一份共享内容。
            agent._current_session_id = session_id
            agent._current_agent_id = resolved_agent_id

            # 每次运行前先压缩调度器会话的内存上下文。
            # 调度器会话按任务固定、每次触发都会追加内容，
            # 不做修剪就会无限增长，把即时成本越推越高。
            # 常规用户聊天不走这里——那条路由代理自己的
            # 上下文管理器负责。
            if session_id and session_id.startswith("scheduler_"):
                from config import conf
                scheduler_keep_turns = max(
                    1, int(conf().get("agent_max_context_turns", 20)) // 5
                )
                self._trim_in_memory_to_turns(agent, scheduler_keep_turns)

            # 在任何内容落库之前先开启运行记录：这样用户消息、
            # 回复都能归属到它名下，而且运行尚在进行时
            # 就已经可以被寻址/取消。
            run_id, run_token, run_store = self._begin_run(
                session_id, resolved_agent_id, context
            )

            # 在运行代理之前急切地保留用户消息，以便
            # 会话和用户的气泡立即可见 - 即使
            # 用户在回复完成之前离开或刷新。
            # 运行后会附加回复（助手/工具消息）
            # 完成；最后的持久化会跳过这个已经存储的用户回合。
            pre_persisted = self._pre_persist_user_message(
                session_id, query, context, clear_history, resolved_agent_id
            )

            # 把该会话标记为运行中：这样自我演化空闲扫描就不会
            # 在单轮运行时间超过空闲阈值时，
            # 与演化评审并发插入。
            try:
                from agent.evolution.trigger import mark_run_active
                mark_run_active(agent, True)
            except Exception:
                pass

            try:
                if session_id:
                    steer_inbox = get_steer_registry().register(session_id)
                # 将代理的 run_stream 方法与事件处理程序结合使用
                response = agent.run_stream(
                    user_message=model_query,
                    on_event=event_handler.handle_event,
                    clear_history=clear_history,
                    cancel_event=cancel_event,
                    steer_inbox=steer_inbox,
                    # 计划任务可能没有任何可报告的内容
                    # （例如“仅在价格下降时通知我”）。没有人是
                    # 等待这次运行，所以空答案保持空，并且
                    # 调度程序根本不发送任何消息。
                    allow_empty_response=bool(context and context.get("is_scheduled_task")),
                )
            finally:
                # 清除中间运行标志，以便空闲扫描可以查看此会话。
                try:
                    from agent.evolution.trigger import mark_run_active
                    mark_run_active(agent, False)
                except Exception:
                    pass

                # 恢复原来的工具
                if context and context.get("is_scheduled_task"):
                    agent.tools = original_tools

                # 日志执行总结
                event_handler.log_summary()

                # 释放取消令牌；保持注册表受限制。
                if token_key:
                    try:
                        registry.unregister(token_key)
                    except Exception:
                        pass
                if session_id and steer_inbox is not None:
                    get_steer_registry().unregister(session_id, steer_inbox)

            # 被取消的轮次不算失败，但也不算完整运行：
            # 这个区分是为了告诉读历史的人，结果到底是
            # 可信的、还是压根不存在。
            if cancel_event is not None and cancel_event.is_set():
                run_status = "cancelled"

            # 保留本次运行期间生成的新消息
            if session_id:
                channel_type = (context.get("channel_type") or "") if context else ""
                new_messages = list(getattr(agent, '_last_run_new_messages', []))
                # 开头的用户消息已在上面抢先持久化过；
                # 这里跳过它，避免存两份。
                if pre_persisted and new_messages and new_messages[0].get("role") == "user":
                    new_messages = new_messages[1:]
                # 给每条回复盖上作者标记，包括所有者自己的。
                # 共享对话里的嘉宾要靠这枚“印章”重建“谁说了什么”：
                # 如果所有者的发言没盖章，重载后就会变成无来源文本，
                # 嘉宾会误把这些话当成自己的角色设定
                # （“我是格雷……”），并用那个口吻回答。
                new_messages = self._attribute_to_speaker(
                    new_messages, speaker_agent_id
                )
                if new_messages:
                    self._persist_messages(
                        session_id,
                        list(new_messages),
                        channel_type,
                        resolved_agent_id,
                        create_if_missing=not pre_persisted,
                    )
            
            # 记录此用户轮次以进行自我进化空闲触发。跳过
            # 调度程序注入/计划任务会话，因此内部运行
            # 不计为用户活动。
            if session_id and not session_id.startswith("scheduler_") and not (
                context and (
                    context.get("is_scheduled_task")
                    or context.get("is_delegated_task")
                )
            ):
                try:
                    from agent.evolution.trigger import note_user_turn
                    ch = (context.get("channel_type") or "") if context else ""
                    rcv = (context.get("receiver") or "") if context else ""
                    is_group = bool(context.get("isgroup")) if context else False
                    # 只对单聊做主动推送（群聊推送太吵）；
                    # 群聊中的演化照常进行，只是不发通知。
                    note_user_turn(agent, channel_type=ch, receiver=(rcv if not is_group else ""))
                except Exception:
                    pass

            # 消息后热重载：检测对 ~/cow/mcp.json 的编辑和
            # 将任何新的/删除的 MCP 工具同步到实时代理中
            # 背景。远离关键路径，因此用户延迟不受影响；
            # 更改将在用户的下一条消息时生效。
            self._schedule_mcp_hot_reload(agent)

            # 检查是否有文件要发送（通过发送/读取工具）
            if hasattr(agent, 'stream_executor') and hasattr(agent.stream_executor, 'files_to_send'):
                files_to_send = agent.stream_executor.files_to_send
                if files_to_send:
                    logger.info(
                        f"[AgentBridge] Sending {len(files_to_send)} file(s), "
                        f"first={files_to_send[0].get('path')}"
                    )

                    # 清除下一个请求的 files_to_send
                    agent.stream_executor.files_to_send = []

                    # 回复管道携带一个回复，因此剩余的
                    # 文件会一直传送，然后通道会发送它们。
                    # 只有第一个带有文本，否则会重复。
                    reply = self._create_file_reply(files_to_send[0], response, context)
                    extras = [
                        self._create_file_reply(f, "", context)
                        for f in files_to_send[1:]
                    ]
                    if extras:
                        reply.extra_replies = extras
                    return reply
            
            return Reply(ReplyType.TEXT, response)
            
        except Exception as e:
            logger.error(f"Agent reply error: {e}")
            run_status = "failed"
            run_error = str(e)
            # 内存中的上下文可能为了从格式错误/溢出中恢复而被重置过，
            # 但存储的历史刻意原样保留：它不可重建，且重新装载时
            # 本来就会剥掉工具块。这里也在错误路径上释放取消令牌（幂等）。
            if cancel_event is not None and token_key:
                try:
                    get_cancel_registry().unregister(token_key)
                except Exception:
                    pass
            if session_id and steer_inbox is not None:
                try:
                    get_steer_registry().unregister(session_id, steer_inbox)
                except Exception:
                    pass
            return Reply(ReplyType.ERROR, f"Agent error: {str(e)}")

        finally:
            self._end_run(run_store, run_id, run_token, run_status, run_error)
    
    def _schedule_mcp_hot_reload(self, agent):
        """
        Fire-and-forget: detect mcp.json edits and reconcile the agent's
        tool dict in the background. Runs after the user's reply is sent,
        so any cost (file stat, hash, server boot) never adds to user latency.
        Failures are isolated and never raise into the message pipeline.
        """
        import threading
        from agent.tools import ToolManager
        from common.runtime_identity import wrap

        def _run():
            try:
                tm = ToolManager()
                tm.refresh_mcp_if_changed()
                added, removed = tm.sync_mcp_into_agent(agent)
                if added or removed:
                    logger.info(
                        f"[AgentBridge] Agent tools synced — "
                        f"added={added}, removed={removed}"
                    )
            except Exception as e:
                logger.warning(f"[AgentBridge] MCP hot-reload failed (non-fatal): {e}")

        # 包装层把路由身份带进线程；否则这里会去重载默认代理的
        # mcp.json，并把工具同步到错误的代理身上，而不是
        # 实际发消息的那个代理。
        threading.Thread(
            target=wrap(_run), daemon=True, name="mcp-hot-reload"
        ).start()

    def _create_file_reply(self, file_info: dict, text_response: str, context: Context = None) -> Reply:
        """
        Create a reply for sending files
        
        Args:
            file_info: File metadata from read tool
            text_response: Text response from agent
            context: Context object
            
        Returns:
            Reply object for file sending
        """
        file_type = file_info.get("file_type", "file")
        file_path = file_info.get("path")
        # 远程 URL 按原样传递；本地路径有一个 file:// 前缀
        # 这样通道就可以从磁盘读取它们。
        remote_url = file_info.get("url", "")
        is_remote = bool(remote_url) and remote_url.lower().startswith(("http://", "https://"))

        def _to_channel_url(p: str) -> str:
            if is_remote:
                return remote_url
            if p and p.lower().startswith(("http://", "https://")):
                return p
            return f"file://{p}"

        # 对于图像，使用 IMAGE_URL 类型（通道将处理上传）
        if file_type == "image":
            file_url = _to_channel_url(file_path)
            logger.info(f"[AgentBridge] Sending image: {file_url}")
            reply = Reply(ReplyType.IMAGE_URL, file_url)
            # 附加文本消息（如果存在）（适用于支持文本+图像的频道）
            if text_response:
                reply.text_content = text_response  # 存储附带文本
            return reply
        
        # 对于所有文件类型（文档、视频、音频），请使用 FILE 类型
        if file_type in ["document", "video", "audio"]:
            file_url = _to_channel_url(file_path)
            logger.info(f"[AgentBridge] Sending {file_type}: {file_url}")
            reply = Reply(ReplyType.FILE, file_url)
            reply.file_name = file_info.get("file_name", os.path.basename(file_path))
            # 附上短信（如果有）
            if text_response:
                reply.text_content = text_response
            return reply
        
        # 对于所有其他文件类型（tar.gz、zip 等），也使用 FILE 类型
        file_url = _to_channel_url(file_path)
        logger.info(f"[AgentBridge] Sending generic file: {file_url}")
        reply = Reply(ReplyType.FILE, file_url)
        reply.file_name = file_info.get("file_name", os.path.basename(file_path))
        if text_response:
            reply.text_content = text_response
        return reply
    
    def _migrate_config_to_env(self, workspace_root: str):
        """
        Sync API keys from config.json to .env file.
        Adds new keys and updates changed values on each startup.

        Args:
            workspace_root: Workspace directory path (not used, kept for compatibility)
        """
        from config import conf
        import os
        
        key_mapping = {
            "open_ai_api_key": "OPENAI_API_KEY",
            "open_ai_api_base": "OPENAI_API_BASE",
            "gemini_api_key": "GEMINI_API_KEY",
            "claude_api_key": "CLAUDE_API_KEY",
            "linkai_api_key": "LINKAI_API_KEY",
        }
        
        env_file = expand_path("~/.cow/.env")
        
        # 读取现有的环境变量（键 -> 值）
        existing_env_vars = {}
        if os.path.exists(env_file):
            try:
                with open(env_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, val = line.split('=', 1)
                            existing_env_vars[key.strip()] = val.strip()
            except Exception as e:
                logger.warning(f"[AgentBridge] Failed to read .env file: {e}")
        
        # 将 config.json 值同步到 .env（添加/更新/删除）
        updated = False
        for config_key, env_key in key_mapping.items():
            raw = conf().get(config_key, "")
            value = raw.strip() if raw else ""
            old_value = existing_env_vars.get(env_key)

            if value:
                if old_value == value:
                    continue
                existing_env_vars[env_key] = value
                os.environ[env_key] = value
                updated = True
            else:
                if old_value is None:
                    continue
                existing_env_vars.pop(env_key, None)
                os.environ.pop(env_key, None)
                updated = True
            updated = True

        if updated:
            try:
                env_dir = os.path.dirname(env_file)
                os.makedirs(env_dir, exist_ok=True)

                with open(env_file, 'w', encoding='utf-8') as f:
                    f.write('# Environment variables for agent\n')
                    f.write('# Auto-managed - synced from config.json on startup\n\n')
                    for key, value in sorted(existing_env_vars.items()):
                        f.write(f'{key}={value}\n')

                logger.info(f"[AgentBridge] Synced API keys from config.json to .env")
            except Exception as e:
                logger.warning(f"[AgentBridge] Failed to sync API keys: {e}")
    
    def _pre_persist_user_message(
        self,
        session_id: str,
        query: str,
        context: Context,
        clear_history: bool,
        agent_id: str = None,
    ) -> bool:
        """Persist the user's message before the agent runs.

        This makes a brand-new session (and the user's bubble) visible even if
        the reply hasn't finished — switching away or refreshing no longer
        loses the in-flight session. Returns True when the user turn was
        stored, so the caller can skip it in the post-run persist.

        Best-effort: any failure is swallowed and reported as not-persisted.
        """
        if not session_id or not query:
            return False
        # 仅真实用户轮流：跳过调度程序注入/计划任务运行。
        if session_id.startswith("scheduler_") or (
            context and context.get("is_scheduled_task")
        ):
            return False
        try:
            from config import conf
            if not conf().get("conversation_persistence", True):
                return False
            store = self.get_conversation_store(agent_id)
            # clear_history 意味着从头开始：先擦掉存储，
            # 让抢先持久化的用户消息落到 seq 0，与内存状态对齐。
            if clear_history:
                store.clear_session(session_id)
            channel_type = (context.get("channel_type") or "") if context else ""
            user_msg = {
                "role": "user",
                "content": [{"type": "text", "text": query}],
            }
            store.append_messages(session_id, [user_msg], channel_type=channel_type)
            return True
        except Exception as e:
            logger.warning(
                f"[AgentBridge] Failed to pre-persist user message for session={session_id}: {e}"
            )
            return False

    def _persist_messages(
        self,
        session_id: str,
        new_messages: list,
        channel_type: str = "",
        agent_id: str = None,
        create_if_missing: bool = True,
    ) -> None:
        """
        Persist new messages to the conversation store after each agent run.

        Failures are logged but never propagate — they must not interrupt replies.

        ``create_if_missing=False`` is used once the user turn is known to be
        stored already: a missing session row then means the user deleted the
        session while the reply was still running, so the reply is dropped
        instead of resurrecting the session without its question.
        """
        if not new_messages:
            return
        try:
            from config import conf
            if not conf().get("conversation_persistence", True):
                return
            # 深度思考展示被关闭时，在持久化之前剥掉“思考”内容，
            # 免得历史重新加载时它们又冒出来。
            # 内存中的消息列表保持完整，供本次运行的多轮 LLM 上下文使用。
            thinking_enabled = bool(conf().get("enable_thinking", False))
            if not thinking_enabled:
                from models.reasoning_capabilities import get_reasoning_capability

                # 仅思考型模型需要把推理轨迹存入历史，
                # 供下一个工具调用回合回显。
                capability = get_reasoning_capability(
                    AgentLLMModel(None)._resolve_bot_type(conf().get("model", "")),
                    conf().get("model", ""),
                )
                thinking_enabled = bool(capability.get("thinking_only"))
        except Exception:
            thinking_enabled = False

        messages_to_store = new_messages
        if not thinking_enabled:
            messages_to_store = self._strip_thinking_blocks(new_messages)

        try:
            stored = self.get_conversation_store(agent_id).append_messages(
                session_id, messages_to_store, channel_type=channel_type,
                create_if_missing=create_if_missing
            )
            if not stored and not create_if_missing:
                logger.info(
                    f"[AgentBridge] Session {session_id} was deleted mid-run, "
                    f"dropped {len(messages_to_store)} reply message(s)"
                )
        except Exception as e:
            logger.warning(
                f"[AgentBridge] Failed to persist messages for session={session_id}: {e}"
            )

    # 用于识别调度程序注入的用户消息的标记，以便我们可以应用
    # 滑动窗口，无需接触真实用户的转动。遗留前缀
    # “计划任务”（v2 PR 写的）在剪枝时也被识别，
    # 因此旧数据可以老化，而不是永远泄漏。
    _SCHEDULED_MARKER = "[SCHEDULED]"
    _SCHEDULED_LEGACY_MARKERS = ("Scheduled task",)

    def remember_scheduled_output(
        self,
        session_id: str,
        content: str,
        channel_type: str = "",
        task_description: str = "",
        agent_id: str = None,
    ) -> None:
        """Add the visible output of a scheduled task to the receiver's session.

        Scheduled task execution uses an isolated session so internal planning and
        tool calls do not leak into the user's chat. The final message is still
        part of the conversation from the user's point of view, so keep a small
        visible turn in the receiver session for follow-up questions.

        Configuration:
            scheduler_inject_to_session (bool, default True):
                Master switch. When False, this method is a no-op.
            scheduler_inject_max_per_session (int, default 3):
                Maximum scheduler-injected user/assistant pairs retained per
                session. Older injections are pruned automatically.

        Content is truncated to 2000 chars to prevent a single high-volume task
        from bloating one entry.
        """
        from config import conf
        if not conf().get("scheduler_inject_to_session", True):
            return
        if not session_id or not content:
            return

        max_len = 2000
        if len(content) > max_len:
            content = content[:max_len] + "..."

        user_text = self._SCHEDULED_MARKER
        if task_description:
            user_text = f"{self._SCHEDULED_MARKER} {task_description}"

        messages = [
            {"role": "user", "content": [{"type": "text", "text": user_text}]},
            {"role": "assistant", "content": [{"type": "text", "text": content}]},
        ]

        # 先持久化，让新消息对拿到稳定的序号；然后修剪数据库里
        # 旧的调度器消息对，最后同步内存中的 agent.messages 缓冲区。
        self._persist_messages(session_id, messages, channel_type, agent_id)

        keep_last_n = max(int(conf().get("scheduler_inject_max_per_session", 3) or 0), 0)
        try:
            deleted = self.get_conversation_store(agent_id).prune_scheduled_messages(
                session_id, keep_last_n=keep_last_n
            )
            if deleted:
                logger.debug(
                    f"[AgentBridge] Pruned {deleted} old scheduler messages "
                    f"for session={session_id} (keep_last_n={keep_last_n})"
                )
        except Exception as e:
            logger.warning(
                f"[AgentBridge] Failed to prune scheduled messages "
                f"for session={session_id}: {e}"
            )

        agent = self.get_cached_agent(session_id, agent_id=agent_id)
        if agent:
            try:
                with agent.messages_lock:
                    agent.messages.extend(messages)
                    self._prune_scheduled_in_memory(agent, keep_last_n)
            except Exception as e:
                logger.warning(
                    f"[AgentBridge] Failed to update in-memory scheduled output "
                    f"for session={session_id}: {e}"
                )

    @staticmethod
    def _trim_in_memory_to_turns(agent, keep_turns: int) -> None:
        """Bound ``agent.messages`` to the most recent ``keep_turns`` real
        user/assistant turns, dropping older history together with any
        intermediate tool_use/tool_result blocks that belonged to it.

        A "real" user message is any user message whose content is not solely a
        tool_result block — matches the heuristic used elsewhere when filtering
        history (see ``AgentInitializer._filter_text_only_messages``).

        No-op when the session is already within budget. Caller does not need
        to hold the lock; this method acquires it itself.
        """
        if keep_turns <= 0:
            return

        def _is_real_user(msg) -> bool:
            if not isinstance(msg, dict) or msg.get("role") != "user":
                return False
            content = msg.get("content")
            if isinstance(content, list):
                if any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content
                ):
                    return False
                return any(
                    isinstance(b, dict) and b.get("type") == "text" and b.get("text")
                    for b in content
                )
            if isinstance(content, str):
                return bool(content.strip())
            return False

        with agent.messages_lock:
            msgs = agent.messages
            real_user_indices = [i for i, m in enumerate(msgs) if _is_real_user(m)]
            if len(real_user_indices) <= keep_turns:
                return

            # 在第 k 条（倒数）真实用户消息处下刀；从那里保留到末尾，
            # 确保保留下来的切片仍是合法的 user/assistant 交替序列。
            cut_idx = real_user_indices[-keep_turns]
            if cut_idx == 0:
                return

            kept = msgs[cut_idx:]
            msgs.clear()
            msgs.extend(kept)
            logger.debug(
                f"[AgentBridge] Trimmed in-memory messages to last "
                f"{keep_turns} turns ({len(kept)} messages remain)"
            )

    @classmethod
    def _prune_scheduled_in_memory(cls, agent, keep_last_n: int) -> None:
        """Mirror conversation_store.prune_scheduled_messages on agent.messages.

        Caller must hold ``agent.messages_lock``.
        """
        if keep_last_n < 0:
            keep_last_n = 0

        markers = (cls._SCHEDULED_MARKER,) + cls._SCHEDULED_LEGACY_MARKERS

        def _is_marker_user(msg) -> bool:
            if not isinstance(msg, dict) or msg.get("role") != "user":
                return False
            content = msg.get("content")
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        break
            return any(text.startswith(m) for m in markers)

        msgs = agent.messages
        pair_indices = []  # （user_idx、assistant_idx_or_None）列表
        for idx, msg in enumerate(msgs):
            if not _is_marker_user(msg):
                continue
            assistant_idx = None
            if idx + 1 < len(msgs):
                nxt = msgs[idx + 1]
                if isinstance(nxt, dict) and nxt.get("role") == "assistant":
                    assistant_idx = idx + 1
            pair_indices.append((idx, assistant_idx))

        if len(pair_indices) <= keep_last_n:
            return

        to_drop = pair_indices[: len(pair_indices) - keep_last_n]
        drop_set = set()
        for u_idx, a_idx in to_drop:
            drop_set.add(u_idx)
            if a_idx is not None:
                drop_set.add(a_idx)

        # 重建列表以保持外部引用稳定。
        kept = [m for i, m in enumerate(msgs) if i not in drop_set]
        msgs.clear()
        msgs.extend(kept)

    @staticmethod
    def _strip_thinking_blocks(messages: list) -> list:
        """Return a shallow copy of messages with assistant "thinking" blocks removed."""
        cleaned = []
        for msg in messages:
            if not isinstance(msg, dict):
                cleaned.append(msg)
                continue
            if msg.get("role") != "assistant":
                cleaned.append(msg)
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                cleaned.append(msg)
                continue
            filtered_blocks = [
                b for b in content
                if not (isinstance(b, dict) and b.get("type") == "thinking")
            ]
            if len(filtered_blocks) == len(content):
                cleaned.append(msg)
            else:
                new_msg = dict(msg)
                new_msg["content"] = filtered_blocks
                cleaned.append(new_msg)
        return cleaned

    def clear_session(self, session_id: str, agent_id: str = None):
        """
        Drop the cached agent for a session. Persisted history is untouched;
        the next request rebuilds the agent and restores from the store.

        Args:
            session_id: Session identifier to clear
        """
        if not session_id:
            return
        resolved_agent_id = self._resolve_agent_id(agent_id)
        key = self._runtime_key(resolved_agent_id, session_id)
        with self._agents_lock:
            removed = self._agent_instances.pop(key, None)
            if resolved_agent_id == self.agent_registry.default_agent_id:
                self.agents.pop(session_id, None)
        if removed is not None:
            logger.info(
                f"[AgentBridge] Clearing session: agent={resolved_agent_id}, "
                f"session={session_id}"
            )

    def clear_agent(self, agent_id: str) -> int:
        """Evict every live runtime instance for one agent workspace."""
        resolved_agent_id = self._resolve_agent_id(agent_id)
        with self._agents_lock:
            keys = [key for key in self._agent_instances if key[0] == resolved_agent_id]
            for key in keys:
                self._agent_instances.pop(key, None)
            self._default_agents.pop(resolved_agent_id, None)
            if resolved_agent_id == self.agent_registry.default_agent_id:
                self.agents.clear()
                self.default_agent = None
        return len(keys)
    
    def clear_all_sessions(self):
        """Clear all agent sessions"""
        with self._agents_lock:
            count = len(self._agent_instances)
            logger.info(f"[AgentBridge] Clearing all sessions ({count} total)")
            self._agent_instances.clear()
            self._default_agents.clear()
            self.agents.clear()
            self.default_agent = None
    
    def refresh_all_skills(self) -> int:
        """
        Refresh skills and conditional tools in all agent instances after
        environment variable changes. This allows hot-reload without restarting.

        Returns:
            Number of agent instances refreshed
        """
        import os
        from dotenv import load_dotenv
        from common.state_dir import env_file as workspace_env_file

        refreshed_count = 0
        loaded_env_files = set()

        # 每个实时代理都会重新加载自己的工作区 .env，而不仅仅是
        # 呼叫者恰好被路由到。
        for agent_id, session_id, agent in self.iter_agent_instances():
            workspace_root = getattr(agent, "workspace_dir", None)
            env_file = str(workspace_env_file(base=workspace_root)) if workspace_root else None
            if env_file and env_file not in loaded_env_files and os.path.exists(env_file):
                load_dotenv(env_file, override=True)
                loaded_env_files.add(env_file)
                logger.info(
                    f"[AgentBridge] Reloaded environment variables from {env_file}"
                )
            # 刷新技能
            if hasattr(agent, 'skill_manager') and agent.skill_manager:
                agent.skill_manager.refresh_skills()

            # 刷新条件工具（例如 web_search 取决于 API 密钥）
            self._refresh_conditional_tools(agent)

            refreshed_count += 1

        if refreshed_count > 0:
            logger.info(f"[AgentBridge] Refreshed skills & tools in {refreshed_count} agent instance(s)")

        return refreshed_count

    @staticmethod
    def _refresh_conditional_tools(agent):
        """
        Add or remove conditional tools based on current environment variables.
        For example, web_search should only be present when BOCHA_API_KEY or
        LINKAI_API_KEY is set.
        """
        try:
            from agent.tools.web_search.web_search import WebSearch

            has_tool = any(t.name == "web_search" for t in agent.tools)
            available = WebSearch.is_available()

            if available and not has_tool:
                # 添加了 API 密钥 - 注入工具
                tool = WebSearch()
                tool.model = agent.model
                agent.tools.append(tool)
                logger.info("[AgentBridge] web_search tool added (API key now available)")
            elif not available and has_tool:
                # API 密钥已删除 - 删除该工具
                agent.tools = [t for t in agent.tools if t.name != "web_search"]
                logger.info("[AgentBridge] web_search tool removed (API key no longer available)")
        except Exception as e:
            logger.debug(f"[AgentBridge] Failed to refresh conditional tools: {e}")
