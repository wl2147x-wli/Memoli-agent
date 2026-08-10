"""SubAgent 任务和事件类型。

这些类型把“子任务请求、执行结果、完成回流事件”从 manager 和 runtime 中拆出来，
方便后续接入后台任务、持久化队列或 peer agent。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from memoli_agent.agent.subagent.models import (
    ContextPackage,
    StructuredSubAgentResult,
)


def utc_now() -> datetime:
    """返回当前 UTC 时间。"""

    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class SubAgentTask:
    """一次子 agent 任务请求。"""

    task_id: str
    instruction: str
    profile_name: str
    parent_session_key: str
    task_dir: Path
    metadata: dict[str, Any] = field(default_factory=dict)
    agent_id: str = ""
    root_agent_id: str = "main"
    parent_agent_id: str = "main"
    parent_task_id: str = ""
    depth: int = 1
    context_package: ContextPackage | None = None
    attempt_id: str = ""
    attempt_no: int = 1
    trace_id: str = ""


@dataclass(frozen=True, slots=True)
class SubAgentResult:
    """一次子 agent 任务结果。"""

    task_id: str
    content: str
    success: bool
    profile_name: str
    task_dir: Path
    metadata: dict[str, Any] = field(default_factory=dict)
    agent_id: str = ""
    trace_id: str = ""
    attempt_id: str = ""
    status: str = "completed"
    structured: StructuredSubAgentResult | None = None


@dataclass(frozen=True, slots=True)
class SubAgentCompletionEvent:
    """子 agent 后台任务完成事件。"""

    task_id: str
    parent_session_key: str
    result: SubAgentResult
    agent_id: str = ""
    timestamp: datetime = field(default_factory=utc_now)
