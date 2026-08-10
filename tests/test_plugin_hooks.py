from __future__ import annotations

import asyncio

from memoli_agent.agent.plugins.events import (
    ContextContributeEvent,
    ContextPatch,
    ContextSection,
    HookKind,
    HookName,
    ResponsePatch,
    ToolBeforeEvent,
    ToolDecision,
    ToolDecisionAction,
    TurnBeforeEvent,
)
from memoli_agent.agent.plugins.hooks import HookBus, HookRegistration


def _registration(
    plugin_id: str,
    hook: HookName,
    kind: HookKind,
    callback: object,
    *,
    priority: int = 0,
    dependency_order: int = 0,
    deadline: float = 0.1,
) -> HookRegistration:
    return HookRegistration(
        plugin_id=plugin_id,
        plugin_version="1.0.0",
        backend="in_process",
        hook=hook,
        kind=kind,
        callback=callback,  # type: ignore[arg-type]
        priority=priority,
        dependency_order=dependency_order,
        deadline_seconds=deadline,
        handler_name="handle",
    )


def test_hook_bus_uses_dependency_priority_and_id_order() -> None:
    called: list[str] = []
    bus = HookBus()
    for plugin_id, priority, dependency_order in (
        ("z", 10, 1),
        ("b", 0, 0),
        ("a", 0, 0),
    ):
        bus.register(
            _registration(
                plugin_id,
                HookName.TURN_AFTER,
                HookKind.OBSERVER,
                lambda event, name=plugin_id: called.append(name),
                priority=priority,
                dependency_order=dependency_order,
            )
        )
    asyncio.run(bus.observe(HookName.TURN_AFTER, TurnBeforeEvent()))
    assert called == ["a", "b", "z"]


def test_transformer_applies_only_typed_patch_and_fails_open() -> None:
    bus = HookBus()
    bus.register(
        _registration(
            "bad",
            HookName.CONTEXT_CONTRIBUTE,
            HookKind.TRANSFORMER,
            lambda event: ResponsePatch(content="越界"),
        )
    )
    bus.register(
        _registration(
            "good",
            HookName.CONTEXT_CONTRIBUTE,
            HookKind.TRANSFORMER,
            lambda event: ContextPatch((ContextSection("hint", "safe"),)),
        )
    )
    result = asyncio.run(
        bus.transform(HookName.CONTEXT_CONTRIBUTE, ContextContributeEvent())
    )
    assert isinstance(result, ContextContributeEvent)
    assert result.sections[0].content == "safe"
    assert result.sections[0].source_plugin == "good"


def test_policy_rewrite_then_deny_and_invalid_result_fail_closed() -> None:
    bus = HookBus()
    bus.register(
        _registration(
            "rewrite",
            HookName.TOOL_BEFORE,
            HookKind.POLICY,
            lambda event: ToolDecision.rewrite({"path": "safe.txt"}),
        )
    )
    bus.register(
        _registration(
            "deny",
            HookName.TOOL_BEFORE,
            HookKind.POLICY,
            lambda event: ToolDecision.deny("blocked"),
            dependency_order=1,
        )
    )
    decision, event = asyncio.run(bus.policy(ToolBeforeEvent(arguments={"path": "x"})))
    assert decision.action is ToolDecisionAction.DENY
    assert event.arguments == {"path": "safe.txt"}

    invalid = HookBus()
    invalid.register(
        _registration(
            "invalid",
            HookName.TOOL_BEFORE,
            HookKind.POLICY,
            lambda event: {"action": "allow"},
        )
    )
    decision, _ = asyncio.run(invalid.policy(ToolBeforeEvent()))
    assert decision.action is ToolDecisionAction.DENY


def test_hook_deadline_policy_closed_observer_open() -> None:
    async def slow(event: object) -> None:
        await asyncio.sleep(0.05)

    policy_bus = HookBus(default_deadline_seconds=0.01)
    policy_bus.register(
        _registration(
            "slow",
            HookName.TOOL_BEFORE,
            HookKind.POLICY,
            slow,
            deadline=0.01,
        )
    )
    decision, _ = asyncio.run(policy_bus.policy(ToolBeforeEvent()))
    assert decision.action is ToolDecisionAction.DENY

    observer_bus = HookBus(default_deadline_seconds=0.01)
    observer_bus.register(
        _registration(
            "slow",
            HookName.TURN_AFTER,
            HookKind.OBSERVER,
            slow,
            deadline=0.01,
        )
    )
    asyncio.run(observer_bus.observe(HookName.TURN_AFTER, TurnBeforeEvent()))


def test_duplicate_hook_and_wrong_kind_are_rejected() -> None:
    bus = HookBus()
    registration = _registration(
        "plugin", HookName.TURN_BEFORE, HookKind.TRANSFORMER, lambda event: None
    )
    undo = bus.register(registration)
    try:
        try:
            bus.register(registration)
        except ValueError:
            pass
        else:
            raise AssertionError("重复 Hook 应被拒绝")
    finally:
        undo()
        undo()
    assert bus.registrations() == []
