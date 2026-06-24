"""SubAgent 管理器。

管理器负责创建 task_id、维护任务目录、调用运行时，并在后台任务完成后
把结果投回主 MessageBus。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from memoli_agent.agent.subagent.events import (
    SubAgentCompletionEvent,
    SubAgentResult,
    SubAgentTask,
)
from memoli_agent.agent.subagent.profiles import SubAgentProfile
from memoli_agent.agent.subagent.runtime import SubAgentRuntime
from memoli_agent.bus.events import InboundMessage
from memoli_agent.bus.queue import MessageBus


@dataclass(slots=True)
class SubAgentManager:
    """子 agent 任务管理器。"""

    runtime: SubAgentRuntime
    bus: MessageBus
    root: Path
    profiles: dict[str, SubAgentProfile]
    default_profile: str = "general"
    max_concurrent: int = 2
    _semaphore: asyncio.Semaphore = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """初始化任务根目录和并发控制器。"""

        self.root.mkdir(parents=True, exist_ok=True)
        self._semaphore = asyncio.Semaphore(max(1, self.max_concurrent))

    async def run_task(
        self,
        instruction: str,
        profile_name: str = "general",
        parent_session_key: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SubAgentResult:
        """同步执行一个子 agent 任务。"""

        task = self._create_task(
            instruction=instruction,
            profile_name=profile_name or self.default_profile,
            parent_session_key=parent_session_key,
            metadata=metadata,
        )
        self._write_task_file(task)

        async with self._semaphore:
            result = await self.runtime.run(task)

        self._write_result_file(result)
        return result

    def spawn_background(
        self,
        instruction: str,
        profile_name: str = "general",
        parent_session_key: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """创建后台子 agent 任务并立即返回 task_id。"""

        task = self._create_task(
            instruction=instruction,
            profile_name=profile_name or self.default_profile,
            parent_session_key=parent_session_key,
            metadata=metadata,
        )
        self._write_task_file(task)
        asyncio.create_task(self._run_background(task))
        return task.task_id

    async def _run_background(self, task: SubAgentTask) -> None:
        """后台执行任务，并把完成事件投回 MessageBus。"""

        async with self._semaphore:
            result = await self.runtime.run(task)

        self._write_result_file(result)
        event = SubAgentCompletionEvent(
            task_id=task.task_id,
            parent_session_key=task.parent_session_key,
            result=result,
        )
        await self.bus.publish_inbound(
            InboundMessage(
                channel="subagent",
                chat_id=task.parent_session_key or task.task_id,
                sender="subagent",
                content=_format_completion_content(event),
                metadata={
                    "event": "subagent_completion",
                    "task_id": task.task_id,
                    "success": result.success,
                    "profile": result.profile_name,
                    "task_dir": str(result.task_dir),
                },
            )
        )

    def _create_task(
        self,
        instruction: str,
        profile_name: str,
        parent_session_key: str,
        metadata: dict[str, Any] | None,
    ) -> SubAgentTask:
        """创建任务对象和独立任务目录。"""

        task_id = _new_task_id()
        task_dir = self.root / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        return SubAgentTask(
            task_id=task_id,
            instruction=instruction.strip(),
            profile_name=profile_name,
            parent_session_key=parent_session_key,
            task_dir=task_dir,
            metadata=dict(metadata or {}),
        )

    def _write_task_file(self, task: SubAgentTask) -> None:
        """把任务请求写入 task.json，方便调试和复盘。"""

        payload = {
            "task_id": task.task_id,
            "instruction": task.instruction,
            "profile_name": task.profile_name,
            "parent_session_key": task.parent_session_key,
            "task_dir": str(task.task_dir),
            "metadata": task.metadata,
        }
        (task.task_dir / "task.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_result_file(self, result: SubAgentResult) -> None:
        """把执行结果写入 result.md。"""

        content = (
            f"# SubAgent Result\n\n"
            f"- task_id: {result.task_id}\n"
            f"- profile: {result.profile_name}\n"
            f"- success: {result.success}\n\n"
            f"## Content\n\n{result.content}\n\n"
            f"## Metadata\n\n```json\n"
            f"{json.dumps(result.metadata, ensure_ascii=False, indent=2)}\n"
            f"```\n"
        )
        (result.task_dir / "result.md").write_text(content, encoding="utf-8")


def _new_task_id() -> str:
    """生成可读且低冲突的任务 ID。"""

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"sub_{timestamp}_{uuid4().hex[:8]}"


def _format_completion_content(event: SubAgentCompletionEvent) -> str:
    """格式化后台完成事件内容。"""

    status = "成功" if event.result.success else "失败"
    return (
        f"子 agent 任务完成：{event.task_id}\n"
        f"状态：{status}\n"
        f"profile：{event.result.profile_name}\n"
        f"结果：\n{event.result.content}"
    )
