"""与厂商 SDK 无关的模型数据合同。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, TypeAlias

from memoli_agent.agent.types import ChatMessage


class ModelCapability(StrEnum):
    """模型可声明的稳定能力。"""

    TEXT = "text"
    TOOLS = "tools"
    REASONING = "reasoning"
    STREAMING = "streaming"
    STRUCTURED_OUTPUT = "structured-output"
    VISION = "vision"
    PROMPT_CACHE = "prompt-cache"


class ReasoningMode(StrEnum):
    """跨提供商的推理启用策略。"""

    OFF = "off"
    ADAPTIVE = "adaptive"


class ReasoningVisibility(StrEnum):
    """允许投影到用户界面的提供商推理信息级别。"""

    HIDDEN = "hidden"
    SUMMARY = "summary"
    UPDATES = "updates"


@dataclass(frozen=True, slots=True)
class ReasoningPolicy:
    """一次逻辑交换中冻结的提供商中立推理策略。"""

    mode: ReasoningMode = ReasoningMode.OFF
    effort: str | None = None
    visibility: ReasoningVisibility = ReasoningVisibility.HIDDEN

    def __post_init__(self) -> None:
        allowed_efforts = {"low", "medium", "high", "xhigh", "max"}
        if self.effort is not None and self.effort not in allowed_efforts:
            raise ValueError(f"未知推理强度：{self.effort}")
        if self.mode is ReasoningMode.OFF and self.effort is not None:
            raise ValueError("关闭推理时不能设置 reasoning_effort。")
        if (
            self.mode is ReasoningMode.OFF
            and self.visibility is not ReasoningVisibility.HIDDEN
        ):
            raise ValueError("关闭推理时 reasoning_visibility 必须为 hidden。")

    @property
    def enabled(self) -> bool:
        return self.mode is not ReasoningMode.OFF


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """一个模型 Profile 的显式能力集合。"""

    values: frozenset[ModelCapability] = field(
        default_factory=lambda: frozenset({ModelCapability.TEXT})
    )

    @classmethod
    def from_strings(cls, values: Sequence[str]) -> ModelCapabilities:
        try:
            parsed = frozenset(ModelCapability(value) for value in values)
        except ValueError as exc:
            raise ValueError(f"未知模型能力：{exc}") from exc
        if ModelCapability.TEXT not in parsed:
            parsed = parsed | {ModelCapability.TEXT}
        return cls(parsed)

    def supports(self, required: ModelCapabilities) -> bool:
        return required.values.issubset(self.values)

    def to_strings(self) -> tuple[str, ...]:
        return tuple(sorted(value.value for value in self.values))


@dataclass(frozen=True, slots=True)
class TextBlock:
    """模型可见文本块。"""

    text: str


@dataclass(frozen=True, slots=True)
class ThinkingBlock:
    """旧版 Provider 私有思考块；仅供迁移读取，不得持久化。"""

    thinking: str = ""
    signature: str | None = None
    redacted: bool = False
    opaque: str | None = None


@dataclass(frozen=True, slots=True)
class ReasoningSummaryBlock:
    """Provider 明确标记且允许展示的有界推理摘要。"""

    text: str
    kind: ReasoningVisibility = ReasoningVisibility.SUMMARY


@dataclass(frozen=True, slots=True)
class OpaqueContinuation:
    """只能原样返回给同一协议的瞬态私有续接信封。"""

    protocol: str
    version: int = 1
    items: tuple[Mapping[str, Any], ...] = ()
    provider: str = ""
    profile: str = ""
    model: str = ""
    reasoning_policy: ReasoningPolicy = field(default_factory=ReasoningPolicy)

    def __post_init__(self) -> None:
        if not self.protocol:
            raise ValueError("不透明续接信封必须包含协议标签。")


@dataclass(slots=True)
class ProviderExchange:
    """一次模型决策到工具结果续接结束的瞬态状态。"""

    exchange_id: str
    reasoning_policy: ReasoningPolicy = field(default_factory=ReasoningPolicy)
    continuation: OpaqueContinuation | None = None
    provider: str = ""
    profile: str = ""
    model: str = ""
    protocol: str = ""
    status: str = "active"

    def accept(self, response: LLMResponse) -> None:
        self.provider = response.provider or self.provider
        self.profile = response.profile or self.profile
        self.model = response.model or self.model
        self.protocol = response.protocol or self.protocol
        self.continuation = response.continuation
        if response.continuation is not None:
            self.reasoning_policy = response.continuation.reasoning_policy

    def complete(self) -> None:
        self.continuation = None
        self.status = "completed"

    def fail(self) -> None:
        self.continuation = None
        self.status = "failed"

    def cancel(self) -> None:
        self.continuation = None
        self.status = "cancelled"


@dataclass(frozen=True, slots=True)
class ToolUseBlock:
    """Assistant 发出的结构化工具调用。"""

    id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id or not self.name:
            raise ValueError("工具调用必须包含非空 id 和 name。")
        if not isinstance(self.arguments, Mapping):
            raise TypeError("工具调用 arguments 必须是对象。")


@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    """与某个工具调用 ID 关联的执行结果。"""

    tool_use_id: str
    content: str
    is_error: bool = False
    name: str | None = None

    def __post_init__(self) -> None:
        if not self.tool_use_id:
            raise ValueError("工具结果必须包含 tool_use_id。")


ContentBlock: TypeAlias = (
    TextBlock
    | ReasoningSummaryBlock
    | ThinkingBlock
    | ToolUseBlock
    | ToolResultBlock
)


@dataclass(frozen=True, slots=True)
class ModelMessage:
    """由有序内容块组成的规范化消息。"""

    role: str
    blocks: tuple[ContentBlock, ...]

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant"}:
            raise ValueError(f"不支持的模型消息角色：{self.role}")
        if self.role == "system" and any(
            not isinstance(block, TextBlock) for block in self.blocks
        ):
            raise ValueError("system 消息只能包含文本块。")
        if self.role == "assistant" and any(
            isinstance(block, ToolResultBlock) for block in self.blocks
        ):
            raise ValueError("assistant 消息不能包含工具结果。")
        if self.role == "user" and any(
            isinstance(block, ThinkingBlock | ToolUseBlock) for block in self.blocks
        ):
            raise ValueError("user 消息不能包含思考或工具调用块。")

    @property
    def text(self) -> str:
        return "".join(
            block.text for block in self.blocks if isinstance(block, TextBlock)
        )


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """跨 Provider 的 Token 使用量。未知字段保持为 None。"""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None

    def to_dict(self) -> dict[str, int]:
        return {
            key: value
            for key, value in (
                ("input_tokens", self.input_tokens),
                ("output_tokens", self.output_tokens),
                ("total_tokens", self.total_tokens),
                ("reasoning_tokens", self.reasoning_tokens),
                ("cached_input_tokens", self.cached_input_tokens),
                ("cache_creation_input_tokens", self.cache_creation_input_tokens),
            )
            if value is not None
        }


@dataclass(frozen=True, slots=True)
class ProviderAttempt:
    """一次可安全投影到 Hook/轨迹的传输尝试。"""

    attempt: int
    outcome: str
    duration_seconds: float
    error_type: str | None = None
    status_code: int | None = None
    retryable: bool = False
    retry_wait_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "outcome": self.outcome,
            "duration_seconds": self.duration_seconds,
            "error_type": self.error_type,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "retry_wait_seconds": self.retry_wait_seconds,
        }


@dataclass(frozen=True, slots=True)
class ToolCall:
    """兼容现有 Reasoner 的规范化工具调用。"""

    name: str
    arguments: dict[str, Any]
    id: str | None = None


class ModelEventKind(StrEnum):
    """流式模型事件种类。"""

    THINKING_DELTA = "thinking_delta"
    REASONING_SUMMARY_DELTA = "reasoning_summary_delta"
    PROGRESS_UPDATE = "progress_update"
    TEXT_DELTA = "text_delta"
    TOOL_CALL_DELTA = "tool_call_delta"
    USAGE = "usage"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class ModelEvent:
    """不暴露 SDK 对象的流式事件。"""

    kind: ModelEventKind
    text: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    arguments_delta: str = ""
    usage: TokenUsage | None = None


EventCallback: TypeAlias = Callable[[ModelEvent], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """一次无状态模型调用。"""

    messages: tuple[ModelMessage, ...]
    tools: tuple[Mapping[str, Any], ...] = ()
    model: str = ""
    max_output_tokens: int = 8192
    tool_choice: str | Mapping[str, Any] = "auto"
    temperature: float | None = None
    reasoning: bool = False
    reasoning_policy: ReasoningPolicy = field(default_factory=ReasoningPolicy)
    continuation: OpaqueContinuation | None = None
    stream: bool = False
    structured_output: Mapping[str, Any] | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens 必须大于 0。")

    def required_capabilities(self) -> ModelCapabilities:
        required = {ModelCapability.TEXT}
        if self.tools:
            required.add(ModelCapability.TOOLS)
        if self.effective_reasoning_policy.enabled:
            required.add(ModelCapability.REASONING)
        if self.stream:
            required.add(ModelCapability.STREAMING)
        if self.structured_output is not None:
            required.add(ModelCapability.STRUCTURED_OUTPUT)
        return ModelCapabilities(frozenset(required))

    @property
    def effective_reasoning_policy(self) -> ReasoningPolicy:
        """兼容旧 `reasoning=True` 调用，同时优先使用显式策略。"""

        if self.reasoning_policy.enabled or not self.reasoning:
            return self.reasoning_policy
        return ReasoningPolicy(mode=ReasoningMode.ADAPTIVE)

    @classmethod
    def from_chat_messages(
        cls,
        messages: Sequence[ChatMessage],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        model: str = "",
        max_output_tokens: int = 8192,
        stream: bool = False,
        reasoning_policy: ReasoningPolicy | None = None,
        continuation: OpaqueContinuation | None = None,
    ) -> ModelRequest:
        return cls(
            messages=tuple(chat_message_to_model(message) for message in messages),
            tools=tuple(dict(tool) for tool in (tools or ())),
            model=model,
            max_output_tokens=max_output_tokens,
            stream=stream,
            reasoning_policy=reasoning_policy or ReasoningPolicy(),
            continuation=continuation,
        )


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """规范化响应，并保持旧 Provider 返回字段兼容。"""

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    provider: str = ""
    fallback_used: bool = False
    finish_reason: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    error_type: str | None = None
    message: ModelMessage | None = None
    model: str = ""
    request_id: str = ""
    protocol: str = ""
    dialect: str = "default"
    profile: str = ""
    requested_provider: str = ""
    requested_model: str = ""
    fallback_reason: str = ""
    attempt_count: int = 1
    attempts: tuple[ProviderAttempt, ...] = ()
    partial_stream: bool = False
    capabilities: tuple[str, ...] = ()
    continuation: OpaqueContinuation | None = None

    @property
    def token_usage(self) -> TokenUsage:
        return token_usage_from_mapping(self.usage)


ModelResponse = LLMResponse


class LLMProvider(Protocol):
    """新 Provider 的统一异步合同。"""

    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> ModelCapabilities: ...

    async def complete(
        self,
        request: ModelRequest,
        on_event: EventCallback | None = None,
    ) -> ModelResponse: ...

    async def aclose(self) -> None: ...


class LegacyLLMProvider(Protocol):
    """迁移期旧 `chat` Provider 合同。"""

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse: ...


def token_usage_from_mapping(value: Mapping[str, Any]) -> TokenUsage:
    """从新旧 Provider usage 字段构造规范化使用量。"""

    def integer(*keys: str) -> int | None:
        for key in keys:
            raw = value.get(key)
            if raw is not None:
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    return None
        return None

    input_tokens = integer("input_tokens", "prompt_tokens")
    output_tokens = integer("output_tokens", "completion_tokens")
    total_tokens = integer("total_tokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        reasoning_tokens=integer("reasoning_tokens"),
        cached_input_tokens=integer("cached_input_tokens", "cache_read_input_tokens"),
        cache_creation_input_tokens=integer("cache_creation_input_tokens"),
    )


def chat_message_to_model(message: ChatMessage) -> ModelMessage:
    """将旧 ChatMessage 转成有序内容块。"""

    if message.blocks is not None:
        return ModelMessage(
            role="user" if message.role == "tool" else message.role,
            blocks=tuple(block_from_dict(block) for block in message.blocks),
        )
    if message.role == "tool":
        return ModelMessage(
            role="user",
            blocks=(
                ToolResultBlock(
                    tool_use_id=message.tool_call_id or "",
                    content=message.content,
                    name=message.name,
                ),
            ),
        )
    blocks: list[ContentBlock] = []
    if message.content:
        blocks.append(TextBlock(message.content))
    if message.role == "assistant":
        for raw_call in message.tool_calls or ():
            function = raw_call.get("function", {})
            raw_arguments = function.get("arguments", {})
            arguments = _json_object(raw_arguments)
            blocks.append(
                ToolUseBlock(
                    id=str(raw_call.get("id") or ""),
                    name=str(function.get("name") or ""),
                    arguments=arguments,
                )
            )
    return ModelMessage(role=message.role, blocks=tuple(blocks))


def model_message_to_chat(message: ModelMessage) -> ChatMessage:
    """将规范化消息转换为旧 Runtime 可保存的 ChatMessage。"""

    tool_results = [
        block for block in message.blocks if isinstance(block, ToolResultBlock)
    ]
    if len(tool_results) == 1 and len(message.blocks) == 1:
        result = tool_results[0]
        return ChatMessage(
            role="tool",
            content=result.content,
            tool_call_id=result.tool_use_id,
            name=result.name,
            blocks=tuple(block_to_dict(block) for block in message.blocks),
        )
    tool_calls = [
        {
            "id": block.id,
            "type": "function",
            "function": {
                "name": block.name,
                "arguments": json.dumps(
                    dict(block.arguments), ensure_ascii=False, sort_keys=True
                ),
            },
        }
        for block in message.blocks
        if isinstance(block, ToolUseBlock)
    ]
    return ChatMessage(
        role=message.role,
        content=message.text,
        tool_calls=tool_calls or None,
        blocks=tuple(block_to_dict(block) for block in message.blocks),
    )


def block_to_dict(block: ContentBlock) -> dict[str, Any]:
    """序列化内容块；opaque 字段只供内存续接，不应写入轨迹。"""

    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ReasoningSummaryBlock):
        return {
            "type": "reasoning_summary",
            "text": block.text,
            "kind": block.kind.value,
        }
    if isinstance(block, ThinkingBlock):
        value: dict[str, Any] = {
            "type": "redacted_thinking" if block.redacted else "thinking",
            "thinking": block.thinking,
        }
        if block.signature is not None:
            value["signature"] = block.signature
        if block.opaque is not None:
            value["opaque"] = block.opaque
        return value
    if isinstance(block, ToolUseBlock):
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": dict(block.arguments),
        }
    return {
        "type": "tool_result",
        "tool_use_id": block.tool_use_id,
        "content": block.content,
        "is_error": block.is_error,
        "name": block.name,
    }


def block_from_dict(value: Mapping[str, Any]) -> ContentBlock:
    """反序列化由 Memoli 自己生成的内容块。"""

    block_type = str(value.get("type") or "")
    if block_type == "text":
        return TextBlock(str(value.get("text") or ""))
    if block_type == "reasoning_summary":
        return ReasoningSummaryBlock(
            text=str(value.get("text") or ""),
            kind=ReasoningVisibility(str(value.get("kind") or "summary")),
        )
    if block_type in {"thinking", "redacted_thinking"}:
        return ThinkingBlock(
            thinking=str(value.get("thinking") or ""),
            signature=(
                str(value["signature"]) if value.get("signature") is not None else None
            ),
            redacted=block_type == "redacted_thinking",
            opaque=(str(value["opaque"]) if value.get("opaque") is not None else None),
        )
    if block_type == "tool_use":
        return ToolUseBlock(
            id=str(value.get("id") or ""),
            name=str(value.get("name") or ""),
            arguments=dict(value.get("input") or {}),
        )
    if block_type == "tool_result":
        return ToolResultBlock(
            tool_use_id=str(value.get("tool_use_id") or ""),
            content=str(value.get("content") or ""),
            is_error=bool(value.get("is_error", False)),
            name=(str(value["name"]) if value.get("name") is not None else None),
        )
    raise ValueError(f"未知内容块类型：{block_type}")


def portable_message(message: ModelMessage) -> ModelMessage:
    """移除跨 Provider 不可安全重放的思考签名。"""

    return ModelMessage(
        role=message.role,
        blocks=tuple(
            block for block in message.blocks if not isinstance(block, ThinkingBlock)
        ),
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        raise ValueError("工具参数必须是 JSON object。")
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("工具参数必须是 JSON object。")
    return parsed
