"""
Message sending channel abstract class
"""

from bridge.bridge import Bridge
from bridge.context import Context
from bridge.reply import *
from common.log import logger
from config import conf


class Channel(object):
    channel_type = ""
    NOT_SUPPORT_REPLYTYPE = [ReplyType.VOICE, ReplyType.IMAGE]

    def __init__(self):
        import threading
        self._startup_event = threading.Event()
        self._startup_error = None
        self.cloud_mode = False  # 与云客户端一起运行时由ChannelManager设置为True
        # 多实例支持。所有可选且默认为空，因此
        # 旧版单实例通道的行为与以前完全相同：
        #   -instance_id：该通道实例的唯一ID（==channel_type
        #     对于传统的单实例通道）。
        #   -bound_agent_id：此实例路由入站消息的代理
        #     到；空意味着“回退到基于配置的路由”。
        #   - _creds：每个实例的凭证覆盖。当为空时，cfg()
        #     直接从全局conf()读取，即遗留行为。
        self.instance_id = ""
        self.bound_agent_id = ""
        self._creds = {}
        # 该实例的所有者 (bound_agent_id) 可以向队友交付工作。
        # 对于独奏机器人来说是空的。注入到每个入站消息的上下文中，以便
        # 共享的委托/@提及机制将对话视为
        # 团队，就像网络团队对话一样。
        self.members = []

    def cfg(self, key, default=None):
        """Read a config value, preferring this instance's credential override.

        Channels must read their credentials through this instead of ``conf()``
        directly so that several instances of the same channel type can each
        carry their own app_id / secret / token. With no override present
        (the default), this is exactly ``conf().get(key, default)``.
        """
        if self._creds and key in self._creds:
            value = self._creds.get(key)
            if value is not None:
                return value
        return conf().get(key, default)

    def apply_instance(self, instance_id="", bound_agent_id="", credentials=None, members=None):
        """Attach multi-instance identity, credentials and team to this channel.

        Called by the factory/manager only on the new multi-instance path;
        legacy startup never calls it, leaving the instance in its default
        single-instance state.
        """
        if instance_id:
            self.instance_id = instance_id
        if bound_agent_id:
            self.bound_agent_id = bound_agent_id
        if credentials:
            self._creds = dict(credentials)
        if members is not None:
            self.members = list(members)
        return self

    def stamp_instance_context(self, context):
        """Inject this instance's routing identity onto an inbound context.

        A channel bound to a specific Agent (multi-instance path) stamps every
        inbound message with its ``bound_agent_id`` so the router sends it there
        rather than falling through to config-based channel_type routing; its
        ``instance_id`` and team ``members`` ride along for logging and team
        handling. All empty on a legacy single-instance channel, so the old
        routing stays intact. Channels that subclass ChatChannel inherit this
        via the base ``_compose_context``; channels that override
        ``_compose_context`` (feishu, telegram, ...) call it explicitly.
        """
        if context is None:
            return context
        bound = getattr(self, "bound_agent_id", "")
        if bound and "bound_agent_id" not in context:
            context["bound_agent_id"] = bound
        if "instance_id" not in context and getattr(self, "instance_id", ""):
            context["instance_id"] = self.instance_id
        members = getattr(self, "members", None)
        if members and "members" not in context:
            context["members"] = list(members)
        return context

    def startup(self):
        """
        init channel
        """
        raise NotImplementedError

    def report_startup_success(self):
        self._startup_error = None
        self._startup_event.set()

    def report_startup_error(self, error: str):
        self._startup_error = error
        self._startup_event.set()

    def wait_startup(self, timeout: float = 3) -> (bool, str):
        """
        Wait for channel startup result.
        Returns (success: bool, error_msg: str).
        """
        ready = self._startup_event.wait(timeout=timeout)
        if not ready:
            return True, ""
        if self._startup_error:
            return False, self._startup_error
        return True, ""

    def stop(self):
        """
        stop channel gracefully, called before restart
        """
        pass

    def handle_text(self, msg):
        """
        process received msg
        :param msg: message object
        """
        raise NotImplementedError

    # 统一的发送函数，每个Channel自行实现，根据reply的type字段发送不同类型的消息
    def send(self, reply: Reply, context: Context):
        """
        send message to user
        :param msg: message content
        :param receiver: receiver channel account
        :return:
        """
        raise NotImplementedError

    def build_reply_content(self, query, context: Context = None) -> Reply:
        """
        Build reply content, using agent if enabled in config
        """
        # 检查代理模式是否开启
        use_agent = conf().get("agent", True)

        if use_agent:
            try:
                logger.info("[Channel] Using agent mode")

                # 如果不存在，则将channel_type添加到上下文中
                if context and "channel_type" not in context:
                    context["channel_type"] = self.channel_type

                # 读取通道注入的 on_event 回调（例如 Web SSE）
                on_event = context.get("on_event") if context else None

                # 使用代理桥来处理查询
                return Bridge().fetch_agent_reply(
                    query=query,
                    context=context,
                    on_event=on_event,
                    clear_history=False
                )
            except Exception as e:
                logger.error(f"[Channel] Agent mode failed, fallback to normal mode: {e}")
                # 如果代理失败则回退到正常模式
                return Bridge().fetch_reply_content(query, context)
        else:
            # 普通模式
            return Bridge().fetch_reply_content(query, context)

    def build_voice_to_text(self, voice_file) -> Reply:
        return Bridge().fetch_voice_to_text(voice_file)

    def build_text_to_voice(self, text) -> Reply:
        return Bridge().fetch_text_to_voice(text)
