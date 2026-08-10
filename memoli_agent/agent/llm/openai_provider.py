"""OpenAI Chat Completions 与显式 compatible dialect Adapter。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any

import openai
from openai import AsyncOpenAI

from memoli_agent.agent.llm.contracts import (
    EventCallback,
    LLMResponse,
    ModelCapabilities,
    ModelCapability,
    ModelEvent,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    TextBlock,
    ThinkingBlock,
    TokenUsage,
    ToolCall,
    ToolResultBlock,
    ToolUseBlock,
    chat_message_to_model,
)
from memoli_agent.agent.llm.dialects import OpenAIDialect, resolve_dialect
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
)
from memoli_agent.agent.llm.retry import RetryPolicy
from memoli_agent.agent.types import ChatMessage


class OpenAIProvider:
    """无会话状态的 OpenAI Chat Completions Provider。"""

    capabilities = ModelCapabilities(
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

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 60.0,
        max_retries: int = 1,
        dialect: str = "default",
        name: str = "openai",
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.name = name
        self.protocol = "openai"
        self.dialect: OpenAIDialect = resolve_dialect(dialect)
        self.retry_policy = RetryPolicy(max_retries=max_retries)
        self._owns_client = client is None
        self._closed = False
        self._client = client or AsyncOpenAI(
            api_key=api_key or "not-needed",
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            max_retries=0,
        )

    async def complete(
        self,
        request: ModelRequest,
        on_event: EventCallback | None = None,
    ) -> LLMResponse:
        """执行一次非流式或流式模型调用。"""

        if self._closed:
            raise ProviderError(
                "Provider 已关闭。", provider=self.name, model=self.model
            )
        if not self.capabilities.supports(request.required_capabilities()):
            from memoli_agent.agent.llm.errors import UnsupportedCapabilityError

            raise UnsupportedCapabilityError(
                "OpenAI Adapter 不支持请求能力。",
                provider=self.name,
                model=request.model or self.model,
            )
        if request.stream:
            return await self._complete_stream(request, on_event)
        return await self._complete_once(request, on_event)

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """迁移期兼容旧 Reasoner。"""

        return await self.complete(
            ModelRequest(
                messages=tuple(chat_message_to_model(message) for message in messages),
                tools=tuple(tools or ()),
                model=self.model,
            )
        )

    async def aclose(self) -> None:
        """幂等释放 SDK 客户端。"""

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
                return await self._client.chat.completions.create(**kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise _map_openai_error(
                    exc, provider=self.name, model=str(kwargs["model"])
                ) from None

        response, attempts = await self.retry_policy.call(operation)
        result = self._parse_response(response, attempts)
        await _emit(on_event, ModelEvent(ModelEventKind.COMPLETED, text=result.content))
        return result

    async def _complete_stream(
        self,
        request: ModelRequest,
        on_event: EventCallback | None,
    ) -> LLMResponse:
        kwargs = self._request_kwargs(request)
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}

        async def operation() -> Any:
            try:
                return await self._client.chat.completions.create(**kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise _map_openai_error(
                    exc, provider=self.name, model=str(kwargs["model"])
                ) from None

        stream, attempts = await self.retry_policy.call(operation)
        text_parts: list[str] = []
        thinking_parts: list[str] = []
        calls: dict[int, dict[str, str]] = {}
        finish_reason = ""
        usage = TokenUsage()
        response_model = str(kwargs["model"])
        request_id = ""
        try:
            async for chunk in stream:
                request_id = request_id or str(getattr(chunk, "id", "") or "")
                response_model = str(getattr(chunk, "model", "") or response_model)
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    usage = _openai_usage(chunk_usage)
                    await _emit(
                        on_event,
                        ModelEvent(ModelEventKind.USAGE, usage=usage),
                    )
                choices = getattr(chunk, "choices", None) or ()
                if not choices:
                    continue
                choice = choices[0]
                finish_reason = str(
                    getattr(choice, "finish_reason", "") or finish_reason
                )
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue
                reasoning = self.dialect.reasoning_delta(delta)
                if reasoning:
                    thinking_parts.append(reasoning)
                    await _emit(
                        on_event,
                        ModelEvent(ModelEventKind.THINKING_DELTA, text=reasoning),
                    )
                content = _openai_content(getattr(delta, "content", None))
                if content:
                    text_parts.append(content)
                    await _emit(
                        on_event,
                        ModelEvent(ModelEventKind.TEXT_DELTA, text=content),
                    )
                for position, raw_call in enumerate(
                    getattr(delta, "tool_calls", None) or ()
                ):
                    index = int(getattr(raw_call, "index", position) or 0)
                    slot = calls.setdefault(
                        index, {"id": "", "name": "", "arguments": ""}
                    )
                    function = getattr(raw_call, "function", None)
                    call_id = str(getattr(raw_call, "id", "") or "")
                    name = str(getattr(function, "name", "") or "")
                    arguments = str(getattr(function, "arguments", "") or "")
                    if call_id:
                        slot["id"] += call_id
                    if name:
                        slot["name"] += name
                    if arguments:
                        slot["arguments"] += arguments
                    await _emit(
                        on_event,
                        ModelEvent(
                            ModelEventKind.TOOL_CALL_DELTA,
                            tool_call_id=call_id,
                            tool_name=name,
                            arguments_delta=arguments,
                        ),
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if isinstance(exc, ProviderError):
                exc.partial_stream = bool(text_parts or thinking_parts or calls)
                raise
            mapped = _map_openai_error(
                exc, provider=self.name, model=str(kwargs["model"])
            )
            mapped.partial_stream = bool(text_parts or thinking_parts or calls)
            raise mapped from None
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result

        blocks: list[TextBlock | ThinkingBlock | ToolUseBlock] = []
        if thinking_parts:
            blocks.append(ThinkingBlock("".join(thinking_parts)))
        content = "".join(text_parts)
        if content:
            blocks.append(TextBlock(content))
        tool_calls: list[ToolCall] = []
        for index in sorted(calls):
            item = calls[index]
            arguments = _strict_arguments(item["arguments"], self.name, response_model)
            call_id = item["id"] or f"call_{index}"
            block = ToolUseBlock(call_id, item["name"], arguments)
            blocks.append(block)
            tool_calls.append(ToolCall(block.name, dict(block.arguments), block.id))
        message = ModelMessage("assistant", tuple(blocks))
        response = LLMResponse(
            content=content,
            tool_calls=tool_calls,
            provider=self.name,
            finish_reason=finish_reason,
            usage=usage.to_dict(),
            message=message,
            model=response_model,
            request_id=request_id,
            protocol=self.protocol,
            dialect=self.dialect.name,
            attempt_count=len(attempts),
            attempts=attempts,
            capabilities=self.capabilities.to_strings(),
        )
        await _emit(on_event, ModelEvent(ModelEventKind.COMPLETED, text=content))
        return response

    def _request_kwargs(self, request: ModelRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": request.model or self.model,
            "messages": _to_openai_messages(request.messages),
            "max_completion_tokens": request.max_output_tokens,
        }
        if request.tools:
            kwargs["tools"] = [dict(tool) for tool in request.tools]
            kwargs["tool_choice"] = request.tool_choice
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.structured_output is not None:
            kwargs["response_format"] = dict(request.structured_output)
        self.dialect.prepare(kwargs, request)
        return kwargs

    def _parse_response(self, response: Any, attempts: tuple[Any, ...]) -> LLMResponse:
        try:
            choice = response.choices[0]
            raw_message = choice.message
        except (AttributeError, IndexError, TypeError) as exc:
            raise ResponseProtocolError(
                "OpenAI 响应缺少 choices[0].message。",
                provider=self.name,
                model=self.model,
            ) from exc
        content = _openai_content(getattr(raw_message, "content", None))
        blocks: list[TextBlock | ToolUseBlock] = []
        if content:
            blocks.append(TextBlock(content))
        tool_calls: list[ToolCall] = []
        for index, raw_call in enumerate(
            getattr(raw_message, "tool_calls", None) or ()
        ):
            function = getattr(raw_call, "function", None)
            name = str(getattr(function, "name", "") or "")
            call_id = str(getattr(raw_call, "id", "") or f"call_{index}")
            if not name:
                raise ResponseProtocolError(
                    "OpenAI 工具调用缺少名称。",
                    provider=self.name,
                    model=self.model,
                )
            arguments = _strict_arguments(
                getattr(function, "arguments", "{}"), self.name, self.model
            )
            block = ToolUseBlock(call_id, name, arguments)
            blocks.append(block)
            tool_calls.append(ToolCall(name, arguments, call_id))
        usage = _openai_usage(getattr(response, "usage", None))
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            provider=self.name,
            finish_reason=str(getattr(choice, "finish_reason", "") or ""),
            usage=usage.to_dict(),
            message=ModelMessage("assistant", tuple(blocks)),
            model=str(getattr(response, "model", "") or self.model),
            request_id=str(getattr(response, "id", "") or ""),
            protocol=self.protocol,
            dialect=self.dialect.name,
            attempt_count=len(attempts),
            attempts=attempts,
            capabilities=self.capabilities.to_strings(),
        )


def _to_openai_messages(messages: Sequence[ModelMessage]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            result.append({"role": "system", "content": message.text})
            continue
        tool_results = [
            block for block in message.blocks if isinstance(block, ToolResultBlock)
        ]
        for block in tool_results:
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": block.tool_use_id,
                    "content": block.content,
                }
            )
        non_results = [
            block for block in message.blocks if not isinstance(block, ToolResultBlock)
        ]
        if not non_results:
            continue
        item: dict[str, Any] = {"role": message.role, "content": message.text or None}
        tool_calls = [
            {
                "id": block.id,
                "type": "function",
                "function": {
                    "name": block.name,
                    "arguments": json.dumps(dict(block.arguments), ensure_ascii=False),
                },
            }
            for block in non_results
            if isinstance(block, ToolUseBlock)
        ]
        if tool_calls:
            item["tool_calls"] = tool_calls
        result.append(item)
    return result


def _openai_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        parts: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                text = item.get("text")
            else:
                text = getattr(item, "text", None)
            if text:
                parts.append(str(text))
        return "".join(parts)
    return str(value)


def _strict_arguments(value: Any, provider: str, model: str) -> dict[str, Any]:
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


def _openai_usage(value: Any) -> TokenUsage:
    if value is None:
        return TokenUsage()
    prompt_details = getattr(value, "prompt_tokens_details", None)
    completion_details = getattr(value, "completion_tokens_details", None)
    return TokenUsage(
        input_tokens=_int_or_none(getattr(value, "prompt_tokens", None)),
        output_tokens=_int_or_none(getattr(value, "completion_tokens", None)),
        total_tokens=_int_or_none(getattr(value, "total_tokens", None)),
        reasoning_tokens=_int_or_none(
            getattr(completion_details, "reasoning_tokens", None)
        ),
        cached_input_tokens=_int_or_none(
            getattr(prompt_details, "cached_tokens", None)
        ),
    )


def _map_openai_error(exc: Exception, *, provider: str, model: str) -> ProviderError:
    status = _status_code(exc)
    retry_after = _retry_after(exc)
    common = {
        "provider": provider,
        "model": model,
        "status_code": status,
        "request_id": str(getattr(exc, "request_id", "") or ""),
        "retry_after": retry_after,
    }
    if isinstance(exc, openai.AuthenticationError) or status == 401:
        return AuthenticationProviderError("模型凭证无效。", **common)
    if isinstance(exc, openai.PermissionDeniedError) or status == 403:
        return PermissionProviderError("模型调用权限不足。", **common)
    if isinstance(exc, openai.RateLimitError) or status == 429:
        return RateLimitProviderError("模型服务限流。", retryable=True, **common)
    if isinstance(exc, openai.APITimeoutError):
        return ProviderTimeoutError("模型请求超时。", retryable=True, **common)
    if isinstance(exc, openai.APIConnectionError):
        return ProviderNetworkError("模型网络连接失败。", retryable=True, **common)
    code = _error_code(exc)
    if code in {"context_length_exceeded", "max_tokens"}:
        return ContextLengthProviderError("模型上下文长度超限。", **common)
    if code in {"content_filter", "content_policy_violation"}:
        return ContentSafetyProviderError("模型内容安全策略拒绝请求。", **common)
    if status in {408, 500, 502, 503, 504}:
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
    return str(error.get("code") or error.get("type") or "").lower()


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
