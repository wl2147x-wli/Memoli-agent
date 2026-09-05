"""State and Card 2.0 rendering for a Feishu agent run."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from common import i18n


_MAX_PANEL_STEPS = 10
_MAX_STEP_CHARS = 800


class FeishuProgressState:
    """Reduce CowAgent stream events into one renderable Feishu card state."""

    def __init__(self, started_at: Optional[float] = None):
        self.started_at = time.monotonic() if started_at is None else started_at
        self.status = "running"
        self.turns = 0
        self.current_text = ""
        # 已完成转弯的提交文本（工具前注释），保留
        # 因此该卡显示完整的多回合流程，而不仅仅是最后一个。
        self._committed_text = ""
        self._reasoning_buffer = ""
        self.reasoning_steps: List[str] = []
        self.tool_steps: List[Dict[str, Any]] = []
        self._tool_index: Dict[str, Dict[str, Any]] = {}
        self.cancelled = False

    @property
    def display_text(self) -> str:
        """Full visible text: committed prior turns plus the current buffer."""
        return self._committed_text + self.current_text

    def finalize_text(self, text: str) -> None:
        """Collapse the accumulated text into a single final buffer.

        Used once the run ends and the caller has the fully resolved text
        (e.g. markdown images uploaded), so ``display_text`` returns it as-is
        without re-prepending the already-included committed history.
        """
        self._committed_text = ""
        self.current_text = text

    def consume(self, event: Dict[str, Any]) -> None:
        """Consume one event emitted by ``AgentStreamHandler``."""
        event_type = event.get("type")
        data = event.get("data") or {}

        if event_type == "turn_start":
            self._mark_running_tools_done()
            turn = data.get("turn")
            if isinstance(turn, int):
                self.turns = max(self.turns, turn)
            else:
                self.turns += 1
            # 将每回合的工具前评论保留在卡上，而不是
            # 擦除它：提交完成的回合文本（带有分隔符），以便
            # 整个“说→运行工具→报告”流程累积在一张卡中。
            if self.turns > 1 and self.current_text.strip():
                self._committed_text += self.current_text.rstrip() + "\n\n---\n\n"
            self.current_text = ""
            return

        if event_type == "reasoning_update":
            self._reasoning_buffer += str(data.get("delta") or "")
            return

        if event_type == "message_update":
            self.current_text += str(data.get("delta") or "")
            return

        if event_type == "message_end":
            self._commit_reasoning()
            return

        if event_type == "tool_execution_start":
            tool_id = data.get("tool_call_id")
            step = {
                "summary": str(data.get("tool_name") or "tool"),
                "status": "running",
                "started_at": time.monotonic(),
                "elapsed": None,
            }
            self.tool_steps.append(step)
            if tool_id:
                self._tool_index[tool_id] = step
            return

        if event_type == "tool_execution_end":
            tool_id = data.get("tool_call_id")
            step = self._tool_index.get(tool_id) if tool_id else None
            if step is None:
                # 当没有 id 匹配时，回退到最近运行的步骤。
                step = next((s for s in reversed(self.tool_steps) if s["status"] == "running"), None)
            if step is not None:
                step["status"] = "error" if data.get("status") not in (None, "success") else "done"
                elapsed = data.get("execution_time")
                if elapsed is None and step.get("started_at") is not None:
                    elapsed = time.monotonic() - step["started_at"]
                step["elapsed"] = elapsed
            return

        if event_type == "agent_cancelled":
            self.cancelled = True
            self.status = "stopped"
            return

        if event_type == "agent_end":
            self._commit_reasoning()
            self._mark_running_tools_done()
            cancelled = self.cancelled or bool(data.get("cancelled"))
            if cancelled:
                self.status = "stopped"
                self.current_text = self.current_text.rstrip() or "_(stopped)_"
            else:
                self.status = "done"
                final_response = data.get("final_response")
                if final_response:
                    self.current_text = str(final_response)

    def build_card(self, streaming: bool, now: Optional[float] = None) -> Dict[str, Any]:
        """Render the current state as a Feishu Card 2.0 object."""
        # 本地化状态标题文本； en/zh/zh-Hant 来自 i18n.t。
        title, template = {
            "running": (i18n.t("处理中", "Working"), "blue"),
            "done": (i18n.t("完成", "Done"), "green"),
            "stopped": (i18n.t("已停止", "Stopped"), "grey"),
            "error": (i18n.t("出错", "Error"), "red"),
        }.get(self.status, (i18n.t("处理中", "Working"), "blue"))

        main_text = self.display_text or "..."
        elements: List[Dict[str, Any]] = []

        # 仅当存在真实推理内容时才渲染推理面板。
        # Upstream仅在启用深度思考时才会发出reasoning_update，因此
        # 空的 Reasoning_steps 意味着我们根本不应该显示任何面板。
        if self.reasoning_steps:
            elements.append(
                _panel(
                    "🤔 {}".format(i18n.t("思考", "Thinking")),
                    [_text_row(step, muted=True) for step in self.reasoning_steps[-_MAX_PANEL_STEPS:]],
                    expanded=streaming,
                )
            )

        if self.tool_steps:
            elements.append(
                _panel(
                    "🔧 {} ({})".format(i18n.t("工具", "Tools"), len(self.tool_steps)),
                    [
                        _text_row(_format_tool_step(step))
                        for step in self.tool_steps[-_MAX_PANEL_STEPS:]
                    ],
                    expanded=streaming,
                )
            )

        elements.append(
            {
                "tag": "markdown",
                "element_id": "stream_md",
                "content": main_text,
            }
        )

        elapsed = max(0.0, (time.monotonic() if now is None else now) - self.started_at)
        turn_label = i18n.t("轮", "turn" if self.turns == 1 else "turns")
        elements.extend(
            [
                {"tag": "hr"},
                {
                    "tag": "markdown",
                    "content": "{:.1f}s · {} {}".format(elapsed, self.turns, turn_label),
                    "text_size": "notation",
                },
            ]
        )

        config: Dict[str, Any] = {
            "streaming_mode": streaming,
            "update_multi": True,
            "enable_forward_interaction": True,
            "summary": {"content": _summary(main_text, title)},
        }
        if streaming:
            config["streaming_config"] = {
                "print_frequency_ms": {"default": 40},
                "print_step": {"default": 4},
                "print_strategy": "fast",
            }

        card: Dict[str, Any] = {
            "schema": "2.0",
            "config": config,
            "body": {"elements": elements},
        }
        # 运行成功完成后隐藏状态标题；一个平原
        # 答案不需要“完成”横幅。保留运行/停止/错误的标头
        # 因此用户仍然可以获得进度和失败信号。
        if self.status != "done":
            card["header"] = {
                "template": template,
                "title": {"tag": "plain_text", "content": title},
            }
        return card

    def _commit_reasoning(self) -> None:
        reasoning = self._reasoning_buffer.strip()
        if reasoning:
            self.reasoning_steps.append(reasoning[-_MAX_STEP_CHARS:])
        self._reasoning_buffer = ""

    def _mark_running_tools_done(self) -> None:
        for step in self.tool_steps:
            if step["status"] == "running":
                step["status"] = "done"
                if step.get("elapsed") is None and step.get("started_at") is not None:
                    step["elapsed"] = time.monotonic() - step["started_at"]


def _tool_status_label(status: str) -> str:
    if status == "running":
        return i18n.t("执行中", "running")
    if status == "error":
        return i18n.t("失败", "error")
    return i18n.t("完成", "done")


def _format_tool_step(step: Dict[str, Any]) -> str:
    # 工具名称加上其自身状态和经过的时间，例如“搜索·完成·1.2秒”。
    parts = [str(step.get("summary") or "tool"), _tool_status_label(step["status"])]
    elapsed = step.get("elapsed")
    if isinstance(elapsed, (int, float)):
        parts.append("{:.1f}s".format(max(0.0, float(elapsed))))
    return " · ".join(parts)


def _panel(title: str, elements: List[Dict[str, Any]], expanded: bool) -> Dict[str, Any]:
    return {
        "tag": "collapsible_panel",
        "expanded": expanded,
        "background_color": "grey",
        # 面板标题使用 markdown，因此我们可以通过 text_size 缩小字体
        # （纯文本标题忽略 text_size 并破坏卡片渲染）。
        "header": {"title": {"tag": "markdown", "content": title, "text_size": "notation"}},
        "border": {"color": "grey"},
        "vertical_spacing": "8px",
        "padding": "4px 8px",
        "elements": elements,
    }


def _text_row(content: str, muted: bool = False) -> Dict[str, Any]:
    text = {
        "tag": "plain_text",
        "content": content,
        "text_size": "notation",
    }
    if muted:
        text["text_color"] = "grey"
    return {"tag": "div", "text": text}


def _summary(text: str, fallback: str) -> str:
    preview = " ".join(text.strip().split())
    return preview[:60] or fallback
