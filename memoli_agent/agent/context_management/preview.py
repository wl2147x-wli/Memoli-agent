"""Frozen, bounded tool-result previews with governed payload references."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from memoli_agent.agent.context_management.models import FrozenToolPreview
from memoli_agent.agent.context_management.repository import ContextStateRepository
from memoli_agent.agent.context_management.tokens import TokenEstimator


@dataclass(frozen=True, slots=True)
class ToolResultPreviewer:
    repository: ContextStateRepository
    estimator: TokenEstimator
    preview_tokens: int

    def freeze(
        self,
        *,
        session_key: str,
        tool_call_id: str,
        tool_name: str,
        content: object,
        payload_ref: str,
        epoch: int = 0,
    ) -> FrozenToolPreview:
        serialized, transformed = _serialize(content)
        content_hash = hashlib.sha256(serialized.encode()).hexdigest()
        # §7.3 preview_id 绑定 epoch：新 epoch 重新冻结取新 preview_id（不复用
        # 旧 epoch 派生预览），与 §7.1 snapshot 跨 epoch 隔离一致。
        preview_id = hashlib.sha256(
            f"{session_key}:{epoch}:{tool_call_id}:{content_hash}".encode()
        ).hexdigest()[:32]
        existing = self.repository.get_preview(preview_id)
        if existing is not None:
            return existing
        visible = _bounded(serialized, self.estimator, self.preview_tokens)
        envelope = {
            "tool": tool_name,
            "content_hash": content_hash,
            "original_chars": len(serialized),
            "transformed": transformed or visible != serialized,
            "payload_ref": payload_ref,
            "preview": visible,
        }
        rendered = json.dumps(envelope, ensure_ascii=False, sort_keys=True)
        # §7.3 canonical tool message hash：对模型将见的 tool 消息体计算稳定指纹，
        # 与 cross_turn._visible_content_hash 同构（sha256 over canonical JSON、
        # "msg:" 前缀）。body 形状与 ChatMessage.to_dict 对 tool 消息输出一致
        # （role/content/tool_call_id/name，tool_calls 为 None 时省略）。恢复期
        # 与 committed message content_hash 比对以验证预览未被篡改/漂移。
        canonical_message_hash = _canonical_tool_message_hash(
            tool_call_id, tool_name, rendered
        )
        preview = FrozenToolPreview(
            preview_id=preview_id,
            session_key=session_key,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            content_hash=content_hash,
            original_chars=len(serialized),
            visible_chars=len(visible),
            preview=rendered,
            payload_ref=payload_ref,
            epoch=epoch,
            canonical_message_hash=canonical_message_hash,
            transformed=bool(envelope["transformed"]),
            created_at=datetime.now(UTC).isoformat(),
        )
        self.repository.save_preview(preview)
        return preview


def _canonical_tool_message_hash(
    tool_call_id: str, tool_name: str, content: str
) -> str:
    """§7.3 对模型所见的 tool 消息体计算 canonical 指纹。

    与 ``cross_turn._visible_content_hash`` 同构（sha256 over canonical JSON、
    ``"msg:"`` 前缀）。body 形状与 ``ChatMessage.to_dict`` 对 tool 消息输出一致
    （role/content/tool_call_id/name，tool_calls 为 None 时省略），故可与
    committed message 的 ``content_hash`` 直接比对以验证预览一致性。
    """

    body = {
        "role": "tool",
        "content": content,
        "tool_call_id": tool_call_id,
        "name": tool_name,
    }
    canonical = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "msg:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _serialize(content: object) -> tuple[str, bool]:
    if isinstance(content, str):
        return content, False
    if isinstance(content, bytes):
        digest = hashlib.sha256(content).hexdigest()
        return (
            f"<binary bytes={len(content)} sha256={digest}>",
            True,
        )
    try:
        return json.dumps(content, ensure_ascii=False, sort_keys=True), True
    except (TypeError, ValueError):
        return f"<{type(content).__name__}: non-serializable>", True


def _bounded(text: str, estimator: TokenEstimator, limit: int) -> str:
    if estimator.count_text(text) <= limit:
        return text
    low, high = 0, len(text)
    while low < high:
        midpoint = (low + high + 1) // 2
        if estimator.count_text(text[:midpoint]) <= limit:
            low = midpoint
        else:
            high = midpoint - 1
    return text[:low] + "\n[truncated; use payload_ref through an authorized tool]"
