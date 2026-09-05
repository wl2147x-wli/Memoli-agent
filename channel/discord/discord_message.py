"""
Discord message adapter.

Convert a discord.py Message into cow's unified ChatMessage.
File downloads are NOT performed here; the channel layer downloads
attachments on demand inside the async event loop.
"""
from bridge.context import ContextType
from channel.chat_message import ChatMessage
from common import state_dir


class DiscordMessage(ChatMessage):
    """Wrap a discord.py Message into the unified ChatMessage."""

    def __init__(self, message, is_group: bool = False, bot_user_id: str = "",
                 ctype: ContextType = ContextType.TEXT, content: str = ""):
        super().__init__(message)
        # 基础字段
        self.msg_id = str(message.id)
        self.create_time = int(message.created_at.timestamp()) if message.created_at else 0
        self.ctype = ctype
        self.content = content

        author = message.author
        channel = message.channel

        # 发件人/聊天信息
        from_user_id = str(author.id)
        from_user_nick = getattr(author, "display_name", None) or getattr(author, "name", None) or from_user_id
        self.from_user_id = from_user_id
        self.from_user_nickname = from_user_nick
        self.to_user_id = bot_user_id or "discord_bot"
        self.to_user_nickname = bot_user_id or "discord_bot"

        self.is_group = is_group
        if is_group:
            # 公会频道：other_user_id=channel_id,actual_user_id=发送者id
            self.other_user_id = str(channel.id)
            self.other_user_nickname = getattr(channel, "name", None) or str(channel.id)
            self.actual_user_id = from_user_id
            self.actual_user_nickname = from_user_nick
        else:
            # DM：使用channel_id，以便回复返回到同一个 DM 频道
            self.other_user_id = str(channel.id)
            self.other_user_nickname = from_user_nick

        # 机器人是否由@-mention触发（由通道层设置）
        self.is_at = False

    @staticmethod
    def get_tmp_dir() -> str:
        """Local download directory, aligned with other channels (workspace tmp)."""
        return str(state_dir.tmp_dir())
