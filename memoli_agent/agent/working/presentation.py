"""工作状态的人类可读与机器可读表现。"""

from __future__ import annotations

import io
import json
from dataclasses import asdict
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from memoli_agent.agent.working.models import WorkingStateSnapshot


def snapshot_to_dict(snapshot: WorkingStateSnapshot) -> dict[str, Any]:
    """生成字段稳定、带 schema 版本的 JSON 对象。"""

    checkpoint = asdict(snapshot.checkpoint) if snapshot.checkpoint else None
    runtime = asdict(snapshot.runtime_status) if snapshot.runtime_status else None
    return {
        "schema_version": snapshot.schema_version,
        "session_key": snapshot.session_key,
        "availability": snapshot.availability,
        "checkpoint": (
            {"trust": "agent", **checkpoint} if checkpoint is not None else None
        ),
        "runtime_status": (
            {"trust": "runtime", **runtime} if runtime is not None else None
        ),
        "truncated": snapshot.truncated,
        "omitted_fields": list(snapshot.omitted_fields),
    }


def snapshot_to_json(snapshot: WorkingStateSnapshot) -> str:
    """使用确定性键顺序输出单个 JSON 对象。"""

    return json.dumps(
        snapshot_to_dict(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def render_working_card(snapshot: WorkingStateSnapshot, max_chars: int = 4_000) -> str:
    """渲染有界工作卡片，使用 Rich Panel + Table 美化输出。"""

    buffer = io.StringIO()
    console = Console(
        file=buffer,
        force_terminal=True,
        color_system="auto",
        width=100,
    )

    # 顶部概览
    overview = Text()
    overview.append("📋 会话: ", style="bold")
    overview.append(snapshot.session_key)
    overview.append("  |  ")
    overview.append("可用性: ", style="bold")
    if snapshot.availability == "available":
        overview.append(snapshot.availability, style="green")
    else:
        overview.append(snapshot.availability, style="yellow")

    checkpoint = snapshot.checkpoint
    if checkpoint is None:
        console.print(Panel(overview, title="当前工作卡片", border_style="cyan"))
        console.print(Text("checkpoint: unavailable", style="dim"))
        return buffer.getvalue()

    # Agent Checkpoint 详细信息
    table = Table(show_header=False, box=None, padding=(0, 2), width=100)
    table.add_column(style="bold cyan", width=14)
    table.add_column(width=80)

    table.add_row("状态:", checkpoint.status)
    table.add_row("stale:", "是" if checkpoint.stale else "否")
    table.add_row("revision:", str(checkpoint.revision))
    table.add_row("更新时间:", checkpoint.updated_at or "unavailable")
    table.add_row("目标:", checkpoint.objective or "unavailable")
    table.add_row("当前步骤:", checkpoint.current_step or "unavailable")
    table.add_row("下一步:", checkpoint.next_action or "unavailable")
    table.add_row("约束:", "；".join(checkpoint.constraints) or "unavailable")
    table.add_row("关键内容:", checkpoint.key_info or "unavailable")
    table.add_row("决策:", "；".join(checkpoint.decisions) or "unavailable")
    table.add_row("产物:", "；".join(checkpoint.artifacts) or "unavailable")
    table.add_row("相关 SOP:", checkpoint.related_sop or "unavailable")

    console.print(Panel(overview, title="当前工作卡片", border_style="cyan"))
    console.print(
        Panel(table, title="Agent Checkpoint (trust=agent)", border_style="blue")
    )

    # Runtime Status
    runtime = snapshot.runtime_status
    if runtime is not None:
        runtime_table = Table(show_header=False, box=None, padding=(0, 2), width=100)
        runtime_table.add_column(style="bold green", width=14)
        runtime_table.add_column(width=80)
        runtime_table.add_row(
            "iteration:",
            f"{runtime.iteration}/{runtime.max_iterations or 'unavailable'}",
        )
        runtime_table.add_row("elapsed:", f"{runtime.elapsed_seconds:.3f}s")
        runtime_table.add_row("last_tool:", runtime.last_tool)
        runtime_table.add_row("last_tool_status:", runtime.last_tool_status)
        runtime_table.add_row(
            "artifacts:", "；".join(runtime.artifacts) or "unavailable"
        )
        console.print(
            Panel(
                runtime_table,
                title="Runtime Status (trust=runtime)",
                border_style="green",
            )
        )
    else:
        console.print(Text("runtime: unavailable", style="dim"))

    content = buffer.getvalue()
    if len(content) <= max_chars:
        return content
    marker = "\n...[已省略低优先级工作内容]"
    return content[: max(0, max_chars - len(marker))] + marker
