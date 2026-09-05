"""
MCP OAuth 2.1 client (authorization code + PKCE) with zero external deps.

Implements the subset of the MCP authorization spec needed to connect to
remote MCP servers that guard their endpoint behind OAuth (e.g. Xmind):

  1. Metadata discovery via RFC 9728 (protected-resource) + RFC 8414
     (authorization-server) .well-known documents.
  2. Dynamic Client Registration (RFC 7591) to obtain a client_id.
  3. PKCE (RFC 7636, S256) authorization-code flow.
  4. Token exchange + refresh, persisted to ~/.cow/mcp_oauth.json.

The actual browser round-trip is completed out-of-band: McpClient generates
an authorization URL, the user opens it, and the web console callback
(/mcp/oauth/callback) feeds the returned code back into finish_authorization().
"""

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from typing import Optional

from common.log import logger


# ------------------------------------------------------------------
# 令牌存储：~/.cow/mcp_oauth.json {server_name: {...credentials...}}
# ------------------------------------------------------------------

_STORE_LOCK = threading.Lock()


def _store_path() -> str:
    base = os.path.expanduser("~/.cow")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        pass
    return os.path.join(base, "mcp_oauth.json")


def _load_store() -> dict:
    path = _store_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"[MCP-OAuth] Failed to read token store: {e}")
        return {}


def _save_store(store: dict) -> None:
    path = _store_path()
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        # 凭证文件：尽可能限制所有者读/写。
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception as e:
        logger.warning(f"[MCP-OAuth] Failed to persist token store: {e}")


def load_server_record(server_name: str) -> dict:
    with _STORE_LOCK:
        return dict(_load_store().get(server_name, {}))


def save_server_record(server_name: str, record: dict) -> None:
    with _STORE_LOCK:
        store = _load_store()
        store[server_name] = record
        _save_store(store)


def clear_server_record(server_name: str) -> None:
    with _STORE_LOCK:
        store = _load_store()
        if server_name in store:
            store.pop(server_name, None)
            _save_store(store)


# ------------------------------------------------------------------
# 待完成的授权，以 OAuth 的 `state` 参数为键。
# 在生成授权 URL 时写入；当浏览器携带 ?code&state
# 重定向回来时，由 Web 回调取出并消费。
# ------------------------------------------------------------------

_PENDING_LOCK = threading.Lock()
_PENDING: dict = {}  # state -> {"handler": OAuthHandler, "created": ts}
_PENDING_TTL = 600  # 秒


def _register_pending(state: str, handler: "OAuthHandler") -> None:
    with _PENDING_LOCK:
        _prune_pending_locked()
        _PENDING[state] = {"handler": handler, "created": time.time()}


def _prune_pending_locked() -> None:
    now = time.time()
    stale = [s for s, v in _PENDING.items() if now - v["created"] > _PENDING_TTL]
    for s in stale:
        _PENDING.pop(s, None)


def pop_pending(state: str) -> Optional["OAuthHandler"]:
    with _PENDING_LOCK:
        _prune_pending_locked()
        entry = _PENDING.pop(state, None)
    return entry["handler"] if entry else None


def has_pending() -> bool:
    with _PENDING_LOCK:
        _prune_pending_locked()
        return bool(_PENDING)


# ------------------------------------------------------------------
# HTTP 帮助程序（仅限 stdlib）
# ------------------------------------------------------------------

_UA = "CowAgent-MCP-OAuth/1.0"


def _http_get_json(url: str, timeout: int = 15) -> Optional[dict]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        logger.debug(f"[MCP-OAuth] GET {url} -> HTTP {e.code}")
        return None
    except Exception as e:
        logger.debug(f"[MCP-OAuth] GET {url} failed: {e}")
        return None


def _http_post_form(url: str, fields: dict, timeout: int = 20) -> dict:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": _UA,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _http_post_json(url: str, payload: dict, timeout: int = 20) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": _UA,
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


# ------------------------------------------------------------------
# 发现（RFC 9728 + RFC 8414）
# ------------------------------------------------------------------

def _origin(url: str) -> str:
    p = urllib.parse.urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def discover_metadata(resource_url: str, www_authenticate: str = "") -> Optional[dict]:
    """
    Resolve the authorization server metadata for a protected MCP resource.

    Returns a dict with at least authorization_endpoint + token_endpoint,
    plus registration_endpoint when the server supports DCR. Returns None
    when discovery fails.
    """
    as_metadata_url = _parse_resource_metadata_url(www_authenticate)

    # 1) 受保护资源元数据 (RFC 9728) 用于定位身份验证服务器。
    auth_server = None
    prm = None
    if as_metadata_url:
        prm = _http_get_json(as_metadata_url)
    if prm is None:
        origin = _origin(resource_url)
        prm = _http_get_json(f"{origin}/.well-known/oauth-protected-resource")
    if prm and isinstance(prm.get("authorization_servers"), list) and prm["authorization_servers"]:
        auth_server = prm["authorization_servers"][0]

    # 2) 授权服务器元数据 (RFC 8414)。当资源方没有对外公布
    #    独立的身份验证服务器时，回退到资源自身的源点。
    base = auth_server or _origin(resource_url)
    asm = _fetch_as_metadata(base)
    if not asm:
        return None

    if not asm.get("authorization_endpoint") or not asm.get("token_endpoint"):
        logger.warning("[MCP-OAuth] Authorization server metadata missing required endpoints")
        return None

    # 导出要请求的 scope。优先级依次为：资源方的
    # required_scopes（RFC 9728）、其 scopes_supported、
    # 以及授权服务器的 scopes_supported。结果会被保存下来，
    # 这样调用方就无需自行配置。
    discovered_scope = ""
    if prm:
        scopes = prm.get("required_scopes") or prm.get("scopes_supported")
        if isinstance(scopes, list) and scopes:
            discovered_scope = " ".join(str(s) for s in scopes)
    if not discovered_scope and isinstance(asm.get("scopes_supported"), list) and asm["scopes_supported"]:
        discovered_scope = " ".join(str(s) for s in asm["scopes_supported"])
    if discovered_scope:
        asm["_discovered_scope"] = discovered_scope
    return asm


def _parse_resource_metadata_url(www_authenticate: str) -> Optional[str]:
    """Extract resource_metadata="..." from a WWW-Authenticate: Bearer header."""
    if not www_authenticate:
        return None
    # 对 `resource_metadata="URL"` 的朴素解析，虽不严谨但已够用
    marker = "resource_metadata="
    idx = www_authenticate.find(marker)
    if idx < 0:
        return None
    rest = www_authenticate[idx + len(marker):].strip()
    if rest.startswith('"'):
        end = rest.find('"', 1)
        return rest[1:end] if end > 0 else None
    # 不加引号，最多逗号/空格
    for sep in (",", " "):
        if sep in rest:
            rest = rest.split(sep, 1)[0]
    return rest or None


def _fetch_as_metadata(base: str) -> Optional[dict]:
    """Try both RFC 8414 and OIDC well-known locations."""
    base = base.rstrip("/")
    candidates = [
        f"{base}/.well-known/oauth-authorization-server",
        f"{base}/.well-known/openid-configuration",
    ]
    for url in candidates:
        data = _http_get_json(url)
        if data and data.get("authorization_endpoint"):
            return data
    return None


# ------------------------------------------------------------------
# PKCE（RFC 7636 授权码交换）
# ------------------------------------------------------------------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _make_pkce() -> tuple:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


# ------------------------------------------------------------------
# OAuthHandler：每服务器 OAuth 状态机
# ------------------------------------------------------------------

class OAuthHandler:
    """Drives the OAuth flow and token lifecycle for a single MCP server."""

    def __init__(self, server_name: str, resource_url: str, redirect_uri: str,
                 scope: str = "", client_name: str = "CowAgent"):
        self.server_name = server_name
        self.resource_url = resource_url
        self.redirect_uri = redirect_uri
        self.scope = scope
        self.client_name = client_name

        rec = load_server_record(server_name)
        self.metadata: dict = rec.get("metadata", {})
        self.client_id: Optional[str] = rec.get("client_id")
        self.client_secret: Optional[str] = rec.get("client_secret")
        self.access_token: Optional[str] = rec.get("access_token")
        self.refresh_token: Optional[str] = rec.get("refresh_token")
        self.expires_at: float = float(rec.get("expires_at", 0) or 0)
        self._verifier: Optional[str] = None

    # ---持久性-------------------------------------------------

    def _persist(self) -> None:
        save_server_record(self.server_name, {
            "resource_url": self.resource_url,
            "metadata": self.metadata,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        })

    # --- 令牌访问 ------------------------------------------------

    def get_valid_access_token(self, leeway: int = 60) -> Optional[str]:
        """Return a usable access token, refreshing proactively when near expiry."""
        if not self.access_token:
            return None
        if self.expires_at and time.time() >= self.expires_at - leeway:
            if not self.refresh():
                return None
        return self.access_token

    def refresh(self) -> bool:
        """Refresh the access token using the stored refresh token."""
        if not self.refresh_token or not self.metadata.get("token_endpoint"):
            return False
        fields = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id or "",
        }
        if self.client_secret:
            fields["client_secret"] = self.client_secret
        try:
            resp = _http_post_form(self.metadata["token_endpoint"], fields)
        except Exception as e:
            logger.warning(f"[MCP-OAuth:{self.server_name}] refresh failed: {e}")
            return False
        return self._absorb_token_response(resp)

    # ---授权代码流程------------------------------------

    def ensure_registered(self, www_authenticate: str = "") -> bool:
        """Discover metadata + register a client if not already done."""
        if not self.metadata.get("authorization_endpoint"):
            meta = discover_metadata(self.resource_url, www_authenticate)
            if not meta:
                return False
            self.metadata = meta
        # 当用户未设置范围时，采用从元数据发现的范围。
        if not self.scope and self.metadata.get("_discovered_scope"):
            self.scope = self.metadata["_discovered_scope"]
            logger.info(f"[MCP-OAuth:{self.server_name}] Using discovered scope: {self.scope}")
        if not self.client_id:
            if not self._register_client():
                return False
        self._persist()
        return True

    def _register_client(self) -> bool:
        reg_endpoint = self.metadata.get("registration_endpoint")
        if not reg_endpoint:
            logger.warning(
                f"[MCP-OAuth:{self.server_name}] No registration_endpoint; "
                f"DCR unavailable. Provide client_id manually."
            )
            return False
        payload = {
            "client_name": self.client_name,
            "redirect_uris": [self.redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }
        if self.scope:
            payload["scope"] = self.scope
        try:
            resp = _http_post_json(reg_endpoint, payload)
        except Exception as e:
            logger.warning(f"[MCP-OAuth:{self.server_name}] DCR failed: {e}")
            return False
        client_id = resp.get("client_id")
        if not client_id:
            logger.warning(f"[MCP-OAuth:{self.server_name}] DCR returned no client_id")
            return False
        self.client_id = client_id
        self.client_secret = resp.get("client_secret")
        logger.info(f"[MCP-OAuth:{self.server_name}] Registered client_id={client_id}")
        return True

    def build_authorization_url(self) -> Optional[str]:
        """Create an authorization URL and register this handler as pending."""
        if not self.metadata.get("authorization_endpoint") or not self.client_id:
            return None
        self._verifier, challenge = _make_pkce()
        state = secrets.token_urlsafe(24)
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        if self.scope:
            params["scope"] = self.scope
        # 公布我们打算访问的资源 (RFC 8707)。
        params["resource"] = self.resource_url
        _register_pending(state, self)
        return f"{self.metadata['authorization_endpoint']}?{urllib.parse.urlencode(params)}"

    def finish_authorization(self, code: str) -> bool:
        """Exchange an authorization code for tokens."""
        if not self.metadata.get("token_endpoint") or not self._verifier:
            return False
        fields = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id or "",
            "code_verifier": self._verifier,
            "resource": self.resource_url,
        }
        if self.client_secret:
            fields["client_secret"] = self.client_secret
        try:
            resp = _http_post_form(self.metadata["token_endpoint"], fields)
        except Exception as e:
            logger.warning(f"[MCP-OAuth:{self.server_name}] token exchange failed: {e}")
            return False
        ok = self._absorb_token_response(resp)
        self._verifier = None
        return ok

    def _absorb_token_response(self, resp: dict) -> bool:
        access = resp.get("access_token")
        if not access:
            logger.warning(f"[MCP-OAuth:{self.server_name}] token response missing access_token: {resp}")
            return False
        self.access_token = access
        if resp.get("refresh_token"):
            self.refresh_token = resp["refresh_token"]
        expires_in = resp.get("expires_in")
        self.expires_at = time.time() + int(expires_in) if expires_in else 0
        self._persist()
        logger.info(f"[MCP-OAuth:{self.server_name}] Access token stored")
        return True
