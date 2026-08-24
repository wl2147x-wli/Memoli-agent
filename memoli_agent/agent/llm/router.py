"""显式能力校验与真实模型 fallback 路由。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from memoli_agent.agent.llm.contracts import (
    EventCallback,
    LLMProvider,
    LLMResponse,
    ModelCapabilities,
    ModelRequest,
    portable_message,
)
from memoli_agent.agent.llm.errors import ProviderError, UnsupportedCapabilityError
from memoli_agent.agent.types import ChatMessage


@dataclass(frozen=True, slots=True)
class ProviderTarget:
    """一个可路由的模型 Profile。"""

    profile: str
    model: str
    provider: LLMProvider
    capabilities: ModelCapabilities
    max_output_tokens: int = 8192
    context_window_tokens: int = 131_072
    context_safety_margin_tokens: int = 4_096
    token_estimator: str = "conservative"
    temperature: float | None = None


class ModelRouter:
    """按配置顺序执行能力兼容的真实 Provider fallback。"""

    def __init__(
        self, primary: ProviderTarget, fallbacks: tuple[ProviderTarget, ...]
    ) -> None:
        if any(target.provider.name == "echo" for target in fallbacks):
            raise ValueError("Echo 不能作为隐式 fallback。")
        self.primary = primary
        self.fallbacks = fallbacks
        self.name = primary.provider.name
        self.model = primary.model
        self.protocol = str(getattr(primary.provider, "protocol", ""))
        self.dialect = str(getattr(primary.provider, "dialect", "default"))
        self.capabilities = primary.capabilities
        self._closed = False

    async def complete(
        self,
        request: ModelRequest,
        on_event: EventCallback | None = None,
    ) -> LLMResponse:
        if self._closed:
            raise ProviderError("Provider Router 已关闭。", provider=self.name)
        required = request.required_capabilities()
        requested_provider = self.primary.provider.name
        requested_model = self.primary.model
        fallback_reason = ""
        attempt_count = 0
        attempt_history = []
        last_error: ProviderError | None = None
        for index, target in enumerate((self.primary, *self.fallbacks)):
            if not target.capabilities.supports(required):
                last_error = UnsupportedCapabilityError(
                    f"模型 Profile {target.profile!r} 不支持请求能力。",
                    provider=target.provider.name,
                    model=target.model,
                )
                fallback_reason = last_error.error_type
                continue
            routed_request = replace(
                request,
                messages=(
                    request.messages
                    if index == 0
                    else tuple(
                        portable_message(message) for message in request.messages
                    )
                ),
                model=target.model,
                max_output_tokens=(
                    request.max_output_tokens
                    if request.max_output_tokens != 8192
                    else target.max_output_tokens
                ),
                temperature=(
                    request.temperature
                    if request.temperature is not None
                    else target.temperature
                ),
            )
            try:
                response = await target.provider.complete(routed_request, on_event)
            except ProviderError as exc:
                attempt_count += max(1, exc.attempt)
                attempt_history.extend(exc.attempts)
                last_error = exc
                fallback_reason = exc.error_type
                if not exc.retryable or exc.partial_stream:
                    raise
                continue
            attempt_count += max(1, response.attempt_count)
            attempt_history.extend(response.attempts)
            return replace(
                response,
                fallback_used=index > 0,
                profile=target.profile,
                requested_provider=requested_provider,
                requested_model=requested_model,
                fallback_reason=fallback_reason if index > 0 else "",
                attempt_count=attempt_count,
                attempts=tuple(attempt_history),
                capabilities=target.capabilities.to_strings(),
            )
        if last_error is not None:
            raise last_error
        raise ProviderError("没有可用模型 Profile。", provider=requested_provider)

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        return await self.complete(
            ModelRequest.from_chat_messages(
                messages,
                tools=tools,
                model=self.primary.model,
                max_output_tokens=self.primary.max_output_tokens,
            )
        )

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        seen: set[int] = set()
        for target in (self.primary, *self.fallbacks):
            identity = id(target.provider)
            if identity in seen:
                continue
            seen.add(identity)
            await target.provider.aclose()
