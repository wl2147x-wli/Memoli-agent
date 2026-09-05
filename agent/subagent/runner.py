"""Running a sub agent: one task, its own context, a summary back.

The parent's context only ever sees the spawn call and the returned summary.
Everything the sub agent read, ran and discarded on the way stays out, which is
the point of spawning one at all.
"""

from __future__ import annotations

import contextvars
import copy
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from common.log import logger
from common.runtime_identity import identity_scope

# 当前运行任务的嵌套深度，0 表示主代理。放在 ContextVar 上
# 而不是挂在 Agent 上，因为子代理运行在工作线程里，
# contextvars.copy_context() 能在线程切换时把它一并携带过去。
_depth: contextvars.ContextVar[int] = contextvars.ContextVar("cow_subagent_depth", default=0)


def current_depth() -> int:
    return _depth.get()


@dataclass(frozen=True)
class SubagentSettings:
    enabled: bool = True
    max_depth: int = 1
    max_concurrent: int = 3
    timeout_seconds: float = 300.0

    @classmethod
    def from_config(cls) -> "SubagentSettings":
        from config import conf

        raw = conf().get("subagent") or {}
        if not isinstance(raw, dict):
            logger.warning("[SubAgent] 'subagent' config must be an object; ignoring")
            raw = {}

        def _bounded(key, default, low, high, cast):
            try:
                value = cast(raw.get(key, default))
            except (TypeError, ValueError):
                logger.warning(f"[SubAgent] Invalid {key!r}; using {default}")
                return default
            if not low <= value <= high:
                logger.warning(
                    f"[SubAgent] {key}={value} out of range [{low}, {high}]; using {default}"
                )
                return default
            return value

        return cls(
            # 默认开启，除非用户显式关闭：即使某个安装从未
            # 配置过子代理，也值得默认启用它；
            # 关闭它应当是用户有意为之。
            enabled=bool(raw.get("enabled", True)),
            max_depth=_bounded("max_depth", 1, 1, 5, int),
            max_concurrent=_bounded("max_concurrent", 3, 1, 10, int),
            timeout_seconds=_bounded("timeout_seconds", 300.0, 10.0, 3600.0, float),
        )


@dataclass
class SubagentTask:
    goal: str
    context: str = ""
    subagent_type: Optional[str] = None


def _build_brief(task: SubagentTask, template) -> str:
    parts = [template.prompt, "", "YOUR TASK:", task.goal.strip()]
    if task.context.strip():
        parts += ["", "CONTEXT:", task.context.strip()]
    return "\n".join(parts)


def _private_tools(parent, template) -> list:
    """This template's tools, as instances no other run shares.

    The agent loop drives tools by assignment — it sets `context`,
    `cancel_event` and `progress_callback` on the instance before each call and
    clears them after. Two sub agents running at once on one instance would
    therefore clear each other's cancel_event mid-call, quietly disarming the
    timeout, and cross-report each other's progress. A shallow copy gives each
    run its own slots for those attributes while leaving anything the tool holds
    open (a browser session, an MCP client) shared, as it already is today.
    """
    return [copy.copy(tool) for tool in template.select_tools(list(parent.tools))]


def _build_child(parent, template, task: SubagentTask):
    """A sibling of the parent Agent that shares its model and workspace.

    Not a copy: no memory manager, no persona files, no message history. It
    knows the task and nothing else, so anything it needs has to arrive through
    the goal and context the parent wrote.
    """
    from agent.protocol.agent import Agent

    child = Agent(
        system_prompt=template.prompt,
        description=f"sub agent ({template.name})",
        model=parent.model,
        tools=_private_tools(parent, template),
        output_mode="logger",
        # 预算取父代理的一半。子代理的任务本身是一份独立的工作，
        # 它从空上下文开始，所以不应获得与委派它的整个对话
        # 同等的运行空间。超出限制并不致命：循环只要求它对自己
        # 完成的工作做一次总结，而这正是它带回来的内容。
        max_steps=max(1, parent.max_steps // 2),
        max_context_tokens=parent.max_context_tokens,
        memory_manager=None,
        name=f"subagent:{template.name}",
        workspace_dir=parent.workspace_dir,
        skill_manager=parent.skill_manager if template.inherits_skills() else None,
        enable_skills=parent.enable_skills and template.inherits_skills(),
        runtime_info=parent.runtime_info,
        skip_context_files=True,
    )
    child.extra_system_suffix = _build_brief(task, template)
    # 与父代理保持一致的工作目录和权限模式：工具副本
    # 已经指向父代理的 cwd，因此把任务委托给子代理
    # 绝不能成为绕过会话权限的途径。
    child.project_dir = parent.project_dir
    child.permission_mode = parent.permission_mode
    return child


def _notify(on_state, index: int, state: Dict[str, Any]) -> None:
    """Report a task's state to the caller. Never lets a reporting problem
    reach the run it is only meant to describe."""
    if not on_state:
        return
    try:
        on_state(index, state)
    except Exception as e:
        logger.debug(f"[SubAgent] state callback failed: {e}")


def _open_run(parent, run_id: str, template) -> Optional[Any]:
    """Record the start of a spawned run, returning the store to close it with.

    None means the spawn is not being recorded, either because the parent's
    workspace is unknown — there is no database to attribute it to, and
    guessing a global one would write another workspace's history — or because
    the write failed. Bookkeeping never blocks a spawn.

    The parent's run id is read before the caller enters its own identity
    scope, so it is still the ambient one and becomes this run's parent.
    """
    workspace = getattr(parent, "workspace_dir", None)
    if not workspace:
        return None
    try:
        from agent.memory import get_conversation_store
        from common.utils import current_agent_run_id

        store = get_conversation_store(workspace)
        store.create_run(
            run_id,
            agent_id=getattr(parent, "_current_agent_id", "") or "",
            session_id=getattr(parent, "_current_session_id", "") or "",
            parent_run_id=current_agent_run_id() or "",
            extras={"subagent_type": template.name},
        )
        return store
    except Exception as e:
        logger.debug(f"[SubAgent] could not record run {run_id}: {e}")
        return None


# 本模块向调用者上报的状态，与“运行表中记录为已完成”的状态之间的映射。
_RUN_STATUS = {"completed": "done", "cancelled": "cancelled", "failed": "failed"}


def _close_run(store, run_id: str, result: Dict[str, Any]) -> None:
    """Mark a spawned run finished. Silent on failure, like _open_run."""
    if store is None:
        return
    try:
        store.finish_run(
            run_id,
            status=_RUN_STATUS.get(result.get("status", ""), "done"),
            error=str(result.get("error", "")),
        )
    except Exception as e:
        logger.debug(f"[SubAgent] could not close run {run_id}: {e}")


def _run_one(parent, template, task: SubagentTask, index: int, cancel_event,
             on_state=None, on_event=None) -> Dict[str, Any]:
    started = time.time()
    run_id = uuid.uuid4().hex[:12]
    # 先于下方的 identity_scope 执行，因此此刻父进程的 run id 仍是环境上下文中的那个。
    run_store = _open_run(parent, run_id, template)
    result: Dict[str, Any] = {"task_index": index, "subagent_type": template.name}
    _notify(on_state, index, {"status": "running", "subagent_type": template.name})

    child_events = None
    if on_event:
        def child_events(event: Dict[str, Any]) -> None:
            # 与 _notify 相同的约定：只是旁观这场运行，绝不能打断它。
            try:
                on_event(index, event)
            except Exception as e:
                logger.debug(f"[SubAgent] event callback failed: {e}")

    try:
        # 在父代理与会话之下新建 run_id：子代理写入的状态
        # 会落到正确的工作空间里，其运行轨迹归属于这次派生，
        # 而不是算到父代理的某一轮头上。
        with identity_scope(run_id=run_id):
            _depth.set(_depth.get() + 1)
            child = _build_child(parent, template, task)
            summary = child.run_stream(
                task.goal, clear_history=True, cancel_event=cancel_event,
                on_event=child_events,
            )
        result["status"] = "cancelled" if cancel_event.is_set() else "completed"
        result["summary"] = summary or ""
    except Exception as e:
        logger.warning(f"[SubAgent] task {index} ({template.name}) failed: {e}")
        result["status"] = "failed"
        result["error"] = str(e)

    result["duration_seconds"] = round(time.time() - started, 2)
    _close_run(run_store, run_id, result)
    _notify(on_state, index, result)
    return result


def run_tasks(
    parent,
    tasks: List[SubagentTask],
    templates,
    settings: SubagentSettings,
    on_state=None,
    on_event=None,
) -> List[Dict[str, Any]]:
    """Run every task and return one result per task, in the order given.

    Tasks run concurrently. A task that times out is cancelled and reported as
    such rather than abandoned, so the parent always gets a full-length result
    list and can tell the difference between "nothing found" and "never ran".

    `on_state(index, state)` is called as each task starts and again as it
    settles, so a caller can follow tasks individually while they run rather
    than learning about all of them at the end. Every task that reports a start
    reports an end, timeouts included.

    `on_event(index, event)` receives the sub agent's own stream events as they
    happen. What the parent's context sees is still only the returned summary;
    this is for whoever is watching the run, who otherwise spends the minutes
    it takes looking at a spinner.
    """
    cancel_events = [threading.Event() for _ in tasks]
    resolved = []
    for task in tasks:
        name = task.subagent_type or ""
        resolved.append(templates[name] if name in templates else templates[_default_name(templates)])

    pool = ThreadPoolExecutor(
        max_workers=min(len(tasks), settings.max_concurrent),
        thread_name_prefix="subagent",
    )
    try:
        futures = []
        for index, (task, template) in enumerate(zip(tasks, resolved)):
            # copy_context 会把运行时身份和深度计数器带进工作线程；
            # 没有它，子代理就都会在默认 Agent 下以深度 0 运行。
            ctx = contextvars.copy_context()
            futures.append(
                pool.submit(
                    ctx.run, _run_one, parent, template, task, index,
                    cancel_events[index], on_state, on_event,
                )
            )

        deadline = time.time() + settings.timeout_seconds
        results: List[Optional[Dict[str, Any]]] = [None] * len(tasks)
        for index, future in enumerate(futures):
            remaining = max(0.0, deadline - time.time())
            try:
                results[index] = future.result(timeout=remaining)
            except FutureTimeout:
                # 通知该运行停止并汇报。工人此刻正处在下一个检查点，
                # 可能需要等一整段 LLM 响应完成后才会退出。
                cancel_events[index].set()
                results[index] = {
                    "task_index": index,
                    "subagent_type": resolved[index].name,
                    "status": "timeout",
                    "error": (
                        f"Exceeded the {settings.timeout_seconds:g}s sub agent budget. "
                        f"Split the task or raise subagent.timeout_seconds."
                    ),
                }
                # 该工人仍在收尾、不会自己上报超时，
                # 所以在此处直接了结该任务，免得正在跟进它的人
                # 空等一个永远不会返回的任务。
                _notify(on_state, index, results[index])
    finally:
        # 有意不等待：`with` 块会把每个刚被我们放弃的线程都 join 一遍，
        # 那样超出预算仍在跑的工具调用就等于是强制等待了。被取消的
        # 运行会自行停止，不影响父代理共享的任何状态。
        pool.shutdown(wait=False)

    return [r for r in results if r is not None]


def _default_name(templates) -> str:
    from agent.subagent.templates import DEFAULT_TEMPLATE_NAME

    if DEFAULT_TEMPLATE_NAME in templates:
        return DEFAULT_TEMPLATE_NAME
    return next(iter(templates))
