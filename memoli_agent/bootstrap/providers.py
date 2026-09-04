"""LLM endpoints、Profiles 与 route 的单一组合根。"""

from __future__ import annotations

from dataclasses import dataclass

from memoli_agent.agent.llm.contracts import (
    LLMProvider,
    ModelCapabilities,
    ReasoningMode,
    ReasoningPolicy,
    ReasoningVisibility,
)
from memoli_agent.agent.llm.openai_responses_provider import OpenAIResponsesProvider
from memoli_agent.agent.llm.router import ModelRouter, ProviderTarget
from memoli_agent.agent.provider import AnthropicProvider, EchoProvider, OpenAIProvider
from memoli_agent.bootstrap.config import (
    LLMConfig,
    LLMProviderEndpointConfig,
)


@dataclass(frozen=True, slots=True)
class ProviderBundle:
    """bootstrap 交给 Runtime 的共享模型服务。"""

    provider: LLMProvider
    model_name: str
    targets: dict[str, ProviderTarget]


def build_model_provider(config: LLMConfig) -> ProviderBundle:
    """同时支持旧单段配置与新的显式 Profile route。"""

    if not config.uses_profiles:
        provider = _legacy_provider(config)
        capabilities = _legacy_capabilities(config.provider)
        router = ModelRouter(
            ProviderTarget(
                profile="default",
                model=config.model,
                provider=provider,
                capabilities=capabilities,
                max_output_tokens=config.max_output_tokens,
                context_window_tokens=config.context_window_tokens,
                context_safety_margin_tokens=config.context_safety_margin_tokens,
                token_estimator=config.token_estimator,
                reasoning_policy=_reasoning_policy(config),
            ),
            (),
        )
        return ProviderBundle(router, config.model, {"default": router.primary})

    endpoint_clients: dict[str, LLMProvider] = {}
    for endpoint_name, endpoint in config.providers.items():
        endpoint_clients[endpoint_name] = _provider_for_endpoint(
            endpoint_name,
            endpoint,
            _first_model_for_endpoint(config, endpoint_name),
        )

    def target(profile_name: str) -> ProviderTarget:
        profile = config.models[profile_name]
        provider = endpoint_clients[profile.provider]
        declared = ModelCapabilities.from_strings(profile.capabilities)
        effective = ModelCapabilities(
            frozenset(declared.values & provider.capabilities.values)
        )
        return ProviderTarget(
            profile=profile_name,
            model=profile.model,
            provider=provider,
            capabilities=effective,
            max_output_tokens=profile.max_output_tokens,
            context_window_tokens=profile.context_window_tokens,
            context_safety_margin_tokens=profile.context_safety_margin_tokens,
            token_estimator=profile.token_estimator,
            temperature=profile.temperature,
            reasoning_policy=_reasoning_policy(profile),
        )

    targets = {name: target(name) for name in config.models}
    primary = targets[config.routes.agent]
    fallbacks = tuple(targets[name] for name in config.routes.fallback)
    return ProviderBundle(ModelRouter(primary, fallbacks), primary.model, targets)


def _legacy_provider(config: LLMConfig) -> LLMProvider:
    provider_name = config.provider
    if provider_name == "echo":
        return EchoProvider()
    if provider_name == "anthropic":
        return AnthropicProvider(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url or "https://api.anthropic.com",
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
        )
    if provider_name == "openai-responses":
        return OpenAIResponsesProvider(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url or "https://api.openai.com/v1",
            timeout_seconds=config.timeout_seconds,
            max_retries=config.max_retries,
        )
    return OpenAIProvider(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url or "https://api.openai.com/v1",
        timeout_seconds=config.timeout_seconds,
        max_retries=config.max_retries,
        dialect=config.dialect,
        name=provider_name,
    )


def _provider_for_endpoint(
    name: str,
    endpoint: LLMProviderEndpointConfig,
    default_model: str,
) -> LLMProvider:
    if endpoint.protocol == "echo":
        return EchoProvider()
    if endpoint.protocol == "anthropic":
        return AnthropicProvider(
            model=default_model,
            api_key=endpoint.api_key,
            base_url=endpoint.base_url or "https://api.anthropic.com",
            timeout_seconds=endpoint.timeout_seconds,
            max_retries=endpoint.max_retries,
            name=name,
        )
    if endpoint.protocol == "openai-responses":
        return OpenAIResponsesProvider(
            model=default_model,
            api_key=endpoint.api_key,
            base_url=endpoint.base_url or "https://api.openai.com/v1",
            timeout_seconds=endpoint.timeout_seconds,
            max_retries=endpoint.max_retries,
            name=name,
        )
    return OpenAIProvider(
        model=default_model,
        api_key=endpoint.api_key,
        base_url=endpoint.base_url or "https://api.openai.com/v1",
        timeout_seconds=endpoint.timeout_seconds,
        max_retries=endpoint.max_retries,
        dialect=endpoint.dialect,
        name=name,
    )


def _first_model_for_endpoint(config: LLMConfig, endpoint_name: str) -> str:
    for profile in config.models.values():
        if profile.provider == endpoint_name:
            return profile.model
    raise ValueError(f"Provider endpoint {endpoint_name!r} 没有对应模型 Profile。")


def _legacy_capabilities(provider: str) -> ModelCapabilities:
    if provider == "echo":
        return ModelCapabilities.from_strings(["text", "tools"])
    values = ["text", "tools", "reasoning", "streaming"]
    if provider in {"openai", "openai-responses", "openai-compatible"}:
        values.append("structured-output")
    if provider == "anthropic":
        values.append("prompt-cache")
    return ModelCapabilities.from_strings(values)


def _reasoning_policy(config: object) -> ReasoningPolicy:
    return ReasoningPolicy(
        mode=ReasoningMode(str(getattr(config, "reasoning_mode", "off"))),
        effort=getattr(config, "reasoning_effort", None),
        visibility=ReasoningVisibility(
            str(getattr(config, "reasoning_visibility", "hidden"))
        ),
    )
