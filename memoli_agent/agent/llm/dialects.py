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

    @property
    def buffer_content(self) -> bool: ...

    def visible_content(self, content: str) -> str: ...


@dataclass(frozen=True, slots=True)
class DefaultDialect:
    name: str = "default"

    def prepare(self, kwargs: dict[str, Any], request: ModelRequest) -> None:
        return None

    def reasoning_delta(self, delta: Any) -> str:
        return ""

    @property
    def buffer_content(self) -> bool:
        return False

    def visible_content(self, content: str) -> str:
        return content


@dataclass(frozen=True, slots=True)
class DeepSeekDialect(DefaultDialect):
    name: str = "deepseek"

    def prepare(self, kwargs: dict[str, Any], request: ModelRequest) -> None:
        # DeepSeek Chat Completions 使用兼容字段 max_tokens。
        kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
        if request.effective_reasoning_policy.enabled:
            kwargs["extra_body"] = {"thinking": {"type": "enabled"}}

    def reasoning_delta(self, delta: Any) -> str:
        return str(getattr(delta, "reasoning_content", "") or "")


@dataclass(frozen=True, slots=True)
class DashScopeDialect(DefaultDialect):
    name: str = "dashscope"

    def prepare(self, kwargs: dict[str, Any], request: ModelRequest) -> None:
        kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
        if request.effective_reasoning_policy.enabled:
            kwargs["extra_body"] = {"enable_thinking": True}


@dataclass(frozen=True, slots=True)
class OllamaDialect(DefaultDialect):
    name: str = "ollama"

    def prepare(self, kwargs: dict[str, Any], request: ModelRequest) -> None:
        kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")


@dataclass(frozen=True, slots=True)
class QwenVLLMDialect(DefaultDialect):
    """vLLM 承载 Qwen3 时使用的显式方言。"""

    name: str = "qwen-vllm"

    def prepare(self, kwargs: dict[str, Any], request: ModelRequest) -> None:
        kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
        extra_body = dict(kwargs.get("extra_body") or {})
        chat_template_kwargs = dict(extra_body.get("chat_template_kwargs") or {})
        chat_template_kwargs["enable_thinking"] = (
            request.effective_reasoning_policy.enabled
        )
        extra_body["chat_template_kwargs"] = chat_template_kwargs
        kwargs["extra_body"] = extra_body

    def reasoning_delta(self, delta: Any) -> str:
        return str(getattr(delta, "reasoning_content", "") or "")

    @property
    def buffer_content(self) -> bool:
        # think 标签可能横跨多个 SSE chunk，分类完成前不能向展示边界发布。
        return True

    def visible_content(self, content: str) -> str:
        return _without_qwen_think_blocks(content)


def _without_qwen_think_blocks(content: str) -> str:
    """删除 Qwen 内联 think 块；不对自然语言做启发式分类。"""

    opening = "<think>"
    closing = "</think>"
    lowered = content.lower()
    visible: list[str] = []
    cursor = 0
    removed = False
    while cursor < len(content):
        start = lowered.find(opening, cursor)
        unmatched_close = lowered.find(closing, cursor)
        if unmatched_close >= 0 and (start < 0 or unmatched_close < start):
            # 部分服务会去掉开标签但保留闭标签；闭标签前仍按推理处理。
            cursor = unmatched_close + len(closing)
            visible.clear()
            removed = True
            continue
        if start < 0:
            visible.append(content[cursor:])
            break
        visible.append(content[cursor:start])
        end = lowered.find(closing, start + len(opening))
        removed = True
        if end < 0:
            # 未闭合推理块采用 fail-closed，避免半截思考泄漏。
            break
        cursor = end + len(closing)
    result = "".join(visible)
    return result.lstrip() if removed else result


_DIALECTS: dict[str, OpenAIDialect] = {
    "default": DefaultDialect(),
    "openai": DefaultDialect(),
    "deepseek": DeepSeekDialect(),
    "dashscope": DashScopeDialect(),
    "ollama": OllamaDialect(),
    "qwen-vllm": QwenVLLMDialect(),
}


def resolve_dialect(name: str) -> OpenAIDialect:
    """按显式名称选择方言，禁止隐式字符串猜测。"""

    key = (name or "default").strip().lower()
    try:
        return _DIALECTS[key]
    except KeyError as exc:
        raise ValueError(f"未知 OpenAI-compatible dialect：{name}") from exc
