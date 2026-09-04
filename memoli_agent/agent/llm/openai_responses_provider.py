"""显式 OpenAI Responses 协议适配器。"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

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
    OpaqueContinuation,
    ReasoningSummaryBlock,
    ReasoningVisibility,
    TextBlock,
    TokenUsage,
    ToolCall,
    ToolResultBlock,
    ToolUseBlock,
)
from memoli_agent.agent.llm.errors import (
    ProviderError,
    ResponseProtocolError,
    UnsupportedReasoningPolicyError,
)
from memoli_agent.agent.llm.openai_provider import (
    _map_openai_error,
    _strict_arguments,
)
from memoli_agent.agent.llm.retry import RetryPolicy


class OpenAIResponsesProvider:
    """使用本地显式重放实现无状态工具续接的 Responses 提供商。"""

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
        name: str = "openai-responses",
        client: Any | None = None,
    ) -> None:
        self.model = model
        self.name = name
        self.protocol = "openai-responses"
        self.dialect = "responses"
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
        if self._closed:
            raise ProviderError(
                "Provider 已关闭。", provider=self.name, model=self.model
            )
        if not self.capabilities.supports(request.required_capabilities()):
            from memoli_agent.agent.llm.errors import UnsupportedCapabilityError

            raise UnsupportedCapabilityError(
                "OpenAI Responses 适配器不支持请求能力。",
                provider=self.name,
                model=request.model or self.model,
            )
        self._validate_policy(request)
        if request.stream:
            return await self._complete_stream(request, on_event)
        return await self._complete_once(request, on_event)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._client.close()

    async def _complete_once(
        self, request: ModelRequest, on_event: EventCallback | None
    ) -> LLMResponse:
        kwargs = self._request_kwargs(request)

        async def operation() -> Any:
            try:
                return await self._client.responses.create(**kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise _map_openai_error(
                    exc, provider=self.name, model=str(kwargs["model"])
                ) from None

        response, attempts = await self.retry_policy.call(operation)
        result = self._parse_response(response, attempts, request)
        await _emit(on_event, ModelEvent(ModelEventKind.COMPLETED, text=result.content))
        return result

    async def _complete_stream(
        self, request: ModelRequest, on_event: EventCallback | None
    ) -> LLMResponse:
        kwargs = self._request_kwargs(request)
        kwargs["stream"] = True

        async def operation() -> Any:
            try:
                return await self._client.responses.create(**kwargs)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise _map_openai_error(
                    exc, provider=self.name, model=str(kwargs["model"])
                ) from None

        stream, attempts = await self.retry_policy.call(operation)
        completed: Any | None = None
        partial = False
        try:
            async for event in stream:
                event_type = str(getattr(event, "type", "") or "")
                if event_type == "response.output_text.delta":
                    text = str(getattr(event, "delta", "") or "")
                    partial = partial or bool(text)
                    await _emit(
                        on_event, ModelEvent(ModelEventKind.TEXT_DELTA, text=text)
                    )
                elif event_type in {
                    "response.reasoning_summary_text.delta",
                    "response.reasoning_summary.delta",
                }:
                    text = str(getattr(event, "delta", "") or "")
                    partial = partial or bool(text)
                    if (
                        request.effective_reasoning_policy.visibility
                        is ReasoningVisibility.UPDATES
                    ):
                        await _emit(
                            on_event,
                            ModelEvent(
                                ModelEventKind.REASONING_SUMMARY_DELTA, text=text
                            ),
                        )
                elif event_type == "response.function_call_arguments.delta":
                    partial = True
                    await _emit(
                        on_event,
                        ModelEvent(
                            ModelEventKind.TOOL_CALL_DELTA,
                            tool_call_id=str(
                                getattr(event, "item_id", "")
                                or getattr(event, "call_id", "")
                                or ""
                            ),
                            arguments_delta=str(getattr(event, "delta", "") or ""),
                        ),
                    )
                elif event_type == "response.completed":
                    completed = getattr(event, "response", None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            mapped = (
                exc
                if isinstance(exc, ProviderError)
                else _map_openai_error(
                    exc, provider=self.name, model=str(kwargs["model"])
                )
            )
            mapped.partial_stream = partial
            raise mapped from None
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                close_result = close()
                if hasattr(close_result, "__await__"):
                    await close_result
        if completed is None:
            raise ResponseProtocolError(
                "OpenAI Responses 流缺少 response.completed。",
                provider=self.name,
                model=str(kwargs["model"]),
                partial_stream=partial,
            )
        result = self._parse_response(completed, attempts, request)
        await _emit(
            on_event, ModelEvent(ModelEventKind.USAGE, usage=result.token_usage)
        )
        await _emit(on_event, ModelEvent(ModelEventKind.COMPLETED, text=result.content))
        return result

    def _request_kwargs(self, request: ModelRequest) -> dict[str, Any]:
        policy = request.effective_reasoning_policy
        kwargs: dict[str, Any] = {
            "model": request.model or self.model,
            "input": _to_responses_input(request.messages, request.continuation),
            "max_output_tokens": request.max_output_tokens,
            "store": False,
        }
        if request.tools:
            kwargs["tools"] = [_to_responses_tool(tool) for tool in request.tools]
            kwargs["tool_choice"] = request.tool_choice
        if policy.enabled:
            reasoning: dict[str, Any] = {}
            if policy.effort is not None:
                reasoning["effort"] = policy.effort
            if policy.visibility is not ReasoningVisibility.HIDDEN:
                reasoning["summary"] = "auto"
            kwargs["reasoning"] = reasoning
            kwargs["include"] = ["reasoning.encrypted_content"]
        if request.structured_output is not None:
            kwargs["text"] = {"format": dict(request.structured_output)}
        return kwargs

    def _validate_policy(self, request: ModelRequest) -> None:
        continuation = request.continuation
        if continuation is not None and (
            continuation.protocol != self.protocol or continuation.version != 1
        ):
            raise UnsupportedReasoningPolicyError(
                "OpenAI Responses 续接信封的协议或版本不受支持。",
                provider=self.name,
                model=request.model or self.model,
            )
        if continuation is not None and not request.effective_reasoning_policy.enabled:
            raise UnsupportedReasoningPolicyError(
                "续接 OpenAI 推理状态时不能关闭推理。",
                provider=self.name,
                model=request.model or self.model,
            )

    def _parse_response(
        self,
        response: Any,
        attempts: tuple[Any, ...],
        request: ModelRequest,
    ) -> LLMResponse:
        output = getattr(response, "output", None)
        if output is None and isinstance(response, Mapping):
            output = response.get("output")
        if not isinstance(output, Sequence):
            raise ResponseProtocolError(
                "OpenAI Responses 响应缺少 output。",
                provider=self.name,
                model=request.model or self.model,
            )
        blocks: list[TextBlock | ReasoningSummaryBlock | ToolUseBlock] = []
        calls: list[ToolCall] = []
        wire_items: list[Mapping[str, Any]] = []
        for index, raw in enumerate(output):
            item = _as_mapping(raw)
            item_type = str(item.get("type") or "")
            if item_type == "reasoning":
                wire_items.append(item)
                if (
                    request.effective_reasoning_policy.visibility
                    is not ReasoningVisibility.HIDDEN
                ):
                    for summary in item.get("summary") or ():
                        summary_map = _as_mapping(summary)
                        text = str(summary_map.get("text") or "")
                        if text:
                            blocks.append(ReasoningSummaryBlock(text))
            elif item_type == "message":
                wire_items.append(item)
                for part in item.get("content") or ():
                    part_map = _as_mapping(part)
                    if part_map.get("type") == "output_text":
                        text = str(part_map.get("text") or "")
                        if text:
                            blocks.append(TextBlock(text))
            elif item_type == "function_call":
                name = str(item.get("name") or "")
                call_id = str(item.get("call_id") or item.get("id") or f"call_{index}")
                if not name:
                    raise ResponseProtocolError(
                        "OpenAI Responses 函数调用缺少名称。",
                        provider=self.name,
                        model=request.model or self.model,
                    )
                arguments = _strict_arguments(
                    item.get("arguments", "{}"), self.name, request.model or self.model
                )
                block = ToolUseBlock(call_id, name, arguments)
                blocks.append(block)
                calls.append(ToolCall(name, arguments, call_id))
                wire_items.append(item)
            else:
                raise ResponseProtocolError(
                    f"OpenAI Responses 返回未知输出项：{item_type}",
                    provider=self.name,
                    model=request.model or self.model,
                )
        message = ModelMessage("assistant", tuple(blocks))
        raw_usage = (
            response.get("usage")
            if isinstance(response, Mapping)
            else getattr(response, "usage", None)
        )
        usage = _responses_usage(raw_usage)
        return LLMResponse(
            content=message.text,
            tool_calls=calls,
            provider=self.name,
            finish_reason=str(
                response.get("status", "")
                if isinstance(response, Mapping)
                else getattr(response, "status", "") or ""
            ),
            usage=usage.to_dict(),
            message=message,
            model=str(
                response.get("model", self.model)
                if isinstance(response, Mapping)
                else getattr(response, "model", "") or self.model
            ),
            request_id=str(
                response.get("id", "")
                if isinstance(response, Mapping)
                else getattr(response, "id", "") or ""
            ),
            protocol=self.protocol,
            dialect=self.dialect,
            attempt_count=len(attempts),
            attempts=attempts,
            capabilities=self.capabilities.to_strings(),
            continuation=(
                OpaqueContinuation(
                    self.protocol,
                    items=tuple(wire_items),
                    provider=self.name,
                    model=request.model or self.model,
                    reasoning_policy=request.effective_reasoning_policy,
                )
                if calls and any(item.get("type") == "reasoning" for item in wire_items)
                else None
            ),
        )


def _to_responses_input(
    messages: Sequence[ModelMessage], continuation: OpaqueContinuation | None
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    replayed = False
    for message in messages:
        tool_results = [
            block for block in message.blocks if isinstance(block, ToolResultBlock)
        ]
        if continuation is not None and message.role == "assistant" and any(
            isinstance(block, ToolUseBlock) for block in message.blocks
        ):
            result.extend(dict(item) for item in continuation.items)
            replayed = True
        elif message.text:
            result.append({"role": message.role, "content": message.text})
        for block in tool_results:
            result.append(
                {
                    "type": "function_call_output",
                    "call_id": block.tool_use_id,
                    "output": block.content,
                }
            )
    if continuation is not None and not replayed:
        raise ResponseProtocolError(
            "OpenAI Responses 续接请求缺少对应的 assistant 工具调用消息。",
            provider="openai-responses",
        )
    return result


def _to_responses_tool(tool: Mapping[str, Any]) -> dict[str, Any]:
    function = tool.get("function", tool)
    if not isinstance(function, Mapping):
        raise ValueError("Responses 工具定义必须是对象。")
    return {
        "type": "function",
        "name": str(function.get("name") or ""),
        "description": str(function.get("description") or ""),
        "parameters": dict(function.get("parameters") or {}),
    }


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        dumped = dump(mode="json", exclude_none=True)
        if isinstance(dumped, Mapping):
            return dict(dumped)
    if hasattr(value, "__dict__"):
        return {
            key: item
            for key, item in vars(value).items()
            if not key.startswith("_") and item is not None
        }
    raise ResponseProtocolError(
        "OpenAI Responses 输出项无法解析。", provider="openai-responses"
    )


def _responses_usage(value: Any) -> TokenUsage:
    usage = _as_mapping(value) if value is not None else {}
    raw_input_details = usage.get("input_tokens_details")
    raw_output_details = usage.get("output_tokens_details")
    input_details = (
        _as_mapping(raw_input_details) if raw_input_details is not None else {}
    )
    output_details = (
        _as_mapping(raw_output_details) if raw_output_details is not None else {}
    )

    def integer(raw: Any) -> int | None:
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    return TokenUsage(
        input_tokens=integer(usage.get("input_tokens")),
        output_tokens=integer(usage.get("output_tokens")),
        total_tokens=integer(usage.get("total_tokens")),
        reasoning_tokens=integer(output_details.get("reasoning_tokens")),
        cached_input_tokens=integer(input_details.get("cached_tokens")),
    )


async def _emit(callback: EventCallback | None, event: ModelEvent) -> None:
    if callback is not None:
        await callback(event)
