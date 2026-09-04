"""LLM Provider 公共入口与旧接口兼容层。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from memoli_agent.agent.llm.anthropic_provider import AnthropicProvider
from memoli_agent.agent.llm.contracts import (
    EventCallback,
    LegacyLLMProvider,
    LLMProvider,
    LLMResponse,
    ModelCapabilities,
    ModelCapability,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    OpaqueContinuation,
    ReasoningPolicy,
    TextBlock,
    ToolCall,
    chat_message_to_model,
)
from memoli_agent.agent.llm.errors import (
    AuthenticationProviderError,
    ContentSafetyProviderError,
    ContextLengthProviderError,
    InvalidRequestProviderError,
    PermissionProviderError,
    ProviderError,
    ProviderNetworkError,
    ProviderTimeoutError,
    RateLimitProviderError,
    ResponseProtocolError,
    UnsupportedCapabilityError,
)
from memoli_agent.agent.llm.openai_provider import OpenAIProvider
from memoli_agent.agent.llm.openai_responses_provider import OpenAIResponsesProvider
from memoli_agent.agent.llm.router import ModelRouter, ProviderTarget
from memoli_agent.agent.types import ChatMessage

ProviderLike = LLMProvider | LegacyLLMProvider


@dataclass(frozen=True, slots=True)
class EchoProvider:
    """必须显式选择的本地测试 Provider。"""

    name: str = "echo"
    model: str = "echo"
    protocol: str = "echo"
    dialect: str = "echo"
    capabilities: ModelCapabilities = field(
        default_factory=lambda: ModelCapabilities(
            frozenset(
                {
                    ModelCapability.TEXT,
                    # Runtime 总会附带工具 schema；Echo 只是不发起工具调用。
                    ModelCapability.TOOLS,
                }
            )
        )
    )

    async def complete(
        self,
        request: ModelRequest,
        on_event: EventCallback | None = None,
    ) -> LLMResponse:
        user_content = ""
        for message in reversed(request.messages):
            if message.role == "user" and message.text:
                user_content = message.text
                break
        content = f"Echo: {user_content}"
        message = ModelMessage("assistant", (TextBlock(content),))
        return LLMResponse(
            content=content,
            provider=self.name,
            model=self.model,
            protocol=self.protocol,
            dialect=self.dialect,
            message=message,
            capabilities=self.capabilities.to_strings(),
        )

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        return await self.complete(
            ModelRequest(
                messages=tuple(chat_message_to_model(message) for message in messages),
                tools=tuple(tools or ()),
                model=self.model,
            )
        )

    async def aclose(self) -> None:
        return None


class OpenAICompatibleProvider(OpenAIProvider):
    """旧类名兼容；实现已切换到异步 OpenAI Adapter。"""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 60.0,
        name: str = "openai-compatible",
        *,
        max_retries: int = 1,
        dialect: str = "default",
        client: Any | None = None,
    ) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            dialect=dialect,
            name=name,
            client=client,
        )


@dataclass(slots=True)
class ScriptedProvider:
    """共享 conformance/Agent Loop 测试用确定性 Provider。"""

    responses: list[LLMResponse | ProviderError]
    name: str = "scripted"
    model: str = "scripted"
    protocol: str = "scripted"
    dialect: str = "scripted"
    calls: list[ModelRequest] = field(default_factory=list)
    capabilities: ModelCapabilities = field(
        default_factory=lambda: ModelCapabilities(
            frozenset(
                {
                    ModelCapability.TEXT,
                    ModelCapability.TOOLS,
                    ModelCapability.REASONING,
                    ModelCapability.STREAMING,
                    ModelCapability.STRUCTURED_OUTPUT,
                }
            )
        )
    )

    async def complete(
        self,
        request: ModelRequest,
        on_event: EventCallback | None = None,
    ) -> LLMResponse:
        self.calls.append(request)
        if not self.responses:
            raise ProviderError("没有更多脚本响应。", provider=self.name)
        item = self.responses.pop(0)
        if isinstance(item, ProviderError):
            raise item
        return item

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        return await self.complete(
            ModelRequest.from_chat_messages(messages, tools=tools, model=self.model)
        )

    async def aclose(self) -> None:
        return None


async def invoke_provider(
    provider: ProviderLike,
    messages: Sequence[ChatMessage],
    tools: Sequence[dict[str, Any]] | None = None,
    *,
    model: str = "",
    max_output_tokens: int = 8192,
    stream: bool = False,
    reasoning_policy: ReasoningPolicy | None = None,
    continuation: OpaqueContinuation | None = None,
    on_event: EventCallback | None = None,
) -> LLMResponse:
    """优先调用新合同，同时兼容只实现 `chat` 的测试 Provider。"""

    dynamic_provider = cast(Any, provider)
    complete = getattr(dynamic_provider, "complete", None)
    if callable(complete):
        invoke_complete = cast(
            Callable[[ModelRequest, EventCallback | None], Awaitable[LLMResponse]],
            complete,
        )
        return await invoke_complete(
            ModelRequest.from_chat_messages(
                messages,
                tools=tools,
                model=model,
                max_output_tokens=max_output_tokens,
                stream=stream,
                reasoning_policy=reasoning_policy,
                continuation=continuation,
            ),
            on_event,
        )
    return await dynamic_provider.chat(
        list(messages), tools=list(tools) if tools else None
    )


__all__ = [
    "AnthropicProvider",
    "AuthenticationProviderError",
    "ContentSafetyProviderError",
    "ContextLengthProviderError",
    "EchoProvider",
    "InvalidRequestProviderError",
    "LLMProvider",
    "LLMResponse",
    "LegacyLLMProvider",
    "ModelRouter",
    "ModelResponse",
    "OpenAICompatibleProvider",
    "OpenAIProvider",
    "OpenAIResponsesProvider",
    "PermissionProviderError",
    "ProviderError",
    "ProviderLike",
    "ProviderNetworkError",
    "ProviderTarget",
    "ProviderTimeoutError",
    "RateLimitProviderError",
    "ResponseProtocolError",
    "ScriptedProvider",
    "ToolCall",
    "UnsupportedCapabilityError",
    "invoke_provider",
]
