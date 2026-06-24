"""Reasoner 模块。

第六阶段的 Reasoner 支持一轮工具调用：

1. 把 tools schema 传给 provider。
2. 如果模型返回 tool_calls，则执行工具。
3. 把工具结果追加到 messages。
4. 再请求一次 provider 获取最终文本。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from memoli_agent.agent.provider import (
    LLMProvider,
    LLMResponse,
    ProviderError,
    ToolCall,
)
from memoli_agent.agent.tools.registry import ToolRegistry
from memoli_agent.agent.types import ChatMessage


@dataclass(frozen=True, slots=True)
class Reasoner:
    """最小推理器。"""

    provider: LLMProvider
    fallback_provider: LLMProvider | None = None
    tool_registry: ToolRegistry | None = None
    max_tool_rounds: int = 1

    async def generate(self, messages: list[ChatMessage]) -> LLMResponse:
        """根据上下文消息生成最终文本回复。"""

        tools = self.tool_registry.get_schemas() if self.tool_registry else None
        response = await self._chat_with_fallback(messages, tools)
        if (
            not response.tool_calls
            or self.tool_registry is None
            or self.max_tool_rounds <= 0
        ):
            return response

        tool_messages = await self._execute_tool_calls(response.tool_calls)
        followup_messages = [
            *messages,
            self._assistant_tool_call_message(response),
            *tool_messages,
        ]
        return await self._chat_with_fallback(followup_messages, tools)

    async def _chat_with_fallback(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
    ) -> LLMResponse:
        """调用主 provider，失败时尝试 fallback。"""

        try:
            return await self.provider.chat(messages, tools=tools)
        except ProviderError:
            if self.fallback_provider is not None:
                return await self._fallback(messages, tools)
            return self._error_response()

    async def _fallback(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
    ) -> LLMResponse:
        """主 provider 失败时尝试 fallback provider。"""

        try:
            response = await self.fallback_provider.chat(messages, tools=tools)
        except ProviderError:
            return self._error_response(fallback_used=True)

        return LLMResponse(
            content=response.content,
            tool_calls=response.tool_calls,
            raw=response.raw,
            provider=response.provider,
            fallback_used=True,
        )

    async def _execute_tool_calls(self, tool_calls: list[ToolCall]) -> list[ChatMessage]:
        """执行一组工具调用并转换为 tool role 消息。"""

        if self.tool_registry is None:
            return []

        messages: list[ChatMessage] = []
        for index, tool_call in enumerate(tool_calls):
            tool_call_id = tool_call.id or f"call_{index}_{tool_call.name}"
            result = await self.tool_registry.execute(
                tool_call.name,
                tool_call.arguments,
            )
            messages.append(
                ChatMessage(
                    role="tool",
                    content=result.content,
                    tool_call_id=tool_call_id,
                    name=tool_call.name,
                )
            )
        return messages

    def _assistant_tool_call_message(self, response: LLMResponse) -> ChatMessage:
        """把模型的 tool_calls 转换为 assistant 消息。"""

        return ChatMessage(
            role="assistant",
            content=response.content,
            tool_calls=[
                {
                    "id": tool_call.id or f"call_{index}_{tool_call.name}",
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": json.dumps(
                            tool_call.arguments,
                            ensure_ascii=False,
                        ),
                    },
                }
                for index, tool_call in enumerate(response.tool_calls)
            ],
        )

    def _error_response(self, fallback_used: bool = False) -> LLMResponse:
        """所有 provider 都失败时返回中文兜底回复。"""

        return LLMResponse(
            content="抱歉，当前模型服务暂时不可用，请稍后再试。",
            provider="error",
            fallback_used=fallback_used,
        )
