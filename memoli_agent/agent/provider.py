"""LLM provider 抽象层。

第四阶段实现最小可替换模型接口：

- EchoProvider：本地测试用，不需要 API key。
- OpenAICompatibleProvider：调用 OpenAI-compatible chat completions 接口。
- LLMProvider 协议：让 Reasoner 不关心具体模型厂商。

当前不实现 streaming 和工具执行循环，只保留 tool call 数据结构。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from memoli_agent.agent.types import ChatMessage


class ProviderError(RuntimeError):
    """模型 provider 调用失败时抛出的统一异常。"""


@dataclass(frozen=True, slots=True)
class ToolCall:
    """模型返回的工具调用请求。

    第四阶段只定义结构，不执行工具调用。
    """

    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """模型返回结果。"""

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] | None = None
    provider: str = ""
    fallback_used: bool = False


class LLMProvider(Protocol):
    """统一的异步聊天 provider 协议。"""

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """根据 messages 生成回复。"""

        ...


@dataclass(frozen=True, slots=True)
class EchoProvider:
    """本地 Echo provider。

    用于无 API key、网络不可用或测试阶段，保证项目始终可运行。
    """

    name: str = "echo"

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """返回最后一条用户消息的 Echo 回复。"""

        user_content = ""
        for message in reversed(messages):
            if message.role == "user":
                user_content = message.content
                break

        return LLMResponse(
            content=f"Echo: {user_content}",
            provider=self.name,
        )


@dataclass(frozen=True, slots=True)
class OpenAICompatibleProvider:
    """OpenAI-compatible chat completions provider。"""

    model: str
    api_key: str
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = 60.0
    name: str = "openai-compatible"

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """调用远程 chat completions 接口。"""

        return await asyncio.to_thread(self._chat_sync, messages, tools)

    def _chat_sync(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
    ) -> LLMResponse:
        """在线程中执行阻塞 HTTP 请求。"""

        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [message.to_dict() for message in messages],
        }
        if tools:
            payload["tools"] = tools
        request = Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"HTTP 请求失败：{exc.code} {detail}") from exc
        except URLError as exc:
            raise ProviderError(f"网络请求失败：{exc.reason}") from exc
        except OSError as exc:
            raise ProviderError(f"provider 请求异常：{exc}") from exc

        try:
            raw = json.loads(raw_body)
            message = raw["choices"][0]["message"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderError("provider 响应格式无法解析。") from exc

        return LLMResponse(
            content=str(message.get("content") or ""),
            tool_calls=_parse_tool_calls(message.get("tool_calls", [])),
            raw=raw,
            provider=self.name,
        )


def _parse_tool_calls(raw_tool_calls: Any) -> list[ToolCall]:
    """解析 OpenAI-compatible tool_calls 字段。"""

    if not isinstance(raw_tool_calls, list):
        return []

    tool_calls: list[ToolCall] = []
    for raw_tool_call in raw_tool_calls:
        if not isinstance(raw_tool_call, dict):
            continue

        function = raw_tool_call.get("function", {})
        if not isinstance(function, dict):
            continue

        name = function.get("name")
        if not isinstance(name, str) or not name:
            continue

        tool_calls.append(
            ToolCall(
                id=raw_tool_call.get("id"),
                name=name,
                arguments=_parse_arguments(function.get("arguments", {})),
            )
        )

    return tool_calls


def _parse_arguments(raw_arguments: Any) -> dict[str, Any]:
    """解析工具调用参数。"""

    if isinstance(raw_arguments, dict):
        return raw_arguments

    if isinstance(raw_arguments, str):
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError:
            return {"raw": raw_arguments}
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}

    return {}
