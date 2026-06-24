"""消息和事件类型定义。

第一阶段只需要最小对话闭环，因此这里只定义两个消息类型：

- InboundMessage：从外部通道进入 agent 的消息。
- OutboundMessage：agent 处理完成后准备发回外部通道的消息。

后续阶段可以继续在这里增加内部事件，例如 subagent 完成事件、
定时任务事件、主动消息事件等。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    """返回当前 UTC 时间。

    使用 timezone-aware datetime，避免后续跨时区和持久化时出现歧义。
    """

    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class InboundMessage:
    """从 channel 进入主 agent 的入站消息。"""

    channel: str
    chat_id: str
    sender: str
    content: str
    timestamp: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def session_key(self) -> str:
        """返回会话唯一标识。

        第一阶段先用 channel + chat_id 组成会话键。
        后续如果接入多用户群聊，可在这里扩展 sender 或 thread 信息。
        """

        return f"{self.channel}:{self.chat_id}"


@dataclass(frozen=True)
class OutboundMessage:
    """从主 agent 发回 channel 的出站消息。"""

    channel: str
    chat_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
