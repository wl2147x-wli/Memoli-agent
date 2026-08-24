"""上下文和 prompt 构建模块。

ContextBuilder 负责把一轮输入变成模型可消费的 messages：

1. system prompt
2. 可选、会话稳定的 Skill Catalog
3. 可选长期记忆 prompt block
4. 当前 epoch 内近期完整 turn（由 CrossTurnContextPhase 从 canonical
   committed turn 重构，§3.1）
5. 当前用户消息

Session 不再维护消息历史副本；编译器只消费结构化的 ``recent_turns`` 来源，
避免在编译前按消息条数提前裁剪压缩来源。
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

        if request.skill_catalog_prompt_block:
            messages.append(
                ChatMessage(role="system", content=request.skill_catalog_prompt_block)
            )

        if request.memory_prompt_block:
            messages.append(
                ChatMessage(
                    role="system",
                    content=request.memory_prompt_block,
                )
            )

        # 近期完整 turn：保持 tool correlation 与稳定顺序（§3.1）。
        messages.extend(request.recent_turns)

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

