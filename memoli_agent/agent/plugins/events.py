"""类型化插件 Hook 事件、Patch 与策略决定。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from typing import Any


class HookName(StrEnum):
    """Agent Runtime 暴露给插件的稳定 Hook。"""

    RUNTIME_START = "runtime.start"
    TURN_BEFORE = "turn.before"
    CONTEXT_CONTRIBUTE = "context.contribute"
    MODEL_BEFORE = "model.before"
    MODEL_AFTER = "model.after"
    TOOL_BEFORE = "tool.before"
    TOOL_AFTER = "tool.after"
    RESPONSE_TRANSFORM = "response.transform"
    TURN_AFTER = "turn.after"
    RUNTIME_STOP = "runtime.stop"


class HookKind(StrEnum):
    """Hook 对主流程的影响语义。"""

    TRANSFORMER = "transformer"
    POLICY = "policy"
    OBSERVER = "observer"


class ToolDecisionAction(StrEnum):
    """工具策略 Hook 的标准动作。"""

    ALLOW = "allow"
    DENY = "deny"
    REWRITE = "rewrite"
    REQUIRE_CONFIRMATION = "require_confirmation"


TRANSFORMER_HOOKS = frozenset(
    {
        HookName.TURN_BEFORE,
        HookName.CONTEXT_CONTRIBUTE,
        HookName.RESPONSE_TRANSFORM,
    }
)
POLICY_HOOKS = frozenset({HookName.TOOL_BEFORE})
OBSERVER_HOOKS = frozenset(set(HookName) - TRANSFORMER_HOOKS - POLICY_HOOKS)


@dataclass(frozen=True, slots=True)
class HookEvent:
    """所有 Hook 事件共享的可追踪字段。"""

    trace_id: str = ""
    session_key: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RuntimeEvent(HookEvent):
    """Runtime 启停事件。"""

    runtime_version: str = ""


@dataclass(frozen=True, slots=True)
class TurnBeforeEvent(HookEvent):
    """用户 turn 开始事件。"""

    channel: str = ""
    chat_id: str = ""
    content: str = ""


@dataclass(frozen=True, slots=True)
class ContextSection:
    """插件贡献的有来源上下文段。"""

    name: str
    content: str
    source_plugin: str = ""
    order: int = 0


@dataclass(frozen=True, slots=True)
class ContextContributeEvent(HookEvent):
    """模型上下文贡献事件。"""

    messages: tuple[Mapping[str, Any], ...] = ()
    sections: tuple[ContextSection, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelBeforeEvent(HookEvent):
    """真实 Provider 请求前事件。"""

    iteration: int = 0
    model: str = ""
    provider: str = ""
    protocol: str = ""
    dialect: str = ""
    profile: str = ""
    capabilities: tuple[str, ...] = ()
    messages: tuple[Mapping[str, Any], ...] = ()
    tools: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ModelAfterEvent(HookEvent):
    """Provider 响应后事件。"""

    iteration: int = 0
    provider: str = ""
    model: str = ""
    protocol: str = ""
    dialect: str = ""
    profile: str = ""
    request_id: str = ""
    finish_reason: str = ""
    attempt_count: int = 1
    attempts: tuple[Mapping[str, Any], ...] = ()
    partial_stream: bool = False
    fallback_used: bool = False
    content: str = ""
    tool_names: tuple[str, ...] = ()
    error_type: str | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolBeforeEvent(HookEvent):
    """工具执行前策略事件。"""

    tool_name: str = ""
    arguments: Mapping[str, Any] = field(default_factory=dict)
    tool_call_id: str = ""


@dataclass(frozen=True, slots=True)
class ToolAfterEvent(HookEvent):
    """工具成功、失败或拒绝后的观察事件。"""

    tool_name: str = ""
    arguments: Mapping[str, Any] = field(default_factory=dict)
    tool_call_id: str = ""
    success: bool = False
    status: str = ""
    content: str = ""
    error_type: str | None = None


@dataclass(frozen=True, slots=True)
class ResponseTransformEvent(HookEvent):
    """出站前回复转换事件。"""

    content: str = ""
    outbound_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TurnAfterEvent(HookEvent):
    """turn 完成观察事件。"""

    content: str = ""
    termination_reason: str = ""


@dataclass(frozen=True, slots=True)
class TurnPatch:
    """`turn.before` 允许修改的字段。"""

    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContextPatch:
    """`context.contribute` 允许追加的上下文段。"""

    sections: tuple[ContextSection, ...] = ()


@dataclass(frozen=True, slots=True)
class ResponsePatch:
    """`response.transform` 允许修改的回复字段。"""

    content: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


HookPatch = TurnPatch | ContextPatch | ResponsePatch


@dataclass(frozen=True, slots=True)
class ToolDecision:
    """工具策略 Hook 的结构化决定。"""

    action: ToolDecisionAction = ToolDecisionAction.ALLOW
    reason: str = ""
    arguments: Mapping[str, Any] = field(default_factory=dict)
    error_type: str | None = None

    @classmethod
    def allow(cls) -> ToolDecision:
        return cls()

    @classmethod
    def deny(cls, reason: str, *, error_type: str | None = None) -> ToolDecision:
        return cls(
            action=ToolDecisionAction.DENY,
            reason=reason,
            error_type=error_type,
        )

    @classmethod
    def rewrite(cls, arguments: Mapping[str, Any], reason: str = "") -> ToolDecision:
        return cls(
            action=ToolDecisionAction.REWRITE,
            reason=reason,
            arguments=dict(arguments),
        )

    @classmethod
    def require_confirmation(cls, reason: str) -> ToolDecision:
        return cls(
            action=ToolDecisionAction.REQUIRE_CONFIRMATION,
            reason=reason,
        )


def validate_decision(value: object) -> ToolDecision:
    """拒绝伪造 action 或字段形状错误的策略结果。"""

    if not isinstance(value, ToolDecision):
        raise TypeError("tool.before 必须返回 ToolDecision。")
    if not isinstance(value.action, ToolDecisionAction):
        raise ValueError("ToolDecision action 无效。")
    if value.action is ToolDecisionAction.REWRITE and not isinstance(
        value.arguments, Mapping
    ):
        raise TypeError("rewrite arguments 必须是对象。")
    return value


_PATCH_TYPES: dict[HookName, type[HookPatch]] = {
    HookName.TURN_BEFORE: TurnPatch,
    HookName.CONTEXT_CONTRIBUTE: ContextPatch,
    HookName.RESPONSE_TRANSFORM: ResponsePatch,
}


def validate_patch(hook: HookName, patch: object) -> HookPatch:
    """校验 Hook 只能返回该阶段允许的 Patch。"""

    expected = _PATCH_TYPES.get(hook)
    if expected is None or not isinstance(patch, expected):
        name = expected.__name__ if expected is not None else "none"
        raise TypeError(f"{hook.value} 必须返回 {name}。")
    if isinstance(patch, ContextPatch):
        for section in patch.sections:
            if not section.name.strip() or len(section.name) > 128:
                raise ValueError("上下文 section 名称无效。")
            if len(section.content) > 32_000:
                raise ValueError("单个上下文 section 超过 32000 字符。")
    if isinstance(patch, ResponsePatch) and patch.content is not None:
        if len(patch.content) > 128_000:
            raise ValueError("插件回复 Patch 超过 128000 字符。")
    return patch


def apply_patch_to_event(event: HookEvent, patch: HookPatch) -> HookEvent:
    """把已校验 Patch 应用到对应不可变事件。"""

    if isinstance(event, TurnBeforeEvent) and isinstance(patch, TurnPatch):
        return replace(event, metadata={**event.metadata, **patch.metadata})
    if isinstance(event, ContextContributeEvent) and isinstance(patch, ContextPatch):
        return replace(event, sections=(*event.sections, *patch.sections))
    if isinstance(event, ResponseTransformEvent) and isinstance(patch, ResponsePatch):
        return replace(
            event,
            content=event.content if patch.content is None else patch.content,
            outbound_metadata={**event.outbound_metadata, **patch.metadata},
        )
    raise TypeError("Patch 与 Hook 事件类型不匹配。")


_EVENT_TYPES = {
    HookName.RUNTIME_START: RuntimeEvent,
    HookName.TURN_BEFORE: TurnBeforeEvent,
    HookName.CONTEXT_CONTRIBUTE: ContextContributeEvent,
    HookName.MODEL_BEFORE: ModelBeforeEvent,
    HookName.MODEL_AFTER: ModelAfterEvent,
    HookName.TOOL_BEFORE: ToolBeforeEvent,
    HookName.TOOL_AFTER: ToolAfterEvent,
    HookName.RESPONSE_TRANSFORM: ResponseTransformEvent,
    HookName.TURN_AFTER: TurnAfterEvent,
    HookName.RUNTIME_STOP: RuntimeEvent,
}


def event_to_dict(event: HookEvent) -> dict[str, Any]:
    """把事件转换为 JSON 兼容结构。"""

    return asdict(event)


def event_from_dict(hook: HookName, value: Mapping[str, Any]) -> HookEvent:
    """在 runner 侧恢复类型化事件。"""

    data = dict(value)
    if hook is HookName.CONTEXT_CONTRIBUTE:
        data["sections"] = tuple(
            ContextSection(**item) for item in data.get("sections", ())
        )
    for name in ("messages", "tools", "tool_names"):
        if name in data:
            data[name] = tuple(data[name])
    return _EVENT_TYPES[hook](**data)


def hook_result_to_dict(value: object) -> dict[str, Any] | None:
    """序列化沙箱 Hook 返回值并携带显式类型标签。"""

    if value is None:
        return None
    if isinstance(value, TurnPatch | ContextPatch | ResponsePatch | ToolDecision):
        return {"type": type(value).__name__, "value": asdict(value)}
    raise TypeError("沙箱 Hook 返回了不支持的类型。")


def hook_result_from_dict(value: object) -> object:
    """恢复沙箱 Hook 返回值。"""

    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("value"), dict):
        raise TypeError("沙箱 Hook 返回结构无效。")
    kind = value.get("type")
    data = dict(value["value"])
    if kind == "TurnPatch":
        return TurnPatch(**data)
    if kind == "ContextPatch":
        data["sections"] = tuple(
            ContextSection(**item) for item in data.get("sections", ())
        )
        return ContextPatch(**data)
    if kind == "ResponsePatch":
        return ResponsePatch(**data)
    if kind == "ToolDecision":
        data["action"] = ToolDecisionAction(data.get("action", "allow"))
        return ToolDecision(**data)
    raise TypeError(f"未知沙箱 Hook 返回类型：{kind}")
