"""工作记忆的数据合同。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

WORKING_PRESENTATION_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class RuntimeStatus:
    """由 Runtime 根据真实执行事件投影的硬状态。"""

    iteration: int = 0
    max_iterations: int = 0
    elapsed_seconds: float = 0.0
    max_elapsed_seconds: float = 0.0
    last_tool: str = "unavailable"
    last_tool_status: str = "unavailable"
    completed_steps: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkingCheckpoint:
    """由 Agent 维护的软 checkpoint；不能覆盖硬状态。"""

    session_key: str
    objective: str = ""
    current_step: str = ""
    next_action: str = ""
    key_info: str = ""
    related_sop: str = ""
    constraints: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    status: str = "active"
    revision: int = 0
    stale: bool = False
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class CheckpointPatch:
    """原子更新请求；未提供的字段保持不变。"""

    expected_revision: int | None = None
    objective: str | None = None
    current_step: str | None = None
    next_action: str | None = None
    key_info: str | None = None
    related_sop: str | None = None
    constraints: tuple[str, ...] | None = None
    decisions: tuple[str, ...] | None = None
    artifacts: tuple[str, ...] | None = None
    status: str | None = None


@dataclass(frozen=True, slots=True)
class WorkingStateRenderResult:
    """状态渲染结果，携带审计所需版本。"""

    content: str
    revision: int
    truncated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkingStateSnapshot:
    """供本地表现层读取的结构化工作状态，不复用模型注入文本。"""

    session_key: str
    availability: str
    checkpoint: WorkingCheckpoint | None = None
    runtime_status: RuntimeStatus | None = None
    schema_version: int = WORKING_PRESENTATION_SCHEMA_VERSION
    truncated: bool = False
    omitted_fields: tuple[str, ...] = ()
