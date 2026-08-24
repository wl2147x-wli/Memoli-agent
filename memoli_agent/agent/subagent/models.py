"""SubAgent 任务图的数据合同。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    """返回稳定的 UTC ISO-8601 时间。"""

    return datetime.now(UTC).isoformat()


class TaskStatus(StrEnum):
    """任务持久状态。"""

    PENDING = "pending"
    BLOCKED = "blocked"
    RUNNABLE = "runnable"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


TERMINAL_STATUSES = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
)

_ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset(
        {TaskStatus.BLOCKED, TaskStatus.RUNNABLE, TaskStatus.CANCELLED}
    ),
    TaskStatus.BLOCKED: frozenset(
        {TaskStatus.RUNNABLE, TaskStatus.CANCELLED, TaskStatus.INTERRUPTED}
    ),
    TaskStatus.RUNNABLE: frozenset(
        {TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.INTERRUPTED}
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.WAITING_INPUT,
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.INTERRUPTED,
        }
    ),
    TaskStatus.WAITING_INPUT: frozenset(
        {TaskStatus.RUNNING, TaskStatus.CANCELLED, TaskStatus.INTERRUPTED}
    ),
    TaskStatus.INTERRUPTED: frozenset({TaskStatus.RUNNABLE, TaskStatus.CANCELLED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """判断状态转换是否合法。"""

    return target in _ALLOWED_TRANSITIONS[current]


@dataclass(frozen=True, slots=True)
class ContextPackage:
    """传给子 Agent 的最小充分上下文。"""

    objective: str
    acceptance_criteria: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    confirmed_facts: tuple[str, ...] = ()
    memory_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    dependency_results: tuple[str, ...] = ()
    expected_output: str = "structured_report"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    """一次结构化委派请求。"""

    objective: str
    profile_name: str = "general"
    parent_session_key: str = ""
    background: bool = False
    acceptance_criteria: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    confirmed_facts: tuple[str, ...] = ()
    memory_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    dependency_ids: tuple[str, ...] = ()
    parent_agent_id: str = "main"
    parent_task_id: str = ""
    root_agent_id: str = "main"
    depth: int = 1
    max_iterations: int | None = None
    max_elapsed_seconds: float | None = None
    side_effecting: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StructuredSubAgentResult:
    """子 Agent 面向父控制链路的结构化结果。"""

    status: str
    conclusion: str
    evidence: tuple[dict[str, Any], ...] = ()
    artifacts: tuple[dict[str, Any], ...] = ()
    completed_criteria: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    remaining_work: tuple[str, ...] = ()
    usage: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    unstructured_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AgentTask:
    """SQLite 中的一条 Agent/Task 节点。"""

    task_id: str
    agent_id: str
    root_agent_id: str
    parent_agent_id: str
    parent_task_id: str
    root_session_key: str
    profile_name: str
    objective: str
    context_package: ContextPackage
    status: TaskStatus
    depth: int
    task_dir: Path
    max_iterations: int
    max_elapsed_seconds: float
    side_effecting: bool = False
    background: bool = False
    trace_id: str = ""
    result_summary: str = ""
    result_data: dict[str, Any] = field(default_factory=dict)
    error_type: str = ""
    error_message: str = ""
    blocked_reason: str = ""
    completion_notified: bool = False
    created_at: str = field(default_factory=utc_now_iso)
    started_at: str = ""
    finished_at: str = ""
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True, slots=True)
class TaskEdge:
    source_task_id: str
    target_task_id: str
    edge_type: str = "depends_on"
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True, slots=True)
class AgentMessage:
    message_id: str
    task_id: str
    from_agent_id: str
    to_agent_id: str
    message_type: str
    content: str
    created_at: str = field(default_factory=utc_now_iso)
    delivered_at: str = ""


@dataclass(frozen=True, slots=True)
class AgentArtifact:
    artifact_id: str
    task_id: str
    agent_id: str
    path: Path
    kind: str = "file"
    mime_type: str = "application/octet-stream"
    sha256: str = ""
    size: int = 0
    created_at: str = field(default_factory=utc_now_iso)


@dataclass(frozen=True, slots=True)
class TaskAttempt:
    attempt_id: str
    task_id: str
    attempt_no: int
    trace_id: str
    status: str = "running"
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str = ""
    error_type: str = ""
