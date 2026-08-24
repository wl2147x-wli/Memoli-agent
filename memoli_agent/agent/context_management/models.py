"""上下文管理跨模块数据合同。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from memoli_agent.agent.types import ChatMessage


@dataclass(frozen=True, slots=True)
class ContextBlock:
    """结构化上下文块：kind/source/trust/priority/required 等元数据在计划阶段确定，

    正文内容不得决定块类型、required、priority 或 trust（§4.1/§4.2）。``layer`` 标注
    该块在五层 Context Plan 中的归属；``epoch``/``source_refs`` 供跨轮一致性与审计引用。
    """

    block_id: str
    kind: str
    content: str
    source: str = "runtime"
    trust: str = "data"
    priority: int = 50
    required: bool = False
    token_count: int = 0
    epoch: int = 0
    layer: str = ""
    source_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TurnEnvelope:
    """Recent Complete Turns 层的选择单位：一个完整 turn 的可见消息组。

    工具协议（assistant tool_call + 关联 tool result）成对保留，选择时以整 envelope
    为单位，不产生孤立 assistant/tool 消息（§4.3）。``kind``/``source``/``trust``/
    ``priority``/``required`` 与 ``ContextBlock`` 同语义，在计划阶段按结构化来源确定，
    不由正文 marker 推导（§4.1/§4.2）；``is_current`` 标记当前正在进行、不可裁剪的
    turn；``complete`` 表示工具协议是否成对完整。
    """

    turn_id: str
    epoch: int
    messages: tuple[ChatMessage, ...]
    source_refs: tuple[str, ...] = ()
    token_count: int = 0
    is_current: bool = False
    complete: bool = True
    kind: str = "complete-turn"
    source: str = "session"
    trust: str = "data"
    priority: int = 60
    required: bool = False


@dataclass(frozen=True, slots=True)
class LayerBudget:
    """单层预算记录：candidate/kept/omitted token 与省略原因（§4.6）。"""

    layer: str
    candidate_tokens: int = 0
    kept_tokens: int = 0
    omitted_tokens: int = 0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ContextBudget:
    context_window_tokens: int
    max_output_tokens: int
    safety_margin_tokens: int
    available_input_tokens: int
    estimated_input_tokens: int
    estimator: str
    exact: bool = False
    candidate_input_tokens: int = 0
    model_profile: str = ""

    @property
    def usage_ratio(self) -> float:
        if self.available_input_tokens <= 0:
            return 1.0
        return self.estimated_input_tokens / self.available_input_tokens

    @property
    def pre_reduction_ratio(self) -> float:
        """降载前候选 token 占可用预算的比率（soft/hard 阈值依据，§4.4）。"""

        if self.available_input_tokens <= 0:
            return 1.0
        return self.candidate_input_tokens / self.available_input_tokens


@dataclass(frozen=True, slots=True)
class ContextDiagnostic:
    action: str
    block_id: str = ""
    kind: str = ""
    source: str = ""
    reason: str = ""
    token_count: int = 0


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    session_key: str
    session_instance_id: str
    layout_version: int
    system_prompt: str
    skill_catalog: str
    tool_schemas_json: str
    system_prompt_hash: str
    skill_catalog_hash: str
    tool_schema_hash: str
    stable_prefix_hash: str
    created_at: str
    # §7.1 快照主键维度：与 session_key 共同标识一次冻结；新 epoch 取新快照，
    # 不复用旧 epoch 的失效原因/frontier/冻结动态内容（spec「Deterministic
    # stable-prefix snapshots」）。默认 0 兼容旧数据与单 epoch 用例。
    conversation_epoch: int = 0
    invalidated_reason: str = ""


@dataclass(frozen=True, slots=True)
class FrozenToolPreview:
    preview_id: str
    session_key: str
    tool_call_id: str
    tool_name: str
    content_hash: str
    original_chars: int
    visible_chars: int
    preview: str
    payload_ref: str
    # §7.3 绑定 epoch 与 canonical tool message hash：恢复期据此校验模型所见
    # 预览与首次提交版本一致（epoch + tool_call_id + canonical hash + payload_ref）。
    # preview_id 也含 epoch，故新 epoch 取新预览、不复用旧 epoch 派生索引（§7.1）。
    # 默认 0/"" 兼容旧数据与未显式传 epoch 的冻结；canonical hash 为空时校验跳过
    # 该项（旧预览无法验证 canonical，仍校验 epoch/tool_call_id/payload_ref）。
    epoch: int = 0
    canonical_message_hash: str = ""
    transformed: bool = True
    created_at: str = ""


@dataclass(frozen=True, slots=True)
class CompactionPlan:
    """压缩协调器的无副作用规划输出（§5.1/§5.2）。

    ``mode`` 取 normal/soft/hard/emergency；``batch`` 为最旧未覆盖完整 turn 的消息组，
    供异步协调器执行任务感知压缩；``target_tokens``/``parent_archive_refs`` 为执行
    约束与父归档引用。plan 阶段不提交 archive、不删除或标记源 turn 已覆盖，仅把降载
    决定交给协调器；``reason`` 与 ``mode`` 一致，供诊断区分触发原因。
    """

    mode: str = "normal"
    batch: tuple[ChatMessage, ...] = ()
    target_tokens: int = 0
    parent_archive_refs: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ContextArchive:
    archive_id: str
    session_key: str
    generation: int
    content: str
    content_hash: str
    source_refs: tuple[str, ...] = ()
    token_count: int = 0
    created_at: str = ""
    epoch: int = 0
    # §6.1 不可变 archive 元数据：分层 level（直接 archive=1，合并=max(parents)+1）、
    # 父归档引用（合并时填，直接 archive 为空）、传递性 source coverage 哈希、
    # archive 自身 schema 版本、活动状态（active=frontier 节点 / superseded=被
    # 合并取代后留存审计，design §5 line 75/104「保留原始 source coverage」）。
    level: int = 1
    parent_archive_refs: tuple[str, ...] = ()
    coverage_hash: str = ""
    schema_version: int = 1
    status: str = "active"


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    """§6.2/§6.6 context audit outbox 行：压缩提交后异步投递的轨迹事件载体。

    与 archive/coverage 在同一 context-state 事务内写入，故 trajectory/hook 投递
    失败不回滚已提交 context state（§6.6）。``payload`` 由 ``commit_archive`` 事务
    内填入已提交 archive 的完整 data JSON（含事务内分配的 generation），投递时由
    协调器解析为窄轨迹 payload；``span_projection`` 为 completed SpanProjection 的
    JSON，投递时复用其 ``span_id``（不调 ``new_span_id``）以关闭 requested 打开的
    span。``UNIQUE(archive_id, event_type)`` 保证重试幂等（同 committed
    事件不重复入队）。
    """

    outbox_id: str
    session_key: str
    archive_id: str
    event_type: str
    span_id: str
    trace_id: str
    parent_span_id: str = ""
    payload: str = ""
    span_projection: str = "{}"
    status: str = "pending"
    attempts: int = 0
    last_error: str = ""
    created_at: str = ""
    delivered_at: str = ""


@dataclass(frozen=True, slots=True)
class ContextCompilation:
    messages: tuple[ChatMessage, ...]
    tools: tuple[dict[str, Any], ...]
    blocks: tuple[ContextBlock, ...]
    budget: ContextBudget
    diagnostics: tuple[ContextDiagnostic, ...]
    layout_version: int
    stable_prefix_hash: str
    tool_schema_hash: str
    context_hash: str
    layers: tuple[LayerBudget, ...] = ()
    archive_generation: int = 0
    working_state_revision: int = 0
    emergency_compacted: bool = False
    compaction_plan: CompactionPlan | None = None

    def metadata(self) -> dict[str, Any]:
        cached = [item for item in self.diagnostics if item.action == "cached"]
        return {
            "layout_version": self.layout_version,
            "stable_prefix_hash": self.stable_prefix_hash,
            "tool_schema_hash": self.tool_schema_hash,
            "context_hash": self.context_hash,
            "archive_generation": self.archive_generation,
            "estimated_input_tokens": self.budget.estimated_input_tokens,
            "available_input_tokens": self.budget.available_input_tokens,
            "candidate_input_tokens": self.budget.candidate_input_tokens,
            "pre_reduction_ratio": self.budget.pre_reduction_ratio,
            "token_estimator": self.budget.estimator,
            "token_estimate_exact": self.budget.exact,
            "model_profile": self.budget.model_profile,
            "context_usage_ratio": self.budget.usage_ratio,
            "compaction_plan": (
                {
                    "mode": self.compaction_plan.mode,
                    "batch_size": len(self.compaction_plan.batch),
                    "target_tokens": self.compaction_plan.target_tokens,
                    "parent_archive_refs": list(
                        self.compaction_plan.parent_archive_refs
                    ),
                    "reason": self.compaction_plan.reason,
                }
                if self.compaction_plan is not None
                else None
            ),
            "layers": [
                {
                    "layer": item.layer,
                    "candidate_tokens": item.candidate_tokens,
                    "kept_tokens": item.kept_tokens,
                    "omitted_tokens": item.omitted_tokens,
                    "reason": item.reason,
                }
                for item in self.layers
            ],
            "diagnostics": [
                {
                    "action": item.action,
                    "block_id": item.block_id,
                    "kind": item.kind,
                    "source": item.source,
                    "reason": item.reason,
                    "token_count": item.token_count,
                }
                for item in self.diagnostics
            ],
            "cached_blocks": len(cached),
        }


def normalized_cache_usage(usage: dict[str, Any]) -> dict[str, float | int]:
    """Expose cache metrics only when providers actually report them."""

    result: dict[str, float | int] = {}
    for key in (
        "input_tokens",
        "cached_input_tokens",
        "cache_creation_input_tokens",
    ):
        value = usage.get(key)
        if isinstance(value, int | float):
            result[key] = value
    input_tokens = result.get("input_tokens")
    cached_tokens = result.get("cached_input_tokens")
    if (
        isinstance(input_tokens, int | float)
        and input_tokens > 0
        and isinstance(cached_tokens, int | float)
    ):
        result["cache_hit_ratio"] = cached_tokens / input_tokens
    return result
