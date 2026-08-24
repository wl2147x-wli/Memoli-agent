"""agent 核心类型。

这里放跨模块共享的轻量数据结构。第三阶段先定义一轮对话、
上下文请求和渲染结果，后续 provider、runner、工具循环都会复用这些类型。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from memoli_agent.agent.session import Session
from memoli_agent.bus.events import InboundMessage


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """发送给模型的标准消息结构。"""

    role: str
    content: str
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    blocks: tuple[dict[str, Any], ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为 OpenAI-compatible messages 字典。"""

        message: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_call_id is not None:
            message["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            message["name"] = self.name
        if self.tool_calls is not None:
            message["tool_calls"] = self.tool_calls
        return message


@dataclass(frozen=True, slots=True)
class TurnState:
    """一轮对话处理时需要共享的状态。"""

    session_key: str
    inbound: InboundMessage
    session: Session


@dataclass(frozen=True, slots=True)
class ContextRequest:
    """上下文构建请求。

    ``recent_turns`` 由 ``CrossTurnContextPhase`` 从 canonical committed turn
    重构得到（§3.1）；Session 不再提供消息历史副本，编译器只消费该结构化来源。
    """

    turn_state: TurnState
    agent_name: str
    system_prompt: str
    skill_catalog_prompt_block: str = ""
    memory_prompt_block: str = ""
    recent_turns: tuple[ChatMessage, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextRenderResult:
    """上下文渲染结果。"""

    messages: list[ChatMessage]
    session_key: str
