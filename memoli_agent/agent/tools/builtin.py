"""内置工具集合。

第六阶段提供一批最小可运行工具。第七阶段开始，memory 工具会接入
Markdown 长期记忆系统。
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from memoli_agent.agent.memory.models import EvidenceRef, MemoryScope
from memoli_agent.agent.memory.runtime import MemoryMutation, MemoryQuery, MemoryRuntime
from memoli_agent.agent.subagent.manager import SubAgentManager
from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.execution import current_tool_context


@dataclass(frozen=True, slots=True)
class TimeTool:
    """返回当前时间。"""

    name: str = "time"
    description: str = "获取当前本地时间和 UTC 时间。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """执行时间查询。"""

        local_now = datetime.now().astimezone()
        utc_now = datetime.now(UTC)
        return ToolResult(
            content=(
                f"本地时间：{local_now.isoformat()}\nUTC 时间：{utc_now.isoformat()}"
            ),
            metadata={"tool": self.name},
        )


@dataclass(slots=True)
class MemoryRecallTool:
    """检索长期记忆。"""

    memory_runtime: MemoryRuntime | None
    name: str = "memory_recall"
    description: str = "按关键词检索长期记忆。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "检索关键词。",
                },
                "types": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                "scope_kind": {"type": "string"},
                "scope_id": {"type": "string"},
                "statuses": {"type": "array", "items": {"type": "string"}},
                "max_sensitivity": {"type": "string"},
                "retrieval_mode": {
                    "type": "string",
                    "enum": [
                        "auto",
                        "card-first",
                        "claim-first",
                        "episode-first",
                        "hybrid",
                    ],
                },
                "detail_level": {
                    "type": "string",
                    "enum": ["summary", "fact", "evidence"],
                },
                "statement_ids": {"type": "array", "items": {"type": "string"}},
                "card_statement_limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                },
                "claim_expansion_limit": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 20,
                },
                "evidence_expansion_limit": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 20,
                },
                "at_time": {
                    "type": "string",
                    "description": "可选 ISO-8601 时间，用于时态检索。",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """检索长期记忆。"""

        if self.memory_runtime is None:
            raw = json.dumps(
                {"status": "disabled", "hits": [], "reason": "memory-disabled"},
                ensure_ascii=False,
            )
            return ToolResult(
                raw,
                success=False,
                raw_content=raw,
                status="disabled",
                metadata={"tool": self.name, "disabled": True},
            )

        query = str(arguments.get("query", "")).strip().lower()
        if not query:
            return ToolResult("缺少 query 参数。", success=False)

        try:
            result = await self.memory_runtime.query(
                MemoryQuery(
                    query=query,
                    limit=min(20, max(1, int(arguments.get("limit", 5)))),
                    item_types=tuple(
                        arguments.get("types") or ("card", "claim", "episode")
                    ),
                    scope=MemoryScope(
                        str(arguments.get("scope_kind") or "user"),
                        str(arguments.get("scope_id") or "default"),
                    ),
                    statuses=tuple(
                        arguments.get("statuses") or ("active", "approved", "frozen")
                    ),
                    max_sensitivity=str(arguments.get("max_sensitivity") or "private"),
                    at_time=(
                        datetime.fromisoformat(str(arguments["at_time"]))
                        if arguments.get("at_time")
                        else None
                    ),
                    retrieval_mode=str(arguments.get("retrieval_mode") or "auto"),  # type: ignore[arg-type]
                    detail_level=str(arguments.get("detail_level") or "summary"),  # type: ignore[arg-type]
                    statement_ids=tuple(arguments.get("statement_ids") or ()),
                    card_statement_limit=int(arguments.get("card_statement_limit", 6)),
                    claim_expansion_limit=int(
                        arguments.get("claim_expansion_limit", 6)
                    ),
                    evidence_expansion_limit=int(
                        arguments.get("evidence_expansion_limit", 3)
                    ),
                )
            )
        except Exception as exc:
            raw = json.dumps(
                {"status": "degraded", "hits": [], "reason": type(exc).__name__},
                ensure_ascii=False,
            )
            return ToolResult(
                raw,
                success=False,
                raw_content=raw,
                status="degraded",
                metadata={"tool": self.name, "degraded": True},
            )
        if not result.items:
            return ToolResult("没有找到相关长期记忆。", metadata={"tool": self.name})

        hits = [
            {
                "id": item.item_id,
                "type": item.item_type,
                "content": item.content,
                "status": item.status,
                "current": item.current,
                "reason": item.recall_reason,
                "evidence": [
                    {"kind": ref.kind, "ref_id": ref.ref_id} for ref in item.evidence
                ],
                "card_id": item.metadata.get("card_id"),
                "version_id": item.metadata.get("version_id"),
                "claim_ids": item.metadata.get("claim_ids", ()),
            }
            for item in result.items
        ]
        content = json.dumps(
            {
                "status": "degraded" if result.degraded else "success",
                "hits": hits,
                "candidate_count": result.candidate_count,
                "filtered_count": result.filtered_count,
                "reason": result.reason,
                "requested_route": result.requested_route,
                "actual_route": result.actual_route,
                "detail_level": result.detail_level,
                "degraded_reasons": result.degraded_reasons,
            },
            ensure_ascii=False,
        )
        return ToolResult(
            content=content,
            raw_content=content,
            metadata={
                "tool": self.name,
                "match_count": len(result.items),
                "degraded": result.degraded,
            },
        )


@dataclass(slots=True)
class MemoryManageTool:
    """带显式证据校验的个人记忆治理入口。"""

    memory_runtime: MemoryRuntime | None
    name: str = "memory_manage"
    description: str = (
        "个人记忆治理入口。remember/correct 是在线证据层：content 必须与当前用户"
        "消息中逐字 basis_quote 一致（可去“请记住/记住/remember”指令包装），禁止改写"
        "人称、加注或润色；归纳、抽象、消歧与冲突合并属离线整理层，不由本工具完成。"
        "单条显式用户陈述即可作为证据写入，是否沉淀为稳定语义记忆由离线整理层决定。"
        "另支持冻结、删除、列出、导出、候选治理与离线整理请求操作。"
    )
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "remember",
                        "correct",
                        "freeze",
                        "forget",
                        "list",
                        "show",
                        "approve",
                        "reject",
                        "review",
                        "request_list",
                        "request_status",
                        "request_retry",
                        "request_cancel",
                        "governance_retry",
                        "export",
                    ],
                },
                "content": {"type": "string"},
                "basis_quote": {
                    "type": "string",
                    "description": (
                        "remember/correct 时的逐字依据：必须逐字复制当前用户消息中的"
                        "原话（可含“请记住/记住/remember”前缀），不得改写人称或加注；"
                        "系统据此确定性去除指令包装得到权威正文，content 须与之一致。"
                    ),
                },
                "entity_type": {
                    "type": "string",
                    "enum": ["claim", "card", "candidate"],
                },
                "entity_id": {"type": "string"},
                "expected_revision": {"type": "integer", "minimum": 0},
                "scope_kind": {"type": "string"},
                "scope_id": {"type": "string"},
                "max_sensitivity": {"type": "string"},
                "fact_type": {
                    "type": "string",
                    "enum": [
                        "preference",
                        "profile",
                        "project",
                        "goal",
                        "health",
                        "credential",
                        "relationship",
                    ],
                },
                "subject": {"type": "string"},
                "entity": {"type": "string"},
                "predicate": {"type": "string"},
                "value": {},
                "sensitivity": {
                    "type": "string",
                    "enum": ["public", "private", "sensitive"],
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        if self.memory_runtime is None:
            return ToolResult(
                json.dumps({"status": "disabled", "hits": []}, ensure_ascii=False),
                success=False,
                status="disabled",
                metadata={"tool": self.name, "disabled": True},
            )
        store = self.memory_runtime.store
        action = str(arguments.get("action") or "")
        scope = MemoryScope(
            str(arguments.get("scope_kind") or "user"),
            str(arguments.get("scope_id") or "default"),
        )
        context = current_tool_context()
        governance = self.memory_runtime.governance_service
        if not _memory_scope_authorized(scope, context):
            return ToolResult(
                "记忆操作被拒绝：scope 不属于当前用户或会话。",
                success=False,
                status="denied",
                metadata={"tool": self.name, "error": "scope-forbidden"},
            )
        if action == "list" and str(arguments.get("entity_type") or "") == "candidate":
            return _json_tool_result(
                self.name,
                {"status": "success", "candidates": governance.list_candidates(scope)},
            )
        if action == "show":
            candidate_id = str(arguments.get("entity_id") or "")
            try:
                detail = governance.show_candidate(candidate_id, scope)
            except (KeyError, PermissionError):
                return ToolResult("candidate-not-found-or-forbidden", success=False)
            return _json_tool_result(self.name, {"status": "success", **detail})
        if action in {"approve", "reject", "review"}:
            candidate_id = str(arguments.get("entity_id") or "")
            basis = str(arguments.get("basis_quote") or "").strip()
            if context is None or not basis or basis not in context.user_content:
                return ToolResult(
                    "Candidate decision requires an explicit current-user instruction.",
                    success=False,
                    status="denied",
                )
            try:
                audit = governance.decide_user(
                    candidate_id,
                    scope,
                    decision_kind=(
                        "needs-user-review" if action == "review" else action
                    ),
                    expected_revision=int(arguments.get("expected_revision", -1)),
                    actor=f"user:{context.user_message_id}",
                )
            except (KeyError, PermissionError, ValueError):
                return ToolResult("candidate-decision-failed", success=False)
            return _json_tool_result(
                self.name,
                {
                    "status": audit.outcome,
                    "decision_id": audit.decision_id,
                    "candidate_id": audit.candidate_id,
                    "actual_revision": audit.actual_revision,
                },
            )
        if action.startswith("request_"):
            request_id = str(arguments.get("entity_id") or "")
            if action == "request_list":
                requests = store.list_long_term_update_requests(scope)
                return _json_tool_result(
                    self.name,
                    {
                        "status": "success",
                        "requests": [
                            {
                                "request_id": item.request_id,
                                "state": item.state,
                                "attempts": item.attempts,
                                "last_error_type": item.last_error_type,
                            }
                            for item in requests
                        ],
                        "diagnostics": store.offline_diagnostics(),
                    },
                )
            if action == "request_status":
                request = store.get_long_term_update_request(request_id, scope)
                return _json_tool_result(
                    self.name,
                    {
                        "status": request.state if request else "not-found",
                        "request_id": request_id,
                        "attempts": request.attempts if request else 0,
                        "last_error_type": (request.last_error_type if request else ""),
                    },
                )
            basis = str(arguments.get("basis_quote") or "").strip()
            if context is None or not basis or basis not in context.user_content:
                return ToolResult(
                    "Request recovery requires an explicit current-user instruction.",
                    success=False,
                    status="denied",
                )
            changed = (
                store.retry_long_term_update_request(request_id, scope)
                if action == "request_retry"
                else store.cancel_long_term_update_request(request_id, scope)
            )
            if changed and self.memory_runtime.offline_worker is not None:
                self.memory_runtime.offline_worker.wake()
            return _json_tool_result(
                self.name,
                {
                    "status": "success" if changed else "not-changed",
                    "request_id": request_id,
                },
            )
        if action == "governance_retry":
            job_id = str(arguments.get("entity_id") or "")
            basis = str(arguments.get("basis_quote") or "").strip()
            if context is None or not basis or basis not in context.user_content:
                return ToolResult(
                    "Governance retry requires an explicit current-user instruction.",
                    success=False,
                    status="denied",
                )
            result = governance.retry_job(job_id, scope)
            if result.get("status") == "retry" and self.memory_runtime.offline_worker:
                self.memory_runtime.offline_worker.wake()
            return _json_tool_result(self.name, result)
        if action in {"remember", "correct"}:
            content = str(arguments.get("content") or "").strip()
            basis = str(arguments.get("basis_quote") or "").strip()
            if (
                context is None
                or not content
                or not basis
                or basis not in context.user_content
            ):
                return ToolResult(
                    "正式记忆写入被拒绝：缺少当前用户消息中的逐字依据。"
                    "请从当前用户消息中逐字引用原话作为 basis_quote，不得改写。",
                    success=False,
                    status="rejected",
                    metadata={"tool": self.name, "error": "missing-explicit-basis"},
                )
            authoritative = _normalize_explicit_basis(basis)
            if not authoritative or not _same_fact(content, authoritative):
                return ToolResult(
                    "正式记忆写入被拒绝：content 与当前用户逐字依据不一致。"
                    "content 必须逐字复制当前用户原话（仅可去“请记住”指令包装），"
                    "不得改写人称、加注或润色；归纳与改写属离线整理层。",
                    success=False,
                    status="rejected",
                    metadata={"tool": self.name, "error": "basis-content-mismatch"},
                )
            fact_type = str(arguments.get("fact_type") or "profile")
            try:
                sensitivity = _sensitivity_floor(
                    authoritative,
                    fact_type,
                    str(arguments.get("sensitivity") or "private"),
                )
            except ValueError as exc:
                return ToolResult(
                    f"正式记忆写入被拒绝：{exc}",
                    success=False,
                    status="rejected",
                    metadata={"tool": self.name, "error": "invalid-fact-metadata"},
                )
            start = context.user_content.find(basis)
            evidence = EvidenceRef(
                "message",
                context.user_message_id,
                basis,
                {
                    "verified": True,
                    "trace_id": context.trace_id,
                    "role": "user",
                    "content_hash": hashlib.sha256(
                        context.user_content.encode()
                    ).hexdigest(),
                    "locator": {"start": start, "end": start + len(basis)},
                    "user_message_id": context.user_message_id,
                },
            )
            mutation = MemoryMutation(
                content=authoritative,
                source="memory-manage",
                scope=scope,
                sensitivity=sensitivity,
                explicitness="explicit-user",
                evidence=(evidence,),
                subject=str(arguments.get("subject") or "general"),
                metadata={
                    "message_id": context.user_message_id,
                    "fact_type": fact_type,
                    "entity": str(arguments.get("entity") or ""),
                    "predicate": str(arguments.get("predicate") or ""),
                    "value": arguments.get("value"),
                    "verification_status": "verified",
                    "prompt_allowed": sensitivity != "sensitive",
                    "embedding_allowed": sensitivity != "sensitive",
                },
            )
            try:
                if action == "correct":
                    old_id = str(arguments.get("entity_id") or "")
                    if not old_id or "expected_revision" not in arguments:
                        raise ValueError("correction-requires-target-and-revision")
                    item = store.correct_claim(
                        old_id,
                        int(arguments["expected_revision"]),
                        mutation,
                        actor=f"user:{context.user_message_id}",
                    )
                else:
                    item = await self.memory_runtime.mutate(mutation)
            except (KeyError, PermissionError, RuntimeError, ValueError) as exc:
                return ToolResult(
                    f"正式记忆写入被拒绝：{exc}",
                    success=False,
                    status="rejected",
                    metadata={"tool": self.name, "error": type(exc).__name__},
                )
            return _json_tool_result(
                self.name,
                {
                    "status": "success",
                    "id": item.item_id,
                    "claim_id": item.item_id,
                    "action": action,
                    "current_user_message_id": context.user_message_id,
                    "basis_quote": basis,
                },
            )
        if action in {"freeze", "forget"}:
            entity_id = str(arguments.get("entity_id") or "")
            if not entity_id:
                return ToolResult("缺少 entity_id。", success=False)
            store.set_status(
                str(arguments.get("entity_type") or "claim"),
                entity_id,
                "frozen" if action == "freeze" else "deleted",
                f"user:{context.user_message_id}" if context else "human",
            )
            return _json_tool_result(self.name, {"status": "success", "id": entity_id})
        if action == "list":
            items = store.list_items(scope)
            return _json_tool_result(
                self.name,
                {"status": "success", "items": [_item_summary(item) for item in items]},
            )
        if action == "export":
            items = store.export_items(
                scope,
                max_sensitivity=str(arguments.get("max_sensitivity") or "private"),
            )
            return _json_tool_result(self.name, {"status": "success", "items": items})
        return ToolResult("不支持的 action。", success=False)


_REMEMBER_WRAPPER = re.compile(
    r"^\s*(?:请记住|记住|remember)\s*(?:[:：]\s*|\s+)", re.IGNORECASE
)
_SENSITIVE_FACT_PATTERN = re.compile(
    r"(?i)(password|passcode|api[_ -]?key|token|credential|密码|口令|密钥|"
    r"过敏|诊断|病史|疾病|用药|医疗)"
)


def _normalize_explicit_basis(basis: str) -> str:
    if "\n" in basis or "\r" in basis:
        return ""
    return _REMEMBER_WRAPPER.sub("", basis, count=1).strip()


def _same_fact(model_content: str, authoritative: str) -> bool:
    def normalized(value: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", value).strip().split())

    return bool(authoritative) and normalized(model_content) == normalized(
        authoritative
    )


def _sensitivity_floor(content: str, fact_type: str, requested: str) -> str:
    if fact_type not in {
        "preference",
        "profile",
        "project",
        "goal",
        "health",
        "credential",
        "relationship",
    }:
        raise ValueError("invalid-fact-type")
    if requested not in {"public", "private", "sensitive"}:
        raise ValueError("invalid-sensitivity")
    if fact_type in {"health", "credential"} or _SENSITIVE_FACT_PATTERN.search(content):
        return "sensitive"
    return requested


def _memory_scope_authorized(scope: MemoryScope, context: Any) -> bool:
    if scope.kind == "user":
        return scope.identifier == "default"
    if scope.kind == "session":
        return context is not None and scope.identifier == context.session_key
    return False


@dataclass(slots=True)
class SpawnSubAgentTool:
    """创建结构化 SubAgent 委派任务。"""

    subagent_manager: SubAgentManager | None
    name: str = "spawn_subagent"
    description: str = "委派一个有明确目标、验收标准和依赖关系的本地子 Agent 任务。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "instruction": {"type": "string", "description": "具体任务目标。"},
                "profile": {
                    "type": "string",
                    "enum": ["general", "research", "coding"],
                },
                "background": {"type": "boolean"},
                "parent_session_key": {
                    "type": "string",
                    "description": "兼容参数；运行时优先使用当前会话。",
                },
                "acceptance_criteria": _string_array("可验证的完成标准。"),
                "constraints": _string_array("执行边界与限制。"),
                "confirmed_facts": _string_array("父 Agent 已确认的事实。"),
                "memory_refs": _string_array("允许读取的记忆引用。"),
                "artifact_refs": _string_array("允许读取的制品引用。"),
                "dependency_ids": _string_array("必须先完成的 task_id。"),
                "side_effecting": {"type": "boolean"},
                "max_iterations": {"type": "integer", "minimum": 1},
                "max_elapsed_seconds": {"type": "number", "exclusiveMinimum": 0},
                "depth": {"type": "integer", "minimum": 1},
            },
            "required": ["instruction"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        if self.subagent_manager is None:
            return ToolResult("SubAgent 系统未启用。", success=False)
        instruction = str(arguments.get("instruction") or "").strip()
        if not instruction:
            return ToolResult("缺少 instruction 参数。", success=False)
        context = current_tool_context()
        session_key = (context.session_key if context is not None else "") or str(
            arguments.get("parent_session_key") or ""
        ).strip()
        options: dict[str, Any] = {
            key: tuple(
                str(item) for item in arguments.get(key, []) if str(item).strip()
            )
            for key in (
                "acceptance_criteria",
                "constraints",
                "confirmed_facts",
                "memory_refs",
                "artifact_refs",
                "dependency_ids",
            )
        }
        options["side_effecting"] = bool(arguments.get("side_effecting", False))
        for key in ("max_iterations", "max_elapsed_seconds", "depth"):
            if arguments.get(key) is not None:
                options[key] = arguments[key]
        profile = str(arguments.get("profile") or "").strip()
        background = bool(arguments.get("background", False))
        try:
            if background:
                task_id = self.subagent_manager.spawn_background(
                    instruction,
                    profile,
                    session_key,
                    {"tool": self.name},
                    **options,
                )
                return ToolResult(
                    f"已创建后台子 Agent 任务：{task_id}",
                    metadata={
                        "tool": self.name,
                        "task_id": task_id,
                        "background": True,
                    },
                )
            result = await self.subagent_manager.run_task(
                instruction,
                profile,
                session_key,
                {"tool": self.name},
                **options,
            )
        except (ValueError, RuntimeError) as exc:
            return ToolResult(str(exc), success=False, metadata={"tool": self.name})
        return ToolResult(
            result.content,
            success=result.success,
            metadata={
                "tool": self.name,
                "task_id": result.task_id,
                "profile": result.profile_name,
                "status": result.status,
                "trace_id": result.trace_id,
                "task_dir": str(result.task_dir),
            },
        )


@dataclass(slots=True)
class ManageSubAgentTool:
    """查询、取消、恢复 SubAgent 任务或重建兼容导出。"""

    subagent_manager: SubAgentManager | None
    name: str = "manage_subagent"
    description: str = "按当前会话管理已持久化的子 Agent 任务。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "get", "cancel", "resume", "regenerate"],
                },
                "task_id": {"type": "string"},
                "confirm_side_effects": {"type": "boolean"},
            },
            "required": ["action"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        if self.subagent_manager is None:
            return ToolResult("SubAgent 系统未启用。", success=False)
        action = str(arguments.get("action") or "").strip()
        task_id = str(arguments.get("task_id") or "").strip()
        context = current_tool_context()
        session_key = context.session_key if context is not None else ""
        try:
            if action == "list":
                payload: Any = [
                    self.subagent_manager.describe_task(task.task_id, session_key)
                    for task in self.subagent_manager.list_tasks(session_key)
                ]
            elif action == "get":
                task = self.subagent_manager.get_task(task_id, session_key)
                if task is None:
                    raise ValueError("任务不存在或不属于当前会话")
                payload = self.subagent_manager.describe_task(task.task_id, session_key)
            elif action == "cancel":
                task = await self.subagent_manager.cancel_task(
                    task_id, root_session_key=session_key
                )
                payload = self.subagent_manager.describe_task(task.task_id, session_key)
            elif action == "resume":
                task = self.subagent_manager.resume_task(
                    task_id,
                    root_session_key=session_key,
                    confirm_side_effects=bool(
                        arguments.get("confirm_side_effects", False)
                    ),
                )
                payload = self.subagent_manager.describe_task(task.task_id, session_key)
            elif action == "regenerate":
                if self.subagent_manager.get_task(task_id, session_key) is None:
                    raise ValueError("任务不存在或不属于当前会话")
                self.subagent_manager.regenerate_exports(task_id)
                payload = {"task_id": task_id, "regenerated": True}
            else:
                raise ValueError(f"不支持的 action：{action}")
        except (ValueError, RuntimeError) as exc:
            return ToolResult(str(exc), success=False, metadata={"tool": self.name})
        return ToolResult(
            json.dumps(payload, ensure_ascii=False, indent=2),
            metadata={"tool": self.name, "action": action},
        )


def _string_array(description: str) -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}, "description": description}


def _json_tool_result(tool: str, payload: dict[str, Any]) -> ToolResult:
    raw = json.dumps(payload, ensure_ascii=False)
    return ToolResult(raw, raw_content=raw, metadata={"tool": tool})


def _item_summary(item: Any) -> dict[str, Any]:
    return {
        "id": item.item_id,
        "type": item.item_type,
        "content": item.content,
        "status": item.status,
    }
