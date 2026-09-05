"""
Integration module for scheduler with AgentBridge
"""

import os
import threading
from typing import Dict, Optional
from config import conf
from common.log import logger
from common.utils import expand_path
from bridge.context import Context, ContextType
from bridge.reply import Reply, ReplyType

# 兼容旧代码的别名，指向配置中的默认代理。
_scheduler_service = None
_task_store = None
_scheduler_services: Dict[str, object] = {}
_task_stores: Dict[str, object] = {}
# 模块级锁：保证跨线程的初始化是幂等的
_init_lock = threading.RLock()


def _resolve_workspace(workspace_root: str = None, agent_id: str = None):
    """An explicit workspace wins, then an explicit agent_id, then the routed
    identity. An agent_id that does not resolve raises: falling back to the
    default workspace here would silently file one Agent's tasks under
    another."""
    if workspace_root is not None:
        return os.path.realpath(expand_path(str(workspace_root)))
    from common.runtime_identity import current_identity
    from common.state_dir import state_root

    identity = current_identity()
    if agent_id:
        identity = identity.derive(agent_id=agent_id)
    return str(state_root(identity))


def init_scheduler(agent_bridge, workspace_root: str = None, agent_id: str = None) -> bool:
    """
    Initialize scheduler service (idempotent).

    Safe to call multiple times and from multiple threads: only the first
    successful call creates the singleton ``SchedulerService`` + background
    scanning thread. Subsequent calls return immediately.

    Args:
        agent_bridge: AgentBridge instance

    Returns:
        True if scheduler is initialized (newly created or already running)
    """
    global _scheduler_service, _task_store
    workspace_root = _resolve_workspace(workspace_root, agent_id)
    agent_id = agent_bridge.agent_registry.get(agent_id).id

    # 快速路径：已初始化并正在运行
    service = _scheduler_services.get(workspace_root)
    if service is not None and getattr(service, "running", False):
        return True

    with _init_lock:
        # 在锁内再次检查，避免竞态：多个线程可能
        # 在任何一个获得锁之前就通过了上面的快速路径检查。
        service = _scheduler_services.get(workspace_root)
        if service is not None and getattr(service, "running", False):
            return True

        try:
            from agent.tools.scheduler.task_store import TaskStore
            from agent.tools.scheduler.scheduler_service import SchedulerService

            from common.state_dir import scheduler_file

            store_path = str(scheduler_file(base=workspace_root))

            # 创建任务存储（如果已创建则重复使用）
            task_store = _task_stores.get(workspace_root)
            if task_store is None:
                task_store = TaskStore(store_path)
                _task_stores[workspace_root] = task_store
                logger.debug(f"[Scheduler] Task store initialized: {store_path}")

            # 创建执行回调：成功返回 True，失败返回 False，
            # 让调度器在下个时钟周期重试（例如进程刚启动、
            # 通道尚未就绪等情形）。
            def execute_task_callback(task: dict):
                # 调度线程自身没有身份，需要把它绑定到当前代理。
                # 这与 chat_channel._handle 的做法对应：由任务触发的
                # 下游代码（ToolManager、tmp_dir、memory 等）便会落在
                # 该代理自己的工作区，而不是默认工作区。
                from common.runtime_identity import identity_scope

                try:
                    with identity_scope(agent_id=agent_id):
                        action = task.get("action", {})
                        action_type = action.get("type")
                        channel_type = _primary_channel_type(action.get("channel_type"))
                        receiver = action.get("receiver", "")

                        if not _is_channel_ready(channel_type, receiver, agent_id):
                            logger.warning(
                                f"[Scheduler] Task {task.get('id')}: channel "
                                f"'{channel_type}' not ready for receiver={receiver} "
                                f"(no inbound msg cached since restart?); deferring"
                            )
                            return False

                        if action_type == "agent_task":
                            return _execute_agent_task(task, agent_bridge, agent_id)
                        elif action_type == "send_message":
                            return _execute_send_message(task, agent_bridge, agent_id)
                        elif action_type == "tool_call":
                            return _execute_tool_call(task, agent_bridge, agent_id)
                        elif action_type == "skill_call":
                            return _execute_skill_call(task, agent_bridge, agent_id)
                        else:
                            logger.warning(f"[Scheduler] Unknown action type: {action_type}")
                            return True
                except Exception as e:
                    logger.error(f"[Scheduler] Error executing task {task.get('id')}: {e}")
                    return False

            # 创建调度程序服务
            service = SchedulerService(task_store, execute_task_callback)
            service.start()
            _scheduler_services[workspace_root] = service
            if agent_id == agent_bridge.agent_registry.default_agent_id:
                _scheduler_service = service
                _task_store = task_store

            logger.info(
                f"[Scheduler] Service initialized for agent={agent_id}, "
                f"workspace={workspace_root}"
            )
            return True

        except Exception as e:
            logger.error(f"[Scheduler] Failed to initialize scheduler: {e}")
            return False


def _primary_channel_type(raw) -> str:
    """Normalize a task's stored channel_type to a single channel name.

    config.json allows a comma-joined value (e.g. "feishu,dingtalk") that
    app.py splits into several channels at startup. A scheduled task, though,
    delivers to one place, and create_channel() only understands a single type
    — passing the whole "feishu,dingtalk" string lands in its `else: raise`.
    Take the first non-empty entry so a task copied from that config still
    delivers instead of failing every tick.
    """
    if not raw:
        return "unknown"
    first = str(raw).split(",")[0].strip()
    return first or "unknown"


def _is_channel_ready(
    channel_type: str, receiver: str, agent_id: str = None
) -> bool:
    """Best-effort readiness probe for outbound channels.

    Returns False when we know the send will drop (e.g. weixin not yet
    logged in, web session has no polling queue), so the scheduler can
    defer instead of consuming the task. Unknown channels return True
    to preserve previous behaviour.
    """
    if not channel_type or channel_type == "unknown":
        return True
    try:
        from channel.channel_factory import create_channel
        channel = create_channel(channel_type)
        if channel is None:
            return False

        if channel_type == "weixin":
            tokens = getattr(channel, "_context_tokens", None)
            if not tokens or receiver not in tokens:
                return False
            return True

        if channel_type == "web":
            if hasattr(channel, "has_session_queue"):
                return channel.has_session_queue(receiver, agent_id)
            queues = getattr(channel, "session_queues", None)
            if not queues or receiver not in queues:
                return False
            return True

        return True
    except Exception as e:
        logger.warning(f"[Scheduler] Channel readiness check failed for {channel_type}: {e}")
        return True


def get_task_store(workspace_root: str = None, agent_id: str = None):
    """Get the task store owned by one agent workspace."""
    workspace_root = _resolve_workspace(workspace_root, agent_id)
    return _task_stores.get(workspace_root)


def get_scheduler_service(workspace_root: str = None, agent_id: str = None):
    """Get the scheduler service owned by one agent workspace."""
    workspace_root = _resolve_workspace(workspace_root, agent_id)
    return _scheduler_services.get(workspace_root)


def reset_scheduler_services(stop: bool = True) -> None:
    """Stop and forget all scheduler services, primarily for reloads/tests."""
    global _scheduler_service, _task_store
    with _init_lock:
        if stop:
            for service in list(_scheduler_services.values()):
                try:
                    service.stop()
                except Exception:
                    pass
        _scheduler_services.clear()
        _task_stores.clear()
        _scheduler_service = None
        _task_store = None


def stop_scheduler(agent_id: str = None, workspace_root: str = None) -> bool:
    """Stop and forget a single Agent's scheduler service, leaving the rest of
    the fleet running. Used when an Agent is archived/removed so a roster edit
    does not have to reset every scheduler. Returns True if one was found.

    The actual stop is detached to a daemon thread: ``service.stop()`` joins the
    scan loop (up to a few seconds), and a roster edit should not block the HTTP
    response on that. We drop the service from the registry synchronously so it
    is immediately forgotten; the thread just winds the loop down."""
    workspace_root = _resolve_workspace(workspace_root, agent_id)
    with _init_lock:
        service = _scheduler_services.pop(workspace_root, None)
        _task_stores.pop(workspace_root, None)
    if service is None:
        return False
    threading.Thread(
        target=lambda: _safe_stop(service), daemon=True, name="scheduler-stop"
    ).start()
    return True


def _safe_stop(service) -> None:
    try:
        service.stop()
    except Exception:
        pass


def _remember_delivered_output(
    agent_bridge,
    task: dict,
    channel_type: str,
    content: str,
    agent_id: str = None,
) -> None:
    """Best-effort persistence of the message the scheduler sent to a user.

    Uses notify_session_id (the real chat session_id stored at task creation time)
    so that group chats correctly associate the output with the user's conversation.
    Falls back to receiver for backward compatibility with old tasks.

    Per-action-type behaviour:
        - agent_task / tool_call / skill_call: gated by ``scheduler_inject_to_session``
          (default True). These produce AI-generated content worth remembering.
        - send_message: additionally gated by ``scheduler_inject_send_message``
          (default False). Fixed reminder text rarely benefits follow-up Q&A and
          would just consume context tokens.
    """
    if not content:
        return
    action = task.get("action", {})
    action_type = action.get("type", "")

    # send_message 默认不被注入；通过配置显式选择加入。
    if action_type == "send_message":
        if not conf().get("scheduler_inject_send_message", False):
            return

    session_id = action.get("notify_session_id") or action.get("receiver")
    if not session_id:
        return
    try:
        remember = getattr(agent_bridge, "remember_scheduled_output", None)
        if remember:
            task_desc = action.get("task_description") or action.get("content", "")
            kwargs = {
                "channel_type": channel_type,
                "task_description": task_desc,
            }
            if hasattr(agent_bridge, "agent_registry"):
                kwargs["agent_id"] = agent_id
            remember(session_id, str(content), **kwargs)
    except Exception as e:
        logger.warning(
            f"[Scheduler] Failed to remember delivered output for {session_id}: {e}"
        )


def _execute_agent_task(task: dict, agent_bridge, agent_id: str = None) -> bool:
    """
    Execute an agent_task action - let Agent handle the task.
    Returns True on successful delivery, False to retry next tick.
    """
    try:
        action = task.get("action", {})
        task_description = action.get("task_description")
        receiver = action.get("receiver")
        is_group = action.get("is_group", False)
        channel_type = _primary_channel_type(action.get("channel_type"))
        
        if not task_description:
            logger.error(f"[Scheduler] Task {task['id']}: No task_description specified")
            return True  # 任务格式有误，避免无限重试
        
        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return True
        
        # 检查是否有不支持的频道
        if channel_type == "dingtalk":
            logger.warning(f"[Scheduler] Task {task['id']}: DingTalk channel does not support scheduled messages (Stream mode limitation). Task will execute but message cannot be sent.")
        
        logger.info(f"[Scheduler] Task {task['id']}: Executing agent task '{task_description}'")

        # 用“立即执行”指令包装原始描述。存储的描述通常
        # 写成规则形式（例如“每天 08:00 发送...”）。若不加此前缀，
        # 代理可能会把它当作需要确认的规则说明，而不是需要
        # 立即执行的任务，尤其在任务此前运行失败之后更是如此。
        execution_prompt = (
            "这是一个定时任务的立即执行请求，当前已到执行时刻。"
            "请直接完成下面描述的任务并产出最终交付内容，"
            "无需复述、确认或讨论任务规则，不要输出任务指令或调试信息。"
            "若执行失败，返回简洁明确的失败说明。\n\n"
            f"任务描述：\n{task_description}"
        )

        # 为定时任务创建独立的 session_id，避免污染用户的对话。
        # 格式：scheduler_<receiver>_<task_id>，以便与普通对话隔离。
        scheduler_session_id = f"scheduler_{receiver}_{task['id']}"
        
        # 为代理创建上下文
        context = Context(ContextType.TEXT, execution_prompt)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = scheduler_session_id
        context["agent_id"] = agent_id
        
        # 特定于通道的设置
        if channel_type == "web":
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
        elif channel_type == "feishu":
            context["receive_id_type"] = "chat_id" if is_group else "open_id"
            context["msg"] = None
        elif channel_type == "dingtalk":
            # 钉钉发送需要 msg 对象；定时任务没有，置为 None
            context["msg"] = None
            if not is_group:
                sender_staff_id = action.get("dingtalk_sender_staff_id")
                if sender_staff_id:
                    context["dingtalk_sender_staff_id"] = sender_staff_id
        elif channel_type == "wecom_bot":
            context["msg"] = None

        # 交由 Agent 执行任务
        # 标记为定时任务执行，避免递归地创建任务
        context["is_scheduled_task"] = True
        
        try:
            # 不清除历史记录：定时任务使用独立的 session_id，不会污染用户的对话
            reply = agent_bridge.agent_reply(execution_prompt, context=context, on_event=None, clear_history=False)

            if not (reply and reply.content):
                # 空结果也属正常：任务已运行，但判定没有值得
                # 汇报的内容（如有条件的提醒、未触发告警的监控）。
                # 此时不会发送任何消息，仅此为止。
                logger.info(
                    f"[Scheduler] Task {task['id']}: agent produced no content, nothing to send"
                )
                return True

            if action.get("silent", False):
                logger.info(
                    f"[Scheduler] Task {task['id']} executed successfully in silent mode"
                )
                return True

            from channel.channel_factory import create_channel
            channel = create_channel(channel_type)
            if not channel:
                logger.error(f"[Scheduler] Failed to create channel: {channel_type}")
                return False

            if channel_type == "web" and hasattr(channel, 'request_to_session'):
                request_id = context.get("request_id")
                if request_id:
                    channel.request_to_session[request_id] = receiver

            try:
                channel.send(reply, context)
            except Exception as e:
                logger.error(f"[Scheduler] Failed to send result: {e}")
                return False

            _remember_delivered_output(
                agent_bridge, task, channel_type, reply.content, agent_id
            )
            logger.info(f"[Scheduler] Task {task['id']} executed successfully, result sent to {receiver}")
            return True

        except Exception as e:
            logger.error(f"[Scheduler] Failed to execute task via Agent: {e}")
            import traceback
            logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
            return False

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_agent_task: {e}")
        import traceback
        logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
        return False


def _execute_send_message(task: dict, agent_bridge, agent_id: str = None) -> bool:
    """Execute a send_message action. Returns True/False for delivery."""
    try:
        action = task.get("action", {})
        content = action.get("content", "")
        receiver = action.get("receiver")
        is_group = action.get("is_group", False)
        channel_type = _primary_channel_type(action.get("channel_type"))
        
        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return True
        
        # 创建发送消息的上下文
        context = Context(ContextType.TEXT, content)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = receiver
        context["agent_id"] = agent_id
        
        # 特定于通道的上下文设置
        if channel_type == "web":
            # Web 渠道需要 request_id
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
            logger.debug(f"[Scheduler] Generated request_id for web channel: {request_id}")
        elif channel_type == "feishu":
            # 飞书频道：定时任务以新消息形式发送（没有可回复的 msg_id），
            # 群聊使用 chat_id，单聊使用 open_id
            context["receive_id_type"] = "chat_id" if is_group else "open_id"
            # 保持 isgroup 不变，仅把 msg 置为 None（没有要回复的原消息），
            # 飞书频道据此判断为“发新消息”而不是“回复消息”
            context["msg"] = None
            logger.debug(f"[Scheduler] Feishu: receive_id_type={context['receive_id_type']}, is_group={is_group}, receiver={receiver}")
        elif channel_type == "dingtalk":
            # 钉钉频道设置
            context["msg"] = None
            # 如果是单聊，需要传递 sender_staff_id
            if not is_group:
                sender_staff_id = action.get("dingtalk_sender_staff_id")
                if sender_staff_id:
                    context["dingtalk_sender_staff_id"] = sender_staff_id
                    logger.debug(f"[Scheduler] DingTalk single chat: sender_staff_id={sender_staff_id}")
                else:
                    logger.warning(f"[Scheduler] Task {task['id']}: DingTalk single chat message missing sender_staff_id")
        elif channel_type == "wecom_bot":
            context["msg"] = None
        elif channel_type == "qq":
            context["msg"] = None

        # 创建回复
        reply = Reply(ReplyType.TEXT, content)
        
        # 获取频道并发送
        from channel.channel_factory import create_channel
        
        channel = create_channel(channel_type)
        if not channel:
            logger.error(f"[Scheduler] Failed to create channel: {channel_type}")
            return False

        if channel_type == "web" and hasattr(channel, 'request_to_session'):
            channel.request_to_session[request_id] = receiver

        try:
            channel.send(reply, context)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send message: {e}")
            return False

        _remember_delivered_output(
            agent_bridge, task, channel_type, content, agent_id
        )
        logger.info(f"[Scheduler] Task {task['id']} executed: sent message to {receiver}")
        return True

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_send_message: {e}")
        import traceback
        logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
        return False


def _execute_tool_call(task: dict, agent_bridge, agent_id: str = None) -> bool:
    """Execute a tool_call action. Returns True/False for delivery."""
    try:
        action = task.get("action", {})
        tool_name = action.get("call_name") or action.get("tool_name")
        tool_params = action.get("call_params") or action.get("tool_params", {})
        result_prefix = action.get("result_prefix", "")
        receiver = action.get("receiver")
        is_group = action.get("is_group", False)
        channel_type = _primary_channel_type(action.get("channel_type"))

        if not tool_name:
            logger.error(f"[Scheduler] Task {task['id']}: No tool_name specified")
            return True
        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return True

        from agent.tools.tool_manager import ToolManager
        tool = ToolManager().create_tool(tool_name)
        if not tool:
            logger.error(f"[Scheduler] Task {task['id']}: Tool '{tool_name}' not found")
            return True

        logger.info(f"[Scheduler] Task {task['id']}: Executing tool '{tool_name}' with params {tool_params}")
        result = tool.execute(tool_params)
        content = result.result if hasattr(result, 'result') else str(result)
        if result_prefix:
            content = f"{result_prefix}\n\n{content}"

        context = Context(ContextType.TEXT, content)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = receiver
        context["agent_id"] = agent_id

        request_id = None
        if channel_type == "web":
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
        elif channel_type == "feishu":
            context["receive_id_type"] = "chat_id" if is_group else "open_id"
            context["msg"] = None
        elif channel_type == "wecom_bot":
            context["msg"] = None

        reply = Reply(ReplyType.TEXT, content)

        from channel.channel_factory import create_channel
        channel = create_channel(channel_type)
        if not channel:
            logger.error(f"[Scheduler] Failed to create channel: {channel_type}")
            return False

        if channel_type == "web" and request_id and hasattr(channel, 'request_to_session'):
            channel.request_to_session[request_id] = receiver

        try:
            channel.send(reply, context)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send tool result: {e}")
            return False

        _remember_delivered_output(
            agent_bridge, task, channel_type, content, agent_id
        )
        logger.info(f"[Scheduler] Task {task['id']} executed: sent tool result to {receiver}")
        return True

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_tool_call: {e}")
        return False


def _execute_skill_call(task: dict, agent_bridge, agent_id: str = None) -> bool:
    """Execute a skill_call action by asking Agent to run the skill.
    Returns True/False for delivery."""
    try:
        action = task.get("action", {})
        skill_name = action.get("call_name") or action.get("skill_name")
        skill_params = action.get("call_params") or action.get("skill_params", {})
        result_prefix = action.get("result_prefix", "")
        receiver = action.get("receiver")
        is_group = action.get("isgroup", False)
        channel_type = _primary_channel_type(action.get("channel_type"))

        if not skill_name:
            logger.error(f"[Scheduler] Task {task['id']}: No skill_name specified")
            return True
        if not receiver:
            logger.error(f"[Scheduler] Task {task['id']}: No receiver specified")
            return True

        logger.info(f"[Scheduler] Task {task['id']}: Executing skill '{skill_name}' with params {skill_params}")

        scheduler_session_id = f"scheduler_{receiver}_{task['id']}"
        param_str = ", ".join([f"{k}={v}" for k, v in skill_params.items()])
        query = f"Use {skill_name} skill"
        if param_str:
            query += f" with {param_str}"

        context = Context(ContextType.TEXT, query)
        context["receiver"] = receiver
        context["isgroup"] = is_group
        context["session_id"] = scheduler_session_id
        context["agent_id"] = agent_id

        if channel_type == "web":
            import uuid
            request_id = f"scheduler_{task['id']}_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
        elif channel_type == "feishu":
            context["receive_id_type"] = "chat_id" if is_group else "open_id"
            context["msg"] = None
        elif channel_type == "wecom_bot":
            context["msg"] = None

        try:
            reply = agent_bridge.agent_reply(query, context=context, on_event=None, clear_history=False)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to execute skill via Agent: {e}")
            import traceback
            logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
            return False

        if not (reply and reply.content):
            logger.error(f"[Scheduler] Task {task['id']}: No result from skill execution")
            return True

        content = reply.content
        if result_prefix:
            content = f"{result_prefix}\n\n{content}"

        from channel.channel_factory import create_channel
        channel = create_channel(channel_type)
        if not channel:
            logger.error(f"[Scheduler] Failed to create channel: {channel_type}")
            return False

        if channel_type == "web" and hasattr(channel, 'request_to_session'):
            req_id = context.get("request_id")
            if req_id:
                channel.request_to_session[req_id] = receiver

        try:
            channel.send(Reply(ReplyType.TEXT, content), context)
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send skill result: {e}")
            return False

        _remember_delivered_output(
            agent_bridge, task, channel_type, content, agent_id
        )
        logger.info(f"[Scheduler] Task {task['id']} executed: skill result sent to {receiver}")
        return True

    except Exception as e:
        logger.error(f"[Scheduler] Error in _execute_skill_call: {e}")
        import traceback
        logger.error(f"[Scheduler] Traceback: {traceback.format_exc()}")
        return False


def attach_scheduler_to_tool(tool, context: Context = None):
    """
    Attach scheduler components to a SchedulerTool instance
    
    Args:
        tool: SchedulerTool instance
        context: Current context (optional)
    """
    if context:
        agent_id = context.get("agent_id")
        task_store = get_task_store(agent_id=agent_id)
        scheduler_service = get_scheduler_service(agent_id=agent_id)
        if task_store:
            tool.task_store = task_store
        if scheduler_service:
            tool.scheduler_service = scheduler_service
        tool.current_context = context
        
        channel_type = context.get("channel_type") or conf().get("channel_type", "unknown")
        if not tool.config:
            tool.config = {}
        tool.config["channel_type"] = channel_type
