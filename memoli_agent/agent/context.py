"""上下文和 prompt 构建模块。

ContextBuilder 负责把一轮输入变成模型可消费的 messages：

1. system prompt
2. 可选长期记忆 prompt block
3. 当前 session 的历史消息
4. 当前用户消息

当前阶段还不调用真实 LLM，但先把结构稳定下来，后续 provider 可以直接复用。
"""

from __future__ import annotations

from dataclasses import dataclass

from memoli_agent.agent.types import ChatMessage, ContextRenderResult, ContextRequest


@dataclass(frozen=True, slots=True)
class ContextBuilder:
    """最小上下文构建器。"""

    agent_name: str
    system_prompt: str

    def render(self, request: ContextRequest) -> ContextRenderResult:
        """渲染当前轮次的 messages。"""

        messages = [ChatMessage(role="system", content=request.system_prompt)]

        if request.memory_prompt_block:
            messages.append(
                ChatMessage(
                    role="system",
                    content=request.memory_prompt_block,
                )
            )

        for history_message in request.turn_state.session.get_history():
            messages.append(
                ChatMessage(
                    role=history_message.role,
                    content=history_message.content,
                )
            )

        messages.append(
            ChatMessage(
                role="user",
                content=request.turn_state.inbound.content,
            )
        )

        return ContextRenderResult(
            messages=messages,
            session_key=request.turn_state.session_key,
        )
