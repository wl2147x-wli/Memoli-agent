"""会话管理模块。

第三阶段先实现内存会话历史：

- 使用 session_key 区分不同会话。
- 记录用户消息和助手消息。
- 按 history_window 保留最近 N 条消息。

当前不做磁盘持久化，后续记忆阶段再接入长期存储。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> datetime:
    """返回带时区的 UTC 时间。"""

    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class SessionMessage:
    """会话中的一条历史消息。"""

    role: str
    content: str
    timestamp: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Session:
    """单个会话的内存状态。"""

    session_key: str
    history_window: int
    _history: list[SessionMessage] = field(default_factory=list)

    def add_user_message(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """写入一条用户消息。"""

        self._append("user", content, metadata)

    def add_assistant_message(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """写入一条助手回复。"""

        self._append("assistant", content, metadata)

    def get_history(self) -> list[SessionMessage]:
        """返回当前会话历史副本。"""

        return list(self._history)

    def _append(
        self,
        role: str,
        content: str,
        metadata: dict[str, Any] | None,
    ) -> None:
        """追加消息并按窗口裁剪历史。"""

        self._history.append(
            SessionMessage(
                role=role,
                content=content,
                metadata=dict(metadata or {}),
            )
        )
        self._trim_history()

    def _trim_history(self) -> None:
        """只保留最近 history_window 条消息。"""

        if self.history_window <= 0:
            self._history.clear()
            return

        if len(self._history) > self.history_window:
            self._history = self._history[-self.history_window :]


@dataclass(slots=True)
class SessionManager:
    """按 session_key 管理多个内存会话。"""

    history_window: int
    _sessions: dict[str, Session] = field(default_factory=dict)

    def get_or_create(self, session_key: str) -> Session:
        """获取已有会话，不存在时创建新会话。"""

        if session_key not in self._sessions:
            self._sessions[session_key] = Session(
                session_key=session_key,
                history_window=self.history_window,
            )
        return self._sessions[session_key]
