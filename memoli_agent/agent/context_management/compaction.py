"""Task-aware archive generation through an explicitly routed real model."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from memoli_agent.agent.context_management.models import ContextArchive, OutboxEvent
from memoli_agent.agent.context_management.repository import (
    ContextStateError,
    ContextStateRepository,
    _archive_from_json,
)
from memoli_agent.agent.context_management.tokens import TokenEstimator
from memoli_agent.agent.provider import ProviderError, ProviderLike, invoke_provider
from memoli_agent.agent.trajectory import (
    NewTrajectoryEvent,
    SpanKind,
    SpanProjection,
    TrajectoryError,
    TrajectoryStore,
    new_span_id,
    utc_now_iso,
)
from memoli_agent.agent.types import ChatMessage

ARCHIVE_FIELDS = (
    "goal_constraints",
    "decisions_reasons",
    "facts_evidence",
    "files_artifacts",
    "verification_status",
    "failure_paths",
    "todo_remaining",
)


class CompactionError(RuntimeError):
    error_type = "context-compaction-failed"


@dataclass(frozen=True, slots=True)
class TaskAwareCompactor:
    provider: ProviderLike
    repository: ContextStateRepository
    estimator: TokenEstimator
    archive_tokens: int
    model: str = ""

    async def compact(
        self,
        *,
        session_key: str,
        messages: list[ChatMessage],
        trace_id: str,
        parent_span_id: str,
        trajectory_store: TrajectoryStore,
        target_tokens: int = 0,
        parent_archive_refs: tuple[str, ...] = (),
        epoch: int = 0,
    ) -> ContextArchive:
        provider_name = str(getattr(self.provider, "name", ""))
        if provider_name == "echo":
            raise CompactionError("Echo cannot generate durable context archives")
        # §5.3：当前目标/约束统一为压缩预算上限，未显式传入时退回协调器配置
        archive_budget = target_tokens or self.archive_tokens
        source_refs = tuple(_message_ref(item) for item in messages)
        request = _request(
            messages,
            source_refs,
            target_tokens=archive_budget,
            parent_archive_refs=parent_archive_refs,
            epoch=epoch,
        )
        # §6.2：span_id 由 requested 打开、committed 经 outbox 原样复用关闭（投递
        # 不调 new_span_id）。generation 在事务内由 (session,epoch) 计数器分配，
        # requested 早于提交、未知 generation，故 requested 不携带 generation。
        span_id = new_span_id()
        started = utc_now_iso()
        span = SpanProjection(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            kind=SpanKind.LLM,
            name="context-compaction",
            started_at=started,
            input_data={
                "source_refs": source_refs,
                "epoch": epoch,
                "target_tokens": archive_budget,
                "parent_archive_refs": parent_archive_refs,
            },
            attributes={"provider": provider_name, "model": self.model},
        )
        try:
            await trajectory_store.record(
                NewTrajectoryEvent(
                    trace_id=trace_id,
                    span_id=span_id,
                    event_type="context_compaction_requested",
                    payload={
                        "source_refs": source_refs,
                        "epoch": epoch,
                        "target_tokens": archive_budget,
                        "parent_archive_refs": parent_archive_refs,
                    },
                    span=span,
                )
            )
            response = await invoke_provider(
                self.provider,
                request,
                model=self.model,
                max_output_tokens=self.archive_tokens,
            )
            data = _validated_archive(
                response.content, source_refs, parent_refs=parent_archive_refs
            )
            content = json.dumps(
                data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            if self.estimator.count_text(content) > archive_budget:
                raise CompactionError("compaction archive exceeds configured budget")
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            # §6.2 archive_id 含 epoch（drop generation）：epoch-scoped，跨 epoch 不
            # 碰撞，同 (session,epoch,content) 重试幂等。generation 占位 0，由
            # commit_archive 事务内分配。
            archive_id = hashlib.sha256(
                f"{session_key}:{epoch}:{content_hash}".encode()
            ).hexdigest()[:32]
            # §6.1/§6.2 传递性 source coverage 哈希：直接 archive = 自身 source_refs
            # 排序集（合并 archive §6.5 取父并集）
            coverage_hash = hashlib.sha256(
                json.dumps(sorted(set(source_refs)), ensure_ascii=False).encode()
            ).hexdigest()
            archive = ContextArchive(
                archive_id=archive_id,
                session_key=session_key,
                generation=0,
                content=content,
                content_hash=content_hash,
                source_refs=source_refs,
                token_count=self.estimator.count_text(content),
                created_at=datetime.now(UTC).isoformat(),
                epoch=epoch,
                level=1,
                parent_archive_refs=parent_archive_refs,
                coverage_hash=coverage_hash,
                schema_version=1,
                status="active",
            )
            # §6.2 outbox 行：committed 事件载体。span_projection 复用 requested
            # span_id 关闭 span；payload 由 commit_archive 事务内填入已提交 archive
            # 完整 data（含分配 generation），供 §6.6 重放自洽投递。
            completed_span = SpanProjection(
                span_id=span_id,
                trace_id=trace_id,
                parent_span_id=parent_span_id,
                kind=SpanKind.LLM,
                name="context-compaction",
                started_at=started,
                ended_at=utc_now_iso(),
                status="completed",
                output_data={"archive_id": archive_id},
                attributes={"provider": provider_name, "model": self.model},
            )
            outbox = OutboxEvent(
                outbox_id=hashlib.sha256(
                    f"committed:{archive_id}".encode()
                ).hexdigest()[:32],
                session_key=session_key,
                archive_id=archive_id,
                event_type="context_compaction_committed",
                span_id=span_id,
                trace_id=trace_id,
                parent_span_id=parent_span_id,
                span_projection=_span_to_json(completed_span),
                status="pending",
                created_at=archive.created_at,
            )
            committed, is_new = self.repository.commit_archive(
                archive, outbox=outbox
            )
            # §6.2/§6.6 提交后投递 outbox（best-effort，绝不 raise 回协调器）：
            # 已提交 context state 不因 trajectory/hook 故障回滚。
            if is_new:
                await self._deliver_committed(outbox, committed, trajectory_store)
            return committed
        except ContextStateError:
            # §6.3：并发/重试 coverage/generation 冲突——commit_archive 事务原子
            # 回滚，无孤立 archive。透传 ContextStateError（非 Provider/校验故障），
            # 交由协调器 fresh re-compile（correction 15：compacted_refs 已过时，
            # 不得复用 stale compilation）。不在此计熔断失败。
            raise
        except (
            ProviderError,
            TrajectoryError,
            CompactionError,
            ValueError,
        ) as exc:
            if isinstance(exc, CompactionError):
                raise
            raise CompactionError(type(exc).__name__) from exc

    async def merge_frontier(
        self,
        *,
        session_key: str,
        trace_id: str,
        parent_span_id: str,
        trajectory_store: TrajectoryStore,
        epoch: int,
        frontier_tokens: int,
        frontier_max_items: int,
    ) -> ContextArchive | None:
        """§6.5 最旧相邻 frontier 分层合并（best-effort frontier 缩减）。

        当活动 frontier 超 ``archive_frontier_tokens`` 或 ``max_items`` 时，取
        最旧相邻 2 个 archive 调 Provider 再次摘要为更高层 archive，原子提交
        （correction 3 顺序：supersede 父 → INSERT merged coverage/archive/outbox）。
        父节点成功前保持活动，成功后 superseded（留存审计）。Provider/校验/冲突
        失败均 best-effort 返回 None（frontier 暂超限，下轮再合并不影响正确性——
        §6.4 bounded injection 兜底；spec「原有 frontier、coverage、源 turn 与当前
        视图保持不变」+ correction 9 失败不回滚已成立 context state）。
        """
        provider_name = str(getattr(self.provider, "name", ""))
        if provider_name == "echo":
            # echo 无法生成 durable archive，亦无法合并
            return None
        frontier = self.repository.list_frontier(session_key)
        if len(frontier) < 2:
            return None
        total_tokens = sum(
            self.estimator.count_text(_archive_render(item)) for item in frontier
        )
        if len(frontier) <= frontier_max_items and total_tokens <= frontier_tokens:
            return None
        # 最旧相邻 2 个：list_frontier 按 generation 升序，前两个即最低 generation
        # 且在排序 frontier 中相邻（design line 77「最旧相邻 frontier 节点」）。
        parents = (frontier[0], frontier[1])
        merged_refs = _union_refs(parents)
        archive_budget = self.archive_tokens
        request = _merge_request(
            parents, merged_refs, target_tokens=archive_budget, epoch=epoch
        )
        span_id = new_span_id()
        started = utc_now_iso()
        span = SpanProjection(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            kind=SpanKind.LLM,
            name="context-compaction-merge",
            started_at=started,
            input_data={
                "parent_archive_refs": [p.archive_id for p in parents],
                "merged_refs": list(merged_refs),
                "epoch": epoch,
                "target_tokens": archive_budget,
            },
            attributes={"provider": provider_name, "model": self.model},
        )
        try:
            await trajectory_store.record(
                NewTrajectoryEvent(
                    trace_id=trace_id,
                    span_id=span_id,
                    event_type="context_compaction_requested",
                    payload={
                        "merge": True,
                        "parent_archive_refs": [p.archive_id for p in parents],
                        "merged_refs": list(merged_refs),
                        "epoch": epoch,
                        "target_tokens": archive_budget,
                    },
                    span=span,
                )
            )
            response = await invoke_provider(
                self.provider,
                request,
                model=self.model,
                max_output_tokens=self.archive_tokens,
            )
            # parent_refs=()：合并有意覆盖父 refs，跳过「与父归档重叠」校验；
            # source_refs 须精确等于父并集（correction 4 invariant）。
            data = _validated_archive(
                response.content, merged_refs, parent_refs=()
            )
            content = json.dumps(
                data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            if self.estimator.count_text(content) > archive_budget:
                raise CompactionError("merge archive exceeds configured budget")
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            # §6.2 archive_id 含 epoch（drop generation），epoch-scoped 重试幂等
            archive_id = hashlib.sha256(
                f"{session_key}:{epoch}:{content_hash}".encode()
            ).hexdigest()[:32]
            # §6.5 coverage_hash = 父并集排序集 sha256（correction 4）
            coverage_hash = hashlib.sha256(
                json.dumps(sorted(set(merged_refs)), ensure_ascii=False).encode()
            ).hexdigest()
            merged = ContextArchive(
                archive_id=archive_id,
                session_key=session_key,
                generation=0,
                content=content,
                content_hash=content_hash,
                source_refs=merged_refs,
                token_count=self.estimator.count_text(content),
                created_at=datetime.now(UTC).isoformat(),
                epoch=epoch,
                # §6.5 高层 archive：level = max(父 level) + 1
                level=max(p.level for p in parents) + 1,
                parent_archive_refs=tuple(p.archive_id for p in parents),
                coverage_hash=coverage_hash,
                schema_version=1,
                status="active",
            )
            completed_span = SpanProjection(
                span_id=span_id,
                trace_id=trace_id,
                parent_span_id=parent_span_id,
                kind=SpanKind.LLM,
                name="context-compaction-merge",
                started_at=started,
                ended_at=utc_now_iso(),
                status="completed",
                output_data={"archive_id": archive_id, "merge": True},
                attributes={"provider": provider_name, "model": self.model},
            )
            outbox = OutboxEvent(
                outbox_id=hashlib.sha256(
                    f"committed:{archive_id}".encode()
                ).hexdigest()[:32],
                session_key=session_key,
                archive_id=archive_id,
                event_type="context_compaction_committed",
                span_id=span_id,
                trace_id=trace_id,
                parent_span_id=parent_span_id,
                span_projection=_span_to_json(completed_span),
                status="pending",
                created_at=merged.created_at,
            )
            committed, is_new = self.repository.merge_archives(
                parents, merged, outbox=outbox
            )
            if is_new:
                await self._deliver_committed(outbox, committed, trajectory_store)
            return committed
        except (
            ContextStateError,
            ProviderError,
            TrajectoryError,
            CompactionError,
            ValueError,
        ):
            # best-effort：合并失败不回滚已提交 direct compact（若本轮已提交），
            # frontier 暂超限、下轮再合并；§6.4 bounded injection 兜底注入。
            return None

    async def _deliver_committed(
        self,
        outbox: OutboxEvent,
        committed: ContextArchive,
        trajectory_store: TrajectoryStore,
    ) -> None:
        """§6.2/§6.6 提交后投递 committed 轨迹事件（best-effort，绝不 raise）。

        context-state 事务已提交（archive/coverage/outbox 行落盘），此处投递失败
        仅标记 outbox=failed 供 §6.6 重放，不得回滚已提交 context state、不得以
        CompactionError 抛回协调器（correction 9）。committed 由 commit_archive 事务
        内分配 generation 后返回，故投递 payload 携带真实 generation。
        """

        try:
            await trajectory_store.record(
                NewTrajectoryEvent(
                    trace_id=outbox.trace_id,
                    span_id=outbox.span_id,
                    event_type=outbox.event_type,
                    payload={
                        "archive_id": committed.archive_id,
                        "generation": committed.generation,
                        "source_refs": list(committed.source_refs),
                    },
                    span=_span_projection_from_json(outbox.span_projection),
                )
            )
            self.repository.mark_outbox_delivered(
                outbox.outbox_id, delivered_at=utc_now_iso()
            )
        except Exception as exc:  # noqa: BLE001 — post-commit 失败不回滚
            try:
                self.repository.mark_outbox_failed(
                    outbox.outbox_id, error=str(exc)
                )
            except Exception:  # noqa: BLE001 — 标记失败也吞掉
                pass

    async def replay_outbox(
        self,
        *,
        session_key: str,
        trajectory_store: TrajectoryStore,
    ) -> int:
        """§6.6 重放未投递/失败的审计 outbox 事件（幂等、best-effort，不 raise）。

        context-state 事务已提交（archive/coverage/frontier/outbox 行落盘），
        此处只补投递轨迹审计事件，**不**调 commit_archive/merge_archives，故不
        触碰 archive generation 与 source coverage（spec「重放 SHALL 幂等且不得
        再次创建 archive generation 或重复 source coverage」）。同
        (trace_id, span_id, event_type) 已投递则 trajectory record 预检
        （_AUDIT_EVENT_TYPES + events_audit_dedup partial UNIQUE）幂等跳过。
        返回本次尝试重放的事件数（pending+failed）。
        """
        events = self.repository.list_pending_outbox(session_key)
        for event in events:
            try:
                committed = _archive_from_json(event.payload)
            except (ValueError, TypeError):
                # payload 非合法 archive JSON（理论不应发生：事务内写入的是
                # commit_archive/merge_archives 返回的 ContextArchive 序列化结果）→
                # 标记失败跳过，重放流程继续后续事件。
                try:
                    self.repository.mark_outbox_failed(
                        event.outbox_id, error="invalid outbox payload"
                    )
                except Exception:  # noqa: BLE001 — 标记失败也吞掉
                    pass
                continue
            await self._deliver_committed(event, committed, trajectory_store)
        return len(events)


def _request(
    messages: list[ChatMessage],
    source_refs: tuple[str, ...],
    *,
    target_tokens: int,
    parent_archive_refs: tuple[str, ...],
    epoch: int,
) -> list[ChatMessage]:
    schema = {key: [] for key in ARCHIVE_FIELDS}
    schema["source_refs"] = list(source_refs)
    return [
        ChatMessage(
            "system",
            "Return only JSON matching the supplied archive object. Preserve task "
            "goals, constraints, decision reasons, evidence, artifacts, verification, "
            "failures and remaining work. Source references must be unchanged.",
        ),
        ChatMessage(
            "user",
            json.dumps(
                {
                    "schema": schema,
                    "messages": [item.to_dict() for item in messages],
                    # §5.3：把当前目标/约束、父归档覆盖引用与 conversation epoch
                    # 一并交给压缩模型，使其在统一输入 schema 下产出任务感知 archive
                    "target_tokens": target_tokens,
                    "parent_archive_refs": list(parent_archive_refs),
                    "epoch": epoch,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        ),
    ]


def _merge_request(
    parents: tuple[ContextArchive, ...],
    merged_refs: tuple[str, ...],
    *,
    target_tokens: int,
    epoch: int,
) -> list[ChatMessage]:
    """§6.5 合并请求：把若干父 archive 的内容交给 Provider 再次摘要为单一高层
    archive。source_refs 必须原样回传父并集（correction 4 invariant，由
    ``_validated_archive`` 校验）。"""
    schema = {key: [] for key in ARCHIVE_FIELDS}
    schema["source_refs"] = list(merged_refs)
    archives_payload: list[Any] = []
    for parent in parents:
        try:
            archives_payload.append(json.loads(parent.content))
        except json.JSONDecodeError:
            # 父 content 非合法 JSON（理论不应发生）→ 仅传 source_refs 降级
            archives_payload.append({"source_refs": list(parent.source_refs)})
    return [
        ChatMessage(
            "system",
            "Return only JSON matching the supplied archive object. Consolidate "
            "the supplied archives into one higher-level archive that preserves "
            "task goals, constraints, decision reasons, evidence, artifacts, "
            "verification, failures and remaining work. Source references must be "
            "the unchanged union supplied.",
        ),
        ChatMessage(
            "user",
            json.dumps(
                {
                    "schema": schema,
                    "archives": archives_payload,
                    "target_tokens": target_tokens,
                    "epoch": epoch,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        ),
    ]


def _union_refs(parents: tuple[ContextArchive, ...]) -> tuple[str, ...]:
    """§6.5 父 source_refs 传递并集（correction 4），保序去重。"""
    return tuple(
        dict.fromkeys(ref for parent in parents for ref in parent.source_refs)
    )


def _archive_render(archive: ContextArchive) -> str:
    """§6.4/§6.5 archive 注入渲染形态（与 compiler._bounded_archive_messages
    一致），用于 frontier 聚合 token 预算计量。"""
    return (
        f'<context_archive generation="{archive.generation}">\n'
        f"{archive.content}\n</context_archive>"
    )


def _validated_archive(
    content: str,
    refs: tuple[str, ...],
    *,
    parent_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise CompactionError("compaction response is not JSON") from exc
    expected = {*ARCHIVE_FIELDS, "source_refs"}
    # §5.4 固定字段与禁止字段：键集合必须精确等于 schema，不允许额外或缺失字段
    if not isinstance(data, dict) or set(data) != expected:
        raise CompactionError("compaction response has invalid fields")
    if any(not isinstance(data[key], list) for key in expected):
        raise CompactionError("compaction archive fields must be arrays")
    # §5.4 引用集合：source_refs 必须与提交批次的 direct refs 完全一致
    if tuple(data["source_refs"]) != refs:
        raise CompactionError("compaction source references changed")
    # §5.4 覆盖无环性：新批次 source refs 不得与父归档已覆盖 refs 重叠，
    # 否则重复压缩或交叉覆盖已归档内容（spec「Archived content is encountered again」）
    if set(refs) & set(parent_refs):
        raise CompactionError("compaction batch overlaps already-covered sources")
    # §5.4 最小任务信息：archive 不得全为空数组，至少捕获一项任务信息
    if not any(data[key] for key in ARCHIVE_FIELDS):
        raise CompactionError("compaction archive carries no task information")
    return data


def _message_ref(message: ChatMessage) -> str:
    canonical = json.dumps(
        message.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "message:" + hashlib.sha256(canonical.encode()).hexdigest()[:24]


def _span_to_json(span: SpanProjection) -> str:
    """§6.2 序列化 completed SpanProjection 至 outbox 行。

    ``asdict(span)`` 把 ``kind: SpanKind``（StrEnum）解为普通字符串，故可直接
    ``json.dumps``；投递端 ``_span_projection_from_json`` 把 ``kind`` 转回
    ``SpanKind`` 再重建 dataclass，避免 StrEnum 比较退化。
    """

    return json.dumps(
        asdict(span), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _span_projection_from_json(raw: str) -> SpanProjection:
    """§6.2 从 outbox ``span_projection`` 重建 completed SpanProjection。

    复用 requested 打开的 ``span_id`` 关闭同一 span（不调 ``new_span_id``），
    故 committed 事件与 requested 共享 span。``kind`` 经 ``json.loads`` 退化为
    ``str``，这里转回 ``SpanKind`` 以匹配 dataclass 字段类型。
    """

    data = json.loads(raw) if raw else {}
    data["kind"] = SpanKind(data.get("kind", "llm"))
    return SpanProjection(**data)
