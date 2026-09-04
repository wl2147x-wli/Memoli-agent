"""Anthropic Messages 原生协议 Adapter。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any

import anthropic
from anthropic import AsyncAnthropic

from memoli_agent.agent.llm.contracts import (
    EventCallback,
    LLMResponse,
    ModelCapabilities,
    ModelCapability,
    ModelEvent,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    OpaqueContinuation,
    ReasoningSummaryBlock,
    ReasoningVisibility,
    TextBlock,
    ThinkingBlock,
    TokenUsage,
    ToolCall,
    ToolResultBlock,
    ToolUseBlock,
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
    UnsupportedReasoningPolicyError,
)
from memoli_agent.agent.llm.retry import RetryPolicy
from memoli_agent.agent.types import ChatMessage


class AnthropicProvider:
    """无会话状态的 Anthropic Messages Provider。"""

    capabilities = ModelCapabilities(
        frozenset(
            {
                ModelCapability.TEXT,
                ModelCapability.TOOLS,
                ModelCapability.REASONING,
                ModelCapability.STREAMING,
                ModelCapability.PROMPT_CACHE,
            }
        )
    )

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        timeout_seconds: float = 60.0,
        max_retries: int = 1,
        name: str = "anthropic",
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.name = name
        self.protocol = "anthropic"
        self.dialect = "anthropic"
        self.retry_policy = RetryPolicy(max_retries=max_retries)
        self._owns_client = client is None
        self._closed = False
        self._client = client or AsyncAnthropic(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            max_retries=0,
        )

    async def complete(
        self,
        request: ModelRequest,
        on_event: EventCallback | None = None,
    ) -> LLMResponse:
        if self._closed:
            raise ProviderError(
                "Provider 已关闭。", provider=self.name, model=self.model
            )
        if not self.capabilities.supports(request.required_capabilities()):
            from memoli_agent.agent.llm.errors import UnsupportedCapabilityError

            raise UnsupportedCapabilityError(
                "Anthropic Adapter 不支持请求能力。",
                provider=self.name,
                model=request.model or self.model,
            )
        self._validate_reasoning_policy(request)
        if request.stream:
            return await self._complete_stream(request, on_event)
        return await self._complete_once(request, on_event)

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
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._client.close()

    async def _complete_once(
        self,
        request: ModelRequest,
        on_event: EventCallback | None,
    ) -> LLMResponse:
        kwargs = self._request_kwargs(request)

        async def operation() -> Any:
            try:
                return await self._client.messages.create(**kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise _map_anthropic_error(
                    exc, provider=self.name, model=str(kwargs["model"])
                ) from None

        response, attempts = await self.retry_policy.call(operation)
        result = self._parse_response(response, attempts, request)
        await _emit(on_event, ModelEvent(ModelEventKind.COMPLETED, text=result.content))
        return result

    async def _complete_stream(
        self,
        request: ModelRequest,
        on_event: EventCallback | None,
    ) -> LLMResponse:
        kwargs = self._request_kwargs(request)
        kwargs["stream"] = True

        async def operation() -> Any:
            try:
                return await self._client.messages.create(**kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise _map_anthropic_error(
                    exc, provider=self.name, model=str(kwargs["model"])
                ) from None

        stream, attempts = await self.retry_policy.call(operation)
        slots: dict[int, dict[str, Any]] = {}
        response_model = str(kwargs["model"])
        request_id = ""
        stop_reason = ""
        usage = TokenUsage()
        try:
            async for event in stream:
                event_type = str(getattr(event, "type", "") or "")
                if event_type == "message_start":
                    message = getattr(event, "message", None)
                    request_id = str(getattr(message, "id", "") or request_id)
                    response_model = str(
                        getattr(message, "model", "") or response_model
                    )
                    usage = _anthropic_usage(getattr(message, "usage", None))
                    await _emit(on_event, ModelEvent(ModelEventKind.USAGE, usage=usage))
                    continue
                if event_type == "content_block_start":
                    index = int(getattr(event, "index", 0) or 0)
                    block = getattr(event, "content_block", None)
                    block_type = str(getattr(block, "type", "") or "")
                    slots[index] = {
                        "type": block_type,
                        "text": str(getattr(block, "text", "") or ""),
                        "thinking": str(getattr(block, "thinking", "") or ""),
                        "signature": str(getattr(block, "signature", "") or ""),
                        "data": str(getattr(block, "data", "") or ""),
                        "id": str(getattr(block, "id", "") or ""),
                        "name": str(getattr(block, "name", "") or ""),
                        "arguments": "",
                        "input": getattr(block, "input", None),
                    }
                    continue
                if event_type == "content_block_delta":
                    index = int(getattr(event, "index", 0) or 0)
                    slot = slots.setdefault(index, {"type": "", "arguments": ""})
                    delta = getattr(event, "delta", None)
                    delta_type = str(getattr(delta, "type", "") or "")
                    if delta_type == "text_delta":
                        text = str(getattr(delta, "text", "") or "")
                        slot["text"] = str(slot.get("text", "")) + text
                        await _emit(
                            on_event,
                            ModelEvent(ModelEventKind.TEXT_DELTA, text=text),
                        )
                    elif delta_type == "thinking_delta":
                        thinking = str(getattr(delta, "thinking", "") or "")
                        slot["thinking"] = str(slot.get("thinking", "")) + thinking
                        if (
                            request.effective_reasoning_policy.visibility
                            is ReasoningVisibility.UPDATES
                        ):
                            await _emit(
                                on_event,
                                ModelEvent(
                                    ModelEventKind.REASONING_SUMMARY_DELTA,
                                    text=thinking,
                                ),
                            )
                    elif delta_type == "signature_delta":
                        slot["signature"] = str(slot.get("signature", "")) + str(
                            getattr(delta, "signature", "") or ""
                        )
                    elif delta_type == "input_json_delta":
                        partial = str(getattr(delta, "partial_json", "") or "")
                        slot["arguments"] = str(slot.get("arguments", "")) + partial
                        await _emit(
                            on_event,
                            ModelEvent(
                                ModelEventKind.TOOL_CALL_DELTA,
                                tool_call_id=str(slot.get("id", "")),
                                tool_name=str(slot.get("name", "")),
                                arguments_delta=partial,
                            ),
                        )
                    continue
                if event_type == "message_delta":
                    delta = getattr(event, "delta", None)
                    stop_reason = str(getattr(delta, "stop_reason", "") or stop_reason)
                    usage = _merge_anthropic_usage(
                        usage, _anthropic_usage(getattr(event, "usage", None))
                    )
                    await _emit(on_event, ModelEvent(ModelEventKind.USAGE, usage=usage))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if isinstance(exc, ProviderError):
                exc.partial_stream = bool(slots)
                raise
            mapped = _map_anthropic_error(
                exc, provider=self.name, model=str(kwargs["model"])
            )
            mapped.partial_stream = bool(slots)
            raise mapped from None
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result

        blocks: list[TextBlock | ReasoningSummaryBlock | ToolUseBlock] = []
        tool_calls: list[ToolCall] = []
        wire_blocks: list[dict[str, Any]] = []
        for index in sorted(slots):
            slot = slots[index]
            block_type = slot.get("type")
            if block_type == "text":
                text = str(slot.get("text", ""))
                blocks.append(TextBlock(text))
                wire_blocks.append({"type": "text", "text": text})
            elif block_type == "thinking":
                thinking = str(slot.get("thinking", ""))
                wire_blocks.append(
                    {
                        "type": "thinking",
                        "thinking": thinking,
                        "signature": str(slot.get("signature", "")),
                    }
                )
                if (
                    thinking
                    and request.effective_reasoning_policy.visibility
                    is not ReasoningVisibility.HIDDEN
                ):
                    blocks.append(ReasoningSummaryBlock(thinking))
            elif block_type == "redacted_thinking":
                wire_blocks.append(
                    {
                        "type": "redacted_thinking",
                        "data": str(slot.get("data", "")),
                    }
                )
            elif block_type == "tool_use":
                raw_arguments = slot.get("arguments") or slot.get("input") or {}
                arguments = _strict_arguments(
                    raw_arguments, provider=self.name, model=response_model
                )
                tool = ToolUseBlock(
                    str(slot.get("id") or f"toolu_{index}"),
                    str(slot.get("name") or ""),
                    arguments,
                )
                blocks.append(tool)
                tool_calls.append(ToolCall(tool.name, dict(tool.arguments), tool.id))
                wire_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tool.id,
                        "name": tool.name,
                        "input": dict(tool.arguments),
                    }
                )
        message = ModelMessage("assistant", tuple(blocks))
        content = message.text
        response = LLMResponse(
            content=content,
            tool_calls=tool_calls,
            provider=self.name,
            finish_reason=stop_reason,
            usage=usage.to_dict(),
            message=message,
            model=response_model,
            request_id=request_id,
            protocol=self.protocol,
            dialect=self.dialect,
            attempt_count=len(attempts),
            attempts=attempts,
            capabilities=self.capabilities.to_strings(),
            continuation=(
                OpaqueContinuation(
                    "anthropic",
                    items=tuple(wire_blocks),
                    provider=self.name,
                    model=response_model,
                    reasoning_policy=request.effective_reasoning_policy,
                )
                if tool_calls and any(
                    item["type"] in {"thinking", "redacted_thinking"}
                    for item in wire_blocks
                )
                else None
            ),
        )
        await _emit(on_event, ModelEvent(ModelEventKind.COMPLETED, text=content))
        return response

    def _request_kwargs(self, request: ModelRequest) -> dict[str, Any]:
        system, messages = _to_anthropic_messages(request.messages)
        if request.continuation is not None:
            _apply_anthropic_continuation(messages, request.continuation)
        kwargs: dict[str, Any] = {
            "model": request.model or self.model,
            "max_tokens": request.max_output_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if request.tools:
            kwargs["tools"] = [_to_anthropic_tool(tool) for tool in request.tools]
            if isinstance(request.tool_choice, str):
                kwargs["tool_choice"] = {"type": request.tool_choice}
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        policy = request.effective_reasoning_policy
        if policy.enabled:
            kwargs["thinking"] = {"type": "adaptive"}
            if policy.effort is not None:
                kwargs["output_config"] = {"effort": policy.effort}
        return kwargs

    def _validate_reasoning_policy(self, request: ModelRequest) -> None:
        policy = request.effective_reasoning_policy
        continuation = request.continuation
        if continuation is not None and continuation.protocol != self.protocol:
            raise UnsupportedReasoningPolicyError(
                "Anthropic 不能接收其他协议的续接信封。",
                provider=self.name,
                model=request.model or self.model,
            )
        if not policy.enabled and continuation is not None:
            raise UnsupportedReasoningPolicyError(
                "续接 Anthropic 推理状态时不能关闭推理。",
                provider=self.name,
                model=request.model or self.model,
            )

    def _parse_response(
        self,
        response: Any,
        attempts: tuple[Any, ...],
        request: ModelRequest,
    ) -> LLMResponse:
        blocks: list[TextBlock | ReasoningSummaryBlock | ToolUseBlock] = []
        tool_calls: list[ToolCall] = []
        wire_blocks: list[dict[str, Any]] = []
        try:
            content_blocks = response.content
        except AttributeError as exc:
            raise ResponseProtocolError(
                "Anthropic 响应缺少 content blocks。",
                provider=self.name,
                model=self.model,
            ) from exc
        for index, raw in enumerate(content_blocks):
            block_type = str(getattr(raw, "type", "") or "")
            if block_type == "text":
                text = str(getattr(raw, "text", "") or "")
                blocks.append(TextBlock(text))
                wire_blocks.append({"type": "text", "text": text})
            elif block_type == "thinking":
                thinking = str(getattr(raw, "thinking", "") or "")
                wire_blocks.append(
                    {
                        "type": "thinking",
                        "thinking": thinking,
                        "signature": str(getattr(raw, "signature", "") or ""),
                    }
                )
                if (
                    thinking
                    and request.effective_reasoning_policy.visibility
                    is not ReasoningVisibility.HIDDEN
                ):
                    blocks.append(ReasoningSummaryBlock(thinking))
            elif block_type == "redacted_thinking":
                wire_blocks.append(
                    {
                        "type": "redacted_thinking",
                        "data": str(getattr(raw, "data", "") or ""),
                    }
                )
            elif block_type == "tool_use":
                arguments = _strict_arguments(
                    getattr(raw, "input", {}), provider=self.name, model=self.model
                )
                tool = ToolUseBlock(
                    str(getattr(raw, "id", "") or f"toolu_{index}"),
                    str(getattr(raw, "name", "") or ""),
                    arguments,
                )
                blocks.append(tool)
                tool_calls.append(ToolCall(tool.name, arguments, tool.id))
                wire_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tool.id,
                        "name": tool.name,
                        "input": dict(tool.arguments),
                    }
                )
            else:
                raise ResponseProtocolError(
                    f"Anthropic 返回未知内容块：{block_type}",
                    provider=self.name,
                    model=self.model,
                )
        message = ModelMessage("assistant", tuple(blocks))
        usage = _anthropic_usage(getattr(response, "usage", None))
        return LLMResponse(
            content=message.text,
            tool_calls=tool_calls,
            provider=self.name,
            finish_reason=str(getattr(response, "stop_reason", "") or ""),
            usage=usage.to_dict(),
            message=message,
            model=str(getattr(response, "model", "") or self.model),
            request_id=str(getattr(response, "id", "") or ""),
            protocol=self.protocol,
            dialect=self.dialect,
            attempt_count=len(attempts),
            attempts=attempts,
            capabilities=self.capabilities.to_strings(),
            continuation=(
                OpaqueContinuation(
                    "anthropic",
                    items=tuple(wire_blocks),
                    provider=self.name,
                    model=str(getattr(response, "model", "") or self.model),
                    reasoning_policy=request.effective_reasoning_policy,
                )
                if tool_calls and any(
                    item["type"] in {"thinking", "redacted_thinking"}
                    for item in wire_blocks
                )
                else None
            ),
        )


def _to_anthropic_messages(
    messages: Sequence[ModelMessage],
) -> tuple[str, list[dict[str, Any]]]:
    systems: list[str] = []
    rendered: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            if message.text:
                systems.append(message.text)
            continue
        content: list[dict[str, Any]] = []
        for block in message.blocks:
            if isinstance(block, TextBlock):
                content.append({"type": "text", "text": block.text})
            elif isinstance(block, ThinkingBlock):
                if block.redacted:
                    content.append(
                        {"type": "redacted_thinking", "data": block.opaque or ""}
                    )
                else:
                    value: dict[str, Any] = {
                        "type": "thinking",
                        "thinking": block.thinking,
                    }
                    if block.signature:
                        value["signature"] = block.signature
                    content.append(value)
            elif isinstance(block, ToolUseBlock):
                content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": dict(block.arguments),
                    }
                )
            elif isinstance(block, ToolResultBlock):
                value = {
                    "type": "tool_result",
                    "tool_use_id": block.tool_use_id,
                    "content": block.content,
                }
                if block.is_error:
                    value["is_error"] = True
                content.append(value)
        if not content:
            content.append({"type": "text", "text": "."})
        if rendered and rendered[-1]["role"] == message.role:
            rendered[-1]["content"].extend(content)
        else:
            rendered.append({"role": message.role, "content": content})
    return "\n\n".join(systems), rendered


def _apply_anthropic_continuation(
    messages: list[dict[str, Any]], continuation: OpaqueContinuation
) -> None:
    """用适配器私有信封恢复最近一次 assistant 工具调用的原始块。"""

    if continuation.protocol != "anthropic" or continuation.version != 1:
        raise UnsupportedReasoningPolicyError(
            "Anthropic 续接信封的协议或版本不受支持。",
            provider="anthropic",
        )
    for message in reversed(messages):
        if message.get("role") == "assistant":
            message["content"] = [dict(item) for item in continuation.items]
            return
    raise ResponseProtocolError(
        "Anthropic 续接请求缺少对应的 assistant 消息。",
        provider="anthropic",
    )


def _to_anthropic_tool(tool: Mapping[str, Any]) -> dict[str, Any]:
    function = tool.get("function", tool)
    if not isinstance(function, Mapping):
        raise ValueError("工具 schema function 必须是对象。")
    return {
        "name": str(function.get("name") or ""),
        "description": str(function.get("description") or ""),
        "input_schema": dict(
            function.get("parameters") or {"type": "object", "properties": {}}
        ),
    }


def _strict_arguments(value: Any, *, provider: str, model: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError as exc:
        raise ResponseProtocolError(
            "模型返回了无法解析的工具参数。",
            provider=provider,
            model=model,
        ) from exc
    if not isinstance(parsed, dict):
        raise ResponseProtocolError(
            "模型工具参数必须是 JSON object。",
            provider=provider,
            model=model,
        )
    return parsed


def _anthropic_usage(value: Any) -> TokenUsage:
    if value is None:
        return TokenUsage()
    input_tokens = _int_or_none(getattr(value, "input_tokens", None))
    output_tokens = _int_or_none(getattr(value, "output_tokens", None))
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=(
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        ),
        cached_input_tokens=_int_or_none(
            getattr(value, "cache_read_input_tokens", None)
        ),
        cache_creation_input_tokens=_int_or_none(
            getattr(value, "cache_creation_input_tokens", None)
        ),
    )


def _merge_anthropic_usage(base: TokenUsage, update: TokenUsage) -> TokenUsage:
    input_tokens = update.input_tokens or base.input_tokens
    output_tokens = update.output_tokens or base.output_tokens
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=(
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else update.total_tokens or base.total_tokens
        ),
        cached_input_tokens=update.cached_input_tokens or base.cached_input_tokens,
        cache_creation_input_tokens=(
            update.cache_creation_input_tokens or base.cache_creation_input_tokens
        ),
    )


def _map_anthropic_error(exc: Exception, *, provider: str, model: str) -> ProviderError:
    status = _status_code(exc)
    common = {
        "provider": provider,
        "model": model,
        "status_code": status,
        "request_id": str(getattr(exc, "request_id", "") or ""),
        "retry_after": _retry_after(exc),
    }
    if isinstance(exc, anthropic.AuthenticationError) or status == 401:
        return AuthenticationProviderError("模型凭证无效。", **common)
    if isinstance(exc, anthropic.PermissionDeniedError) or status == 403:
        return PermissionProviderError("模型调用权限不足。", **common)
    if isinstance(exc, anthropic.RateLimitError) or status == 429:
        return RateLimitProviderError("模型服务限流。", retryable=True, **common)
    if isinstance(exc, anthropic.APITimeoutError):
        return ProviderTimeoutError("模型请求超时。", retryable=True, **common)
    if isinstance(exc, anthropic.APIConnectionError):
        return ProviderNetworkError("模型网络连接失败。", retryable=True, **common)
    code = _error_code(exc)
    if code in {"request_too_large", "context_length_exceeded"}:
        return ContextLengthProviderError("模型上下文长度超限。", **common)
    if code in {"content_filter", "content_policy_violation"}:
        return ContentSafetyProviderError("模型内容安全策略拒绝请求。", **common)
    if status in {408, 500, 502, 503, 504, 529}:
        return ProviderNetworkError("模型服务暂时不可用。", retryable=True, **common)
    if status is not None and 400 <= status < 500:
        return InvalidRequestProviderError("模型请求无效。", **common)
    return ProviderError("模型 Provider 调用失败。", **common)


def _status_code(exc: Exception) -> int | None:
    raw = getattr(exc, "status_code", None)
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _error_code(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    if not isinstance(body, Mapping):
        return ""
    error = body.get("error", body)
    if not isinstance(error, Mapping):
        return ""
    return str(error.get("type") or error.get("code") or "").lower()


def _retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not isinstance(headers, Mapping):
        return None
    raw = headers.get("retry-after")
    try:
        return max(0.0, float(raw)) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def _emit(callback: EventCallback | None, event: ModelEvent) -> None:
    if callback is not None:
        await callback(event)
