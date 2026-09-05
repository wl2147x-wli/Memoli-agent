"""Synchronous delegation between independently configured agent workspaces."""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple

from agent.tools.base_tool import BaseTool, ToolResult
from bridge.context import Context, ContextType
from bridge.reply import ReplyType
from common.log import logger

# 标记委托运行，以便可以区分用户启动的轮次。
TASK_SOURCE = "delegation"


def format_delegate_result(
    source_name: str,
    target_name: str,
    content: str,
    status: str = "done",
    duration_seconds: float = 0,
) -> str:
    """The delegation's outcome, written for a person.

    The tool returns JSON for the delegating model to parse, but whoever is
    watching wants to see who handed what to whom and read the teammate's
    answer as prose, not a JSON blob. So the same outcome goes out a second
    time as markdown: a "source → target" heading and the teammate's reply
    (which is itself markdown), exactly the shape the sub agent report uses.
    """
    from agent.tools.subagent.subagent import _format_duration

    heading = f"{source_name} → {target_name}"
    if duration_seconds:
        heading += f" · {_format_duration(duration_seconds)}"
    body = content or "(no output)"
    if status != "done":
        body = f"**{status}** — {body}"
    return f"### {heading}\n\n{body}"


class _DelegateView:
    """What someone following the run sees of one delegation call.

    The delegating Agent's context is unaffected: it still receives only the
    teammate's returned result, which is the whole point. This is the other
    audience — the person watching — for whom a teammate that reports nothing
    until it finishes is indistinguishable from one that hung. So the
    teammate's tool calls are relayed under this call's card, the same way a
    sub agent's are, while its prose and reasoning are dropped (those render as
    the assistant speaking, and a teammate muttering into the main reply reads
    as the Agent losing the thread).
    """

    def __init__(self, tool, card_id: str):
        self.tool = tool
        self.card_id = card_id

    def relay(self, event: dict) -> None:
        if not isinstance(event, dict):
            return
        event_type = event.get("type")
        data = event.get("data") or {}
        if event_type == "tool_execution_start":
            self.tool.emit_event(
                "subagent_step",
                {
                    "card_id": self.card_id,
                    "step_id": self._step_id(data),
                    "phase": "start",
                    "tool_name": data.get("tool_name", "tool"),
                    "arguments": data.get("arguments") or {},
                },
            )
        elif event_type == "tool_execution_end":
            status = data.get("status", "success")
            step = {
                "card_id": self.card_id,
                "step_id": self._step_id(data),
                "phase": "end",
                "tool_name": data.get("tool_name", "tool"),
                "status": status,
                "execution_time": round(data.get("execution_time") or 0, 2),
            }
            if status != "success":
                from agent.tools.subagent.subagent import _error_text

                step["error"] = _error_text(data.get("result"))
            self.tool.emit_event("subagent_step", step)

    def _step_id(self, data: dict) -> str:
        return f"{self.card_id}:{data.get('tool_call_id') or uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class DelegationPolicy:
    enabled: bool = True
    allowed_targets: Optional[Mapping[str, Tuple[str, ...]]] = None
    max_depth: int = 3
    timeout_seconds: float = 600.0
    max_message_chars: int = 8000

    @classmethod
    def from_config(cls, raw) -> "DelegationPolicy":
        if raw is False:
            return cls(enabled=False)
        if raw is None or raw is True:
            raw = {}
        if not isinstance(raw, Mapping):
            raise ValueError("agent_delegation must be an object or boolean")

        allow = raw.get("allowed_targets")
        normalized = None
        if allow is not None:
            if not isinstance(allow, Mapping):
                raise ValueError("allowed_targets must map source Agent IDs to lists")
            normalized = {}
            for source, targets in allow.items():
                if not isinstance(source, str) or not isinstance(targets, (list, tuple)):
                    raise ValueError("allowed_targets entries must contain lists")
                if not all(isinstance(target, str) for target in targets):
                    raise ValueError("allowed target IDs must be strings")
                normalized[source] = tuple(targets)

        max_depth = int(raw.get("max_depth", 3))
        timeout_seconds = float(raw.get("timeout_seconds", 600))
        max_message_chars = int(raw.get("max_message_chars", 8000))
        if not 1 <= max_depth <= 8:
            raise ValueError("max_depth must be between 1 and 8")
        if not 0.01 <= timeout_seconds <= 600:
            raise ValueError("timeout_seconds must be between 0.01 and 600")
        if not 1 <= max_message_chars <= 100000:
            raise ValueError("max_message_chars must be between 1 and 100000")
        return cls(
            enabled=bool(raw.get("enabled", True)),
            allowed_targets=normalized,
            max_depth=max_depth,
            timeout_seconds=timeout_seconds,
            max_message_chars=max_message_chars,
        )

    def allows(self, source_agent_id: str, target_agent_id: str) -> bool:
        if not self.enabled:
            return False
        if self.allowed_targets is None:
            return source_agent_id != target_agent_id
        targets = self.allowed_targets.get(source_agent_id, ())
        return "*" in targets or target_agent_id in targets


# 一个被委派的目标在同一会话里一次只能作答一轮，因此针对
# 同一中继会话的并发委托会在该锁后面串行排队，
# 而不是在目标对象的转录中交错混杂。
_relay_locks = {}
_relay_locks_guard = threading.Lock()


def _relay_lock(session_id: str) -> threading.Lock:
    with _relay_locks_guard:
        return _relay_locks.setdefault(session_id, threading.Lock())


class AgentDelegateTool(BaseTool):
    """Hand a bounded subtask to a teammate in this team conversation."""

    name = "agent_delegate"
    description = (
        "Delegate a task to a teammate in this team conversation and wait for "
        "its result. The teammates you can delegate to, and their IDs, are the "
        "ones listed in the team conversation section of your context. The "
        "teammate works in its own workspace and returns a result to you."
    )
    params = {
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": (
                    "The teammate's Agent ID (the @id shown for them in the team "
                    "conversation section)."
                ),
            },
            "task": {
                "type": "string",
                "description": (
                    "A self-contained task for the teammate, with everything it "
                    "needs to act without seeing this conversation."
                ),
            },
        },
        "required": ["agent_id", "task"],
    }

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.agent_bridge = None
        self.current_context = None

    def _policy(self) -> DelegationPolicy:
        if self.config:
            return DelegationPolicy.from_config(self.config)
        from config import conf

        return DelegationPolicy.from_config(conf().get("agent_delegation", {}))

    @staticmethod
    def _session_id(
        source_agent_id: str, target_agent_id: str, root_session_id: str
    ) -> str:
        digest = hashlib.sha256(root_session_id.encode("utf-8")).hexdigest()[:16]
        return f"delegate_{source_agent_id}_{target_agent_id}_{digest}"

    def _team_members(self, context_values: dict, source_agent_id: str) -> list:
        """The teammates the source Agent may delegate to this turn.

        Exactly the roster the "team conversation" prompt section lists: the
        conversation's members, minus the source itself and anyone the ACL
        forbids. Delegation is bounded to the people the Agent was actually told
        it is working with, so it can never hand work to an Agent outside the
        room. Returns ``[{id, name}]`` so an error can name the real options.

        On a delegated turn the source runs in its own private session, which
        carries no ``members`` of its own; the original team's roster rides
        down the chain in the context instead (``delegation_members``), so a
        teammate can hand work onward to the same team, not just answer.
        """
        members = context_values.get("delegation_members")
        if not members:
            session_id = str(
                context_values.get("delegation_root_session")
                or context_values.get("session_id")
                or ""
            )
            if not session_id:
                return []
            try:
                from agent.workspace import session_prefs

                members = session_prefs.get_prefs(session_id, source_agent_id).get(
                    "members"
                )
            except Exception as exc:
                logger.warning(f"[AgentDelegate] Could not read team members: {exc}")
                return []

        policy = self._policy_safe()
        roster = []
        for member_id in members or []:
            if not member_id or member_id == source_agent_id:
                continue
            if policy is not None and not policy.allows(source_agent_id, member_id):
                continue
            try:
                profile = self.agent_bridge.agent_registry.get(member_id)
            except (KeyError, ValueError):
                continue
            roster.append({"id": profile.id, "name": profile.name})
        return roster

    def _policy_safe(self) -> Optional[DelegationPolicy]:
        try:
            return self._policy()
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _roster_hint(roster: list) -> str:
        """One-line "who you can actually delegate to" for an error message."""
        if not roster:
            return "There are no teammates you can delegate to in this conversation."
        names = ", ".join(f"{item['name']} ({item['id']})" for item in roster)
        return f"Teammates you can delegate to: {names}."

    def execute(self, params: dict) -> ToolResult:
        if self.agent_bridge is None or self.current_context is None:
            return ToolResult.fail("Agent delegation is not attached to this turn")

        try:
            policy = self._policy()
        except (TypeError, ValueError) as exc:
            return ToolResult.fail(f"Invalid delegation policy: {exc}")
        if not policy.enabled:
            return ToolResult.fail("Agent delegation is disabled")
        context_values = dict(self.current_context.kwargs)
        source_agent_id = context_values.get("agent_id")
        if not source_agent_id:
            return ToolResult.fail("Source Agent could not be resolved")
        try:
            source = self.agent_bridge.agent_registry.get(source_agent_id)
        except (KeyError, ValueError):
            return ToolResult.fail(f"Source Agent '{source_agent_id}' is not available")

        roster = self._team_members(context_values, source.id)
        return self._delegate(params, policy, source, context_values, roster)

    def _delegate(
        self,
        params: dict,
        policy: DelegationPolicy,
        source,
        context_values: dict,
        roster: list,
    ) -> ToolResult:
        # 花名册里的 id 以 “@id” 形式展示，因此模型常常连 “@” 一起传进来。
        # 这里把它剥离掉，而不是因一个前缀符号就拒绝正确的目标。
        target_agent_id = (params.get("agent_id") or "").strip().lstrip("@")
        task = (params.get("task") or "").strip()
        if not target_agent_id or not task:
            return ToolResult.fail("agent_id and task are required for delegation")
        if len(task) > policy.max_message_chars:
            return ToolResult.fail(
                f"Delegated task exceeds {policy.max_message_chars} characters"
            )
        # 目标必须是本次对话中的队友，而不只是 ACL 允许的任意代理：
        # 委托应局限在用户组建的团队之内。错误信息里列出真实可用的
        # 选项，让模型能够一步自我纠正，而不必再次猜测。
        if target_agent_id not in {item["id"] for item in roster}:
            return ToolResult.fail(
                f"'{target_agent_id}' is not a teammate you can delegate to in this "
                f"conversation. {self._roster_hint(roster)}"
            )
        try:
            target = self.agent_bridge.agent_registry.get(target_agent_id)
        except (KeyError, ValueError):
            return ToolResult.fail(f"Target Agent '{target_agent_id}' is not available")

        raw_trace = context_values.get("delegation_trace") or (source.id,)
        if not isinstance(raw_trace, (list, tuple)) or not all(
            isinstance(item, str) for item in raw_trace
        ):
            return ToolResult.fail("Delegation trace is invalid")
        trace = tuple(raw_trace)
        if not trace or trace[-1] != source.id:
            return ToolResult.fail("Delegation trace does not match the source Agent")
        if target.id in trace:
            return ToolResult.fail(
                f"Delegation cycle rejected: {' -> '.join((*trace, target.id))}"
            )
        if not policy.allows(source.id, target.id):
            return ToolResult.fail(
                f"Agent '{source.id}' is not allowed to delegate to '{target.id}'"
            )

        depth = int(context_values.get("delegation_depth", len(trace) - 1)) + 1
        if depth > policy.max_depth:
            return ToolResult.fail(
                f"Delegation depth {depth} exceeds the maximum {policy.max_depth}"
            )

        root_session_id = str(
            context_values.get("delegation_root_session")
            or context_values.get("session_id")
            or uuid.uuid4()
        )
        session_id = self._session_id(source.id, target.id, root_session_id)
        request_id = f"delegate_{uuid.uuid4().hex}"

        # run_id 在这里生成并以值的形式随请求携带：目标环境里的
        # ambient run_id 可能与之不同，但只要把子节点挂到这个父节点上，
        # 运行树的任何一端都能向上回溯到另一端。
        from common.utils import current_agent_run_id

        run_id = uuid.uuid4().hex
        parent_run_id = current_agent_run_id() or ""

        delegated_context = Context(ContextType.TEXT, task, kwargs={})
        delegated_context["session_id"] = session_id
        delegated_context["request_id"] = request_id
        delegated_context["receiver"] = target.id
        delegated_context["isgroup"] = False
        delegated_context["channel_type"] = "agent"
        delegated_context["agent_id"] = target.id
        delegated_context["is_delegated_task"] = True
        delegated_context["delegated_by"] = source.id
        delegated_context["delegation_depth"] = depth
        delegated_context["delegation_trace"] = [*trace, target.id]
        delegated_context["delegation_root_session"] = root_session_id
        # 把原始团队的名单沿委托链传递下去，这样队友就能把工作继续
        # 转交给同一个团队——它私有的委托会话并没有自己的成员。
        # 源本身也包含在名单里，方便后续环节能追溯回它；真正阻止
        # 循环的是循环守卫，而不是这份名单。此外还要把链上已经
        # 出现过的人从名单里剔除，好只暴露真正可到达的选项。
        team_ids = {source.id, *(item["id"] for item in roster)}
        team_ids |= set(context_values.get("delegation_members") or [])
        delegated_context["delegation_members"] = sorted(team_ids - set(trace))
        delegated_context["run_id"] = run_id
        delegated_context["parent_run_id"] = parent_run_id
        delegated_context["task_source"] = TASK_SOURCE

        prompt = (
            f"Delegated by Agent '{source.name}' ({source.id}).\n\n"
            f"Task:\n{task}\n\n"
            "Return a concise result to the delegating Agent. Do not address the user directly."
        )

        # 把队友的工具步骤转发到本次调用的卡片下，让观察者能像看待
        # 子代理那样实时跟随委托工作的进展。这里的卡片就是本次工具
        # 调用本身，因为一次委托恰好对应一张卡片。
        card_id = getattr(self, "tool_call_id", None) or run_id
        view = _DelegateView(self, card_id)

        # 对同一目标会话做互不交错的串行化，然后再内联执行：
        # 调用方等待队友的回复，拿到结果后直接返回。
        lock = _relay_lock(session_id)
        if not lock.acquire(timeout=policy.timeout_seconds):
            display = format_delegate_result(
                source.name, target.name, "timed out waiting for the teammate to be free",
                status="failed",
            )
            return ToolResult.fail(
                f"Delegation to '{target.id}' timed out waiting for the target to be free",
                display=display,
            )
        started_at = time.monotonic()
        try:
            reply = self.agent_bridge.agent_reply(
                prompt, context=delegated_context, on_event=view.relay
            )
        except Exception as exc:
            display = format_delegate_result(
                source.name, target.name, str(exc), status="failed"
            )
            return ToolResult.fail(
                f"Delegation to '{target.id}' failed: {exc}", display=display
            )
        finally:
            lock.release()
        duration = time.monotonic() - started_at

        if reply is not None and reply.type == ReplyType.ERROR:
            display = format_delegate_result(
                source.name, target.name, str(reply.content), status="failed",
                duration_seconds=duration,
            )
            return ToolResult.fail(
                f"Delegation to '{target.id}' failed: {reply.content}", display=display
            )
        content = reply.content if reply is not None else ""
        display = format_delegate_result(
            source.name, target.name, content, status="done", duration_seconds=duration,
        )
        return ToolResult.success(
            {
                "run_id": run_id,
                "agent_id": target.id,
                "agent_name": target.name,
                "delegated_by": source.id,
                "depth": depth,
                "session_id": session_id,
                "status": "done",
                "content": content,
            },
            display=display,
        )


def attach_agent_delegate_to_tool(tool, agent_bridge, context: Context) -> None:
    """Bind the current source turn and bridge to a delegation tool instance."""

    tool.agent_bridge = agent_bridge
    tool.current_context = context
