"""
Slack message adapter.

Convert a Slack event payload into cow's unified ChatMessage.
File downloads are NOT performed here; the channel layer downloads files
on demand because it needs the bot token for authenticated download URLs.
"""
from bridge.context import ContextType
from channel.chat_message import ChatMessage
from common import state_dir


class SlackMessage(ChatMessage):
    """Wrap a Slack event into the unified ChatMessage."""

    def __init__(self, event: dict, is_group: bool = False, bot_user_id: str = "",
                 ctype: ContextType = ContextType.TEXT, content: str = ""):
        super().__init__(event)
        # 基础字段
        self.msg_id = event.get("client_msg_id") or event.get("ts") or ""
        try:
            self.create_time = int(float(event.get("ts", 0)))
        except (TypeError, ValueError):
            self.create_time = 0
        self.ctype = ctype
        self.content = content

        # 发件人/聊天信息
        from_user_id = event.get("user", "unknown")
        channel_id = event.get("channel", "")
        self.from_user_id = from_user_id
        self.from_user_nickname = from_user_id
        self.to_user_id = bot_user_id or "slack_bot"
        self.to_user_nickname = bot_user_id or "slack_bot"

        self.is_group = is_group
        if is_group:
            # 频道聊天： other_user_id = 频道_id，actual_user_id = 发送者id
            self.other_user_id = channel_id
            self.other_user_nickname = channel_id
            self.actual_user_id = from_user_id
            self.actual_user_nickname = from_user_id
        else:
            # DM：使用channel_id，以便回复返回到同一个 DM 频道
            self.other_user_id = channel_id or from_user_id
            self.other_user_nickname = from_user_id

        # 机器人是否由@-mention触发（由通道层设置）
        self.is_at = False

    @staticmethod
    def get_tmp_dir() -> str:
        """Local download directory, aligned with other channels (workspace tmp)."""
        return str(state_dir.tmp_dir())
