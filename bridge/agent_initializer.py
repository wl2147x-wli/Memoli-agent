"""
Agent Initializer - Handles agent initialization logic
"""

import os
import asyncio
import datetime
import threading
import time
from typing import Dict, List, Optional

from agent.protocol import Agent
from agent.tools import ToolManager
from common.log import logger
from common.utils import expand_path

# 用于跨并发会话序列化调度程序 init 的模块级锁
_scheduler_init_lock = threading.Lock()

# 保护下面的运行中内存同步集，以便并发会话初始化
# 同一工作区不会各自调度冗余的后台同步线程。
_memory_sync_lock = threading.Lock()
# 当前在后台运行内存同步的工作区。一个新的
# 对同一工作区的请求被删除，而不是分叉另一个线程，
# 因此，突发消息无法叠加数十个嵌入 HTTP 调用。
_memory_sync_inflight: set = set()


class AgentInitializer:
    """
    Handles agent initialization including:
    - Workspace setup
    - Memory system initialization  
    - Tool loading
    - System prompt building
    """
    
    def __init__(self, bridge, agent_bridge):
        """
        Initialize agent initializer
        
        Args:
            bridge: COW bridge instance
            agent_bridge: AgentBridge instance (for create_agent method)
        """
        self.bridge = bridge
        self.agent_bridge = agent_bridge
    
    def initialize_agent(
        self,
        session_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        host_agent_id: Optional[str] = None,
    ) -> Agent:
        """
        Initialize agent for a session
        
        Args:
            session_id: Session ID (None for default agent)
            agent_id: Agent profile identifier. Omit for the configured default.
            host_agent_id: Agent that owns this conversation, when it is not
                ``agent_id``. A conversation belongs to the session rather than
                to whoever happens to be answering, so a guest reads the host's
                transcript and roster instead of starting a private one.
        
        Returns:
            Initialized agent instance
        """
        from agent.registry import get_agent_registry
        from common.runtime_identity import current_identity

        # 显式的 agent_id 获胜（管理、预热、测试）；否则遵循
        # 为此消息建立的身份路由。
        identity = current_identity()
        registry = get_agent_registry()
        profile = registry.get(agent_id or identity.agent_id)
        workspace_root = profile.workspace
        host_profile = profile
        if host_agent_id and host_agent_id != profile.id:
            try:
                host_profile = registry.get(host_agent_id, require_enabled=False)
            except Exception as e:
                logger.warning(
                    f"[AgentInitializer] Unknown conversation host "
                    f"'{host_agent_id}', falling back to {profile.id}: {e}"
                )
        
        # 迁移 API 密钥
        self._migrate_config_to_env(workspace_root)
        
        # 加载环境变量
        self._load_env_file()
        
        # 初始化工作区
        from agent.prompt import ensure_workspace, load_context_files, PromptBuilder
        workspace_files = ensure_workspace(workspace_root, create_templates=True)
        
        if session_id is None:
            logger.info(f"[AgentInitializer] Workspace initialized at: {workspace_root}")
        
        # 设置记忆系统
        memory_manager, memory_tools = self._setup_memory_system(workspace_root, session_id)
        
        # 加载工具
        tools = self._load_tools(
            workspace_root, memory_manager, memory_tools, session_id, host_profile.id
        )
        
        # 如果需要初始化调度程序
        self._initialize_scheduler(
            tools, session_id, workspace_root=workspace_root, agent_id=profile.id
        )
        
        # 加载上下文文件
        context_files = load_context_files(workspace_root)
        
        # 初始化技能管理器
        skill_manager = self._initialize_skill_manager(workspace_root, session_id)
        
        # 构建系统提示
        prompt_builder = PromptBuilder(workspace_dir=workspace_root, language="zh")
        runtime_info = self._get_runtime_info(workspace_root)
        runtime_info["agent_id"] = profile.id
        runtime_info["agent_name"] = profile.name
        runtime_info["_get_teammates"] = self._teammates_getter(
            session_id, profile.id, host_profile.id
        )
        
        system_prompt = prompt_builder.build(
            tools=tools,
            context_files=context_files,
            skill_manager=skill_manager,
            memory_manager=memory_manager,
            runtime_info=runtime_info,
        )
        
        # 获取成本控制参数
        from config import conf
        max_steps = conf().get("agent_max_steps", 20)
        max_context_tokens = conf().get("agent_max_context_tokens", 50000)
        
        # 创建代理
        agent = self.agent_bridge.create_agent(
            system_prompt=system_prompt,
            tools=tools,
            max_steps=max_steps,
            output_mode="logger",
            workspace_dir=workspace_root,
            skill_manager=skill_manager,
            enable_skills=True,
            max_context_tokens=max_context_tokens,
            runtime_info=runtime_info  # 传递runtime_info以进行动态时间更新
        )
        
        # 附加内存管理器并共享LLM模型进行总结
        if memory_manager:
            agent.memory_manager = memory_manager
            if hasattr(agent, 'model') and agent.model:
                memory_manager.flush_manager.llm_model = agent.model

        agent.agent_id = profile.id
        agent.agent_profile = profile
        agent.workspace_dir = workspace_root

        # 把系统提示中的模型行绑定到代理的*有效*模型，
        # 让会话级覆盖（见 AgentLLMModel.set_session_override）
        # 也能体现在提示里。否则提示会一直报告全局配置的
        # 模型，而 LLM（会读到那一行）自报的模型名就是错的，
        # 哪怕实际 API 调用用的已是会话模型。
        llm = getattr(agent, "model", None)
        # 默认代理没有自己的固定模型：它按控制台当前的模型设置
        # 作答，所以那项设置只需在一处修改即可生效。
        # 其它代理则可以被精确指定各自使用的模型。
        if llm is not None and hasattr(llm, "set_agent_default"):
            is_default = profile.id == self.agent_bridge.agent_registry.default_agent_id
            llm.set_agent_default(
                None if is_default else profile.bot_type,
                None if is_default else profile.model,
            )
        if llm is not None and hasattr(llm, "model"):
            runtime_info["_get_model"] = lambda: getattr(llm, "model", None) or conf().get("model", "unknown")

        # 恢复此会话的持久对话历史记录
        if session_id:
            self._restore_conversation_history(
                agent, session_id, host_profile.workspace, host_profile.id
            )

        # 启动每日内存刷新计时器（一次，在第一个代理初始化时，无论会话如何）
        self._start_daily_flush_timer()

        return agent

    def _restore_conversation_history(
        self,
        agent,
        session_id: str,
        transcript_workspace: Optional[str] = None,
        host_agent_id: Optional[str] = None,
    ) -> None:
        """
        Load persisted conversation messages from SQLite and inject them
        into the agent's in-memory message list.

        Only user text and assistant text are restored. Tool call chains
        (tool_use / tool_result) are stripped out because:
        1. They are intermediate process, the value is already in the final
           assistant text reply.
        2. They consume massive context tokens (often 80%+ of history).
        3. Different models have incompatible tool message formats, so
           restoring tool chains across model switches causes 400 errors.
        4. Eliminates the entire class of tool_use/tool_result pairing bugs.
        """
        from config import conf
        if not conf().get("conversation_persistence", True):
            return

        reader = getattr(agent, "agent_id", "") or ""
        shared = self._is_shared_conversation(session_id, host_agent_id or reader)

        try:
            from agent.memory import get_conversation_store
            store = get_conversation_store(
                transcript_workspace or agent.workspace_dir
            )
            max_turns = conf().get("agent_max_context_turns", 20)
            # 恢复时遵守会话各自的上下文边界（被清除的历史
            # 永远不会找回），因此可以把窗口放宽一些，
            # 同时仍不超过运行时的上限。常规聊天恢复约一半的
            # 运行时预算，让对话重启后依然感觉连续。
            # 调度器任务跑在稳定的隔离会话里，一天可能触发
            # 好几次，因此只保留较小的窗口：够看到最近几次
            # 运行的趋势/去重即可，同时控制即时成本。
            if session_id.startswith("scheduler_"):
                restore_turns = max(1, max_turns // 4)
            else:
                restore_turns = max(3, max_turns // 2)
            saved = store.load_messages(
                session_id, max_turns=restore_turns, with_authors=shared
            )
            if saved:
                filtered = self._filter_text_only_messages(saved)
                if shared:
                    filtered = self._attribute_history(filtered, reader)
                if filtered:
                    with agent.messages_lock:
                        agent.messages = filtered
                    logger.debug(
                        f"[AgentInitializer] Restored {len(filtered)} text messages "
                        f"(from {len(saved)} total, {restore_turns} turns cap) "
                        f"for session={session_id}"
                    )
        except Exception as e:
            logger.warning(
                f"[AgentInitializer] Failed to restore conversation history for "
                f"session={session_id}: {e}"
            )

    @staticmethod
    def _is_shared_conversation(session_id: str, host_agent_id: str) -> bool:
        """Whether anyone besides the owner was invited into this conversation."""
        if not session_id:
            return False
        try:
            from agent.workspace import session_prefs

            return bool(session_prefs.get_prefs(session_id, host_agent_id).get("members"))
        except Exception:
            return False

    @staticmethod
    def _attribute_history(messages: list, reader_agent_id: str) -> list:
        """Name the author of replies this Agent did not write.

        Without this a shared transcript reads as a monologue: every earlier
        reply arrives in the same ``assistant`` role, so an Agent takes a
        colleague's work — and its promises — for its own. Its own turns are
        left bare, so "unlabelled" reads as "mine"; the team prompt says so.
        """
        from agent.registry import get_agent_registry

        registry = get_agent_registry()
        names: Dict[str, str] = {}

        def name_of(agent_id: str) -> str:
            if agent_id not in names:
                try:
                    names[agent_id] = registry.get(agent_id, require_enabled=False).name
                except Exception:
                    names[agent_id] = agent_id
            return names[agent_id]

        attributed = []
        for message in messages:
            author = message.get("agent_id") or ""
            plain = {"role": message["role"], "content": message["content"]}
            if author and author != reader_agent_id and plain["role"] == "assistant":
                blocks = plain["content"]
                if isinstance(blocks, list) and blocks and blocks[0].get("type") == "text":
                    label = f"[{name_of(author)}] "
                    plain["content"] = [
                        {**blocks[0], "text": label + blocks[0].get("text", "")},
                        *blocks[1:],
                    ]
            attributed.append(plain)
        return attributed

    @staticmethod
    def _filter_text_only_messages(messages: list) -> list:
        """
        Extract clean user/assistant turn pairs from raw message history.

        Groups messages into turns (each starting with a real user query),
        then keeps only:
        - The first user text in each turn (the actual user input)
        - The last assistant text in each turn (the final answer)

        All tool_use, tool_result, intermediate assistant thoughts, and
        internal hint messages injected by the agent loop are discarded.
        """

        def _extract_text(content) -> str:
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = [
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                return "\n".join(p for p in parts if p).strip()
            return ""

        def _is_real_user_msg(msg: dict) -> bool:
            """True for actual user input, False for tool_result or internal hints."""
            if msg.get("role") != "user":
                return False
            content = msg.get("content")
            if isinstance(content, list):
                has_tool_result = any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content
                )
                if has_tool_result:
                    return False
            text = _extract_text(content)
            return bool(text)

        # 分组轮流：每个轮流以真实的用户消息开始
        turns = []
        current_turn = None
        for msg in messages:
            if _is_real_user_msg(msg):
                if current_turn is not None:
                    turns.append(current_turn)
                current_turn = {"user": msg, "assistants": []}
            elif current_turn is not None and msg.get("role") == "assistant":
                text = _extract_text(msg.get("content"))
                if text:
                    current_turn["assistants"].append(
                        (text, msg.get("agent_id") or "")
                    )
        if current_turn is not None:
            turns.append(current_turn)

        # 构建结果：每回合一条用户消息+一条助手消息
        filtered = []
        for turn in turns:
            user_text = _extract_text(turn["user"].get("content"))
            if not user_text:
                continue
            filtered.append({
                "role": "user",
                "content": [{"type": "text", "text": user_text}]
            })
            if turn["assistants"]:
                final_reply, author = turn["assistants"][-1]
                reply = {
                    "role": "assistant",
                    "content": [{"type": "text", "text": final_reply}],
                }
                if author:
                    reply["agent_id"] = author
                filtered.append(reply)

        return filtered
    
    def _load_env_file(self):
        """Load environment variables from .env file"""
        env_file = expand_path("~/.cow/.env")
        if os.path.exists(env_file):
            try:
                from dotenv import load_dotenv
                load_dotenv(env_file, override=True)
            except ImportError:
                logger.warning("[AgentInitializer] python-dotenv not installed")
            except Exception as e:
                logger.warning(f"[AgentInitializer] Failed to load .env file: {e}")
    
    def _setup_memory_system(self, workspace_root: str, session_id: Optional[str] = None):
        """
        Setup memory system
        
        Returns:
            (memory_manager, memory_tools) tuple
        """
        memory_manager = None
        memory_tools = []
        
        try:
            from agent.memory import MemoryManager, MemoryConfig, register_memory_config
            from agent.tools import MemorySearchTool, MemoryGetTool
            from config import conf

            memory_config = MemoryConfig(workspace_root=workspace_root)
            # 按工作区注册，而不是进程级单例：每个代理各注册一次，
            # 全局只留一个槽位的话，最后初始化的代理就会
            # 决定所有代理的记忆写入位置。
            register_memory_config(memory_config)

            embedding_provider = self._init_embedding_provider(
                memory_config, session_id=session_id
            )

            memory_manager = MemoryManager(memory_config, embedding_provider=embedding_provider)
            self._sync_memory(memory_manager, session_id)

            memory_tools = [
                MemorySearchTool(memory_manager),
                MemoryGetTool(memory_manager)
            ]
            
            if session_id is None:
                logger.info("[AgentInitializer] Memory system initialized")
        
        except Exception as e:
            logger.warning(f"[AgentInitializer] Memory system not available: {e}")
        
        return memory_manager, memory_tools

    def _init_embedding_provider(self, memory_config, session_id: Optional[str] = None):
        """
        Initialize the embedding provider for memory.

        Delegates to the shared factory so agent init, knowledge sync and
        index rebuild all select the same provider:
          A. Default (no `embedding_provider` in config.json):
             Auto-init OpenAI -> LinkAI fallback.
          B. Explicit (`embedding_provider` is set):
             Initialize the requested vendor.
        """
        from agent.memory import create_default_embedding_provider
        return create_default_embedding_provider()

    def _sync_memory(self, memory_manager, session_id: Optional[str] = None):
        """Bring the memory index up to date with the workspace files.

        Runs entirely on a background daemon thread. sync() re-embeds any file
        whose hash changed (MEMORY.md / memory/*.md / knowledge/*.md), and each
        embed_batch is a blocking HTTP call that can take 20-50s from China-side
        networks. Daily memory files change on nearly every session, so keeping
        this on the init path made every user's first message wait for that
        round-trip. The index is only read on the *next* memory search, so a
        slightly stale index for the current turn is an acceptable trade-off —
        the same design MCP tool loading already uses.

        Idempotent per workspace: a burst of concurrent session inits dispatches
        at most one sync thread, so messages can't stack up embedding calls.
        """
        workspace_key = None
        try:
            workspace_key = str(memory_manager.config.get_workspace())
        except Exception:
            workspace_key = None

        with _memory_sync_lock:
            if workspace_key is not None and workspace_key in _memory_sync_inflight:
                return
            if workspace_key is not None:
                _memory_sync_inflight.add(workspace_key)

        def _run():
            try:
                loop = asyncio.new_event_loop()
                try:
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(memory_manager.sync())
                finally:
                    loop.close()
            except Exception as e:
                logger.warning(f"[AgentInitializer] Memory sync failed: {e}")
            finally:
                if workspace_key is not None:
                    with _memory_sync_lock:
                        _memory_sync_inflight.discard(workspace_key)

        threading.Thread(
            target=_run, daemon=True, name="memory-sync"
        ).start()
    
    def _load_tools(self, workspace_root: str, memory_manager, memory_tools: List, session_id: Optional[str] = None, host_agent_id: Optional[str] = None):
        """Load all tools"""
        from config import conf

        tool_manager = ToolManager()
        tool_manager.load_tools()
        
        tools = []
        file_config = {
            "cwd": workspace_root,
            "memory_manager": memory_manager
        } if memory_manager else {"cwd": workspace_root}
        
        for tool_name in tool_manager.tool_classes.keys():
            try:
                # 如果没有可用的 API 密钥，则跳过 web_search
                if tool_name == "web_search":
                    from agent.tools.web_search.web_search import WebSearch
                    if not WebSearch.is_available():
                        logger.debug("[AgentInitializer] WebSearch skipped - no search provider configured")
                        continue

                # 自我演化被禁用时跳过 evolution_undo：没有演化
                # 就没有可撤销的东西，装上它纯属累赘。
                if tool_name == "evolution_undo":
                    from agent.evolution.config import get_evolution_config
                    if not get_evolution_config().enabled:
                        logger.debug("[AgentInitializer] evolution_undo skipped - self-evolution disabled")
                        continue

                if tool_name == "agent_delegate":
                    delegation = conf().get("agent_delegation", {})
                    enabled = delegation is not False and (
                        not isinstance(delegation, dict)
                        or delegation.get("enabled", True)
                    )
                    enabled_agents = self.agent_bridge.agent_registry.list(
                        include_disabled=False
                    )
                    # 只有对话里真的存在队友时，委派才有意义。
                    # 单聊——哪怕该代理是在团队配置下定义的——
                    # 不应携带该工具，这样单个代理永远不会试图
                    # 把工作交给未受邀的参与者。
                    shared = self._is_shared_conversation(
                        session_id or "", host_agent_id or ""
                    )
                    if not enabled or len(enabled_agents) < 2 or not shared:
                        logger.debug(
                            "[AgentInitializer] agent_delegate skipped - "
                            "needs a shared conversation with 2+ Agents"
                        )
                        continue

                # EnvConfig 工具的特殊处理
                if tool_name == "env_config":
                    from agent.tools import EnvConfig
                    tool = EnvConfig({"agent_bridge": self.agent_bridge})
                else:
                    tool = tool_manager.create_tool(tool_name)

                if tool:
                    # 将工作区配置应用于文件操作工具。
                    # 合并到现有的tool.config（由ToolManager设置）
                    # config.json 的 `tools.<name>` 部分）而不是替换
                    # 它，否则每个工具的用户配置（例如 browser.cdp_endpoint）
                    # 会被无声无息地丢弃。
                    if tool_name in ['read', 'write', 'edit', 'bash', 'search_files', 'ls', 'web_fetch', 'send', 'browser']:
                        merged_config = dict(getattr(tool, 'config', None) or {})
                        merged_config.update(file_config)
                        tool.config = merged_config
                        tool.cwd = merged_config.get("cwd", getattr(tool, 'cwd', None))
                        if hasattr(tool, 'timeout'):
                            # create_tool() 构建实例在 tool_configs 合并
                            # 之前，因此由配置派生的 .timeout 已被冻结在
                            # __init__ 时的默认值；与上面的 cwd 一样在这里
                            # 重新导出，并按属性（而不是按工具名）判断，
                            # 这样未来任何带 .timeout 属性的工具都不会被漏掉。
                            tool.timeout = merged_config.get("timeout", getattr(tool, 'timeout', None))
                        if 'memory_manager' in merged_config:
                            tool.memory_manager = merged_config['memory_manager']
                        # 重新派生期间设置的配置派生属性
                        # __init__ （在从用户配置填充 tool.config 之前）。
                        # bash 是唯一具有此类属性的工具（default_timeout、
                        # 安全模式）；通用模式适用于任何工具。
                        if hasattr(tool, 'default_timeout'):
                            tool.default_timeout = merged_config.get(
                                "timeout", tool.default_timeout
                            )
                        if hasattr(tool, 'safety_mode'):
                            tool.safety_mode = merged_config.get(
                                "safety_mode", tool.safety_mode
                            )
                    tools.append(tool)
            except Exception as e:
                logger.warning(f"[AgentInitializer] Failed to load tool {tool_name}: {e}")

        # 添加 MCP 工具（快照以避免与后台加载程序竞争）
        mcp_tools_snapshot = list(tool_manager._mcp_tool_instances.items())
        if mcp_tools_snapshot:
            for _, mcp_tool in mcp_tools_snapshot:
                tools.append(mcp_tool)
            if session_id is None:
                names = [name for name, _ in mcp_tools_snapshot]
                logger.info(
                    f"[AgentInitializer] Added {len(names)} MCP tool(s): {names}"
                )

        # 添加记忆工具
        if memory_tools:
            tools.extend(memory_tools)
            if session_id is None:
                logger.info(f"[AgentInitializer] Added {len(memory_tools)} memory tools")
        
        if session_id is None:
            logger.info(f"[AgentInitializer] Loaded {len(tools)} tools: {[t.name for t in tools]}")
        
        return tools
    
    def _initialize_scheduler(
        self,
        tools: List,
        session_id: Optional[str] = None,
        workspace_root: str = None,
        agent_id: str = None,
    ):
        """Initialize scheduler service if needed.

        Serialize the check-and-set under a module-level lock so concurrent
        first-time session inits cannot each create a new SchedulerService
        (which would leak background scanning threads).
        """
        if agent_id not in self.agent_bridge.scheduler_agent_ids:
            with _scheduler_init_lock:
                if agent_id not in self.agent_bridge.scheduler_agent_ids:
                    try:
                        from agent.tools.scheduler.integration import init_scheduler
                        if init_scheduler(
                            self.agent_bridge,
                            workspace_root=workspace_root,
                            agent_id=agent_id,
                        ):
                            self.agent_bridge.scheduler_agent_ids.add(agent_id)
                            self.agent_bridge.scheduler_initialized = True
                            if session_id is None:
                                logger.info(
                                    f"[AgentInitializer] Scheduler initialized "
                                    f"for agent={agent_id}"
                                )
                    except Exception as e:
                        logger.warning(f"[AgentInitializer] Failed to initialize scheduler: {e}")
        
        # 注入调度程序依赖项
        if agent_id in self.agent_bridge.scheduler_agent_ids:
            try:
                from agent.tools.scheduler.integration import get_task_store, get_scheduler_service
                from agent.tools import SchedulerTool
                from config import conf
                
                task_store = get_task_store(
                    workspace_root=workspace_root, agent_id=agent_id
                )
                scheduler_service = get_scheduler_service(
                    workspace_root=workspace_root, agent_id=agent_id
                )
                
                for tool in tools:
                    if isinstance(tool, SchedulerTool):
                        tool.task_store = task_store
                        tool.scheduler_service = scheduler_service
                        if not tool.config:
                            tool.config = {}
                        raw_ct = conf().get("channel_type", "unknown")
                        if isinstance(raw_ct, list):
                            ct = raw_ct[0] if raw_ct else "unknown"
                        elif isinstance(raw_ct, str) and "," in raw_ct:
                            ct = raw_ct.split(",")[0].strip()
                        else:
                            ct = raw_ct
                        tool.config["channel_type"] = ct
                        tool.config["agent_id"] = agent_id
            except Exception as e:
                logger.warning(f"[AgentInitializer] Failed to inject scheduler dependencies: {e}")
    
    def _initialize_skill_manager(self, workspace_root: str, session_id: Optional[str] = None):
        """Initialize skill manager"""
        try:
            from agent.skills import build_skill_manager
            return build_skill_manager(workspace_dir=workspace_root)
        except Exception as e:
            logger.warning(f"[AgentInitializer] Failed to initialize SkillManager: {e}")
            return None

    @staticmethod
    def _teammates_getter(
        session_id: Optional[str], agent_id: str, host_agent_id: Optional[str] = None
    ):
        """Resolve this conversation's roster lazily, on each prompt build.

        A closure rather than a resolved list: the Agent instance is cached per
        session, so a roster resolved once here would stay stale until the
        session was evicted, and inviting somebody would not take effect.

        The roster is stored against the conversation's host, who is in the
        room too, so a guest sees the host plus the other members, never itself.
        """
        host_id = host_agent_id or agent_id

        def resolve():
            if not session_id:
                return []
            try:
                from agent.registry import get_agent_registry
                from agent.workspace import session_prefs

                members = session_prefs.get_prefs(session_id, host_id).get("members")
                if not members:
                    return []
                registry = get_agent_registry()
                roster = []
                for member_id in [host_id, *members]:
                    if member_id == agent_id or any(
                        item["id"] == member_id for item in roster
                    ):
                        continue
                    try:
                        profile = registry.get(member_id)
                    except Exception:
                        # 此后存档的成员根本不再存在
                        # 在团队中；命名它会导致切换失败。
                        continue
                    roster.append(
                        {
                            "id": profile.id,
                            "name": profile.name,
                            "description": profile.description or "",
                        }
                    )
                return roster
            except Exception as e:
                logger.warning(f"[AgentInitializer] Failed to resolve teammates: {e}")
                return []

        return resolve
    
    def _get_runtime_info(self, workspace_root: str):
        """Get runtime information with dynamic time support"""
        from config import conf
        
        def get_current_time():
            """Get current time dynamically - called each time system prompt is accessed"""
            now = datetime.datetime.now()
            
            # 获取时区信息
            try:
                offset = -time.timezone if not time.daylight else -time.altzone
                hours = offset // 3600
                minutes = (offset % 3600) // 60
                timezone_name = f"UTC{hours:+03d}:{minutes:02d}" if minutes else f"UTC{hours:+03d}"
            except Exception:
                timezone_name = "UTC"
            
            # 工作日：英文名称为 en，否则为中文映射
            weekday_en = now.strftime("%A")
            try:
                from common import i18n
                is_en = i18n.get_language() == "en"
            except Exception:
                is_en = False
            if is_en:
                weekday = weekday_en
            else:
                weekday_map = {
                    'Monday': '星期一', 'Tuesday': '星期二', 'Wednesday': '星期三',
                    'Thursday': '星期四', 'Friday': '星期五', 'Saturday': '星期六', 'Sunday': '星期日'
                }
                weekday = weekday_map.get(weekday_en, weekday_en)

            return {
                'time': now.strftime("%Y-%m-%d %H:%M:%S"),
                'weekday': weekday,
                'timezone': timezone_name
            }
        
        def get_model():
            """Get current model name dynamically from config"""
            return conf().get("model", "unknown")

        return {
            "_get_model": get_model,
            "workspace": workspace_root,
            "channel": ", ".join(conf().get("channel_type")) if isinstance(conf().get("channel_type"), list) else conf().get("channel_type", "unknown"),
            "_get_current_time": get_current_time  # 动态时间函数
        }
    
    def _migrate_config_to_env(self, workspace_root: str):
        """Migrate API keys from config.json to .env file"""
        from config import conf
        
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
                logger.warning(f"[AgentInitializer] Failed to read .env file: {e}")
        
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

        if updated:
            try:
                env_dir = os.path.dirname(env_file)
                os.makedirs(env_dir, exist_ok=True)

                # 重写整个.env文件以确保一致性
                with open(env_file, 'w', encoding='utf-8') as f:
                    f.write('# Environment variables for agent\n')
                    f.write('# Auto-managed - synced from config.json on startup\n\n')
                    for key, value in sorted(existing_env_vars.items()):
                        f.write(f'{key}={value}\n')

                logger.info(f"[AgentInitializer] Synced API keys from config.json to .env")
            except Exception as e:
                logger.warning(f"[AgentInitializer] Failed to sync API keys: {e}")

    def _start_daily_flush_timer(self):
        """Start a background thread that flushes all agents' memory daily at 23:55."""
        if getattr(self.agent_bridge, '_daily_flush_started', False):
            return
        self.agent_bridge._daily_flush_started = True

        import threading

        def _daily_flush_loop():
            import random
            last_run_date = None  # 跟踪上次成功运行日期以防止当天重新触发
            while True:
                try:
                    now = datetime.datetime.now()
                    jitter_min = random.randint(50, 55)
                    jitter_sec = random.randint(0, 59)
                    target = now.replace(hour=23, minute=jitter_min, second=jitter_sec, microsecond=0)
                    # 今天已经跑过、或目标时刻已过，则顺延到明天
                    if target <= now or (last_run_date == now.date()):
                        target += datetime.timedelta(days=1)
                    wait_seconds = (target - now).total_seconds()
                    logger.info(f"[DailyFlush] Next flush at {target.strftime('%Y-%m-%d %H:%M:%S')} (in {wait_seconds/3600:.1f}h)")
                    time.sleep(wait_seconds)

                    self._flush_all_agents()
                    # 记录计划运行日期：跨越午夜的运行
                    # 不能把新的一天误标为已完成。
                    last_run_date = target.date()
                except Exception as e:
                    logger.warning(f"[DailyFlush] Error in daily flush loop: {e}")
                    time.sleep(3600)

        t = threading.Thread(target=_daily_flush_loop, daemon=True)
        t.start()

    def _flush_all_agents(self):
        """Flush memory for all active agent sessions, then run Deep Dream."""
        agents = [
            (f"{agent_id}:{session_id or 'default'}", agent)
            for agent_id, session_id, agent in self.agent_bridge.iter_agent_instances()
        ]

        if not agents:
            return

        # 第一阶段：刷新每日总结
        flushed = 0
        flush_threads = []
        dream_candidates = {}
        for label, agent in agents:
            try:
                if not agent.memory_manager:
                    continue
                dream_candidates.setdefault(
                    agent.agent_id, agent.memory_manager.flush_manager
                )
                with agent.messages_lock:
                    messages = list(agent.messages)
                if not messages:
                    continue
                result = agent.memory_manager.flush_manager.create_daily_summary(messages)
                if result:
                    flushed += 1
                    t = agent.memory_manager.flush_manager._last_flush_thread
                    if t:
                        flush_threads.append(t)
            except Exception as e:
                logger.warning(f"[DailyFlush] Failed for session {label}: {e}")

        if flushed:
            logger.info(f"[DailyFlush] Flushed {flushed}/{len(agents)} agent session(s)")

        # 等待所有刷新线程完成后再做梦
        for t in flush_threads:
            t.join(timeout=60)

        # 第二阶段：深梦——提炼每日记忆 → MEMORY.md + 梦日记
        for agent_id, dream_candidate in dream_candidates.items():
            try:
                result = dream_candidate.deep_dream()
                if result:
                    logger.info(
                        f"[DeepDream] Memory distillation completed for "
                        f"agent={agent_id}"
                    )
            except Exception as e:
                logger.warning(f"[DeepDream] Failed for agent={agent_id}: {e}")
