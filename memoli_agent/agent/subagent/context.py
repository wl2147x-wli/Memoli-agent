"""SubAgent 上下文编译与结构化结果解析。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from memoli_agent.agent.subagent.models import (
    ContextPackage,
    DelegationRequest,
    StructuredSubAgentResult,
)


@dataclass(frozen=True, slots=True)
class ContextCompiler:
    """确定性组合委派参数和依赖摘要，不复制主对话。"""

    max_dependency_chars: int = 4_000

    def compile(
        self,
        request: DelegationRequest,
        *,
        dependency_results: tuple[str, ...] = (),
    ) -> ContextPackage:
        bounded = tuple(
            _bound_text(item, self.max_dependency_chars)
            for item in dependency_results
            if item.strip()
        )
        return ContextPackage(
            objective=request.objective.strip(),
            acceptance_criteria=request.acceptance_criteria,
            constraints=request.constraints,
            confirmed_facts=request.confirmed_facts,
            memory_refs=request.memory_refs,
            artifact_refs=request.artifact_refs,
            dependency_results=bounded,
        )

    @staticmethod
    def render(context: ContextPackage) -> str:
        """用清晰边界把 Context Package 交给模型。"""

        return (
            "请完成下面的结构化子任务。不要假设你看过主对话；只使用这里的上下文"
            "以及允许的工具。\n<context_package>\n"
            + json.dumps(context.to_dict(), ensure_ascii=False, indent=2)
            + "\n</context_package>\n"
            "最终优先输出一个 JSON 对象，字段为 status、conclusion、evidence、"
            "artifacts、completed_criteria、open_questions、remaining_work、usage、error。"
        )


def parse_structured_result(
    content: str,
    *,
    default_status: str,
    usage: dict[str, Any] | None = None,
    error_type: str | None = None,
) -> StructuredSubAgentResult:
    """解析模型 JSON；无法解析时保留原文并明确降级。"""

    payload = _parse_json_object(content)
    if payload is None:
        return StructuredSubAgentResult(
            status=default_status,
            conclusion=content.strip(),
            usage=dict(usage or {}),
            error={"type": error_type} if error_type else None,
            unstructured_fallback=True,
        )
    status = str(payload.get("status") or default_status)
    conclusion = str(payload.get("conclusion") or "").strip()
    if not conclusion:
        conclusion = content.strip()
    return StructuredSubAgentResult(
        status=status,
        conclusion=conclusion,
        evidence=_dict_tuple(payload.get("evidence")),
        artifacts=_dict_tuple(payload.get("artifacts")),
        completed_criteria=_str_tuple(payload.get("completed_criteria")),
        open_questions=_str_tuple(payload.get("open_questions")),
        remaining_work=_str_tuple(payload.get("remaining_work")),
        usage=dict(payload.get("usage") or usage or {}),
        error=(
            dict(payload["error"]) if isinstance(payload.get("error"), dict) else None
        ),
        unstructured_fallback=False,
    )


def _parse_json_object(content: str) -> dict[str, Any] | None:
    text = content.strip()
    candidates = [text]
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        candidates.append("\n".join(lines[1:-1]))
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _dict_tuple(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, dict))


def _str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value if str(item).strip())


def _bound_text(content: str, limit: int) -> str:
    if len(content) <= limit:
        return content
    return content[: max(0, limit - 20)] + "\n...[TRUNCATED]"
