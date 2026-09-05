"""Self-evolution executor.

Runs an isolated review agent over an idle conversation's transcript and, if a
clear signal is found, lets it edit memory / skills via a restricted toolset.
Conservative by design: most runs return ``[SILENT]`` and change nothing.

Flow:
    1. Build a transcript from the session's new (since last pass) messages.
    2. Snapshot MEMORY.md + daily file + editable skills (for undo) -> backup_id.
    3. Run an isolated agent (same model, restricted tools, evolution prompt).
    4. If output is [SILENT], or no workspace file actually changed -> done.
    5. Otherwise -> record to the evolution log, inject an [EVOLUTION] note into
       the user session (so the main agent can honor "undo"), and push the
       summary to the user's channel.

Reuses existing infrastructure (AgentBridge.create_agent, ToolManager,
remember_scheduled_output, channel_factory) rather than introducing a fork.
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from common.log import logger

from agent.evolution.backup import create_backup
from agent.evolution.config import get_evolution_config
from agent.evolution.prompts import (
    EVOLUTION_MARKER,
    EVOLUTION_SYSTEM_PROMPT,
    SILENT_TOKEN,
    build_review_user_message,
)
from agent.evolution.record import append_session_evolution

# 隔离进化代理可用的工具集，其余工具一律不开放，
# 因此无人值守的评审只能读取上下文并编辑受批准的工作区工件；
# 技能文件也可通过 write 工具直接创建。
_ALLOWED_TOOLS = {"read", "write", "edit", "ls", "memory_search", "memory_get"}

# 限制同时进行的进化轮次，避免一批空闲会话瞬间触发大量
# 后台模型运行；多出的会话只需等待下一次扫描。
_MAX_CONCURRENT = 2
_running_lock = threading.Lock()
_running_count = 0

# 同一工作区的演化事务不得重叠：否则一次失败的传递在
# 回滚快照时，可能覆盖另一并发传递已提交的改动。
# 不同工作区仍可保有上面设定的全局并发能力。
_workspace_locks_guard = threading.Lock()
_workspace_locks: dict[Path, threading.Lock] = {}


def _get_workspace_lock(workspace_dir: Path) -> threading.Lock:
    workspace = workspace_dir.resolve()
    with _workspace_locks_guard:
        lock = _workspace_locks.get(workspace)
        if lock is None:
            lock = threading.Lock()
            _workspace_locks[workspace] = lock
        return lock


def _builtin_skill_names() -> set:
    """Names of skills shipped with the product (project-root ``skills/``).

    These are protected: the evolution agent must never edit them, even though
    a same-named copy exists in the workspace at runtime. The project dir is the
    authoritative list of what counts as built-in.
    """
    try:
        # 由 executor.py 逐级向上：evolution → agent → 项目根目录
        project_root = Path(__file__).resolve().parents[2]
        builtin_dir = project_root / "skills"
        if not builtin_dir.is_dir():
            return set()
        names = set()
        for entry in builtin_dir.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                names.add(entry.name)
        return names
    except Exception:
        return set()


def _build_transcript(messages: List[dict], max_chars: int = 12000) -> str:
    """Render the session messages into a compact text transcript."""
    lines: List[str] = []
    for msg in messages:
        role = msg.get("role", "")
        if role not in ("user", "assistant"):
            continue
        content = msg.get("content", "")
        text = _extract_text(content)
        if not text.strip():
            continue
        speaker = "User" if role == "user" else "Assistant"
        lines.append(f"{speaker}: {text.strip()}")
    transcript = "\n".join(lines)
    # 若内容过长，则只保留最近的上下文（尾部最相关）。
    if len(transcript) > max_chars:
        transcript = "...(earlier omitted)...\n" + transcript[-max_chars:]
    return transcript


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""


def _select_tools(all_tools: list) -> list:
    return [t for t in all_tools if getattr(t, "name", None) in _ALLOWED_TOOLS]


# 演化过程中，写入操作必须被限制在工作区内的工具。
_WRITE_TOOLS = {"write", "edit"}


class _EvolutionWriteTransaction:
    """Make writes performed by one unattended evolution pass atomic."""

    _MISSING = object()

    def __init__(self, workspace: Path):
        self._workspace = workspace.resolve()
        self._before: dict[Path, object] = {}
        self._missing_parents: set[Path] = set()
        self._committed = False

    def record(self, path: Path) -> None:
        path = path.resolve()
        if path in self._before:
            return
        parent = path.parent
        while parent != self._workspace:
            try:
                parent.relative_to(self._workspace)
            except ValueError:
                break
            if parent.exists():
                break
            self._missing_parents.add(parent)
            parent = parent.parent
        try:
            self._before[path] = path.read_bytes() if path.is_file() else self._MISSING
        except OSError as e:
            raise PermissionError(f"cannot snapshot '{path}' before evolution write: {e}")

    def commit(self) -> None:
        self._committed = True

    def has_changes(self) -> bool:
        """Return whether a guarded write changed or created a file."""
        for path, before in self._before.items():
            try:
                after = path.read_bytes() if path.is_file() else self._MISSING
            except OSError:
                after = self._MISSING
            if before is self._MISSING:
                if after is not self._MISSING:
                    return True
            elif after is self._MISSING or after != before:
                return True
        return False

    def rollback(self) -> None:
        if self._committed:
            return
        for path, before in reversed(list(self._before.items())):
            try:
                if before is self._MISSING:
                    if path.is_file() or path.is_symlink():
                        path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(before)
            except OSError as e:
                logger.error(f"[Evolution] Failed to roll back {path}: {e}")
        for directory in sorted(
            self._missing_parents, key=lambda p: len(p.parts), reverse=True
        ):
            try:
                directory.rmdir()
            except OSError:
                pass


def _denied_evolution_path(
    workspace: Path, resolved: Path, protected_skills: set
) -> bool:
    """Block only workspace paths Self-Evolution must never modify."""
    try:
        relative = resolved.relative_to(workspace)
    except ValueError:
        return True
    parts = relative.parts
    if not parts:
        return True
    folded = tuple(part.casefold() for part in parts)
    if folded == ("skills", "skills_config.json"):
        return True
    if folded[0] == "memory" and len(folded) >= 2:
        if folded[1] == ".evolution_backups":
            return True
    if folded[0] == "skills" and len(folded) >= 2:
        protected = {name.casefold() for name in protected_skills}
        if folded[1] in protected:
            return True
    return False


class _WorkspaceWriteGuard:
    """Wraps a write/edit tool so it can ONLY write inside the workspace.

    Hard engineering guard (not prompt-based): any write resolving outside the
    workspace — e.g. the project's bundled ``skills/`` dir — is rejected. This
    protects built-in skills regardless of what the model attempts.
    """

    def __init__(
        self, inner, workspace_dir: str, protected_skills: set,
        transaction: _EvolutionWriteTransaction,
    ):
        self._inner = inner
        self._ws = Path(workspace_dir).resolve()
        self._protected_skills = protected_skills
        self._transaction = transaction
        # 镜像代理运行时从工具读取的属性。
        self.name = inner.name
        self.description = inner.description
        self.params = inner.params

    def __getattr__(self, item):
        return getattr(self._inner, item)

    def execute_tool(self, params):
        # 代理运行时调用的是 execute_tool（而非 execute）；在此把它
        # 转发到受保护的执行逻辑，确保路径检查始终生效。
        try:
            return self.execute(params)
        except Exception as e:
            logger.error(f"[Evolution] guarded tool error: {e}")
            from agent.tools.base_tool import ToolResult
            return ToolResult.fail(f"Error: {e}")

    def execute(self, args):
        from agent.tools.base_tool import ToolResult
        path = (args.get("path") or "").strip()
        if not path:
            return ToolResult.fail("Error: evolution write path is required.")
        try:
            resolved = Path(self._inner._resolve_path(path)).resolve()
        except Exception as e:
            return ToolResult.fail(f"Error: invalid evolution write path '{path}': {e}")
        if _denied_evolution_path(
            self._ws, resolved, self._protected_skills
        ):
            return ToolResult.fail(
                "Error: evolution cannot write outside the workspace or modify "
                "protected skills and bookkeeping files; "
                f"path '{path}' was blocked."
            )
        try:
            self._transaction.record(resolved)
        except Exception as e:
            return ToolResult.fail(f"Error: {e}")
        return self._inner.execute(args)


def _guard_tools(
    tools: list, workspace_dir: str, protected_skills: set,
    transaction: _EvolutionWriteTransaction,
) -> list:
    """Wrap evolution write tools with path and transaction guards."""
    guarded = []
    for t in tools:
        name = getattr(t, "name", None)
        if name in _WRITE_TOOLS:
            guarded.append(_WorkspaceWriteGuard(
                t, workspace_dir, protected_skills, transaction
            ))
        else:
            guarded.append(t)
    return guarded


# 值得关注进化引发改动的工作区子树；AGENT.md 也在监控之列，
# 因为进化偶尔会完善助理的角色定位与文风。
_WATCH_SUBDIRS = ("MEMORY.md", "AGENT.md", "skills", "knowledge", "output")
# memory/ 下需要忽略的子路径：进化自身的簿记，以及每晚的
# “梦想日记”——这些都不算面向用户的改动信号。
_MEMORY_IGNORE = (".evolution_backups", "dreams", "evolution")
# 技能子系统自动维护的文件（技能启停索引）。
# 这类文件不是进化产物，被重写也不算改动信号。
_WATCH_IGNORE_NAMES = ("skills_config.json",)


def _workspace_snapshot(workspace_dir) -> dict:
    """Map relative path -> (mtime, size) for watched files. Cheap, no reads."""
    ws = Path(workspace_dir)
    snap: dict = {}
    for name in _WATCH_SUBDIRS:
        root = ws / name
        if root.is_file():
            try:
                st = root.stat()
                snap[name] = (st.st_mtime, st.st_size)
            except OSError:
                pass
            continue
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.name in _WATCH_IGNORE_NAMES:
                continue
            try:
                st = p.stat()
                snap[str(p.relative_to(ws))] = (st.st_mtime, st.st_size)
            except OSError:
                pass

    # 监控每日记忆文件（memory/*.md，以及每个用户各自的每日文件），
    # 因为进化会把学习所得记在那里；备份、梦想等簿记子目录一律跳过。
    mem_dir = ws / "memory"
    if mem_dir.is_dir():
        for p in mem_dir.rglob("*.md"):
            rel_parts = p.relative_to(mem_dir).parts
            if rel_parts and rel_parts[0] in _MEMORY_IGNORE:
                continue
            try:
                st = p.stat()
                snap[str(p.relative_to(ws))] = (st.st_mtime, st.st_size)
            except OSError:
                pass
    return snap


def _workspace_changed(workspace_dir, pre: dict) -> bool:
    """True if any watched file was added, removed, or modified since ``pre``."""
    return _workspace_snapshot(workspace_dir) != pre


_MAX_EVOLUTION_SUMMARY_CHARS = 4000


def _valid_evolution_result(result: str) -> bool:
    """Reject malformed/no-content summaries before committing file changes."""
    cleaned = (result or "").replace(SILENT_TOKEN, "").strip()
    return bool(cleaned) and any(ch.isalnum() for ch in cleaned)


def _truncate_evolution_result(result: str) -> str:
    """Bound notification/log size without vetoing valid completed work."""
    if len(result) <= _MAX_EVOLUTION_SUMMARY_CHARS:
        return result
    suffix = "\n\n[summary truncated]"
    return result[:_MAX_EVOLUTION_SUMMARY_CHARS - len(suffix)].rstrip() + suffix


def run_evolution_for_session(
    agent_bridge,
    session_id: str,
    agent_id: str = "default",
    channel_type: str = "",
    receiver: str = "",
    user_id: Optional[str] = None,
    idle_minutes: float = 0.0,
) -> bool:
    """Run one evolution pass for a session. Returns True if it changed anything.

    Safe to call from a background thread. All failures are swallowed and
    logged — evolution must never disrupt the main pipeline.
    """
    cfg = get_evolution_config()
    if not cfg.enabled:
        return False

    # 并发控制闸门：限制同时运行的进化轮次数。
    global _running_count
    with _running_lock:
        if _running_count >= _MAX_CONCURRENT:
            logger.info(
                f"[Evolution] busy ({_running_count}/{_MAX_CONCURRENT} running); "
                f"skipping session={session_id} this scan"
            )
            return False
        _running_count += 1

    transaction: Optional[_EvolutionWriteTransaction] = None
    workspace_lock: Optional[threading.Lock] = None
    try:
        if hasattr(agent_bridge, "get_cached_agent"):
            agent = agent_bridge.get_cached_agent(session_id, agent_id=agent_id)
        else:
            agent = agent_bridge.agents.get(session_id) or agent_bridge.default_agent
        if not agent:
            return False

        # 能走到这里，说明前面的并发闸门已经放行；
        # 被闸门挡下的会话会保留其累计的回合数，
        # 下一次扫描时仍会继续评估它。
        agent._evo_turns = 0

        with agent.messages_lock:
            all_messages = list(agent.messages)
        total_msgs = len(all_messages)
        # 内存中的演化游标：只处理上次运行之后新增的消息，
        # 以免长时间会话反复评判（并重写）旧内容。
        # 游标保存在代理实例上，重启即丢失（可接受：最坏情况是
        # 重启后多跑一次冗余轮次；下游的文件改动检查
        # 会兜住它，不会把同一段记忆重复写入）。
        done = int(getattr(agent, "_evo_done_msg_count", 0))
        if done > total_msgs:
            done = 0  # 历史记录被修剪/重置；重新开始
        new_messages = all_messages[done:]
        transcript = _build_transcript(new_messages)
        if not transcript.strip():
            # 常规空转分支：每分钟的扫描都会遍历所有空闲会话。
            # 这里直接推进游标，避免反复扫描同一段尾部；且不记日志（纯属噪音）。
            agent._evo_done_msg_count = total_msgs
            return False

        logger.info(
            f"[Evolution] ▶ Reviewing session={session_id} "
            f"(idle {idle_minutes:.1f}min, {len(new_messages)} new/{total_msgs} msgs, "
            f"~{len(transcript)} chars)"
        )

        # 解析工作区与相关文件，为撤销操作准备一份快照。
        mem_cfg = getattr(getattr(agent, "memory_manager", None), "config", None)
        if mem_cfg is None:
            from agent.memory.config import get_default_memory_config
            mem_cfg = get_default_memory_config()
        workspace_dir = mem_cfg.get_workspace()
        workspace_lock = _get_workspace_lock(Path(workspace_dir))
        workspace_lock.acquire()
        if user_id:
            memory_file = Path(workspace_dir) / "memory" / "users" / user_id / "MEMORY.md"
        else:
            memory_file = Path(workspace_dir) / "MEMORY.md"
        skills_dir = mem_cfg.get_skills_dir()

        # 对 MEMORY.md 及每个不受保护技能的 SKILL.md 建立快照。
        # 受保护的内置技能从一开始就不允许被编辑，
        # 因此无需纳入备份。
        protected_names = _builtin_skill_names()
        transaction = _EvolutionWriteTransaction(Path(workspace_dir))
        # 备份 MEMORY.md 与今日的每日文件：进化目前会写入每日文件，
        # 而 MEMORY.md 建快照成本很低，
        # 万一模型改动过它，也能保证可撤销。
        today_daily = Path(workspace_dir) / "memory" / (
            datetime.now().strftime("%Y-%m-%d") + ".md"
        )
        if user_id:
            today_daily = Path(workspace_dir) / "memory" / "users" / user_id / (
                datetime.now().strftime("%Y-%m-%d") + ".md"
            )
        # AGENT.md（角色定义）也一并备份，以便能撤销罕见的角色改动。
        # 角色按工作区全局生效（并非按用户区分），无论 user_id 如何，
        # 它始终位于工作区根目录。
        agent_file = Path(workspace_dir) / "AGENT.md"
        backup_files = [Path(memory_file), today_daily, agent_file]
        if skills_dir.exists():
            for skill_md in skills_dir.rglob("SKILL.md"):
                # 技能目录是其名下 SKILL.md 的父级（或祖先）；
                # 这里通过检查 SKILL.md 的直接顶层目录来判断归属，以作保护。
                try:
                    top = skill_md.relative_to(skills_dir).parts[0]
                except (ValueError, IndexError):
                    continue
                if top in protected_names:
                    continue
                backup_files.append(skill_md)
        backup_id = create_backup(workspace_dir, backup_files)
        _backup_n = sum(1 for f in backup_files if Path(f).exists())

        # 对整片工作区做快照（路径 -> mtime/size），
        # 以便可靠地侦测任何文件变化——包括代理为完成手头任务而写出的
        # 新输出文件（这些文件并不在 backup_files 之中）。
        pre_snapshot = _workspace_snapshot(workspace_dir)

        # 构建隔离的评审代理：沿用同一模型、受限工具，
        # 并以硬性防护把一切写入限定在工作区内（确保项目自带的
        # 内置技能永远不会被改动）。
        review_tools = _guard_tools(
            _select_tools(list(getattr(agent, "tools", []) or [])),
            str(workspace_dir),
            protected_names,
            transaction,
        )
        review_agent = agent_bridge.create_agent(
            system_prompt="",
            tools=review_tools,
            description="Self-evolution review agent",
            max_steps=cfg.max_steps,
            workspace_dir=str(workspace_dir),
            skill_manager=getattr(agent, "skill_manager", None),
            memory_manager=getattr(agent, "memory_manager", None),
            enable_skills=True,
            runtime_info=getattr(agent, "runtime_info", None),
        )
        # 将该代理标记为受限评审代理，好让运行时的 MCP 协调逻辑
        # (ToolManager.sync_mcp_into_agent) 不会悄悄重新注入
        # _select_tools()/_guard_tools() 有意剔除的 MCP 工具。
        # 若没有该标记，评审边界会在第一个 LLM 回合就被重新打开。
        review_agent._evolution_restricted = True
        # 重用实时模型，使其遵循用户配置的模型。
        review_agent.model = agent.model
        # 在完整系统提示之后追加进化任务简介：代理既能
        # 拿到完整上下文（工具、工作区、用户偏好、记忆、时间），
        # 进化专属指令又位于最前面，
        # 二者互不覆盖。
        review_agent.extra_system_suffix = EVOLUTION_SYSTEM_PROMPT

        logger.info(
            f"[Evolution] backup {backup_id} ({_backup_n} files) → running review agent"
        )
        user_msg = build_review_user_message(transcript, protected_skills=list(protected_names))
        result = review_agent.run_stream(user_msg, clear_history=True)
        result = (result or "").strip()

        # 这批消息已评审完毕；推进游标，
        # 让下一次只处理此后新增的消息（与本次是否静默无关）。
        agent._evo_done_msg_count = total_msgs

        # 尊重明确的“静默”判决：结果为空白、整体为 [SILENT]，
        # 或以 [SILENT] 开头，都表示模型选择不发声。
        if not result or result.startswith(SILENT_TOKEN):
            logger.info(f"[Evolution] ✗ No change for session={session_id} ([SILENT])")
            return False

        # 反打扰兜底：只有事务确实写入过文件，
        # 或工作区快照检测到任何变化时，才视为有效成果；
        # 若两者都无变化，就绝不通知，以免空报。
        if not (
            transaction.has_changes()
            or _workspace_changed(workspace_dir, pre_snapshot)
        ):
            logger.info(
                f"[Evolution] ✗ session={session_id}: text produced but no file "
                f"changed — staying silent"
            )
            return False

        # 模型确实产出了总结。清掉正文中间残留的 [SILENT] 标记，
        # 然后再对外通知。
        result = result.replace(SILENT_TOKEN, "").strip()
        if not _valid_evolution_result(result):
            logger.info(
                f"[Evolution] ✗ Invalid/no-content result for session={session_id}; "
                "rolling back"
            )
            return False
        result = _truncate_evolution_result(result)

        logger.info(f"[Evolution] ✓ session={session_id} evolved:\n{result}")
        append_session_evolution(workspace_dir, result, backup_id=backup_id, user_id=user_id)
        # 注入 [EVOLUTION] 消息，好让主代理能执行“撤销”。
        _inject_evolution_record(
            agent_bridge, session_id, channel_type, result, backup_id, agent_id
        )
        # 注入的这些消息（[SCHEDULED]/[EVOLUTION]）都出自我们自己的输出。
        # 把游标移到它们之后，避免下一次扫描
        # 将进化自身的簿记误当作新的用户内容而再次触发。
        try:
            with agent.messages_lock:
                agent._evo_done_msg_count = len(agent.messages)
        except Exception:
            pass

        # 把摘要推送到用户的频道。“确实改动了文件”这一
        # 判定就是我们所需的唯一节流阀：真正的进化很少发生，
        # 因此无需额外的开关或每日次数限制。
        if channel_type and receiver:
            _notify_user(channel_type, receiver, result)

        transaction.commit()
        return True

    except Exception as e:
        logger.warning(f"[Evolution] Run failed for session={session_id}: {e}")
        return False
    finally:
        try:
            if transaction is not None:
                transaction.rollback()
        finally:
            if workspace_lock is not None:
                workspace_lock.release()
            with _running_lock:
                _running_count -= 1


def _inject_evolution_record(
    agent_bridge,
    session_id: str,
    channel_type: str,
    summary: str,
    backup_id: Optional[str],
    agent_id: str = None,
) -> None:
    """Add an [EVOLUTION] note to the user session so the main agent can undo."""
    try:
        note = f"{EVOLUTION_MARKER} {summary}"
        if backup_id:
            note += f"\n(backup_id: {backup_id}; to undo, restore this backup)"
        # 复用调度器的输出注入通道：在隔离状态下执行，
        # 只往用户会话写入一条紧凑的记录。
        remember_kwargs = {
            "session_id": session_id,
            "content": note,
            "channel_type": channel_type,
            "task_description": "self-evolution",
        }
        if hasattr(agent_bridge, "agent_registry"):
            remember_kwargs["agent_id"] = agent_id
        agent_bridge.remember_scheduled_output(**remember_kwargs)
    except Exception as e:
        logger.debug(f"[Evolution] Failed to inject evolution record: {e}")


def _notify_user(channel_type: str, receiver: str, summary: str) -> None:
    """Push the evolution summary to the user's channel as a new message."""
    try:
        from bridge.context import Context, ContextType
        from bridge.reply import Reply, ReplyType
        from channel.channel_factory import create_channel

        context = Context(ContextType.TEXT, summary)
        context["receiver"] = receiver
        context["isgroup"] = False
        context["session_id"] = receiver
        # 会去回复原消息的通道，需要把 msg 置为 None 才能发起新推送。
        if channel_type in ("feishu", "dingtalk", "wecom_bot", "qq"):
            context["msg"] = None
        if channel_type == "feishu":
            context["receive_id_type"] = "open_id"

        channel = create_channel(channel_type)
        if not channel:
            return

        # Web 是请求-响应：后台推送需要合成 request_id
        # 加上请求->会话映射，以便通道可以将消息路由到
        # 用户的轮询队列（与调度程序使用的方法相同）。
        if channel_type == "web":
            import uuid
            request_id = f"evolution_{uuid.uuid4().hex[:8]}"
            context["request_id"] = request_id
            if hasattr(channel, "request_to_session"):
                channel.request_to_session[request_id] = receiver

        channel.send(Reply(ReplyType.TEXT, summary), context)
        logger.info(f"[Evolution] Notified user via {channel_type}")
    except Exception as e:
        logger.warning(f"[Evolution] Failed to notify user: {e}")
