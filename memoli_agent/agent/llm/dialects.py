"""显式注册的 OpenAI-compatible 方言。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from memoli_agent.agent.llm.contracts import ModelRequest


class OpenAIDialect(Protocol):
    """仅处理已知厂商字段差异，不参与路由。"""

    @property
    def name(self) -> str: ...

    def prepare(self, kwargs: dict[str, Any], request: ModelRequest) -> None: ...

    def reasoning_delta(self, delta: Any) -> str: ...


@dataclass(frozen=True, slots=True)
class DefaultDialect:
    name: str = "default"

    def prepare(self, kwargs: dict[str, Any], request: ModelRequest) -> None:
        return None

    def reasoning_delta(self, delta: Any) -> str:
        return ""


@dataclass(frozen=True, slots=True)
class DeepSeekDialect(DefaultDialect):
    name: str = "deepseek"

    def prepare(self, kwargs: dict[str, Any], request: ModelRequest) -> None:
        # DeepSeek Chat Completions 使用兼容字段 max_tokens。
        kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
        if request.reasoning:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

    def reasoning_delta(self, delta: Any) -> str:
        return str(getattr(delta, "reasoning_content", "") or "")


@dataclass(frozen=True, slots=True)
class DashScopeDialect(DefaultDialect):
    name: str = "dashscope"

    def prepare(self, kwargs: dict[str, Any], request: ModelRequest) -> None:
        kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
        if request.reasoning:
            kwargs["extra_body"] = {"enable_thinking": True}


@dataclass(frozen=True, slots=True)
class OllamaDialect(DefaultDialect):
    name: str = "ollama"

    def prepare(self, kwargs: dict[str, Any], request: ModelRequest) -> None:
        kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")


_DIALECTS: dict[str, OpenAIDialect] = {
    "default": DefaultDialect(),
    "openai": DefaultDialect(),
    "deepseek": DeepSeekDialect(),
    "dashscope": DashScopeDialect(),
    "ollama": OllamaDialect(),
}


def resolve_dialect(name: str) -> OpenAIDialect:
    """按显式名称选择方言，禁止隐式字符串猜测。"""

    key = (name or "default").strip().lower()
    try:
        return _DIALECTS[key]
    except KeyError as exc:
        raise ValueError(f"未知 OpenAI-compatible dialect：{name}") from exc
