from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from memoli_agent.agent.llm.anthropic_provider import AnthropicProvider
from memoli_agent.agent.llm.contracts import (
    ModelCapabilities,
    ModelMessage,
    ModelRequest,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    model_message_to_chat,
)
from memoli_agent.agent.llm.errors import (
    AuthenticationProviderError,
    ProviderNetworkError,
    UnsupportedCapabilityError,
)
from memoli_agent.agent.llm.openai_provider import OpenAIProvider
from memoli_agent.agent.llm.router import ModelRouter, ProviderTarget
from memoli_agent.agent.provider import EchoProvider, LLMResponse, ScriptedProvider
from memoli_agent.bootstrap.config import load_config
from memoli_agent.bootstrap.providers import build_model_provider


def test_ordered_blocks_round_trip_through_legacy_chat_message() -> None:
    message = ModelMessage(
        "assistant",
        (
            ThinkingBlock("分析", signature="opaque-signature"),
            TextBlock("准备调用工具"),
            ToolUseBlock("call-1", "read_file", {"path": "README.md"}),
        ),
    )

    restored = ModelRequest.from_chat_messages(
        [model_message_to_chat(message)]
    ).messages[0]

    assert restored == message
    assert restored.blocks[2] == ToolUseBlock(
        "call-1", "read_file", {"path": "README.md"}
    )


def test_invalid_role_block_combinations_are_rejected() -> None:
    with pytest.raises(ValueError, match="system"):
        ModelMessage("system", (ToolUseBlock("call-1", "x", {}),))
    with pytest.raises(ValueError, match="assistant"):
        ModelMessage("assistant", (ToolResultBlock("call-1", "ok"),))
    with pytest.raises(ValueError, match="user"):
        ModelMessage("user", (ThinkingBlock("private"),))


def test_router_falls_back_only_for_retryable_provider_failure() -> None:
    primary = ScriptedProvider(
        [ProviderNetworkError("temporary", provider="primary", retryable=True)],
        name="primary",
    )
    backup = ScriptedProvider(
        [LLMResponse("fallback answer", provider="backup", attempt_count=1)],
        name="backup",
    )
    capabilities = ModelCapabilities.from_strings(["text"])
    router = ModelRouter(
        ProviderTarget("main", "model-a", primary, capabilities),
        (ProviderTarget("backup", "model-b", backup, capabilities),),
    )

    response = asyncio.run(
        router.complete(ModelRequest((ModelMessage("user", (TextBlock("hi"),)),)))
    )

    assert response.content == "fallback answer"
    assert response.fallback_used is True
    assert response.profile == "backup"
    assert response.requested_provider == "primary"
    assert response.requested_model == "model-a"
    assert response.attempt_count == 2


def test_router_does_not_hide_permanent_authentication_failure() -> None:
    primary = ScriptedProvider(
        [AuthenticationProviderError("bad key", provider="primary")],
        name="primary",
    )
    backup = ScriptedProvider([LLMResponse("must not run")], name="backup")
    capabilities = ModelCapabilities.from_strings(["text"])
    router = ModelRouter(
        ProviderTarget("main", "model-a", primary, capabilities),
        (ProviderTarget("backup", "model-b", backup, capabilities),),
    )

    with pytest.raises(AuthenticationProviderError):
        asyncio.run(
            router.complete(ModelRequest((ModelMessage("user", (TextBlock("hi"),)),)))
        )
    assert not backup.calls


def test_router_does_not_continue_partial_stream_on_another_provider() -> None:
    primary = ScriptedProvider(
        [
            ProviderNetworkError(
                "stream broke",
                provider="primary",
                retryable=True,
                partial_stream=True,
            )
        ],
        name="primary",
    )
    backup = ScriptedProvider([LLMResponse("must not continue")], name="backup")
    capabilities = ModelCapabilities.from_strings(["text"])
    router = ModelRouter(
        ProviderTarget("main", "model-a", primary, capabilities),
        (ProviderTarget("backup", "model-b", backup, capabilities),),
    )

    with pytest.raises(ProviderNetworkError):
        asyncio.run(
            router.complete(ModelRequest((ModelMessage("user", (TextBlock("hi"),)),)))
        )
    assert not backup.calls


def test_router_rejects_missing_capability_before_network_call() -> None:
    provider = ScriptedProvider([LLMResponse("must not run")])
    router = ModelRouter(
        ProviderTarget(
            "text-only",
            "model-a",
            provider,
            ModelCapabilities.from_strings(["text"]),
        ),
        (),
    )
    request = ModelRequest(
        (ModelMessage("user", (TextBlock("hi"),)),),
        tools=({"type": "function", "function": {"name": "x"}},),
    )

    with pytest.raises(UnsupportedCapabilityError):
        asyncio.run(router.complete(request))
    assert not provider.calls


def test_echo_can_only_be_explicit_primary() -> None:
    capabilities = ModelCapabilities.from_strings(["text", "tools"])
    with pytest.raises(ValueError, match="Echo"):
        ModelRouter(
            ProviderTarget("main", "model-a", ScriptedProvider([]), capabilities),
            (ProviderTarget("echo", "echo", EchoProvider(), capabilities),),
        )


def test_new_config_supports_direct_and_environment_api_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MEMOLI_TEST_ANTHROPIC_KEY", "anthropic-secret")
    path = tmp_path / "config.toml"
    path.write_text(
        """
[llm.providers.openai]
protocol = "openai"
api_key = "openai-secret"

[llm.providers.anthropic]
protocol = "anthropic"
api_key = "${MEMOLI_TEST_ANTHROPIC_KEY}"

[llm.models.fast]
provider = "openai"
model = "gpt-test"
capabilities = ["text", "tools"]

[llm.models.deep]
provider = "anthropic"
model = "claude-test"
capabilities = ["text", "tools", "reasoning"]

[llm.routes]
agent = "fast"
fallback = ["deep"]
""",
        encoding="utf-8",
    )

    config = load_config(path).llm

    assert config.providers["openai"].api_key == "openai-secret"
    assert config.providers["anthropic"].api_key == "anthropic-secret"
    assert config.primary_model == "gpt-test"
    assert config.routes.fallback == ["deep"]
    assert "openai-secret" not in repr(config)
    assert "anthropic-secret" not in repr(config)


def test_formal_provider_missing_key_fails_fast(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        '[llm]\nprovider = "anthropic"\nmodel = "claude-test"\napi_key = ""\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="api_key"):
        load_config(path)


def test_profiles_on_same_endpoint_share_stateless_sdk_client(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[llm.providers.shared]
protocol = "openai"
api_key = "test-only"

[llm.models.main]
provider = "shared"
model = "model-a"
capabilities = ["text"]

[llm.models.backup]
provider = "shared"
model = "model-b"
capabilities = ["text"]

[llm.routes]
agent = "main"
fallback = ["backup"]
""",
        encoding="utf-8",
    )

    bundle = build_model_provider(load_config(path).llm)

    assert isinstance(bundle.provider, ModelRouter)
    assert bundle.provider.primary.provider is bundle.provider.fallbacks[0].provider
    asyncio.run(bundle.provider.aclose())


def test_missing_config_uses_explicit_echo() -> None:
    config = load_config("definitely-missing-memoli-config.toml")
    assert config.llm.provider == "echo"
    assert config.llm.model == "echo"


class _BlockingStream:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.closed = False

    def __aiter__(self) -> _BlockingStream:
        return self

    async def __anext__(self) -> Any:
        self.started.set()
        await asyncio.Event().wait()
        raise StopAsyncIteration

    async def close(self) -> None:
        self.closed = True


class _CreateEndpoint:
    def __init__(self, stream: _BlockingStream) -> None:
        self.stream = stream

    async def create(self, **kwargs: Any) -> _BlockingStream:
        return self.stream


@pytest.mark.parametrize("kind", ["openai", "anthropic"])
def test_stream_cancellation_closes_sdk_stream(kind: str) -> None:
    async def scenario() -> None:
        stream = _BlockingStream()
        endpoint = _CreateEndpoint(stream)
        if kind == "openai":
            client = SimpleNamespace(
                chat=SimpleNamespace(completions=endpoint),
            )
            provider = OpenAIProvider(model="model", api_key="unused", client=client)
        else:
            client = SimpleNamespace(messages=endpoint)
            provider = AnthropicProvider(model="model", api_key="unused", client=client)
        task = asyncio.create_task(
            provider.complete(
                ModelRequest((ModelMessage("user", (TextBlock("go"),)),), stream=True)
            )
        )
        await stream.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed is True

    asyncio.run(scenario())


def test_router_cancellation_never_starts_fallback() -> None:
    class CancelledProvider(ScriptedProvider):
        async def complete(
            self, request: ModelRequest, on_event: Any = None
        ) -> LLMResponse:
            raise asyncio.CancelledError

    primary = CancelledProvider([], name="primary")
    backup = ScriptedProvider([LLMResponse("must not run")], name="backup")
    capabilities = ModelCapabilities.from_strings(["text"])
    router = ModelRouter(
        ProviderTarget("main", "model-a", primary, capabilities),
        (ProviderTarget("backup", "model-b", backup, capabilities),),
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            router.complete(ModelRequest((ModelMessage("user", (TextBlock("go"),)),)))
        )
    assert not backup.calls


def test_router_close_is_idempotent_and_closes_shared_provider_once() -> None:
    class CloseTrackingProvider(ScriptedProvider):
        close_count = 0

        async def aclose(self) -> None:
            self.close_count += 1

    provider = CloseTrackingProvider([])
    capabilities = ModelCapabilities.from_strings(["text"])
    router = ModelRouter(
        ProviderTarget("main", "model-a", provider, capabilities),
        (ProviderTarget("backup", "model-b", provider, capabilities),),
    )

    async def scenario() -> None:
        await router.aclose()
        await router.aclose()

    asyncio.run(scenario())
    assert provider.close_count == 1
