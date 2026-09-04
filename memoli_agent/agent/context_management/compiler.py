"""缓存感知的五层上下文编译器，紧邻 Provider 调用前生成模型可见上下文。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from memoli_agent.agent.context_management.models import (
    CompactionPlan,
    ContextArchive,
    ContextBlock,
    ContextBudget,
    ContextCompilation,
    ContextDiagnostic,
    ContextSnapshot,
    LayerBudget,
    normalized_cache_usage,
)
from memoli_agent.agent.context_management.repository import (
    ContextStateError,
    ContextStateRepository,
)
from memoli_agent.agent.context_management.tokens import TokenEstimator
from memoli_agent.agent.types import ChatMessage

LAYOUT_VERSION = 1

# 五层 Context Plan 的稳定顺序与标识（§4.3）。
_LAYER_ORDER: tuple[str, ...] = (
    "stable-prefix",
    "archive-frontier",
    "recent-turns",
    "frozen-tool-evidence",
    "governed-dynamic",
)


class ContextBudgetExhausted(RuntimeError):
    error_type = "context-budget-exhausted"


class ContextCompactionCircuitOpen(RuntimeError):
    error_type = "context-compaction-circuit-open"


class ContextSnapshotInvalidated(RuntimeError):
    """§7.2 安全撤销 fail-closed：snapshot 因能力撤销失效，编译拒绝使用其冻结
    schema（仍含已撤销能力）向模型暴露。恢复需新 epoch 重新冻结当前 schema。"""

    error_type = "context-snapshot-invalidated"


@dataclass(frozen=True, slots=True)
class ContextCompilerSettings:
    context_window_tokens: int
    max_output_tokens: int
    safety_margin_tokens: int
    soft_threshold_ratio: float = 0.75
    hard_threshold_ratio: float = 0.90
    recent_tail_tokens: int = 12_000
    archive_tokens: int = 4_000
    # §6.4 有界 archive frontier：archive_frontier_tokens 为跨所有注入 archive 的
    # 聚合 token 预算（区别于 per-archive archive_tokens）；archive_frontier_max_items
    # 为注入活动 frontier 节点数上限。超预算时按 level DESC/created_at DESC 取子集，
    # 最旧最低层 archive 不注入（coverage 仍生效，永久缩减由 §6.5 合并）。
    archive_frontier_tokens: int = 16_000
    archive_frontier_max_items: int = 8
    # §8.1 单次压缩批次 token 上限：批次累计达此值即停止扩充（design line 77）。
    compaction_batch_tokens: int = 32_000
    plugin_max_tokens: int = 2_000
    compaction_enabled: bool = True
    compaction_failure_limit: int = 2
    emergency_retry_limit: int = 1
    model_profile: str = ""


class ContextCompiler:
    """冻结稳定输入并产出单一不可变请求/审计表示。"""

    def __init__(
        self,
        repository: ContextStateRepository,
        estimator: TokenEstimator,
        settings: ContextCompilerSettings,
    ) -> None:
        self.repository = repository
        self.estimator = estimator
        self.settings = settings
        self._last: dict[str, ContextCompilation] = {}
        self._cache_usage: dict[str, dict[str, float | int]] = {}

    def compile(
        self,
        *,
        session_key: str,
        session_instance_id: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        working_state_revision: int = 0,
        emergency: bool = False,
        epoch: int = 0,
        compacted_this_turn: bool = False,
        revoked_tool_names: frozenset[str] = frozenset(),
        capability_revision: int | None = None,
    ) -> ContextCompilation:
        if not messages or messages[0].role != "system":
            raise ContextBudgetExhausted("required system prompt is missing")
        failures = self.repository.get_compaction_failures(session_key)
        if emergency and failures >= self.settings.compaction_failure_limit:
            raise ContextCompactionCircuitOpen(
                "context compaction circuit is open for this session"
            )
        snapshot, capability_diagnostics = self._snapshot(
            session_key,
            epoch,
            session_instance_id,
            messages,
            tools or [],
            capability_revision,
        )
        disclosures = self.repository.list_tool_disclosures(
            session_key, epoch, snapshot.capability_revision
        )
        disclosed_tools: list[dict[str, Any]] = []
        disclosed_names: set[str] = set()
        for disclosure in disclosures:
            if _hash(disclosure.schema_json) != disclosure.schema_hash:
                self.repository.invalidate_snapshot(
                    session_key,
                    f"tool-disclosure-corrupt:{disclosure.tool_name}",
                    epoch=epoch,
                    revision=snapshot.capability_revision,
                )
                raise ContextSnapshotInvalidated(
                    f"tool-disclosure-corrupt:{disclosure.tool_name}"
                )
            schema = json.loads(disclosure.schema_json)
            name = _tool_schema_name(schema)
            if not name or name != disclosure.tool_name or name in disclosed_names:
                self.repository.invalidate_snapshot(
                    session_key,
                    f"tool-disclosure-invalid:{disclosure.tool_name}",
                    epoch=epoch,
                    revision=snapshot.capability_revision,
                )
                raise ContextSnapshotInvalidated(
                    f"tool-disclosure-invalid:{disclosure.tool_name}"
                )
            disclosed_names.add(name)
            disclosed_tools.append(schema)
        self._mark_revoked_tools(snapshot, revoked_tool_names, disclosed_names)
        snapshot = (
            self.repository.get_snapshot(
                session_key, epoch, snapshot.capability_revision
            )
            or snapshot
        )
        # §7.2 安全撤销 fail-closed：snapshot 因能力撤销失效时，其冻结 schema 仍
        # 含已撤销能力；编译立即拒绝向模型暴露该能力（不静默替换为其他版本），
        # 仅留 audit 失效原因。恢复需新 epoch 重新冻结当前（不含撤销能力）schema。
        if snapshot.invalidated_reason:
            raise ContextSnapshotInvalidated(snapshot.invalidated_reason)
        base_tools = list(json.loads(snapshot.tool_schemas_json))
        base_names = _tool_names(base_tools)
        if base_names & disclosed_names:
            raise ContextSnapshotInvalidated("tool-disclosure-overlaps-base")
        effective_tools = tuple([*base_tools, *disclosed_tools])
        effective_tools_json = json.dumps(
            effective_tools,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        effective_tool_hash = _hash(effective_tools_json)
        diagnostics: list[ContextDiagnostic] = list(capability_diagnostics)
        diagnostics.extend(
            ContextDiagnostic(
                "tool-disclosed",
                block_id=item.tool_name,
                kind="tool-schema",
                source="tool-search",
                reason=f"epoch:{epoch}",
            )
            for item in disclosures
        )
        # §4.2 结构化来源分类：仅 system 角色按注入来源分桶；user/tool/assistant
        # 一律进 trajectory，正文 marker 不再重排、改写角色或提升信任。
        plugins, dynamic, trajectory = self._partition(messages[1:], diagnostics)
        trajectory = _remove_deterministic_noise(
            trajectory, self.estimator, diagnostics
        )
        archives = self.repository.list_frontier(session_key)
        compacted_refs = {
            source_ref for archive in archives for source_ref in archive.source_refs
        }
        archive_messages = self._bounded_archive_messages(archives, diagnostics)
        stable = [ChatMessage(role="system", content=snapshot.system_prompt)]
        if snapshot.skill_catalog:
            stable.append(ChatMessage(role="system", content=snapshot.skill_catalog))
        plugin_messages = self._bounded_plugins(plugins, diagnostics)
        # §5 已被现有 archive 完整覆盖的 turn 不再注入模型可见原文（spec
        # 「Archived content is encountered again」），改由非重叠 frontier archive
        # 替代；按完整 turn 整组排除，避免部分覆盖拆散 tool 协议。
        trajectory = self._drop_covered_groups(
            trajectory, compacted_refs, diagnostics
        )
        all_trajectory = trajectory
        # §4.3 完整 committed turn / tool pair 为选择单位，不逐条弹出孤立协议。
        trajectory = _complete_suffix(
            all_trajectory, self.estimator, self.settings.recent_tail_tokens
        )
        candidate = [
            *stable,
            *plugin_messages,
            *archive_messages,
            *trajectory,
            *dynamic,
        ]
        # §4.4 降载前候选 token（含全部 turn）与降载后请求 token 分开记录；
        # messages、tools 与协议开销纳入同一 count_request 预算。
        full_candidate = [
            *stable,
            *plugin_messages,
            *archive_messages,
            *all_trajectory,
            *dynamic,
        ]
        candidate_tokens = self.estimator.count_request(full_candidate, effective_tools)
        available = (
            self.settings.context_window_tokens
            - self.settings.max_output_tokens
            - self.settings.safety_margin_tokens
        )
        # §4.5 required 最小集：稳定前缀 + 当前 turn + 最小最新状态；
        # memory/plugin 不再因 system role 进入最小集而不可裁剪。
        minimum = [
            *stable,
            *_required_current_group(trajectory),
            *_minimal_latest_state(dynamic),
        ]
        if self.estimator.count_request(minimum, effective_tools) > available:
            raise ContextBudgetExhausted(
                "minimum required context exceeds model budget"
            )
        estimated = self.estimator.count_request(candidate, effective_tools)
        threshold = self.settings.hard_threshold_ratio if emergency else 1.0
        target = max(1, int(available * threshold))
        while estimated > target and len(trajectory) > len(
            _required_current_group(trajectory)
        ):
            group, trajectory = _pop_oldest_group(trajectory)
            candidate = [
                *stable,
                *plugin_messages,
                *archive_messages,
                *trajectory,
                *dynamic,
            ]
            estimated = self.estimator.count_request(candidate, effective_tools)
            diagnostics.append(
                ContextDiagnostic(
                    "trimmed",
                    kind="trajectory",
                    source="session",
                    reason="global-token-budget",
                    token_count=sum(
                        self.estimator.count_text(item.content) for item in group
                    ),
                )
            )
        # §4.6 governed dynamic 降载：trajectory 已到当前轮仍超目标时，按优先级
        # 省略非 required 的 memory/plugin，保留最新 working-state。
        if estimated > target:
            dynamic = _shed_governed_dynamic(
                dynamic, self.estimator, diagnostics
            )
            candidate = [
                *stable,
                *plugin_messages,
                *archive_messages,
                *trajectory,
                *dynamic,
            ]
            estimated = self.estimator.count_request(candidate, effective_tools)
        usage_ratio = estimated / max(1, available)
        # §5.1/§5.2 plan 阶段：按降载前候选比率判定 normal/soft/hard/emergency；
        # §5.5 删除同步机械 _archive——compile 不再提交 archive、不再按角色塞 JSON，
        # 仅把最旧未覆盖完整 turn 交给异步协调器执行任务感知压缩，重编译在提交后进行。
        pre_ratio = candidate_tokens / max(1, available)
        if emergency:
            plan_mode = "emergency"
        elif pre_ratio >= self.settings.hard_threshold_ratio:
            plan_mode = "hard"
        elif (
            pre_ratio >= self.settings.soft_threshold_ratio
            or usage_ratio >= self.settings.soft_threshold_ratio
        ):
            plan_mode = "soft"
        else:
            plan_mode = "normal"
        # §5.2 主动选最旧未覆盖完整 turn 作为压缩批次（不含当前 turn），投影压缩
        # 后候选 token 降到对应阈值以下即停；soft/emergency 降到 soft 阈值、
        # hard 降到 hard 阈值。投影模型为「批次折叠为单份 archive_tokens archive」。
        # §5.6 loop-guard：本轮已成功压缩则不再规划新批次，把后续压缩推迟到下一轮，
        # 避免单轮内反复调用压缩 Provider。
        batch = (
            self._select_compaction_batch(
                all_trajectory, plan_mode, candidate_tokens, available
            )
            if not compacted_this_turn
            else ()
        )
        compaction_plan: CompactionPlan | None = None
        if self.settings.compaction_enabled and plan_mode != "normal" and batch:
            compaction_plan = CompactionPlan(
                mode=plan_mode,
                batch=tuple(batch),
                target_tokens=self.settings.archive_tokens,
                parent_archive_refs=tuple(sorted(compacted_refs)),
                reason=plan_mode,
            )
            diagnostics.append(
                ContextDiagnostic(
                    "compaction-planned",
                    kind="archive",
                    source="context-state",
                    reason=plan_mode,
                    token_count=sum(
                        self.estimator.count_text(item.content) for item in batch
                    ),
                )
            )
        if estimated > available:
            raise ContextBudgetExhausted("compiled context exceeds model budget")
        blocks = tuple(self._blocks(candidate, epoch=epoch))
        layers = self._layer_budgets(full_candidate, candidate)
        context_hash = _hash(
            json.dumps(
                [message.to_dict() for message in candidate],
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        compilation = ContextCompilation(
            messages=tuple(candidate),
            tools=effective_tools,
            blocks=blocks,
            budget=ContextBudget(
                self.settings.context_window_tokens,
                self.settings.max_output_tokens,
                self.settings.safety_margin_tokens,
                available,
                estimated,
                self.estimator.name,
                self.estimator.exact,
                candidate_input_tokens=candidate_tokens,
                model_profile=self.settings.model_profile,
            ),
            diagnostics=tuple(diagnostics),
            layout_version=LAYOUT_VERSION,
            stable_prefix_hash=snapshot.stable_prefix_hash,
            tool_schema_hash=effective_tool_hash,
            context_hash=context_hash,
            capability_revision=snapshot.capability_revision,
            layers=layers,
            archive_generation=archives[-1].generation if archives else 0,
            working_state_revision=working_state_revision,
            emergency_compacted=emergency,
            compaction_plan=compaction_plan,
        )
        self.repository.save_diagnostics(session_key, compilation.diagnostics)
        self._last[session_key] = compilation
        return compilation

    def _mark_revoked_tools(
        self,
        snapshot: ContextSnapshot,
        revoked_tool_names: frozenset[str],
        disclosed_tool_names: set[str] | None = None,
    ) -> None:
        # §7.2 安全撤销 fail-closed：仅显式安全撤销（frozen ∩ revoked）使 snapshot
        # 失效。普通工具集变更（增删/重排）属非安全性变更，不失效、不 fail-closed，
        # 已冻结前缀保持稳定、仅影响后续新 epoch（spec「Runtime state changes
        # during an epoch」「Capability is revoked for safety」）。
        frozen_names = _tool_names(json.loads(snapshot.tool_schemas_json))
        visible_names = frozen_names | (disclosed_tool_names or set())
        revoked = sorted(visible_names & revoked_tool_names)
        if revoked and not snapshot.invalidated_reason:
            self.repository.invalidate_snapshot(
                snapshot.session_key,
                "tool-revoked:" + ",".join(revoked),
                epoch=snapshot.conversation_epoch,
                revision=snapshot.capability_revision,
            )

    def latest_summary(self, session_key: str) -> dict[str, Any]:
        # §8.2 runtime 诊断视图：聚合「最近一次编译 metadata」+「仓库派生运营状态」
        # + Provider 实报 cache。§8.3 安全：metadata() 与 diagnostic_summary() 均只
        # 含哈希/计数/稳定引用/原因/模式名，不含 API key/隐藏 reasoning/embedding/
        # 未脱敏 payload（payload 原文留在 trajectory 审计层，本视图仅为派生只读面）。
        repo = self.repository.diagnostic_summary(session_key)
        cache = self._cache_usage.get(session_key, {})
        current = self._last.get(session_key)
        if current is None:
            # 未编译：仅仓库派生状态 + cache；epoch/恢复等级由 CLI handler 另取。
            return {**repo, **cache}
        summary: dict[str, object] = dict(current.metadata())
        # metadata() 未覆盖的运行期信号：emergency 标记 + 压缩模式扁平串（便于渲染）。
        summary["emergency_compacted"] = current.emergency_compacted
        summary["compaction_mode"] = (
            current.compaction_plan.mode if current.compaction_plan else "normal"
        )
        # §6.4 frontier / §5.6 熔断 / §6.6 outbox：仓库派生状态（计数 + 安全原因）。
        summary["frontier_active_count"] = repo.get("frontier_active_count", 0)
        summary["archive_level"] = repo.get("archive_level", 0)
        summary["compaction_failures"] = repo.get("compaction_failures", 0)
        summary["outbox_pending"] = repo.get("outbox_pending", 0)
        summary["outbox_failed"] = repo.get("outbox_failed", 0)
        summary["diagnostic_actions"] = repo.get("diagnostic_actions", ())
        # cache 指标最后并入，覆盖同名键（Provider 实报优先）。
        summary.update(cache)
        return summary

    def record_provider_usage(
        self, session_key: str, usage: dict[str, Any]
    ) -> dict[str, float | int]:
        normalized = normalized_cache_usage(usage)
        if normalized:
            self._cache_usage[session_key] = normalized
        return normalized

    def record_compaction_failure(self, session_key: str) -> int:
        failures = self.repository.get_compaction_failures(session_key) + 1
        self.repository.set_compaction_failures(session_key, failures)
        return failures

    def clear_compaction_failures(self, session_key: str) -> None:
        self.repository.set_compaction_failures(session_key, 0)

    def reset_session(self, session_key: str) -> None:
        self._last.pop(session_key, None)
        self._cache_usage.pop(session_key, None)
        self.repository.reset_session(session_key)

    def _snapshot(
        self,
        session_key: str,
        epoch: int,
        session_instance_id: str,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
        capability_revision: int | None,
    ) -> tuple[ContextSnapshot, tuple[ContextDiagnostic, ...]]:
        if capability_revision is not None:
            pinned = self.repository.get_snapshot(
                session_key, epoch, capability_revision
            )
            if pinned is None:
                raise ContextStateError(
                    f"capability revision not found: {capability_revision}"
                )
            return pinned, ()
        skill = next(
            (
                item.content
                for item in messages[1:]
                if item.role == "system" and "<skill_catalog" in item.content
            ),
            "",
        )
        schemas = json.dumps(
            tools, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        system_hash, skill_hash, tool_hash = (
            _hash(messages[0].content),
            _hash(skill),
            _hash(schemas),
        )
        snapshot = ContextSnapshot(
            session_key,
            session_instance_id,
            LAYOUT_VERSION,
            messages[0].content,
            skill,
            schemas,
            system_hash,
            skill_hash,
            tool_hash,
            _hash(f"{LAYOUT_VERSION}:{system_hash}:{skill_hash}:{tool_hash}"),
            datetime.now(UTC).isoformat(),
            conversation_epoch=epoch,
        )
        previous = self.repository.get_snapshot(session_key, epoch)
        committed = self.repository.save_snapshot(snapshot)
        if (
            previous is None
            or previous.capability_revision == committed.capability_revision
        ):
            return committed, ()
        return committed, _capability_change_diagnostics(previous, committed)

    def _partition(
        self,
        messages: list[ChatMessage],
        diagnostics: list[ContextDiagnostic],
    ) -> tuple[list[ChatMessage], list[ChatMessage], list[ChatMessage]]:
        """按结构化来源分流：仅 system 角色依注入来源进 plugins/dynamic；

        user/assistant/tool 一律进 trajectory，正文 marker 不改写其角色、信任或
        required（§4.2，spec「User content resembles an internal marker」）。
        """

        plugins, dynamic, trajectory = [], [], []
        for message in messages:
            if message.role == "system":
                content = message.content
                if "<skill_catalog" in content:
                    continue  # 已在稳定前缀冻结
                if "<plugin_context" in content or "[插件上下文" in content:
                    plugins.append(message)
                    continue
                if any(
                    marker in content
                    for marker in (
                        "<memory_context",
                        "<agent_status",
                        "<working_checkpoint>",
                    )
                ):
                    dynamic.append(message)
                    continue
            trajectory.append(message)
        return plugins, dynamic, trajectory

    def _drop_covered_groups(
        self,
        trajectory: list[ChatMessage],
        compacted_refs: set[str],
        diagnostics: list[ContextDiagnostic],
    ) -> list[ChatMessage]:
        """排除已被现有 archive 完整覆盖的 turn（§5）。

        spec「Archived content is encountered again」：按完整 turn 整组判断，
        整组 source refs 全部在 compacted_refs 中才排除，避免部分覆盖拆散 tool
        协议；被排除原文记 deduplicated 诊断，改由非重叠 frontier archive 替代，
        杜绝原文与 archive 双重注入。
        """

        kept: list[ChatMessage] = []
        for group in _groups(trajectory):
            refs = {_message_ref(item) for item in group}
            if refs and refs <= compacted_refs:
                for item in group:
                    diagnostics.append(
                        ContextDiagnostic(
                            "deduplicated",
                            kind="trajectory",
                            source="session",
                            reason=f"already-compacted-by:{_message_ref(item)}",
                            token_count=self.estimator.count_text(item.content),
                        )
                    )
                continue
            kept.extend(group)
        return kept

    def _bounded_archive_messages(
        self,
        frontier: tuple[ContextArchive, ...],
        diagnostics: list[ContextDiagnostic],
    ) -> list[ChatMessage]:
        """§6.4 有界 archive frontier 注入。

        仅本轮为 Provider 选活动 frontier（``status=active``）的有界子集：按
        ``level`` 降序、``created_at`` 降序（合并层级最高/最新的优先），累加注入
        token 至 ``archive_frontier_tokens``、节点数至 ``archive_frontier_max_items``
        即停。超预算的最旧最低层 archive 不注入——其 coverage 仍由 ``compacted_refs``
        生效（design「被某 committed archive 覆盖后不再注入」），原始 turn 仍被排除，
        永久缩减由 §6.5 合并完成；DB 中 active frontier 不变。
        """
        if not frontier:
            return []
        ordered = sorted(
            frontier,
            key=lambda item: (item.level, item.created_at),
            reverse=True,
        )
        messages: list[ChatMessage] = []
        total_tokens = 0
        for item in ordered:
            if len(messages) >= self.settings.archive_frontier_max_items:
                break
            message = ChatMessage(
                role="system",
                content=f'<context_archive generation="{item.generation}">\n'
                f"{item.content}\n</context_archive>",
            )
            tokens = self.estimator.count_text(message.content)
            # 首个 archive 即使单独超聚合预算也注入（优于零摘要/优于回退原文），
            # 其余加入即超则停止——已注入的层级更高/更新，更适合本轮保留。
            frontier_tokens = self.settings.archive_frontier_tokens
            if messages and total_tokens + tokens > frontier_tokens:
                break
            messages.append(message)
            total_tokens += tokens
        if len(ordered) > len(messages):
            diagnostics.append(
                ContextDiagnostic(
                    "frontier-trimmed",
                    kind="archive",
                    source="context-state",
                    reason="archive-frontier-budget",
                    token_count=total_tokens,
                )
            )
        return messages

    def _select_compaction_batch(
        self,
        all_trajectory: list[ChatMessage],
        plan_mode: str,
        candidate_tokens: int,
        available: int,
    ) -> list[ChatMessage]:
        """选最旧未覆盖完整 turn 作为压缩批次（§5.2）。

        soft/hard/emergency 均按降载前候选比率触发，主动取最旧的完整 turn（当前
        turn 永不入选），投影压缩后候选 token 降到对应阈值之下即停止扩充。投影
        模型为「批次折叠为单份 archive_tokens 的 archive」：projected =
        candidate_tokens - batch_tokens + archive_tokens。``all_trajectory`` 应
        已由 ``_drop_covered_groups`` 排除已覆盖原文。
        """

        if plan_mode == "normal" or not all_trajectory:
            return []
        groups = _groups(all_trajectory)
        if len(groups) <= 1:
            return []  # 仅有当前 turn，无可压缩对象
        target_ratio = (
            self.settings.hard_threshold_ratio
            if plan_mode == "hard"
            else self.settings.soft_threshold_ratio
        )
        target = available * target_ratio
        batch: list[ChatMessage] = []
        batch_tokens = 0
        for group in groups[:-1]:  # 最旧优先，排除当前 turn
            batch.extend(group)
            batch_tokens += sum(
                self.estimator.count_text(item.content) for item in group
            )
            # §8.1 compaction_batch_tokens 硬上限：批次 token 达上限即停止扩充，
            # 剩余未覆盖 turn 留待下一轮分批推进（design line 77「协调器可分批推进」）。
            # 至少已纳入一个完整 turn（上面 extend），故不会返回空批——空批由
            # 上方 len(groups) <= 1 守卫保证。
            if batch_tokens >= self.settings.compaction_batch_tokens:
                break
            projected = (
                candidate_tokens - batch_tokens + self.settings.archive_tokens
            )
            if projected <= target:
                break
        return batch

    def _bounded_plugins(
        self,
        messages: list[ChatMessage],
        diagnostics: list[ContextDiagnostic],
    ) -> list[ChatMessage]:
        output, used = [], 0
        for message in messages:
            count = self.estimator.count_text(message.content)
            if used + count > self.settings.plugin_max_tokens:
                diagnostics.append(
                    ContextDiagnostic(
                        "trimmed",
                        kind="plugin",
                        source="extension",
                        reason="plugin-budget",
                        token_count=count,
                    )
                )
                continue
            output.append(message)
            used += count
        return output

    def _blocks(
        self, messages: list[ChatMessage], *, epoch: int = 0
    ) -> list[ContextBlock]:
        """按角色与计划位置产出结构化 block（§4.2/§4.5）。

        正文不决定 kind/required/trust；layer/epoch/source_refs 在计划阶段确定。
        """

        current_start = _current_turn_start(messages)
        latest_state = _latest_working_state_index(messages)
        blocks: list[ContextBlock] = []
        for index, message in enumerate(messages):
            kind = _kind(message)
            is_stable = index == 0
            required = is_stable or index >= current_start or index == latest_state
            blocks.append(
                ContextBlock(
                    block_id=f"message-{index}",
                    kind=kind,
                    content=message.content,
                    source=_source(message),
                    trust=_trust_of(kind, is_stable),
                    priority=_priority_of(kind, is_stable, required),
                    required=required,
                    token_count=self.estimator.count_text(message.content),
                    epoch=epoch,
                    layer=_layer_of(kind),
                    source_refs=(_message_ref(message),),
                )
            )
        return blocks

    def _layer_token_map(
        self, messages: list[ChatMessage]
    ) -> dict[str, int]:
        """按层聚合正文 token（candidate/kept/omitted 计算用，§4.6）。"""

        result: dict[str, int] = {}
        for message in messages:
            layer = _layer_of(_kind(message))
            result[layer] = (
                result.get(layer, 0) + self.estimator.count_text(message.content)
            )
        return result

    def _layer_budgets(
        self,
        full_candidate: list[ChatMessage],
        candidate: list[ChatMessage],
    ) -> tuple[LayerBudget, ...]:
        """各层 candidate/kept/omitted token 与省略原因（§4.6）。"""

        candidate_by_layer = self._layer_token_map(full_candidate)
        kept_by_layer = self._layer_token_map(candidate)
        budgets: list[LayerBudget] = []
        for layer in _LAYER_ORDER:
            candidate_tokens = candidate_by_layer.get(layer, 0)
            kept_tokens = kept_by_layer.get(layer, 0)
            omitted_tokens = max(0, candidate_tokens - kept_tokens)
            budgets.append(
                LayerBudget(
                    layer=layer,
                    candidate_tokens=candidate_tokens,
                    kept_tokens=kept_tokens,
                    omitted_tokens=omitted_tokens,
                    reason=_layer_omission_reason(layer, omitted_tokens),
                )
            )
        return tuple(budgets)


def _complete_suffix(
    messages: list[ChatMessage], estimator: TokenEstimator, token_limit: int
) -> list[ChatMessage]:
    """以完整组为单位从尾部选择近期 turn（§4.3）。

    首部孤立协议整体丢弃，不逐条弹出拆散 tool pair。
    """

    groups = _drop_leading_orphaned_groups(_groups(list(messages)))
    selected: list[list[ChatMessage]] = []
    used = 0
    for group in reversed(groups):
        count = sum(estimator.count_text(item.content) for item in group)
        if selected and used + count > token_limit:
            break
        selected.append(group)
        used += count
    return [item for group in reversed(selected) for item in group]


def _remove_deterministic_noise(
    messages: list[ChatMessage],
    estimator: TokenEstimator,
    diagnostics: list[ContextDiagnostic],
) -> list[ChatMessage]:
    """Remove only empty or byte-identical adjacent messages without protocol data."""

    output: list[ChatMessage] = []
    for message in messages:
        removable = (
            not message.tool_calls and not message.tool_call_id and not message.blocks
        )
        if removable and not message.content.strip():
            diagnostics.append(
                ContextDiagnostic(
                    "deduplicated",
                    kind="trajectory",
                    source="session",
                    reason="provably-empty",
                    token_count=estimator.count_text(message.content),
                )
            )
            continue
        if removable and output and message == output[-1]:
            diagnostics.append(
                ContextDiagnostic(
                    "deduplicated",
                    kind="trajectory",
                    source="session",
                    reason="byte-identical-adjacent",
                    token_count=estimator.count_text(message.content),
                )
            )
            continue
        output.append(message)
    return output


def _groups(messages: list[ChatMessage]) -> list[list[ChatMessage]]:
    groups: list[list[ChatMessage]] = []
    for message in messages:
        if message.role == "user" or not groups:
            groups.append([message])
        else:
            groups[-1].append(message)
    return groups


def _drop_leading_orphaned_groups(
    groups: list[list[ChatMessage]],
) -> list[list[ChatMessage]]:
    """丢弃首部不完整的孤立组整体（§4.3）。

    不以 user/system 起始且非完整 tool pair 的组才被整体丢弃。
    """

    while groups and not _group_starts_turn(groups[0]) and not _is_complete_tool_pair(
        groups[0]
    ):
        groups.pop(0)
    return groups


def _group_starts_turn(group: list[ChatMessage]) -> bool:
    return bool(group) and group[0].role in {"user", "system"}


def _is_complete_tool_pair(group: list[ChatMessage]) -> bool:
    """组是否为 assistant tool_call + 关联 tool result 的完整协议对（§4.3）。"""

    if not group or group[0].role != "assistant" or not group[0].tool_calls:
        return False
    call_ids = {
        call.get("id")
        for call in group[0].tool_calls
        if isinstance(call, dict)
    }
    if not call_ids:
        return False
    result_ids = {
        item.tool_call_id
        for item in group[1:]
        if item.role == "tool" and item.tool_call_id
    }
    return bool(call_ids & result_ids)


def _shed_governed_dynamic(
    dynamic: list[ChatMessage],
    estimator: TokenEstimator,
    diagnostics: list[ContextDiagnostic],
) -> list[ChatMessage]:
    """超预算时按优先级省略非 required 的 memory/plugin（§4.6）。

    保留最新 working-state；system role 不使块不可裁剪。
    """

    latest_state = -1
    for index in range(len(dynamic) - 1, -1, -1):
        content = dynamic[index].content
        if "<agent_status" in content or "<working_checkpoint>" in content:
            latest_state = index
            break
    kept: list[ChatMessage] = []
    for index, message in enumerate(dynamic):
        kind = _kind(message)
        if kind in ("memory", "plugin") and index != latest_state:
            diagnostics.append(
                ContextDiagnostic(
                    "trimmed",
                    kind=kind,
                    source="governor" if kind == "memory" else "extension",
                    reason="dynamic-load-shed",
                    token_count=estimator.count_text(message.content),
                )
            )
            continue
        kept.append(message)
    return kept


def _minimal_latest_state(dynamic: list[ChatMessage]) -> list[ChatMessage]:
    """governed dynamic 中仅最新 working-state 进入 required 最小集（§4.5）。"""

    for message in reversed(dynamic):
        if (
            "<agent_status" in message.content
            or "<working_checkpoint>" in message.content
        ):
            return [message]
    return []


def _required_current_group(messages: list[ChatMessage]) -> list[ChatMessage]:
    groups = _groups(messages)
    return groups[-1] if groups else []


def _pop_oldest_group(
    messages: list[ChatMessage],
) -> tuple[list[ChatMessage], list[ChatMessage]]:
    groups = _groups(messages)
    if len(groups) <= 1:
        return [], messages
    return groups[0], [item for group in groups[1:] for item in group]


def _current_turn_start(messages: list[ChatMessage]) -> int:
    """最后一个 user 消息索引；其后（含自身）为不可裁剪的当前 turn（§4.5）。"""

    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role == "user":
            return index
    return len(messages)


def _latest_working_state_index(messages: list[ChatMessage]) -> int:
    """最后一个 working-state 系统消息索引（最小最新状态，§4.5）。"""

    for index in range(len(messages) - 1, -1, -1):
        content = messages[index].content
        if messages[index].role == "system" and (
            "<agent_status" in content or "<working_checkpoint>" in content
        ):
            return index
    return -1


def _kind(message: ChatMessage) -> str:
    """按角色 + system 注入来源确定 kind；user/tool 不因正文 marker 改判（§4.2）。"""

    if message.role == "system":
        content = message.content
        if "<context_archive" in content:
            return "archive"
        if "<plugin_context" in content or "[插件上下文" in content:
            return "plugin"
        if "<memory_context" in content:
            return "memory"
        if "<agent_status" in content or "<working_checkpoint>" in content:
            return "working-state"
        if "<skill_catalog" in content:
            return "skill-catalog"
        return "stable-prefix"
    if message.role == "user":
        return "user-input"
    if message.role == "tool":
        return "tool-result"
    if message.role == "assistant":
        return "tool-call" if message.tool_calls else "assistant"
    return "trajectory"


def _source(message: ChatMessage) -> str:
    if message.role == "system":
        content = message.content
        if "<context_archive" in content:
            return "context-state"
        if "<plugin_context" in content or "[插件上下文" in content:
            return "extension"
        if "<memory_context" in content:
            return "governor"
        return "runtime"
    return "session"


def _layer_of(kind: str) -> str:
    if kind in ("stable-prefix", "skill-catalog"):
        return "stable-prefix"
    if kind == "archive":
        return "archive-frontier"
    if kind in ("memory", "plugin", "working-state"):
        return "governed-dynamic"
    if kind in ("tool-call", "tool-result"):
        return "frozen-tool-evidence"
    return "recent-turns"


def _trust_of(kind: str, is_stable: bool) -> str:
    if is_stable or kind == "skill-catalog":
        return "instruction"
    return "data"


def _priority_of(kind: str, is_stable: bool, required: bool) -> int:
    if is_stable:
        return 100
    if kind == "skill-catalog":
        return 95
    if kind == "user-input":
        return 90 if required else 60
    if kind in ("tool-call", "tool-result"):
        return 70
    if kind == "plugin":
        return 40
    if kind == "working-state":
        return 35
    if kind == "memory":
        return 30
    if kind == "archive":
        return 20
    return 60


def _layer_omission_reason(layer: str, omitted_tokens: int) -> str:
    if omitted_tokens <= 0:
        return ""
    if layer == "recent-turns":
        return "recent-tail-or-budget-trim"
    if layer == "governed-dynamic":
        return "dynamic-load-shed"
    if layer == "archive-frontier":
        return "frontier-bound"
    return "priority-dropped"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _message_ref(message: ChatMessage) -> str:
    canonical = json.dumps(
        message.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return f"message:{_hash(canonical)[:24]}"


def _tool_names(tools: list[dict[str, Any]]) -> set[str]:
    return {
        str(item.get("function", {}).get("name") or "")
        for item in tools
        if isinstance(item.get("function"), dict)
    } - {""}


def _tool_schema_name(schema: object) -> str:
    if not isinstance(schema, dict):
        return ""
    function = schema.get("function")
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "")


def _capability_change_diagnostics(
    previous: ContextSnapshot, current: ContextSnapshot
) -> tuple[ContextDiagnostic, ...]:
    """生成不携带 schema 正文的名称级能力差异。"""

    before = {
        _tool_schema_name(item): _hash(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        for item in json.loads(previous.tool_schemas_json)
    }
    after = {
        _tool_schema_name(item): _hash(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        for item in json.loads(current.tool_schemas_json)
    }
    diagnostics = [
        ContextDiagnostic(
            "capability-revision-created",
            block_id=f"{previous.capability_revision}->{current.capability_revision}",
            kind="capability-snapshot",
            source="runtime",
            reason="stable-prefix-changed",
        )
    ]
    diagnostics.extend(
        ContextDiagnostic("tool-added", block_id=name, kind="tool-schema")
        for name in sorted(after.keys() - before.keys())
    )
    diagnostics.extend(
        ContextDiagnostic("tool-removed", block_id=name, kind="tool-schema")
        for name in sorted(before.keys() - after.keys())
    )
    diagnostics.extend(
        ContextDiagnostic("tool-schema-changed", block_id=name, kind="tool-schema")
        for name in sorted(before.keys() & after.keys())
        if before[name] != after[name]
    )
    for changed, name in (
        (previous.system_prompt_hash != current.system_prompt_hash, "system-prompt"),
        (previous.skill_catalog_hash != current.skill_catalog_hash, "skill-catalog"),
        (previous.layout_version != current.layout_version, "layout"),
    ):
        if changed:
            diagnostics.append(
                ContextDiagnostic(
                    "capability-component-changed",
                    block_id=name,
                    kind="stable-prefix",
                )
            )
    return tuple(diagnostics)
