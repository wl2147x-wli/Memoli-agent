"""
ChatService - Wraps the Agent stream execution to produce CHAT protocol chunks.

Translates agent events (message_update, message_end, tool_execution_end, etc.)
into the CHAT socket protocol format (content chunks with segment_id, tool_calls chunks).
"""

import time
from typing import Callable, Optional

from common.log import logger


class ChatService:
    """
    High-level service that runs an Agent for a given query and streams
    the results as CHAT protocol chunks via a callback.

    Usage:
        svc = ChatService(agent_bridge)
        svc.run(query, session_id, send_chunk_fn)
    """

    def __init__(self, agent_bridge):
        """
        :param agent_bridge: AgentBridge instance (manages agent lifecycle)
        """
        self.agent_bridge = agent_bridge

    def run(
        self,
        query: str,
        session_id: str,
        send_chunk_fn: Callable[[dict], None],
        channel_type: str = "",
        agent_id: str = None,
        request_id: str = None,  # noqa: RUF013
    ):
        """
        Run the agent for *query* and stream results back via *send_chunk_fn*.

        The method blocks until the agent finishes. After it returns the SDK
        will automatically send the final (streaming=false) message.

        :param query: user query text
        :param session_id: session identifier for agent isolation
        :param send_chunk_fn: callable(chunk_data: dict) to send a streaming chunk
        :param channel_type: source channel (e.g. "web", "feishu") for persistence
        :param agent_id: selected agent profile; defaults to the configured default
        :param request_id: per-request cancellation key; defaults to session scope
        """
        resolved_agent_id = self.agent_bridge._resolve_agent_id(agent_id)
        agent = self.agent_bridge.get_agent(
            session_id=session_id, agent_id=resolved_agent_id
        )
        if agent is None:
            raise RuntimeError("Failed to initialise agent for the session")

        # 把上下文元数据传给后续 API 请求所使用的模型
        if hasattr(agent, 'model'):
            agent.model.channel_type = channel_type or ""
            agent.model.session_id = session_id or ""
            agent.model.agent_id = resolved_agent_id

        # 构建上下文，让上下文感知工具（如调度器）能解析
        # 接收者/会话。流式路径绕过了 agent_bridge.agent_reply，
        # 因此原本在那边完成的附加步骤也必须在此补齐。
        context = self._build_context(
            query, session_id, channel_type, resolved_agent_id
        )
        self._attach_context_aware_tools(agent, context)

        # 把本会话标记为运行中，避免单轮执行超过 idle_minutes 时，
        # 自我演化的空闲扫描又在这一轮运行期间同时触发。
        self._mark_run_active(agent, True)

        # 事件回调与本 run 方法之间共享的状态
        state = _StreamState()

        def flush_file_links():
            """Emit any buffered file links as content, then drop them."""
            if not state.pending_file_links:
                return
            links = state.pending_file_links
            state.pending_file_links = []
            send_chunk_fn({
                "chunk_type": "content",
                "delta": "\n\n" + "\n\n".join(links) + "\n\n",
                "segment_id": state.segment_id,
            })

        def on_event(event: dict):
            """Translate agent events into CHAT protocol chunks."""
            event_type = event.get("type")
            data = event.get("data", {})

            if event_type == "reasoning_update":
                delta = data.get("delta", "")
                if delta:
                    send_chunk_fn({
                        "chunk_type": "reasoning",
                        "delta": delta,
                        "segment_id": state.segment_id,
                    })

            elif event_type == "message_update":
                # 消息的增量文本内容
                delta = data.get("delta", "")
                if delta:
                    send_chunk_fn({
                        "chunk_type": "content",
                        "delta": delta,
                        "segment_id": state.segment_id,
                    })

            elif event_type == "message_end":
                # 一段消息内容到此结束。
                tool_calls = data.get("tool_calls", [])
                if tool_calls:
                    # 本轮含有 tool_calls：执行之后的正文将归属
                    # 新的片段；在此之前持续收集工具结果直到 turn_end。
                    state.pending_tool_results = []

            elif event_type == "tool_retrieval":
                # 转发经过清理的检索元数据以用于进度显示。
                send_chunk_fn({
                    "chunk_type": "tool_retrieval",
                    "data": data,
                })

            elif event_type == "file_to_send":
                url = data.get("url") or ""
                if url:
                    fname = data.get("file_name") or "file"
                    ft = data.get("file_type") or "file"
                    if ft == "image":
                        link = f"![{fname}]({url})"
                    else:
                        link = f"[{fname}]({url})"
                    state.pending_file_links.append(link)
                    # 删除 url，以便模型不会在回复中重复它
                    data.pop("url", None)

            elif event_type == "tool_execution_start":
                # 通知客户端工具即将运行（及其输入参数）
                tool_name = data.get("tool_name", "")
                arguments = data.get("arguments", {})
                # 缓存由 tool_call_id 键控的参数，以便 tool_execution_end 可以包含它们
                tool_call_id = data.get("tool_call_id", tool_name)
                state.pending_tool_arguments[tool_call_id] = arguments
                send_chunk_fn({
                    "chunk_type": "tool_start",
                    "tool": tool_name,
                    "arguments": arguments,
                    # 带上 call id，方便之后把 subagent_step 事件挂到正确的
                    # 卡片上：其内部步骤正是通过 card_id 到达对应卡片的。
                    "tool_id": tool_call_id,
                })

            elif event_type == "tool_execution_end":
                tool_name = data.get("tool_name", "")
                tool_call_id = data.get("tool_call_id", tool_name)
                # 从匹配的 tool_execution_start 事件中检索缓存的参数
                arguments = state.pending_tool_arguments.pop(tool_call_id, data.get("arguments", {}))
                result = data.get("result", "")
                status = data.get("status", "unknown")
                execution_time = data.get("execution_time", 0)
                elapsed_str = f"{execution_time:.2f}s"

                # 如果需要，将结果序列化为字符串
                if not isinstance(result, str):
                    import json
                    try:
                        result = json.dumps(result, ensure_ascii=False)
                    except Exception:
                        result = str(result)

                tool_info = {
                    "name": tool_name,
                    "arguments": arguments,
                    "result": result,
                    "status": status,
                    "elapsed": elapsed_str,
                    # 匹配的 tool_start 带有相同的 id，前端可据此把
                    # 子代理从“加载中”卡片迁到这张已完成的卡片上
                    # （参见 collectLoadingSubsteps / card.get）。
                    "id": tool_call_id,
                }

                if state.pending_tool_results is not None:
                    state.pending_tool_results.append(tool_info)

            elif event_type == "subagent_step":
                # 子代理在 `subagent` 工具调用仍在执行时产出的中间步骤。
                # 立即转发（不并入批量的 tool_execution_end 工具结果），
                # 让控制台能实时跟进子代理的进度，而不必等整段流程
                # 跑完几分钟后，直到 turn_end 才一次性刷新。
                send_chunk_fn({
                    "chunk_type": "subagent_step",
                    "card_id": data.get("card_id"),
                    "step_id": data.get("step_id"),
                    "phase": data.get("phase"),
                    # 前端需要 `tool`；该事件带有`tool_name`。
                    "tool": data.get("tool_name") or data.get("tool") or "tool",
                    "arguments": data.get("arguments") or {},
                    "status": data.get("status"),
                    "execution_time": data.get("execution_time"),
                    "error": data.get("error"),
                })

            elif event_type == "artifact":
                # （子）代理写出的文件。实时转发，这样文件一旦生成
                # 就能被预览，而不必等整个回合结束。
                send_chunk_fn({
                    "chunk_type": "artifact",
                    "artifact": data,
                })

            elif event_type == "turn_end":
                has_tool_calls = data.get("has_tool_calls", False)
                if has_tool_calls and state.pending_tool_results:
                    # 将收集的工具结果刷新为单个 tool_calls 块
                    send_chunk_fn({
                        "chunk_type": "tool_calls",
                        "tool_calls": state.pending_tool_results,
                    })
                    state.pending_tool_results = None
                    # 下一个内容属于新片段
                    state.segment_id += 1
                # 工具结果既已发出，这些文件链接便归属于
                # 紧随其后的正文内容。
                flush_file_links()

        # 使用我们的事件回调运行代理 ---------------------------
        logger.info(
            f"[ChatService] Starting agent run: agent={resolved_agent_id}, "
            f"session={session_id}, query={query[:80]}"
        )

        from config import conf
        max_context_turns = conf().get("agent_max_context_turns", 20)

        # 获得完整的系统提示与技能
        full_system_prompt = agent.get_full_system_prompt()

        # 为本次执行创建消息副本
        with agent.messages_lock:
            messages_copy = agent.messages.copy()
            original_length = len(agent.messages)

        from agent.protocol.agent_stream import AgentStreamExecutor

        # 注册取消令牌，让 /cancel 能中止正在进行的本轮运行：
        # API 调用可按 request 维度取消，IM 通道则仍以会话为作用域。
        from agent.protocol import get_cancel_registry, get_steer_registry
        registry = get_cancel_registry()
        steer_registry = get_steer_registry()
        scoped_session_key = (
            self.agent_bridge._cancel_key(
                resolved_agent_id,
                session_id,
                self.agent_bridge.agent_registry.default_agent_id,
            )
            if session_id
            else None
        )
        cancel_key = (
            self.agent_bridge._cancel_key(
                resolved_agent_id,
                request_id,
                self.agent_bridge.agent_registry.default_agent_id,
            )
            if request_id
            else scoped_session_key
        )
        # 令牌与其会话分组都做了命名空间隔离：即使两个代理
        # 服务于同一个会话 ID，也不得相互取消或越权操控对方。
        cancel_event = (
            registry.register(cancel_key, session_id=scoped_session_key)
            if cancel_key
            else None
        )
        steer_inbox = (
            steer_registry.register(scoped_session_key) if scoped_session_key else None
        )

        executor = AgentStreamExecutor(
            agent=agent,
            model=agent.model,
            system_prompt=full_system_prompt,
            tools=agent.tools,
            max_turns=agent.max_steps,
            on_event=on_event,
            messages=messages_copy,
            max_context_turns=max_context_turns,
            cancel_event=cancel_event,
            steer_inbox=steer_inbox,
        )

        try:
            if cancel_event is not None and cancel_event.is_set():
                logger.info(
                    f"[ChatService] Skipping pre-cancelled run: agent={resolved_agent_id}, "
                    f"session={session_id}"
                )
                return
            response = executor.run_stream(query)
        except Exception:
            # 如果执行器清除消息（上下文溢出），则同步回来
            if len(executor.messages) == 0:
                with agent.messages_lock:
                    agent.messages.clear()
                    logger.info("[ChatService] Cleared agent message history after executor recovery")
            raise
        finally:
            # 清除“运行中”标志，让空闲扫描能再次审视该会话。
            self._mark_run_active(agent, False)
            # 释放取消令牌，避免注册表无限膨胀。
            if cancel_key:
                try:
                    registry.unregister(cancel_key)
                except Exception:
                    pass
            if scoped_session_key and steer_inbox is not None:
                steer_registry.unregister(scoped_session_key, steer_inbox)

        # 未以 turn_end 收尾便结束的运行（例如最后一轮没有工具结果
        # 需要刷新），也必须把 send 工具上传的内容补发出去。
        flush_file_links()

        # 把执行器消息同步回代理（线程安全）。
        # 执行器可能已修剪过上下文，使其消息列表短于
        # 原始长度。此时必须整体替换——若只是简单
        # 追加，agent.messages 中会残留修剪前的旧消息，
        # 导致每个后续请求都重复触发同样的修剪。
        with agent.messages_lock:
            trimmed = len(executor.messages) < original_length
            if trimmed:
                # 上下文被修剪过：执行器是在修剪前追加用户查询的，
                # 因此新增消息（用户 + 助手 + 工具）都排在修剪后列表的末尾。
                # 不能直接按 original_length 切片（该值已大于修剪后的
                # 列表长度），而要计算执行器在“修剪后基线”之上新增了多少条。
                #
                # executor.run_stream 内部的时间线：
                #   1. 消息共有 `original_length` 条
                #   2. 追加用户查询 → original_length + 1
                #   3. _trim_messages() 修剪为某个更小的数字（其中仍包含
                #      用户查询，因为它属于最后一轮，不会被裁掉）
                #   4. 再追加 LLM 回复 / 工具调用
                #
                # 用户查询消息永远是最后一轮的第一条（它不可能被裁掉），
                # 所以只要定位到它，就能确定“新增消息”从哪里开始。
                new_start = original_length  # 后备
                for idx in range(len(executor.messages) - 1, -1, -1):
                    msg = executor.messages[idx]
                    if msg.get("role") == "user":
                        content = msg.get("content", [])
                        is_user_query = False
                        if isinstance(content, list):
                            has_text = any(
                                isinstance(b, dict) and b.get("type") == "text"
                                for b in content
                            )
                            has_tool_result = any(
                                isinstance(b, dict) and b.get("type") == "tool_result"
                                for b in content
                            )
                            is_user_query = has_text and not has_tool_result
                        elif isinstance(content, str):
                            is_user_query = True
                        if is_user_query:
                            new_start = idx
                            break
                new_messages = list(executor.messages[new_start:])
            else:
                new_messages = list(executor.messages[original_length:])
            agent.messages = list(executor.messages)

        # 将新消息保留到 SQLite，以便它们在重新启动后仍然存在
        # 可以通过HISTORY接口查询。
        if new_messages:
            self._persist_messages(
                session_id,
                list(new_messages),
                channel_type,
                workspace_root=agent.workspace_dir,
            )

        # 保存执行器引用，供 file_to_send 相关逻辑访问
        agent.stream_executor = executor

        # 执行后处理工具
        agent._execute_post_process_tools()

        # 记录本轮用户交互，供自我演化的空闲触发使用。
        # 流式路径绕过了 agent_bridge.agent_reply，因此必须在这里
        # 补记这次活动，否则空闲扫描将永远收不到演化信号。
        self._note_evolution_turn(agent, context)

        logger.info(
            f"[ChatService] Agent run completed: agent={resolved_agent_id}, "
            f"session={session_id}"
        )



    @staticmethod
    def _build_context(
        query: str, session_id: str, channel_type: str, agent_id: str = "default"
    ):
        """Build a Context for tool resolution on the streaming chat path.

        receiver falls back to session_id; the scheduler's delivery keys on
        session_id as the receiver.
        """
        from bridge.context import Context, ContextType
        # 显式传入 kwargs 字典：Context 的默认 kwargs 是共享的
        # 可变默认值，省略它会导致字段跨会话泄漏。
        ctx = Context(ContextType.TEXT, query, kwargs={})
        ctx["session_id"] = session_id
        ctx["receiver"] = session_id
        ctx["isgroup"] = False
        ctx["channel_type"] = channel_type or ""
        ctx["agent_id"] = agent_id
        return ctx

    def _attach_context_aware_tools(self, agent, context):
        """Attach the current context to tools that need turn metadata."""
        try:
            if not (context and getattr(agent, "tools", None)):
                return
            for tool in agent.tools:
                if tool.name == "scheduler":
                    from agent.tools.scheduler.integration import attach_scheduler_to_tool
                    attach_scheduler_to_tool(tool, context)
                elif tool.name == "agent_delegate":
                    from agent.tools.agent_delegate.agent_delegate import attach_agent_delegate_to_tool
                    attach_agent_delegate_to_tool(tool, self.agent_bridge, context)
        except Exception as e:
            logger.warning(f"[ChatService] Failed to attach context to scheduler: {e}")

    @staticmethod
    def _mark_run_active(agent, active):
        """Toggle the self-evolution mid-run flag for this session's agent."""
        try:
            from agent.evolution.trigger import mark_run_active
            mark_run_active(agent, active)
        except Exception:
            pass

    @staticmethod
    def _note_evolution_turn(agent, context):
        """Record a user turn so the self-evolution idle trigger has signal."""
        try:
            from agent.evolution.trigger import note_user_turn
            ch = (context.get("channel_type") or "") if context else ""
            rcv = (context.get("receiver") or "") if context else ""
            is_group = bool(context.get("isgroup")) if context else False
            # 只有单聊才能获得主动推送目标；群推很吵。
            note_user_turn(agent, channel_type=ch, receiver=(rcv if not is_group else ""))
        except Exception:
            pass

    @staticmethod
    def _persist_messages(
        session_id: str,
        new_messages: list,
        channel_type: str = "",
        workspace_root: str = None,
    ):
        try:
            from config import conf
            if not conf().get("conversation_persistence", True):
                return
        except Exception:
            pass
        try:
            from agent.memory import get_conversation_store
            get_conversation_store(workspace_root).append_messages(
                session_id, new_messages, channel_type=channel_type
            )
        except Exception as e:
            logger.warning(
                f"[ChatService] Failed to persist messages for session={session_id}: {e}"
            )


class _StreamState:
    """Mutable state shared between the event callback and the run method."""

    def __init__(self):
        self.segment_id: int = 0
        # None 表示当前没有在积累工具结果；
        # 非空列表表示正处于工具执行阶段。
        self.pending_tool_results: Optional[list] = None
        # 记录 tool_call_id -> 参数的映射（取自 tool_execution_start），
        # 以便 tool_execution_end 能补上对应的输入参数。
        self.pending_tool_arguments: dict = {}
        # send 工具上传的文件的 Markdown 链接，先暂存到回合结束、
        # 工具结果刷新之后再发出。当 send 工具报告文件时，它会在
        # 该工具的 start 与 result 事件之间插入正文——其他工具不会
        # 这样做——这让客户端无法自行把二者配对起来。
        self.pending_file_links: list = []
