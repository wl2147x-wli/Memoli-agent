"""Remote channel actions route to the right path based on channelId.

A remote action carrying a per-connection id must take the multi-instance path
(stored per instance in the roster); without one it must take the original
single-connection path unchanged. Only the dispatch decision and the static
credential/binding mappers are exercised here — the full client needs its
parent SDK, which is out of scope for a unit test.
"""

import sys
import types

import pytest


# 远程客户端模块导入不存在的可选运行时 SDK
# 在测试环境中。存根它在导入时绑定的几个名称，以便我们可以
# 在没有真正传输的情况下对我们自己的调度/映射逻辑进行单元测试。
if "linkai" not in sys.modules:
    _stub = types.ModuleType("linkai")

    class _LinkAIClient:  # 最小基数，以便 CloudClient 可以对其进行子类化
        def __init__(self, *a, **k):
            pass

    class _PushMsg:
        pass

    _stub.LinkAIClient = _LinkAIClient
    _stub.PushMsg = _PushMsg
    sys.modules["linkai"] = _stub

from common.cloud_client import CloudClient  # noqa: E402


# ---------------------------------------------------------------------------
# 静态映射器
# ---------------------------------------------------------------------------

def test_instance_credentials_from_maps_app_id_secret():
    creds = CloudClient._instance_credentials_from(
        "feishu", {"appId": "A", "appSecret": "S"}
    )
    assert creds == {"feishu_app_id": "A", "feishu_app_secret": "S"}


def test_instance_credentials_from_single_token_channel():
    # 电报没有密钥；仅令牌映射
    creds = CloudClient._instance_credentials_from(
        "telegram", {"appId": "tok", "appSecret": "ignored"}
    )
    assert creds == {"telegram_token": "tok"}


def test_instance_credentials_from_unknown_type_is_empty():
    assert CloudClient._instance_credentials_from("nope", {"appId": "A"}) == {}


def test_instance_agent_id_accepts_aliases():
    assert CloudClient._instance_agent_id({"agentId": "x"}) == "x"
    assert CloudClient._instance_agent_id({"agent_id": " y "}) == "y"
    assert CloudClient._instance_agent_id({"boundAgentId": "z"}) == "z"


def test_instance_agent_id_absent_is_none():
    assert CloudClient._instance_agent_id({"channelType": "feishu"}) is None
    assert CloudClient._instance_agent_id({"agentId": "  "}) is None


# ---------------------------------------------------------------------------
# 调度决策：channelId 存在 -> 实例路径，不存在 -> 旧路径
# ---------------------------------------------------------------------------

def _dispatch_stub():
    """A CloudClient-shaped object with the real dispatch method and stubbed
    handlers, so we can assert which path a payload takes without constructing
    the real client (which needs the parent SDK connection)."""
    obj = types.SimpleNamespace()
    calls = []
    for name in (
        "_handle_channel_create", "_handle_channel_update", "_handle_channel_delete",
        "_handle_instance_create", "_handle_instance_update", "_handle_instance_delete",
    ):
        setattr(obj, name, (lambda n: (lambda *a, **k: calls.append(n)))(name))
    obj._dispatch_channel_action = types.MethodType(
        CloudClient._dispatch_channel_action, obj
    )
    return obj, calls


def test_dispatch_without_channel_id_takes_legacy_path():
    obj, calls = _dispatch_stub()
    obj._dispatch_channel_action("channel_create", {"channelType": "feishu"})
    assert calls == ["_handle_channel_create"]


def test_dispatch_with_channel_id_takes_instance_path():
    obj, calls = _dispatch_stub()
    obj._dispatch_channel_action(
        "channel_update", {"channelType": "feishu", "channelId": "feishu-abc"}
    )
    assert calls == ["_handle_instance_update"]


def test_dispatch_missing_channel_type_is_ignored():
    obj, calls = _dispatch_stub()
    obj._dispatch_channel_action("channel_create", {"channelId": "x"})
    assert calls == []
