"""持久化 SubAgent 任务图的编排、恢复与完成事件回流。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from memoli_agent.agent.subagent.context import ContextCompiler
from memoli_agent.agent.subagent.events import (
    SubAgentCompletionEvent,
    SubAgentResult,
    SubAgentTask,
)
from memoli_agent.agent.subagent.models import (
    AgentArtifact,
    AgentMessage,
    AgentTask,
    DelegationRequest,
    TaskAttempt,
    TaskStatus,
)
from memoli_agent.agent.subagent.profiles import SubAgentProfile
from memoli_agent.agent.subagent.repository import TaskGraphRepository
from memoli_agent.agent.subagent.runtime import SubAgentRuntime
from memoli_agent.agent.trajectory import new_trace_id
from memoli_agent.bus.events import InboundMessage
from memoli_agent.bus.queue import MessageBus


@dataclass(slots=True)
class SubAgentManager:
    """以 SQLite 为事实源，串行调度 SubAgent Task DAG。"""

    runtime: SubAgentRuntime
    repository: TaskGraphRepository
    bus: MessageBus
    root: Path
    profiles: dict[str, SubAgentProfile]
    default_profile: str = "general"
    max_concurrent: int = 1
    max_depth: int = 1
    context_compiler: ContextCompiler = field(default_factory=ContextCompiler)
    _semaphore: asyncio.Semaphore = field(init=False, repr=False)
    _active: dict[str, asyncio.Task[SubAgentResult]] = field(
        init=False, default_factory=dict, repr=False
    )
    _stopping: bool = field(init=False, default=False, repr=False)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._semaphore = asyncio.Semaphore(max(1, self.max_concurrent))

    async def start(self) -> None:
        """恢复时只标记中断，不擅自重放可能带副作用的任务。"""

        await self.repository.start()
        self.repository.recover_interrupted()
        for task in self.repository.list_tasks():
            if task.background and task.status is TaskStatus.RUNNABLE:
                self._schedule(task.task_id)

    async def stop(self) -> None:
        """停止新调度，并把尚未结束的执行保存为 interrupted。"""

        self._stopping = True
        active = tuple(self._active.items())
        for _, future in active:
            future.cancel()
        if active:
            await asyncio.gather(
                *(future for _, future in active), return_exceptions=True
            )
        await self.repository.close()

    async def run_task(
        self,
        instruction: str,
        profile_name: str = "",
        parent_session_key: str = "",
        metadata: dict[str, Any] | None = None,
        **options: Any,
    ) -> SubAgentResult:
        """创建并同步执行任务；保留旧调用入口。"""

        request = self._request(
            instruction,
            profile_name,
            parent_session_key,
            False,
            metadata,
            options,
        )
        task = self.create_task(request)
        if task.status is TaskStatus.BLOCKED:
            return self._status_result(task)
        return await self._execute(task.task_id)

    def spawn_background(
        self,
        instruction: str,
        profile_name: str = "",
        parent_session_key: str = "",
        metadata: dict[str, Any] | None = None,
        **options: Any,
    ) -> str:
        """持久化后立即返回 task_id；可运行任务进入本地串行调度器。"""

        request = self._request(
            instruction,
            profile_name,
            parent_session_key,
            True,
            metadata,
            options,
        )
        task = self.create_task(request)
        if task.status is TaskStatus.RUNNABLE:
            self._schedule(task.task_id)
        return task.task_id

    def create_task(self, request: DelegationRequest) -> AgentTask:
        """校验委派边界、创建节点与依赖边，并计算初始可运行状态。"""

        objective = request.objective.strip()
        if not objective:
            raise ValueError("objective 不能为空")
        profile = self.profiles.get(request.profile_name or self.default_profile)
        if profile is None:
            raise ValueError(f"未知 SubAgent profile：{request.profile_name}")
        if request.depth > min(self.max_depth, profile.max_depth):
            raise ValueError(
                f"委派深度 {request.depth} 超过允许值 "
                f"{min(self.max_depth, profile.max_depth)}"
            )
        if request.max_iterations is not None and request.max_iterations <= 0:
            raise ValueError("max_iterations 必须大于 0")
        if (
            request.max_elapsed_seconds is not None
            and request.max_elapsed_seconds <= 0
        ):
            raise ValueError("max_elapsed_seconds 必须大于 0")
        for dependency_id in request.dependency_ids:
            dependency = self.repository.get_task(dependency_id)
            if dependency is None:
                raise ValueError(f"依赖任务不存在：{dependency_id}")
            if dependency.root_session_key != request.parent_session_key:
                raise ValueError("不能依赖其他根会话的私有任务")
        task_id = _new_task_id()
        agent_id = f"agent_{uuid4().hex[:12]}"
        task_dir = self.root / task_id
        task_dir.mkdir(parents=True, exist_ok=False)
        context = self.context_compiler.compile(request)
        task = AgentTask(
            task_id=task_id,
            agent_id=agent_id,
            root_agent_id=request.root_agent_id,
            parent_agent_id=request.parent_agent_id,
            parent_task_id=request.parent_task_id,
            root_session_key=request.parent_session_key,
            profile_name=profile.name,
            objective=objective,
            context_package=context,
            status=TaskStatus.PENDING,
            depth=request.depth,
            task_dir=task_dir,
            max_iterations=min(
                request.max_iterations or profile.max_iterations,
                profile.max_iterations,
            ),
            max_elapsed_seconds=(
                min(
                    request.max_elapsed_seconds or profile.max_elapsed_seconds,
                    profile.max_elapsed_seconds,
                )
            ),
            side_effecting=request.side_effecting,
            background=request.background,
        )
        self.repository.create_task(task, request.dependency_ids)
        status = self.repository.refresh_task_readiness(task_id)
        persisted = self.repository.get_task(task_id)
        if persisted is None:  # pragma: no cover - SQLite 已保证写入
            raise RuntimeError(f"任务持久化失败：{task_id}")
        self.regenerate_exports(task_id)
        return persisted if persisted.status is status else persisted

    def get_task(self, task_id: str, root_session_key: str = "") -> AgentTask | None:
        task = self.repository.get_task(task_id)
        if task is None or (
            root_session_key and task.root_session_key != root_session_key
        ):
            return None
        return task

    def list_tasks(self, root_session_key: str = "") -> list[AgentTask]:
        return self.repository.list_tasks(root_session_key)

    def describe_task(
        self, task_id: str, root_session_key: str = ""
    ) -> dict[str, Any]:
        """返回稳定、会话隔离的任务管理视图。"""

        task = self._owned_task(task_id, root_session_key)
        payload = _task_dict(task)
        payload["dependencies"] = self.repository.dependencies(task_id)
        payload["dependents"] = self.repository.dependents(task_id)
        payload["attempts"] = [
            asdict(attempt) for attempt in self.repository.attempts(task_id)
        ]
        payload["artifacts"] = [
            {**asdict(artifact), "path": str(artifact.path)}
            for artifact in self.repository.artifacts(task_id)
        ]
        return payload

    async def cancel_task(
        self,
        task_id: str,
        *,
        root_session_key: str = "",
        reason: str = "user_cancelled",
    ) -> AgentTask:
        task = self._owned_task(task_id, root_session_key)
        self.repository.record_message(
            AgentMessage(
                message_id=f"msg_{uuid4().hex}",
                task_id=task_id,
                from_agent_id=task.parent_agent_id,
                to_agent_id=task.agent_id,
                message_type="cancel",
                content=reason,
            )
        )
        future = self._active.get(task_id)
        if future is not None:
            future.cancel()
            await asyncio.gather(future, return_exceptions=True)
        current = self._owned_task(task_id, root_session_key)
        if current.status in {
            TaskStatus.PENDING,
            TaskStatus.BLOCKED,
            TaskStatus.RUNNABLE,
            TaskStatus.WAITING_INPUT,
            TaskStatus.INTERRUPTED,
        }:
            self.repository.transition(
                task_id,
                TaskStatus.CANCELLED,
                expected={
                    TaskStatus.PENDING,
                    TaskStatus.BLOCKED,
                    TaskStatus.RUNNABLE,
                    TaskStatus.WAITING_INPUT,
                    TaskStatus.INTERRUPTED,
                },
                reason=reason,
            )
        self.regenerate_exports(task_id)
        cancelled = self._owned_task(task_id, root_session_key)
        if cancelled.background and cancelled.status is TaskStatus.CANCELLED:
            await self._publish_completion(cancelled, self._status_result(cancelled))
        return cancelled

    def resume_task(
        self,
        task_id: str,
        *,
        root_session_key: str = "",
        confirm_side_effects: bool = False,
    ) -> AgentTask:
        task = self._owned_task(task_id, root_session_key)
        if task.status is not TaskStatus.INTERRUPTED:
            raise ValueError("只有 interrupted 任务可以恢复")
        if task.side_effecting and not confirm_side_effects:
            raise ValueError("该任务可能产生副作用，恢复前必须显式确认")
        self.repository.transition(
            task_id,
            TaskStatus.RUNNABLE,
            expected=TaskStatus.INTERRUPTED,
            reason="operator_resume",
        )
        refreshed = self._owned_task(task_id, root_session_key)
        self._schedule(task_id)
        self.regenerate_exports(task_id)
        return refreshed

    def regenerate_exports(self, task_id: str) -> None:
        """从 SQLite 重建 task.json/result.md；文件不是事实源。"""

        task = self.repository.get_task(task_id)
        if task is None:
            raise ValueError(f"任务不存在：{task_id}")
        task.task_dir.mkdir(parents=True, exist_ok=True)
        payload = _task_dict(task)
        payload["dependencies"] = self.repository.dependencies(task_id)
        payload["artifacts"] = [
            {**asdict(item), "path": str(item.path)}
            for item in self.repository.artifacts(task_id)
        ]
        attempts_json = json.dumps(
            [asdict(item) for item in self.repository.attempts(task_id)],
            ensure_ascii=False,
            indent=2,
        )
        (task.task_dir / "task.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        content = (
            "# SubAgent Result\n\n"
            f"- task_id: {task.task_id}\n"
            f"- agent_id: {task.agent_id}\n"
            f"- profile: {task.profile_name}\n"
            f"- status: {task.status.value}\n"
            f"- trace_id: {task.trace_id}\n\n"
            f"## Conclusion\n\n{task.result_summary}\n\n"
            "## Structured Result\n\n```json\n"
            f"{json.dumps(task.result_data, ensure_ascii=False, indent=2)}\n"
            "```\n\n"
            "## Attempts\n\n```json\n"
            f"{attempts_json}\n"
            "```\n\n"
            f"## Error\n\n{task.error_type}: {task.error_message}\n"
        )
        (task.task_dir / "result.md").write_text(content, encoding="utf-8")

    async def _execute(self, task_id: str) -> SubAgentResult:
        async with self._semaphore:
            task = self.repository.get_task(task_id)
            if task is None:
                raise ValueError(f"任务不存在：{task_id}")
            if task.status is not TaskStatus.RUNNABLE:
                return self._status_result(task)
            dependency_results = tuple(
                dependency.result_summary
                for dependency_id in self.repository.dependencies(task_id)
                if (dependency := self.repository.get_task(dependency_id)) is not None
            )
            request = DelegationRequest(
                objective=task.objective,
                acceptance_criteria=task.context_package.acceptance_criteria,
                constraints=task.context_package.constraints,
                confirmed_facts=task.context_package.confirmed_facts,
                memory_refs=task.context_package.memory_refs,
                artifact_refs=task.context_package.artifact_refs,
            )
            context = self.context_compiler.compile(
                request, dependency_results=dependency_results
            )
            task = self.repository.replace_context(task_id, context)
            trace_id = new_trace_id()
            attempt_no = len(self.repository.attempts(task_id)) + 1
            attempt_id = f"attempt_{uuid4().hex[:16]}"
            if not self.repository.transition(
                task_id,
                TaskStatus.RUNNING,
                expected=TaskStatus.RUNNABLE,
                reason="scheduler_dispatch",
                trace_id=trace_id,
            ):
                return self._status_result(self._owned_task(task_id, ""))
            self.repository.create_attempt(
                TaskAttempt(attempt_id, task_id, attempt_no, trace_id)
            )
            runtime_task = SubAgentTask(
                task_id=task.task_id,
                instruction=task.objective,
                profile_name=task.profile_name,
                parent_session_key=task.root_session_key,
                task_dir=task.task_dir,
                agent_id=task.agent_id,
                root_agent_id=task.root_agent_id,
                parent_agent_id=task.parent_agent_id,
                parent_task_id=task.parent_task_id,
                depth=task.depth,
                context_package=context,
                attempt_id=attempt_id,
                attempt_no=attempt_no,
                trace_id=trace_id,
                metadata={
                    "max_iterations": task.max_iterations,
                    "max_elapsed_seconds": task.max_elapsed_seconds,
                },
            )
            try:
                result = await self.runtime.run(runtime_task)
            except asyncio.CancelledError:
                target = (
                    TaskStatus.INTERRUPTED
                    if self._stopping
                    else TaskStatus.CANCELLED
                )
                self.repository.transition(
                    task_id,
                    target,
                    expected=TaskStatus.RUNNING,
                    reason="runtime_stopped" if self._stopping else "cancelled",
                )
                self.repository.finish_attempt(attempt_id, target.value)
                self.regenerate_exports(task_id)
                raise
            target = _target_status(result.status, result.success)
            error_type = str(result.metadata.get("error") or "")
            self.repository.transition(
                task_id,
                target,
                expected=TaskStatus.RUNNING,
                reason="runtime_finished",
                result_summary=result.content,
                result_data=(
                    result.structured.to_dict() if result.structured is not None else {}
                ),
                error_type=error_type,
                error_message=result.content if target is TaskStatus.FAILED else "",
            )
            self.repository.finish_attempt(attempt_id, target.value, error_type)
            self._register_artifacts(task, result)
            self.regenerate_exports(task_id)
            persisted = self._owned_task(task_id, "")
            if persisted.background and target in {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }:
                await self._publish_completion(persisted, result)
            for dependent in self.repository.refresh_dependents(task_id):
                self.regenerate_exports(dependent.task_id)
                if dependent.background:
                    self._schedule(dependent.task_id)
            return result

    def _schedule(self, task_id: str) -> None:
        if self._stopping or task_id in self._active:
            return
        future = asyncio.create_task(self._execute(task_id))
        self._active[task_id] = future
        future.add_done_callback(lambda _: self._active.pop(task_id, None))

    async def _publish_completion(
        self, task: AgentTask, result: SubAgentResult
    ) -> None:
        if not self.repository.mark_completion_notified(task.task_id):
            return
        event = SubAgentCompletionEvent(
            task_id=task.task_id,
            parent_session_key=task.root_session_key,
            result=result,
            agent_id=task.agent_id,
        )
        await self.bus.publish_inbound(
            InboundMessage(
                channel="subagent",
                chat_id=task.root_session_key or task.task_id,
                sender="subagent",
                content=_format_completion_content(event),
                metadata={
                    "event": "subagent_completion",
                    "task_id": task.task_id,
                    "agent_id": task.agent_id,
                    "status": task.status.value,
                    "success": result.success,
                    "profile": result.profile_name,
                    "trace_id": result.trace_id,
                    "result_ref": str(task.task_dir / "result.md"),
                },
            )
        )

    def _register_artifacts(self, task: AgentTask, result: SubAgentResult) -> None:
        if result.structured is None:
            return
        root = task.task_dir.resolve()
        for item in result.structured.artifacts:
            raw_path = str(item.get("path") or "").strip()
            if not raw_path:
                continue
            candidate = (root / raw_path).resolve()
            if root not in candidate.parents or not candidate.is_file():
                continue
            data = candidate.read_bytes()
            self.repository.record_artifact(
                AgentArtifact(
                    artifact_id=f"artifact_{uuid4().hex[:16]}",
                    task_id=task.task_id,
                    agent_id=task.agent_id,
                    path=candidate,
                    kind=str(item.get("kind") or "file"),
                    mime_type=(
                        str(item.get("mime_type") or "")
                        or mimetypes.guess_type(candidate.name)[0]
                        or "application/octet-stream"
                    ),
                    sha256=hashlib.sha256(data).hexdigest(),
                    size=len(data),
                )
            )

    def _owned_task(self, task_id: str, root_session_key: str) -> AgentTask:
        task = self.get_task(task_id, root_session_key)
        if task is None:
            raise ValueError("任务不存在或不属于当前会话")
        return task

    def _status_result(self, task: AgentTask) -> SubAgentResult:
        return SubAgentResult(
            task_id=task.task_id,
            content=task.result_summary or task.blocked_reason or task.status.value,
            success=task.status is TaskStatus.COMPLETED,
            profile_name=task.profile_name,
            task_dir=task.task_dir,
            agent_id=task.agent_id,
            trace_id=task.trace_id,
            status=task.status.value,
        )

    def _request(
        self,
        instruction: str,
        profile_name: str,
        parent_session_key: str,
        background: bool,
        metadata: dict[str, Any] | None,
        options: dict[str, Any],
    ) -> DelegationRequest:
        reserved = {
            "objective",
            "profile_name",
            "parent_session_key",
            "background",
            "metadata",
        }
        allowed = {
            key: value
            for key, value in options.items()
            if key in DelegationRequest.__dataclass_fields__ and key not in reserved
        }
        return DelegationRequest(
            objective=instruction,
            profile_name=profile_name or self.default_profile,
            parent_session_key=parent_session_key,
            background=background,
            metadata=dict(metadata or {}),
            **allowed,
        )


def _new_task_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"sub_{timestamp}_{uuid4().hex[:8]}"


def _target_status(status: str, success: bool) -> TaskStatus:
    if status == TaskStatus.WAITING_INPUT.value:
        return TaskStatus.WAITING_INPUT
    return TaskStatus.COMPLETED if success else TaskStatus.FAILED


def _task_dict(task: AgentTask) -> dict[str, Any]:
    payload = asdict(task)
    payload["status"] = task.status.value
    payload["task_dir"] = str(task.task_dir)
    return payload


def _format_completion_content(event: SubAgentCompletionEvent) -> str:
    return (
        f"子 Agent 任务已结束：{event.task_id}\n"
        f"状态：{event.result.status}\n"
        f"profile：{event.result.profile_name}\n"
        f"结果：\n{event.result.content}"
    )
