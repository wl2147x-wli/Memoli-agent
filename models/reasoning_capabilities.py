"""Provider-native reasoning capability metadata."""

from __future__ import annotations

from copy import deepcopy
from typing import Optional


DEEPSEEK_VALUES = ["low", "high", "xhigh", "max"]
ZHIPU_VALUES = ["low", "medium", "high", "xhigh", "max"]
# GLM-5.3总是思考（拒绝thinking.type =“disabled”）并且只暴露
# 三个努力层。请参阅 https://docs.bigmodel.cn GLM-5.3 发行说明。
ZHIPU_GLM53_VALUES = ["low", "high", "max"]
CLAUDE_VALUES = ["low", "medium", "high", "xhigh", "max"]
CLAUDE_MAX_ONLY_VALUES = ["low", "medium", "high", "max"]
DASHSCOPE_QWEN38_VALUES = ["low", "medium", "xhigh"]
DASHSCOPE_HIGH_MAX_VALUES = ["high", "max"]
DASHSCOPE_MAX_ONLY_VALUES = ["max"]
KIMI_K3_VALUES = ["low", "high", "max"]
CLAUDE_XHIGH_MODELS = (
    "claude-fable-5-1",
    "claude-fable-5",
    "claude-mythos-5",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-sonnet-5",
)
CLAUDE_MAX_ONLY_MODELS = (
    "claude-mythos-preview",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-opus-4-5",
)
DASHSCOPE_QWEN38_MODELS = (
    # qwen3.8-max/-flash 及其 -preview 快照共享低/中/xhigh
    # 枚举（默认 xhigh）并始终思考。
    "qwen3.8-max",
    "qwen3.8-flash",
)
DASHSCOPE_HIGH_MAX_MODELS = (
    "glm-5.2",
    "glm-5.1",
    "glm-5",
)
DASHSCOPE_MAX_ONLY_MODELS = (
    "kimi/kimi-k3",
)
# 无论由哪个网关代理，GLM-5.3 都会始终思考。
ZHIPU_GLM53_MODELS = (
    "glm-5.3",
)


def _option(value: str) -> dict:
    return {"value": value, "label": value}


def _capability(
    values: list[str],
    default: str = "high",
    param: str = "reasoning_effort",
    thinking_only: bool = False,
) -> dict:
    """Build the JSON shape shared by Web/Desktop config clients."""
    capability = {
        "supported": True,
        "param": param,
        "default": default,
        "options": [_option(value) for value in values],
    }
    if thinking_only:
        capability["thinking_only"] = True
    return capability


def _base_provider_id(provider_id: str) -> str:
    """Normalize legacy config ids to the provider ids used in this module."""
    pid = (provider_id or "").strip()
    if pid.startswith("custom:"):
        return "custom"
    if pid == "chatGPT":
        return "openai"
    if pid == "claudeAPI":
        return "claude"
    return pid


def get_reasoning_capability(provider_id: str, model_name: str = "") -> dict:
    """Return provider-native reasoning metadata for a provider/model pair."""
    base_pid = _base_provider_id(provider_id)
    model = (model_name or "").strip().lower()

    if base_pid == "deepseek" and model.startswith("deepseek-v4"):
        return _capability(DEEPSEEK_VALUES, default="high")

    if base_pid == "zhipu":
        if model.startswith(ZHIPU_GLM53_MODELS):
            return _capability(ZHIPU_GLM53_VALUES, default="max", thinking_only=True)
        return _capability(ZHIPU_VALUES, default="high")

    if base_pid == "claude":
        # Claude 使用 Anthropic 的 output_config.effort 字段，因此 UI 可能
        # 即使通用思维切换被禁用，也会暴露它。
        if model.startswith(CLAUDE_XHIGH_MODELS):
            return _capability(CLAUDE_VALUES, default="high", param="effort")
        if model.startswith(CLAUDE_MAX_ONLY_MODELS):
            return _capability(CLAUDE_MAX_ONLY_VALUES, default="high", param="effort")

    if base_pid == "dashscope":
        # DashScope 代理多家供应商。保持功能模型范围
        # 不受支持的 Qwen/GLM/Kimi 变体不会继承另一个枚举集。
        if model.startswith(DASHSCOPE_QWEN38_MODELS):
            return _capability(DASHSCOPE_QWEN38_VALUES, default="xhigh", thinking_only=True)
        # 无论托管在何处，deepseek-v4 都采用相同的枚举；两个
        # 变体仅在内部映射值的方式上有所不同。
        if model.startswith("deepseek-v4"):
            return _capability(DEEPSEEK_VALUES, default="high")
        if model.startswith(ZHIPU_GLM53_MODELS):
            return _capability(ZHIPU_GLM53_VALUES, default="max", thinking_only=True)
        if model.startswith(DASHSCOPE_HIGH_MAX_MODELS):
            return _capability(DASHSCOPE_HIGH_MAX_VALUES, default="high")
        if model.startswith(DASHSCOPE_MAX_ONLY_MODELS):
            return _capability(DASHSCOPE_MAX_ONLY_VALUES, default="max")

    if base_pid == "moonshot" and model.startswith("kimi-k3"):
        return _capability(KIMI_K3_VALUES, default="max", thinking_only=True)

    if base_pid == "linkai":
        # LinkAI是一个网关；只暴露模型的直通工作
        # 上游协议已在这里得到验证。
        if model.startswith("deepseek-v4"):
            return _capability(DEEPSEEK_VALUES, default="high")
        if model.startswith(ZHIPU_GLM53_MODELS):
            return _capability(ZHIPU_GLM53_VALUES, default="max", thinking_only=True)
        if model.startswith("glm-"):
            return _capability(ZHIPU_VALUES, default="high")
        if model.startswith("kimi-k3"):
            return _capability(KIMI_K3_VALUES, default="max", thinking_only=True)

    return {"supported": False, "options": []}


def _legacy_remap(base_pid: str, model: str, effort: str) -> str:
    """Map a legacy global effort value to a provider-native enum.

    This exists only to migrate the old single global ``reasoning_effort`` key.
    Per-model values stored in ``reasoning_effort_by_model`` are *not* remapped
    (see ``resolve_reasoning_effort``) — they are the model's own intent.
    """
    if base_pid == "dashscope":
        if model.startswith(DASHSCOPE_QWEN38_MODELS):
            effort = {
                "high": "xhigh",
                "max": "xhigh",
                "minimal": "low",
            }.get(effort, effort)
        elif model.startswith(DASHSCOPE_HIGH_MAX_MODELS):
            effort = {
                "low": "high",
                "medium": "high",
                "xhigh": "max",
            }.get(effort, effort)
        elif model.startswith(DASHSCOPE_MAX_ONLY_MODELS):
            effort = {
                "low": "max",
                "medium": "max",
                "high": "max",
                "xhigh": "max",
            }.get(effort, effort)
    elif base_pid == "linkai":
        if model.startswith("glm-"):
            effort = {
                "minimal": "high",
                "none": "high",
            }.get(effort, effort)
        elif model.startswith("kimi-k3"):
            effort = {
                "medium": "max",
                "xhigh": "max",
            }.get(effort, effort)

    return effort


def _validate_effort(value: object, capability: dict) -> Optional[str]:
    """Pure validation: return ``value`` if it is in the capability's allowed
    set, otherwise fall back to the capability's default. No remapping."""
    effort = str(value or "").strip()
    allowed = [item["value"] for item in capability.get("options", [])]
    if effort in allowed:
        return effort
    return capability.get("default")


def normalize_reasoning_effort(provider_id: str, model_name: str, value: object) -> Optional[str]:
    """Validate a saved effort value against the active provider capability.

    Applies the legacy remap (migration of the old global key). See
    ``resolve_reasoning_effort`` for the per-model config resolution path.
    """
    capability = get_reasoning_capability(provider_id, model_name)
    if not capability.get("supported"):
        return None

    base_pid = _base_provider_id(provider_id)
    model = (model_name or "").strip().lower()
    effort = _legacy_remap(base_pid, model, str(value or "").strip())
    return _validate_effort(effort, capability)


def resolve_reasoning_effort(
    provider_id: str, model_name: str, by_model: dict, legacy_value: object
) -> Optional[str]:
    """Resolve the effective effort for an active provider/model.

    This is *config resolution*, not provider normalization: it reads a
    per-model value from ``reasoning_effort_by_model`` and only validates it
    against the model's capability. It never remaps across vendors — a value a
    user set for a specific model is their intent for that model.

    Candidate keys are tried in order so that ``custom:foo:model`` is not
    collapsed to ``custom:model`` when two custom providers share a model name:
      ``<raw_provider>:<model>`` → ``<base_provider>:<model>`` → ``<model>``

    When no per-model value exists, falls back to the legacy global
    ``reasoning_effort`` (which may be remapped for migration).
    """
    raw = (provider_id or "").strip()
    base = _base_provider_id(raw)
    model = (model_name or "").strip().lower()
    capability = get_reasoning_capability(base, model)
    if not capability.get("supported"):
        return None

    # 防止格式错误的持久值（例如手工编辑的 config.json
    # 或 env 覆盖将地图变成非字典），所以我们降级为
    # 遗留回退而不是提高/返回一个奇怪的值。
    if not isinstance(by_model, dict):
        by_model = {}

    for key in (f"{raw}:{model}", f"{base}:{model}", model):
        if key in by_model:
            return _validate_effort(by_model[key], capability)

    return normalize_reasoning_effort(base, model, legacy_value)


def provider_reasoning_metadata(provider_id: str, model_name: str = "") -> dict:
    """Return a defensive copy safe to embed in JSON responses."""
    return deepcopy(get_reasoning_capability(provider_id, model_name))
