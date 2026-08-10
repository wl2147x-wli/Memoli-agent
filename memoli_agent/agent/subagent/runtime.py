"""复用主 Reasoner 的独立、有界 SubAgent Runtime。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from memoli_agent.agent.core.reasoner import Reasoner
from memoli_agent.agent.core.results import TerminationReason
from memoli_agent.agent.plugins.hooks import HookBus
from memoli_agent.agent.provider import ProviderLike
from memoli_agent.agent.skills.runtime import SkillRuntime
from memoli_agent.agent.subagent.context import ContextCompiler, parse_structured_result
from memoli_agent.agent.subagent.events import SubAgentResult, SubAgentTask
from memoli_agent.agent.subagent.models import ContextPackage
from memoli_agent.agent.subagent.profiles import (
    ProfileToolRegistryFactory,
    SubAgentProfile,
)
from memoli_agent.agent.tools.control import WorkingStateStore
from memoli_agent.agent.trajectory import (
    NewTrajectoryEvent,
    SpanKind,
    SpanProjection,
    TraceProjection,
    TrajectoryError,
    TrajectoryStore,
    new_span_id,
    new_trace_id,
    utc_now_iso,
)
from memoli_agent.agent.types import ChatMessage


@dataclass(frozen=True, slots=True)
class SubAgentRuntimeFactory:
    """按任务构造独立 Reasoner，避免共享上下文和 working state。"""

    provider: ProviderLike
    fallback_provider: ProviderLike | None
    tool_registry_factory: ProfileToolRegistryFactory
    trajectory_store: TrajectoryStore
    model_name: str = ""
    no_progress_limit: int = 3
    hook_bus: HookBus | None = None
    skill_runtime: SkillRuntime | None = None
    stream_model: bool = False

    def build(self, profile: SubAgentProfile, task: SubAgentTask) -> Reasoner:
        iteration_override = task.metadata.get("max_iterations")
        elapsed_override = task.metadata.get("max_elapsed_seconds")
        profile = replace(
            profile,
            max_iterations=(
                int(iteration_override)
                if isinstance(iteration_override, int | float | str)
                else profile.max_iterations
            ),
            max_elapsed_seconds=(
                float(elapsed_override)
                if isinstance(elapsed_override, int | float | str)
                else profile.max_elapsed_seconds
            ),
        )
        memory_refs = (
            task.context_package.memory_refs if task.context_package is not None else ()
        )
        registry = self.tool_registry_factory.build(profile, task.task_dir, memory_refs)
        return Reasoner(
            provider=self.provider,
            fallback_provider=self.fallback_provider,
            tool_registry=registry,
            trajectory_store=self.trajectory_store,
            max_iterations=profile.max_iterations,
            max_elapsed_seconds=profile.max_elapsed_seconds,
            no_progress_limit=self.no_progress_limit,
            model_name=self.model_name,
            # 独立内存 repository，避免 begin_turn 把主会话 checkpoint 标为 stale。
            working_state=WorkingStateStore(),
            hook_bus=self.hook_bus,
            stream_model=self.stream_model,
        )


@dataclass(slots=True)
class SubAgentRuntime:
    """执行一个已经持久化的子任务。"""

    factory: SubAgentRuntimeFactory
    profiles: dict[str, SubAgentProfile]

    async def run(self, task: SubAgentTask) -> SubAgentResult:
        profile = self.profiles.get(task.profile_name)
        if profile is None:
            return _failure(
                task,
                f"子 agent profile 不存在：{task.profile_name}",
                "UnknownProfile",
            )

        reasoner = self.factory.build(profile, task)
        context = task.context_package or ContextPackage(objective=task.instruction)
        trace_id = task.trace_id or new_trace_id()
        root_span_id = new_span_id()
        started_at = utc_now_iso()
        trace = TraceProjection(
            trace_id=trace_id,
            session_id=f"subagent:{task.agent_id or task.task_id}",
            started_at=started_at,
            provider=str(getattr(self.factory.provider, "name", "")),
            model=self.factory.model_name,
        )
        root_span = SpanProjection(
            span_id=root_span_id,
            trace_id=trace_id,
            parent_span_id=None,
            kind=SpanKind.AGENT,
            name="subagent-task",
            started_at=started_at,
            input_data={"context_package": context.to_dict()},
            attributes={
                "agent_id": task.agent_id,
                "root_agent_id": task.root_agent_id,
                "parent_agent_id": task.parent_agent_id,
                "task_id": task.task_id,
                "parent_task_id": task.parent_task_id,
                "profile": profile.name,
                "depth": task.depth,
                "attempt_id": task.attempt_id,
                "attempt_no": task.attempt_no,
            },
        )
        try:
            await self.factory.trajectory_store.record(
                NewTrajectoryEvent(
                    trace_id=trace_id,
                    span_id=root_span_id,
                    event_type="subagent_trace_started",
                    payload={
                        "lineage": dict(root_span.attributes),
                        "limits": {
                            "max_iterations": profile.max_iterations,
                            "max_elapsed_seconds": profile.max_elapsed_seconds,
                        },
                    },
                    trace=trace,
                    span=root_span,
                )
            )
        except TrajectoryError:
            return _failure(
                task, "子 agent 轨迹初始化失败。", "TrajectoryError", trace_id
            )

        actual_tools = (
            {tool.name for tool in reasoner.tool_registry.list_tools()}
            if reasoner.tool_registry is not None
            else set()
        )
        messages = [
            ChatMessage(
                role="system",
                content=_build_subagent_system_prompt(profile, actual_tools),
            )
        ]
        session_instance_id = task.attempt_id or task.task_id
        if self.factory.skill_runtime is not None:
            catalog = self.factory.skill_runtime.build_catalog(
                session_instance_id=session_instance_id,
                session_key=f"subagent:{task.agent_id or task.task_id}",
                tools=actual_tools,
                mcp_servers=set(),
            )
            if catalog.content:
                messages.append(ChatMessage(role="system", content=catalog.content))
        messages.append(
            ChatMessage(role="user", content=ContextCompiler.render(context))
        )
        try:
            turn = await reasoner.run_turn(
                messages,
                session_key=f"subagent:{task.agent_id or task.task_id}",
                trace_id=trace_id,
                root_span_id=root_span_id,
                root_span_attributes=dict(root_span.attributes),
                session_instance_id=session_instance_id,
            )
        except Exception as exc:
            return _failure(
                task,
                f"子 agent 执行失败：{exc}",
                type(exc).__name__,
                trace_id,
            )
        finally:
            if reasoner.working_state is not None:
                reasoner.working_state.close()

        status = _result_status(turn.termination_reason)
        structured = parse_structured_result(
            turn.response.content,
            default_status=status,
            usage={**turn.usage, "iterations": turn.iterations},
            error_type=turn.error_type,
        )
        success = turn.termination_reason is TerminationReason.COMPLETED
        return SubAgentResult(
            task_id=task.task_id,
            content=structured.conclusion,
            success=success,
            profile_name=profile.name,
            task_dir=task.task_dir,
            metadata={
                "provider": turn.response.provider,
                "fallback_used": turn.fallback_used,
                "iterations": turn.iterations,
                "termination_reason": turn.termination_reason.value,
                "unstructured_fallback": structured.unstructured_fallback,
            },
            agent_id=task.agent_id,
            trace_id=trace_id,
            attempt_id=task.attempt_id,
            status=status,
            structured=structured,
        )


def _build_subagent_system_prompt(
    profile: SubAgentProfile, actual_tools: set[str]
) -> str:
    allowed_tools = ", ".join(sorted(actual_tools)) or "无"
    return (
        f"你是 Memoli 的本地子 Agent，profile={profile.name}。\n"
        f"职责：{profile.description}\n"
        f"实际可用工具：{allowed_tools}\n"
        "你不直接与最终用户沟通，也不能写长期记忆或修改主会话 checkpoint。"
        "所有结论必须区分证据、推断和未完成内容。"
    )


def _result_status(reason: TerminationReason) -> str:
    return {
        TerminationReason.COMPLETED: "completed",
        TerminationReason.NEEDS_USER: "waiting_input",
        TerminationReason.BUDGET_EXHAUSTED: "failed",
        TerminationReason.FAILED: "failed",
    }[reason]


def _failure(
    task: SubAgentTask, content: str, error_type: str, trace_id: str = ""
) -> SubAgentResult:
    structured = parse_structured_result(
        content,
        default_status="failed",
        error_type=error_type,
    )
    return SubAgentResult(
        task_id=task.task_id,
        content=content,
        success=False,
        profile_name=task.profile_name,
        task_dir=task.task_dir,
        metadata={"error": error_type},
        agent_id=task.agent_id,
        trace_id=trace_id,
        attempt_id=task.attempt_id,
        status="failed",
        structured=structured,
    )
