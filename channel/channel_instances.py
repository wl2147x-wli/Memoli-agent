"""Resolve which channel instances to run, bridging legacy and multi-instance.

A legacy install configures channels through ``channel_type`` (a list of type
names) plus flat credentials in ``config.json``; every type maps to exactly one
running channel bound to the default Agent. This is the "shared by default"
world and must keep working untouched.

A multi-Agent install opts in by adding ``channel_instances`` to ``team.json``:
a list of records, each with its own ``instance_id``, ``channel_type``, the
``agent_id`` it routes to, and its own ``credentials``. Several records may
share a ``channel_type`` (e.g. two Feishu bots), which is exactly what a team of
independent AI employees needs.

``resolve_channel_instances`` returns a uniform list of :class:`ChannelInstance`
for both worlds, so the launcher never branch on which config style is in play. When ``channel_instances`` is absent it synthesizes one
instance per legacy ``channel_type`` with no credential override, i.e. the old
behavior byte-for-byte.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

from common import const
from common.log import logger

# 生成的实例 ID 中的随机后缀的长度。 10 个十六进制字符给出
# 约 40 位熵，足以避免用户自己的机器人之间发生冲突
# 保持足够短的时间以便阅读和打字。
_INSTANCE_ID_RANDOM_LEN = 10


def new_instance_id(channel_type: str, taken: Iterable[str] = ()) -> str:
    """Return a stable, unique id for a freshly created channel instance.

    Shape is ``{channel_type}-{random}`` (e.g. ``feishu-a3f9c2e1b7``): the
    prefix keeps the type recognizable at a glance, the random suffix makes it
    unique and stable across restarts. Ids provided elsewhere (e.g. handed down
    by a remote controller) are honored as-is and never regenerated; this helper
    is only for the local "create a new instance" path.
    """
    ctype = _normalize_type((channel_type or "").strip()) or "channel"
    existing = set(taken)
    while True:
        candidate = f"{ctype}-{secrets.token_hex(_INSTANCE_ID_RANDOM_LEN // 2 + 1)[:_INSTANCE_ID_RANDOM_LEN]}"
        if candidate not in existing:
            return candidate


# 对于每个通道类型，构成其凭证的配置密钥。只有这些
# 键被复制到每个实例的覆盖中；其他一切（端口、功能
# flags) 在conf() 中保持全局。与通道类的 cfg() 保持同步
# 读。随着更多通道类型获得多实例支持而扩展。
CREDENTIAL_KEYS: Dict[str, tuple] = {
    const.FEISHU: (
        "feishu_app_id",
        "feishu_app_secret",
        "feishu_token",
        "feishu_bot_name",
    ),
    const.DINGTALK: (
        "dingtalk_client_id",
        "dingtalk_client_secret",
        "dingtalk_robot_code",
    ),
    const.WECOM_BOT: (
        "wecom_bot_id",
        "wecom_bot_secret",
        "wecom_bot_token",
        "wecom_bot_encoding_aes_key",
    ),
    const.WEIXIN: (
        "weixin_token",
        "weixin_base_url",
    ),
    const.QQ: (
        "qq_app_id",
        "qq_app_secret",
    ),
    const.TELEGRAM: (
        "telegram_token",
    ),
    const.SLACK: (
        "slack_bot_token",
        "slack_app_token",
    ),
    const.DISCORD: (
        "discord_token",
    ),
}

# 目前实际上支持运行多个实例的通道类型。
# 其他可能出现在channel_instances中，但将作为单个实例运行
# （他们的@singleton还没有被绕过）；我们优雅地记录和回退。
MULTI_INSTANCE_READY = frozenset({
    const.FEISHU,
    const.DINGTALK,
    const.QQ,
    const.TELEGRAM,
    const.SLACK,
    const.DISCORD,
    const.WEIXIN,
    const.WECOM_BOT,
})


@dataclass(frozen=True)
class ChannelInstance:
    """One channel to bring up, with its identity, binding and credentials."""

    instance_id: str
    channel_type: str
    agent_id: str = ""
    credentials: Dict[str, Any] = field(default_factory=dict)
    #：其他特工共享此频道的对话。 ``agent_id`` 是
    #：接收每条入站消息的所有者/领导者； ``members`` 是
    #：它可能会将工作交给队友（通过@mention或agent_delegate工具），
    #：就像网络团队对话一样。空意味着一个单独的机器人。业主是
    #: 从未在这里列出。
    members: List[str] = field(default_factory=list)
    #：当从旧版channel_type而不是显式合成时为真
    #：channel_instances记录。旧实例不进行凭证覆盖。
    legacy: bool = True


def _normalize_type(channel_type: str) -> str:
    if channel_type in (const.WEIXIN, "wx"):
        return const.WEIXIN
    return channel_type


def _parse_channel_type(raw) -> List[str]:
    """Legacy channel_type -> list of type names (string / CSV / list)."""
    if isinstance(raw, list):
        return [str(ch).strip() for ch in raw if str(ch).strip()]
    if isinstance(raw, str):
        return [ch.strip() for ch in raw.split(",") if ch.strip()]
    return []


def _legacy_instances(settings: Mapping[str, Any]) -> List[ChannelInstance]:
    """One instance per legacy channel_type, no credential override.

    Byte-for-byte the pre-multi-instance behavior: instance_id == channel_type,
    credentials read from the global conf() at runtime, routing left to the
    existing config-based AgentRouter (agent_id empty here).
    """
    out: List[ChannelInstance] = []
    for name in _parse_channel_type(settings.get("channel_type", "")):
        ctype = _normalize_type(name)
        out.append(ChannelInstance(instance_id=ctype, channel_type=ctype))
    return out


def _explicit_instances(raw_list: list) -> List[ChannelInstance]:
    out: List[ChannelInstance] = []
    seen_ids = set()
    for index, raw in enumerate(raw_list):
        if not isinstance(raw, Mapping):
            logger.warning(f"[ChannelInstances] entry #{index} is not an object, skipping")
            continue
        channel_type = _normalize_type(str(raw.get("channel_type") or "").strip())
        if not channel_type:
            logger.warning(f"[ChannelInstances] entry #{index} has no channel_type, skipping")
            continue
        instance_id = str(raw.get("instance_id") or "").strip() or channel_type
        if instance_id in seen_ids:
            logger.warning(
                f"[ChannelInstances] duplicate instance_id '{instance_id}', skipping"
            )
            continue
        seen_ids.add(instance_id)

        agent_id = str(raw.get("agent_id") or "").strip()

        raw_members = raw.get("members")
        members: List[str] = []
        if isinstance(raw_members, list):
            for m in raw_members:
                mid = str(m or "").strip()
                # 所有者从来都不是自己团队的成员，并且出现 ids
                # 一次：此处的重复项将显示同一队友两次。
                if mid and mid != agent_id and mid not in members:
                    members.append(mid)

        # 凭证可以在“凭证”下内联给出，或者作为平键给出
        # 记录本身；仅保留该类型的已知密钥。
        raw_creds = raw.get("credentials")
        source = raw_creds if isinstance(raw_creds, Mapping) else raw
        creds: Dict[str, Any] = {}
        for key in CREDENTIAL_KEYS.get(channel_type, ()):
            if source.get(key) is not None:
                creds[key] = source.get(key)

        if channel_type not in MULTI_INSTANCE_READY:
            logger.info(
                f"[ChannelInstances] '{channel_type}' does not support multiple "
                f"instances yet; '{instance_id}' will run as a single instance"
            )

        out.append(
            ChannelInstance(
                instance_id=instance_id,
                channel_type=channel_type,
                agent_id=agent_id,
                credentials=creds,
                members=members,
                legacy=False,
            )
        )
    return out


def resolve_channel_instances(settings: Mapping[str, Any]) -> List[ChannelInstance]:
    """Channel instances to run for *settings*.

    Prefers explicit ``channel_instances`` (multi-Agent); otherwise synthesizes
    the legacy set from ``channel_type``. The ``web`` console is intentionally
    not represented here — it is managed separately by the launcher.
    """
    raw_list = settings.get("channel_instances")
    if isinstance(raw_list, list) and raw_list:
        instances = _explicit_instances(raw_list)
        if instances:
            return instances
        logger.warning(
            "[ChannelInstances] channel_instances present but yielded nothing; "
            "falling back to legacy channel_type"
        )
    return _legacy_instances(settings)


# ---------------------------------------------------------------------------
# 显式多实例列表的持久性助手。
#
# 这些编辑名册文件 (team.json) 中的 ``channel_instances`` 数组并
# 完全保留遗留的“`channel_type`”+平面凭证路径，所以
# 从不选择多个实例的安装永远不会被触及。
# ---------------------------------------------------------------------------

def _filtered_credentials(channel_type: str, source: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep only the credential keys meaningful for *channel_type*."""
    ctype = _normalize_type((channel_type or "").strip())
    creds: Dict[str, Any] = {}
    for key in CREDENTIAL_KEYS.get(ctype, ()):
        value = source.get(key)
        if value is not None:
            creds[key] = value
    return creds


def bootstrap_legacy_instances(
    settings: Mapping[str, Any],
    roster: Mapping[str, Any],
    default_agent_id: str = "",
) -> List[Dict[str, Any]]:
    """Fold a legacy single-channel setup into ``channel_instances`` records.

    Called when an install first crosses into multi-Agent territory (team.json
    is being written for the first time). A legacy install keeps its channel
    credentials as flat keys in config.json and names the channel in
    ``channel_type``; multi-Agent mode routes entirely off ``channel_instances``,
    so those flat channels would silently go dark unless carried over.

    For every multi-instance-ready channel named in ``channel_type`` that has
    credentials in ``settings`` and no existing record, synthesize one record
    bound to the default Agent (``instance_id == channel_type``, matching the
    legacy id so nothing else has to change). The config.json flat keys are left
    in place untouched — multi-Agent startup simply ignores them.

    Returns the (possibly extended) channel_instances list.
    """
    records = [
        dict(item)
        for item in (roster.get("channel_instances") or [])
        if isinstance(item, Mapping)
    ]
    have_types = {
        _normalize_type(str(r.get("channel_type") or "").strip()) for r in records
    }
    default_id = (default_agent_id or roster.get("default_agent_id") or "").strip()

    for name in _parse_channel_type(settings.get("channel_type", "")):
        ctype = _normalize_type(name)
        if ctype not in MULTI_INSTANCE_READY or ctype in have_types:
            continue
        creds = _filtered_credentials(ctype, settings)
        if not creds:
            continue
        records.append(
            {
                "instance_id": ctype,
                "channel_type": ctype,
                "agent_id": default_id,
                "credentials": creds,
            }
        )
        have_types.add(ctype)
        # 微信的扫描登录令牌位于凭据文件中，而不是 config.json。
        # 引导实例（instance_id ==“weixin”）读取每个实例
        # 文件，因此将旧的默认文件传递给它 - 否则用户
        # 仅仅因为他们添加了代理就必须重新扫描。
        if ctype == const.WEIXIN:
            _carry_weixin_credentials_file(ctype)
        logger.info(
            f"[ChannelInstances] bootstrapped legacy '{ctype}' credentials into a "
            f"channel_instances record bound to '{default_id or 'default'}'"
        )
    return records


def _carry_weixin_credentials_file(instance_id: str) -> None:
    """Copy the legacy Weixin token file to the per-instance path, once.

    Best-effort and idempotent: if the legacy default file exists and the
    per-instance file does not yet, the token (and persisted context tokens) are
    copied so the bootstrapped instance stays logged in. Never overwrites an
    existing per-instance file, and never raises into the write path.
    """
    try:
        import shutil
        from config import get_weixin_credentials_path

        legacy = get_weixin_credentials_path()
        target = get_weixin_credentials_path(instance_id)
        if legacy == target:
            return
        if os.path.exists(legacy) and not os.path.exists(target):
            shutil.copy2(legacy, target)
            logger.info(
                f"[ChannelInstances] carried Weixin credentials '{legacy}' -> "
                f"'{target}' so the bootstrapped instance stays logged in"
            )
    except Exception as e:
        logger.warning(f"[ChannelInstances] Weixin credentials carry-over skipped: {e}")


def read_raw_instances(settings: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The raw ``channel_instances`` records as stored, or an empty list."""
    from agent import team

    roster = team.read(settings)
    raw = roster.get("channel_instances")
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, Mapping)]
    return []


def _clean_members(members, owner_id: str) -> list:
    """Normalize a members list: strings, de-duped, no owner, order preserved."""
    out: list = []
    owner = (owner_id or "").strip()
    for m in members or []:
        mid = str(m or "").strip()
        if mid and mid != owner and mid not in out:
            out.append(mid)
    return out


def upsert_instance(
    settings: Mapping[str, Any],
    channel_type: str,
    instance_id: str = "",
    agent_id: Optional[str] = None,
    credentials: Optional[Mapping[str, Any]] = None,
    members: Optional[list] = None,
) -> ChannelInstance:
    """Create or update one channel instance record and persist it.

    Matching is by ``instance_id``. When it is empty a new stable id is
    generated. ``agent_id``, ``credentials`` and ``members`` are merged onto any
    existing record so a partial update (e.g. credentials only) does not drop
    the binding or the team. Pass ``members=None`` to leave the team untouched,
    or ``members=[]`` to clear it. Returns the resulting :class:`ChannelInstance`.
    """
    from agent import team

    ctype = _normalize_type((channel_type or "").strip())
    records = read_raw_instances(settings)
    taken = {str(r.get("instance_id") or "").strip() for r in records}

    target_id = (instance_id or "").strip()
    if not target_id:
        target_id = new_instance_id(ctype, taken)

    incoming_creds = _filtered_credentials(ctype, credentials or {})

    updated = False
    for record in records:
        if str(record.get("instance_id") or "").strip() != target_id:
            continue
        record["channel_type"] = ctype
        if agent_id is not None:
            record["agent_id"] = str(agent_id).strip()
        if incoming_creds:
            merged = dict(record.get("credentials") or {})
            merged.update(incoming_creds)
            record["credentials"] = merged
        if members is not None:
            cleaned = _clean_members(members, record.get("agent_id") or "")
            if cleaned:
                record["members"] = cleaned
            else:
                record.pop("members", None)
        updated = True
        result_record = record
        break

    if not updated:
        result_record = {
            "instance_id": target_id,
            "channel_type": ctype,
            "agent_id": str(agent_id).strip() if agent_id is not None else "",
            "credentials": incoming_creds,
        }
        cleaned = _clean_members(members, result_record["agent_id"])
        if cleaned:
            result_record["members"] = cleaned
        records.append(result_record)

    roster = team.read(settings)
    roster["channel_instances"] = records
    team.write(settings, roster)

    return ChannelInstance(
        instance_id=target_id,
        channel_type=ctype,
        agent_id=str(result_record.get("agent_id") or ""),
        credentials=dict(result_record.get("credentials") or {}),
        members=list(result_record.get("members") or []),
        legacy=False,
    )


def remove_instance(settings: Mapping[str, Any], instance_id: str) -> bool:
    """Drop one instance record by id. Returns True if something was removed."""
    from agent import team

    target_id = (instance_id or "").strip()
    if not target_id:
        return False
    records = read_raw_instances(settings)
    kept = [r for r in records if str(r.get("instance_id") or "").strip() != target_id]
    if len(kept) == len(records):
        return False
    roster = team.read(settings)
    roster["channel_instances"] = kept
    team.write(settings, roster)
    return True


def get_instance(settings: Mapping[str, Any], instance_id: str) -> Optional[ChannelInstance]:
    """Resolve one instance by id, or None.

    Overlays the roster file first so the lookup works even when the caller
    passes bare ``conf()`` (channel_instances lives in team.json, not config).
    """
    from agent import team

    target_id = (instance_id or "").strip()
    resolved = team.resolve(settings)
    for inst in resolve_channel_instances(resolved):
        if inst.instance_id == target_id:
            return inst
    return None
