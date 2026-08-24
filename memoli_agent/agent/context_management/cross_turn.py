"""跨轮规范化 turn 合同与 ContextSource（§2 conversation epoch 与 canonical turn）。

事实层（trajectory）持久化 committed 事件；本模块把事件重构为 ``CommittedTurn`` /
``CommittedMessage``，并按 capture 模式判定恢复等级。三个实现：

- ``TrajectoryContextSource``：durable 读取，跨重启可恢复（exact/governed）；
- ``InProcessTurnSource``：隔离的进程内降级来源，``restorable=false``；
- ``LegacyTurnSource``：对旧事件做 ``legacy-inferred`` 有界兼容读取。

主 Agent 被动 turn 装配 durable source；memory-governor 与普通 SubAgent 默认使用
in-process 或不装配，保持隔离（§7.5）。

canonical envelope 复用 ``ChatMessage.to_dict()``（已排除 blocks/隐藏 reasoning），
凭证脱敏与外置策略由 ``TrajectoryStore`` 的 ``_save_payload``→``_clean_value`` 在
落盘时统一处理，本模块不在记录侧重复脱敏（§2.4）。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from memoli_agent.agent.context_management.models import FrozenToolPreview
from memoli_agent.agent.trajectory import TrajectoryError, TrajectoryStore
from memoli_agent.agent.types import ChatMessage


class RestorationLevel(StrEnum):
    """跨轮 turn 恢复保真等级。"""

    EXACT = "exact"  # capture=full-local 且 payload 可读，可精确回放
    GOVERNED = "governed"  # capture=redacted，内容经脱敏治理
    LEGACY_INFERRED = "legacy-inferred"  # 旧事件推断，不保证 tool/response fidelity
    UNAVAILABLE = "unavailable"  # 轨迹关闭/metadata-only/payload 损坏，无法恢复


@dataclass(frozen=True, slots=True)
class CommittedMessage:
    """一条已提交的规范化可见消息（跨轮事实的原子单位）。"""

    turn_seq: int
    message_seq: int
    role: str
    content: str
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_calls: tuple[dict[str, Any], ...] = ()
    content_hash: str = ""
    capture_mode: str = ""
    degradation: str = ""

    def to_chat_message(self) -> ChatMessage:
        """重构为 provider 可用的 ChatMessage（保留工具协议字段）。"""

        calls = list(self.tool_calls) if self.tool_calls else None
        return ChatMessage(
            role=self.role,
            content=self.content,
            tool_call_id=self.tool_call_id,
            name=self.tool_name,
            tool_calls=calls,
        )


@dataclass(frozen=True, slots=True)
class CommittedTurn:
    """一个已终止、顺序完整的 turn（含其全部规范化消息）。"""

    epoch: int
    turn_seq: int
    trace_id: str
    status: str
    started_at: str
    ended_at: str
    messages: tuple[CommittedMessage, ...] = ()
    content_hash: str = ""
    restoration: RestorationLevel = RestorationLevel.EXACT
    degradation_reason: str = ""

    def to_messages(self) -> list[ChatMessage]:
        """按稳定序号重构 turn 的全部消息。"""

        return [message.to_chat_message() for message in self.messages]


# §6.7 单次有界读取的默认行数保护：仅 max_bytes 生效、max_turns 为空时以此
# 兜底存储侧行抓取上限，避免无界拉取。max_turns=max_bytes=None 时仍读取全部
# （保留当前行为，供压缩协调器枚举全部未覆盖 turn 推进覆盖；spec「读取上限
# SHALL 是可继续推进的 I/O 防护而不是隐式语义历史窗口」）。
_DEFAULT_READ_PAGE = 200


@dataclass(frozen=True, slots=True)
class TurnRead:
    """§6.7 单次有界读取结果。

    ``truncated`` 区分「触及 turn/byte I/O 上限尚有未读」与「确无更多历史」：
    前者 True 且 ``next_after_turn_seq`` 指向续读游标；后者 False 且游标为 None。
    压缩协调器据此分批推进覆盖——绝不把截断的未读内容标记为不存在或已归档
    （spec「Source reader reaches an I/O bound」）。
    """

    turns: tuple[CommittedTurn, ...]
    truncated: bool
    next_after_turn_seq: int | None


class ContextSource(Protocol):
    """跨轮规范化 turn 来源协议（主被动 turn 装配；SubAgent 默认不装配）。"""

    async def read_turns(
        self,
        *,
        session_key: str,
        epoch: int,
        exclude_trace_id: str | None = None,
        after_turn_seq: int | None = None,
        max_turns: int | None = None,
        max_bytes: int | None = None,
    ) -> TurnRead: ...

    async def restoration_level(
        self, session_key: str, epoch: int
    ) -> RestorationLevel: ...


@runtime_checkable
class CommittedTurnStore(Protocol):
    """Reasoner 用于判定能否记录 committed turn 的最小能力协议。

    ``NullTrajectoryStore`` 不实现这两个方法，因此 ``isinstance`` 检查天然排除
    轨迹关闭的情形（§2.6）。
    """

    async def current_epoch(self, session_id: str) -> int: ...

    async def next_turn_seq(self, session_id: str, epoch: int) -> int: ...


@runtime_checkable
class PreviewIntegrityLookup(Protocol):
    """§7.3 恢复期按 (session_key, epoch, tool_call_id) 取冻结预览的最小协议。

    ``ContextStateRepository`` 实现该方法；未装配（SubAgent/降级，§7.5）时
    ``CrossTurnContextPhase`` 传 None，跳过预览引用完整性校验、保持隔离。
    """

    def get_preview_by_ref(
        self, session_key: str, epoch: int, tool_call_id: str
    ) -> FrozenToolPreview | None: ...


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _visible_content_hash(body: dict[str, Any]) -> str:
    """对可见消息体计算稳定指纹（记录侧用原始内容，供诊断与一致性核对）。"""

    digest = hashlib.sha256(_canonical_json(body).encode("utf-8"))
    return "msg:" + digest.hexdigest()[:24]


def build_envelope(
    message: ChatMessage,
    *,
    epoch: int,
    turn_seq: int,
    message_seq: int,
    capture_mode: str = "",
    degradation: str = "",
) -> dict[str, Any]:
    """构造 canonical committed envelope（记录侧调用）。

    body 取自 ``ChatMessage.to_dict()``——已排除 blocks/隐藏 reasoning/训练评价字段；
    凭证脱敏由 trajectory 落盘时的 ``_clean_value`` 统一完成（§2.4）。
    """

    body = message.to_dict()
    return {
        "epoch": epoch,
        "turn_seq": turn_seq,
        "message_seq": message_seq,
        "role": body["role"],
        "content": body["content"],
        "tool_call_id": body.get("tool_call_id"),
        "tool_name": body.get("name"),
        "tool_calls": tuple(body.get("tool_calls") or ()),
        "content_hash": _visible_content_hash(body),
        "capture_mode": capture_mode,
        "degradation": degradation,
    }


def envelope_to_committed_message(
    envelope: dict[str, Any],
    *,
    restoration: RestorationLevel,
) -> CommittedMessage | None:
    """把存储侧 envelope 字典重构为 CommittedMessage；损坏/缺字段返回 None。"""

    try:
        role = envelope.get("role")
        content = envelope.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            return None
        raw_calls = envelope.get("tool_calls") or ()
        return CommittedMessage(
            turn_seq=int(envelope.get("turn_seq", 0)),
            message_seq=int(envelope.get("message_seq", 0)),
            role=role,
            content=content,
            tool_call_id=envelope.get("tool_call_id"),
            tool_name=envelope.get("tool_name"),
            tool_calls=tuple(raw_calls) if isinstance(raw_calls, list | tuple) else (),
            content_hash=str(envelope.get("content_hash", "")),
            capture_mode=str(envelope.get("capture_mode", "")),
            degradation=str(
                envelope.get("degradation")
                or (
                    "legacy-inferred"
                    if restoration is RestorationLevel.LEGACY_INFERRED
                    else ""
                )
            ),
        )
    except (TypeError, ValueError):
        return None


def _map_restoration(raw: str) -> RestorationLevel:
    """映射存储侧恢复等级字符串到枚举。"""

    for level in RestorationLevel:
        if level.value == raw:
            return level
    return RestorationLevel.UNAVAILABLE


def _build_committed_turn(
    raw: dict[str, Any],
    restoration: RestorationLevel,
) -> CommittedTurn | None:
    """把存储侧 turn 字典重构为 CommittedTurn；corrupt turn 返回 None（排除）。"""

    if raw.get("corrupt"):
        # 任一 committed envelope 不可读即视为 corrupt turn，整体排除（§2.5）。
        return None
    messages: list[CommittedMessage] = []
    hashes: list[str] = []
    for envelope in raw.get("messages") or []:
        if not isinstance(envelope, dict):
            continue
        message = envelope_to_committed_message(envelope, restoration=restoration)
        if message is None:
            # 单条 envelope 损坏令整 turn 不可信。
            return None
        messages.append(message)
        if message.content_hash:
            hashes.append(message.content_hash)
    if not messages:
        # 无 committed 消息（旧 trace 迁移后无 committed 事件）交给 legacy reader，
        # durable reader 不返回空消息 turn（§2.5/§2.7 边界）。
        return None
    try:
        return CommittedTurn(
            epoch=int(raw.get("epoch", 0)),
            turn_seq=int(raw.get("turn_seq", 0)),
            trace_id=str(raw.get("trace_id", "")),
            status=str(raw.get("status", "")),
            started_at=str(raw.get("started_at", "")),
            ended_at=str(raw.get("ended_at", "")),
            messages=tuple(messages),
            content_hash=hashlib.sha256(
                "|".join(hashes).encode("utf-8")
            ).hexdigest()[:24]
            if hashes
            else "",
            restoration=restoration,
            degradation_reason=str(raw.get("degradation_reason", "")),
        )
    except (TypeError, ValueError):
        return None


def _turn_byte_size(turn: CommittedTurn) -> int:
    """§6.7 单 turn 的稳定字节度量：注入形态（消息 dict 列表）的 UTF-8 长度。"""

    payload = [message.to_chat_message().to_dict() for message in turn.messages]
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _fetch_cap(max_turns: int | None, max_bytes: int | None) -> int | None:
    """§6.7 折算存储侧行抓取上限（+1 探测是否触及 turn/默认行上限）。"""

    if max_turns is not None:
        return max_turns + 1
    if max_bytes is not None:
        return _DEFAULT_READ_PAGE + 1
    return None


def _bound_turns(
    raw_turns: list[dict[str, Any]],
    *,
    builder: Callable[[dict[str, Any]], CommittedTurn | None],
    after_turn_seq: int | None,
    fetch_cap: int | None,
    max_bytes: int | None,
) -> TurnRead:
    """§6.7 对已按 (started_at, trace_id) 排序、含稳定 turn_seq 的 raw turn 字典
    施加 turn/byte 上限，产出 TurnRead。

    存储侧已按 ``fetch_cap`` 抓取（``fetch_cap = max_turns+1`` 或默认页 +1 或
    None）；``count_cap = fetch_cap - 1`` 为本轮纳入上限，多抓的 1 行仅用于探测
    「触及 turn 上限尚有未读」（``has_more_by_count``）。byte 上限在纳入侧逐 turn
    累加，超 ``max_bytes`` 即停止并置 ``byte_stopped``。二者任一为真即
    ``truncated=True``。续读游标规则：未截断时为 ``None``（游标之后确无更多
    历史，绝不与截断混淆）；截断且已纳入 turn 时取末纳入 turn 的稳定 turn_seq；
    截断但一 turn 也未纳入（首 turn 已超 max_bytes）则游标不变
    （``after_turn_seq``），信号「当前 bound 过小无法推进」。
    """

    count_cap = fetch_cap - 1 if fetch_cap is not None else None
    has_more_by_count = (
        fetch_cap is not None and len(raw_turns) > (count_cap or 0)
    )
    kept: list[CommittedTurn] = []
    used = 0
    byte_stopped = False
    for raw in raw_turns:
        if count_cap is not None and len(kept) >= count_cap:
            break  # 已达 turn 上限；多抓的探测行不计入（has_more_by_count 已置）
        turn = builder(raw)
        if turn is None:
            continue
        if max_bytes is not None and used + _turn_byte_size(turn) > max_bytes:
            byte_stopped = True
            break
        kept.append(turn)
        used += _turn_byte_size(turn)

    truncated = has_more_by_count or byte_stopped
    if not truncated:
        next_cursor = None  # 未触及上限：游标之后确无更多历史（≠截断）
    elif kept:
        next_cursor = kept[-1].turn_seq  # 截断且已纳入：续读游标指向末纳入 turn
    else:
        # 截断但一 turn 未纳入（bound 过小）：游标不变，调用方可知未推进。
        next_cursor = after_turn_seq
    return TurnRead(tuple(kept), truncated, next_cursor)


def _build_legacy_turn(
    raw: dict[str, Any], *, epoch: int
) -> CommittedTurn | None:
    """§2.7/§6.7 把存储侧 legacy-inferred turn 字典重构为 CommittedTurn。

    与 durable ``_build_committed_turn`` 对应：单条 envelope 损坏令整 turn 不可信
    （返回 None 排除）；无 committed 消息亦返回 None 交由上层判定。
    """

    if raw.get("restoration") == "unavailable":
        return None
    messages: list[CommittedMessage] = []
    hashes: list[str] = []
    for envelope in raw.get("messages") or []:
        if not isinstance(envelope, dict):
            continue
        message = envelope_to_committed_message(
            envelope, restoration=RestorationLevel.LEGACY_INFERRED
        )
        if message is None:
            return None  # 单条损坏令整 turn 不可信
        messages.append(message)
        if message.content_hash:
            hashes.append(message.content_hash)
    if not messages:
        return None
    try:
        return CommittedTurn(
            epoch=int(raw.get("epoch", epoch)),
            turn_seq=int(raw.get("turn_seq", 0)),
            trace_id=str(raw.get("trace_id", "")),
            status=str(raw.get("status", "")),
            started_at=str(raw.get("started_at", "")),
            ended_at=str(raw.get("ended_at", "")),
            messages=tuple(messages),
            content_hash=hashlib.sha256(
                "|".join(hashes).encode("utf-8")
            ).hexdigest()[:24]
            if hashes
            else "",
            restoration=RestorationLevel.LEGACY_INFERRED,
            degradation_reason="legacy-inferred",
        )
    except (TypeError, ValueError):
        return None


def verify_turn_previews(
    turn: CommittedTurn,
    *,
    session_key: str,
    preview_lookup: PreviewIntegrityLookup | None,
) -> CommittedTurn | None:
    """§7.3 恢复期引用完整性校验：对 turn 内已冻结预览的 tool-result 消息，比对
    epoch、tool_call_id、canonical message hash 与 payload_ref 与 canonical turn
    是否一致；任一不一致返回 None（排除整个受影响 turn，绝不拆散 assistant
    tool_call 与 tool result 配对、不重新生成预览，spec「Preview validation
    fails during restoration」）。

    - 无 ``preview_lookup``（SubAgent/降级来源，§7.5）→ 不校验，原样返回 turn。
    - tool-result 消息无冻结预览（小结果未超预算）→ 跳过该条（不视为不一致）。
    - 预览 ``transformed`` 为 False（小结果，模型见原始内容而非预览 envelope）→
      跳过：预览非模型所见内容的绑定锚点，无可比对的 canonical hash。
    - 预览 ``canonical_message_hash`` 为空（§7.3 之前冻结的旧预览）→ 跳过该项
      canonical 比对，仍校验 epoch/tool_call_id/payload_ref（旧数据宽松通过）。
    """

    if preview_lookup is None:
        return turn
    for message in turn.messages:
        if message.role != "tool" or not message.tool_call_id:
            continue
        preview = preview_lookup.get_preview_by_ref(
            session_key, turn.epoch, message.tool_call_id
        )
        if preview is None:
            continue  # 未冻结预览（小结果）：无可校验的绑定
        if not preview.transformed:
            # 小结果：模型见原始内容而非预览 envelope，预览非绑定锚点，跳过。
            continue
        canonical_ok = (
            not preview.canonical_message_hash
            or preview.canonical_message_hash == message.content_hash
        )
        if (
            preview.epoch != turn.epoch
            or preview.tool_call_id != message.tool_call_id
            or not canonical_ok
            or not preview.payload_ref
        ):
            # 引用不一致：排除整 turn（不拆 tool pair、不重生成预览）。
            return None
    return turn


@dataclass(slots=True)
class TrajectoryContextSource:
    """durable 跨轮 turn 来源：从 trajectory committed 事件重构完整 turn。

    跨重启可恢复；metadata-only/轨迹关闭/payload 损坏时降级为 ``unavailable`` 并
    返回空列表（§2.5/§2.6）。
    """

    store: TrajectoryStore
    capture_mode: str = ""

    def __post_init__(self) -> None:
        if not self.capture_mode:
            object.__setattr__(
                self, "capture_mode", getattr(self.store, "capture_content", "") or ""
            )

    async def restoration_level(self, session_key: str, epoch: int) -> RestorationLevel:
        # TrajectoryStore Protocol 不声明 restoration_level（仅 durable 具体存储有）；
        # getattr+None 收窄替代 hasattr，避免直接属性访问触发 pyright。
        reader = getattr(self.store, "restoration_level", None)
        if reader is None:
            return RestorationLevel.UNAVAILABLE
        try:
            raw = await reader(session_key, epoch)
        except TrajectoryError:
            return RestorationLevel.UNAVAILABLE
        return _map_restoration(str(raw))

    async def read_turns(
        self,
        *,
        session_key: str,
        epoch: int,
        exclude_trace_id: str | None = None,
        after_turn_seq: int | None = None,
        max_turns: int | None = None,
        max_bytes: int | None = None,
    ) -> TurnRead:
        """§6.7 有界读取：返回 TurnRead（turns + truncated + 续读游标）。

        跨重启可恢复；metadata-only/轨迹关闭/payload 损坏时降级为
        ``unavailable`` 并返回空 TurnRead（不截断、无续读，§2.5/§2.6）。
        """

        level = await self.restoration_level(session_key, epoch)
        if level is RestorationLevel.UNAVAILABLE:
            return TurnRead((), False, None)
        # Protocol 不声明 read_committed_turns（仅 durable 具体存储有）；
        # getattr+None 收窄替代 hasattr，避免直接属性访问触发 pyright。
        reader = getattr(self.store, "read_committed_turns", None)
        if reader is None:
            return TurnRead((), False, None)
        fetch_cap = _fetch_cap(max_turns, max_bytes)
        try:
            raw_turns = await reader(
                session_id=session_key,
                epoch=epoch,
                exclude_trace_id=exclude_trace_id,
                after_turn_seq=after_turn_seq,
                max_turns=fetch_cap,
            )
        except TrajectoryError:
            return TurnRead((), False, None)
        return _bound_turns(
            raw_turns,
            builder=lambda raw: _build_committed_turn(raw, restoration=level),
            after_turn_seq=after_turn_seq,
            fetch_cap=fetch_cap,
            max_bytes=max_bytes,
        )


@dataclass(slots=True)
class InProcessTurnSource:
    """隔离的进程内降级来源：不读取跨轮事实，``restorable=false``（§2.6）。

    用于轨迹关闭、metadata-only 或不可读时的 fail-closed 降级；也作为 SubAgent
    默认隔离的占位来源（不赋予跨轮历史）。
    """

    reason: str = "trajectory-unavailable"

    async def read_turns(
        self,
        *,
        session_key: str,
        epoch: int,
        exclude_trace_id: str | None = None,
        after_turn_seq: int | None = None,
        max_turns: int | None = None,
        max_bytes: int | None = None,
    ) -> TurnRead:
        # 隔离来源无可读历史：空 TurnRead、不截断、无续读（≠「截断的未读」）。
        return TurnRead((), False, None)

    async def restoration_level(self, session_key: str, epoch: int) -> RestorationLevel:
        return RestorationLevel.UNAVAILABLE


@dataclass(slots=True)
class LegacyTurnSource:
    """对旧事件做 legacy-inferred 有界兼容读取（§2.7）。

    旧 DB 的 trace 在迁移后获得默认 epoch 但无 committed 事件；本来源从
    ``model_requested``/``model_responded``/``tool_finished``/``trace_finished``
    推断消息序列。无法保持 tool/response fidelity 的 turn 被排除。
    """

    store: TrajectoryStore

    async def restoration_level(self, session_key: str, epoch: int) -> RestorationLevel:
        # legacy 永远是 legacy-inferred（若 epoch 内无旧 trace，read_turns 返回空）。
        return RestorationLevel.LEGACY_INFERRED

    async def read_turns(
        self,
        *,
        session_key: str,
        epoch: int,
        exclude_trace_id: str | None = None,
        after_turn_seq: int | None = None,
        max_turns: int | None = None,
        max_bytes: int | None = None,
    ) -> TurnRead:
        """§2.7/§6.7 legacy-inferred 有界读取：返回 TurnRead，支持续读游标。"""

        # TrajectoryStore Protocol 不声明 read_legacy_turns（仅 durable 具体存储有）；
        # getattr+None 收窄替代 hasattr，避免直接属性访问触发 pyright。
        reader = getattr(self.store, "read_legacy_turns", None)
        if reader is None:
            return TurnRead((), False, None)
        fetch_cap = _fetch_cap(max_turns, max_bytes)
        try:
            raw_turns = await reader(
                session_id=session_key,
                epoch=epoch,
                exclude_trace_id=exclude_trace_id,
                after_turn_seq=after_turn_seq,
                max_turns=fetch_cap,
            )
        except TrajectoryError:
            return TurnRead((), False, None)
        return _bound_turns(
            raw_turns,
            builder=lambda raw: _build_legacy_turn(raw, epoch=epoch),
            after_turn_seq=after_turn_seq,
            fetch_cap=fetch_cap,
            max_bytes=max_bytes,
        )
