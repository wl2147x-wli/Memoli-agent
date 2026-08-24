"""会话管理模块。

跨轮上下文事实由 trajectory store 的 canonical committed turn 提供（§2），
Session 只维护身份与瞬态控制状态，不再维护消息历史副本，也不按消息条数提前
裁剪压缩来源（§3.1）。``conversation_epoch`` 为进程内瞬态镜像，权威值由
``CrossTurnContextPhase`` 从 trajectory store 读取；``/clear`` 成功后推进该值（§3.3）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(slots=True)
class Session:
    """单个会话的瞬态控制状态。

    跨轮上下文事实（canonical turn）由 trajectory store 持久化，Session 不再
    保存消息历史副本。``conversation_epoch`` 为进程内瞬态镜像，仅作快速可见与
    /clear 后回退之用；权威 epoch 恒由 ``CrossTurnContextPhase`` 从 trajectory
    store 读取，重启后即使镜像过期也会被权威值覆盖。
    """

    session_key: str
    session_instance_id: str = field(default_factory=lambda: uuid4().hex)
    conversation_epoch: int = 1


@dataclass(slots=True)
class SessionManager:
    """按 session_key 管理多个内存会话。"""

    _sessions: dict[str, Session] = field(default_factory=dict)

    def get_or_create(self, session_key: str) -> Session:
        """获取已有会话，不存在时创建新会话。"""

        if session_key not in self._sessions:
            self._sessions[session_key] = Session(session_key=session_key)
        return self._sessions[session_key]

    def clear(self, session_key: str) -> bool:
        """清除当前进程的瞬态控制状态，不触碰轨迹/payload/记忆/working-state。

        持久 epoch 边界由 ``/clear`` 命令在 trajectory store 成功推进后显式建立；
        本方法只重置进程内 Session 实例（下次 ``get_or_create`` 重建，
        ``conversation_epoch`` 回到镜像默认，权威值仍由 store 决定），属 §3.3
        「重置派生 context 状态」的进程内部分。
        """

        return self._sessions.pop(session_key, None) is not None
