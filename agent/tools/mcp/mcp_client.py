"""
MCP (Model Context Protocol) client module.

Implements JSON-RPC 2.0 over stdio, SSE and Streamable HTTP transports
without any external MCP SDK dependency.
"""

import json
import os
import queue
import subprocess
import threading
import urllib.request
import urllib.error
from typing import Optional

from common.log import logger


# Streamable HTTP 传输类型接受的别名
_STREAMABLE_HTTP_ALIASES = {"streamable-http", "streamable_http", "streamablehttp", "http"}


# stdio MCP 子进程正常运行所需的系统环境变量（node/python/npx 工具链）。
# 默认情况下，其余变量一律被剔除，
# 以免代理自身环境中的 API 密钥泄漏到服务器中。
_STDIO_ENV_PASSTHROUGH = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
    "TERM", "TZ", "TMPDIR", "NODE_PATH", "NVM_DIR", "PYTHONPATH", "PYTHONHOME",
    # Windows 必需品
    "SYSTEMROOT", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "APPDATA",
    "LOCALAPPDATA", "USERPROFILE", "PROGRAMFILES", "PROGRAMFILES(X86)",
    "PROGRAMDATA", "TEMP", "TMP", "HOMEDRIVE", "HOMEPATH",
)
# 即使开启 inherit_full_env，匹配敏感名称模式的变量也仍会被剔除，不会透传。
_STDIO_ENV_SENSITIVE = ("_KEY", "_SECRET", "_TOKEN", "_PASSWORD", "_PASSWD", "_CREDENTIAL")


# OAuth 授权完成后会触发的可选回调，
# 工具管理器借此让刚完成授权的服务器上线。签名：
# reload_fn(server_name: str) -> None。由工具管理器注册。
_reload_callback = None


def set_reload_callback(fn) -> None:
    """Register a callback fired after a server's OAuth flow succeeds."""
    global _reload_callback
    _reload_callback = fn


def notify_server_authorized(server_name: str) -> None:
    """Called by the web callback once tokens are stored for a server."""
    fn = _reload_callback
    if fn is None:
        logger.debug(f"[MCP:{server_name}] Authorized but no reload callback registered")
        return
    try:
        fn(server_name)
    except Exception as e:
        logger.warning(f"[MCP:{server_name}] reload callback failed: {e}")


def _oauth_redirect_uri() -> str:
    """Build the OAuth redirect URI served by the web console callback.

    Priority: explicit mcp_oauth_redirect_base config, otherwise the local
    web console address (127.0.0.1:<web_port>). Both point at the shared
    /mcp/oauth/callback route.
    """
    try:
        from config import conf
        base = (conf().get("mcp_oauth_redirect_base") or "").strip().rstrip("/")
        if not base:
            port = int(os.environ.get("COW_WEB_PORT") or conf().get("web_port", 9899))
            base = f"http://127.0.0.1:{port}"
    except Exception:
        base = "http://127.0.0.1:9899"
    return f"{base}/mcp/oauth/callback"


class McpClient:
    """Single MCP Server client supporting stdio, SSE and Streamable HTTP transports."""

    def __init__(self, config: dict):
        """
        config examples:
          stdio:           {"name": "filesystem", "type": "stdio", "command": "npx", "args": [...]}
          SSE:             {"name": "my-api",    "type": "sse",   "url": "http://localhost:8000/sse"}
          streamable-http: {"name": "pubmed",    "type": "streamable-http", "url": "https://x/mcp"}
        """
        self.config = config
        self.name: str = config.get("name", "unknown")
        raw_transport: str = config.get("type", "stdio")
        # 每个服务器各自的工具调用超时时间（默认 120s，适合数据查询）
        self._timeout: int = int(config.get("timeout", 120))
        # 将 Streamable-http 别名标准化为单个内部键
        self.transport: str = (
            "streamable-http"
            if raw_transport.lower() in _STREAMABLE_HTTP_ALIASES
            else raw_transport
        )

        # 标准输入输出状态
        self._proc: Optional[subprocess.Popen] = None
        self._read_queue: queue.Queue = queue.Queue()

        # SSE 状态
        self._sse_url: Optional[str] = None
        self._post_url: Optional[str] = None  # 发送消息的端点（从SSE解析）

        # Streamable HTTP 传输状态
        self._http_url: Optional[str] = None
        self._http_headers: dict = {}  # 用户配置中的额外标头（例如授权）
        self._http_session_id: Optional[str] = None  # 服务器分配的Mcp-Session-Id

        # OAuth 状态（仅限 Streamable-http）。
        # 在服务器返回 401 且用户未提供静态令牌时才延迟创建。
        self._oauth = None  # OAuthHandler 实例
        # 当 401 无法自动解决、必须由用户完成浏览器授权时，
        # 该标记置为 True；调用方可以据此提示用户。
        self.needs_auth: bool = False

        # 共享状态
        self._next_id = 1
        self._id_lock = threading.Lock()
        # _call_lock 序列化单个 stdio 管道上的所有请求。
        # SSE 与 Streamable-http 各自发送独立的 HTTP 请求，
        # 因此无需获取此锁（参见 _send_request）。
        self._call_lock = threading.Lock()
        # _http_lock 用于保护 _http_session_id 的初始化，
        # 防止并发的 streamable-http 请求相互干扰。
        self._http_lock = threading.Lock()
        # 在替换过期会话时阻止新请求。
        # RLock 允许恢复握手使用正常的 HTTP 路径。
        self._http_reinit_lock = threading.RLock()
        self._initialized = False

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """Connect and perform the MCP handshake. Returns True on success."""
        try:
            if self.transport == "stdio":
                return self._init_stdio()
            elif self.transport == "sse":
                return self._init_sse()
            elif self.transport == "streamable-http":
                return self._init_streamable_http()
            else:
                logger.warning(f"[MCP:{self.name}] Unknown transport type: {self.transport!r}")
                return False
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] Initialization failed: {e}")
            return False

    def list_tools(self) -> list:
        """Return the tool list from this server.

        Each item is a dict: {"name": str, "description": str, "inputSchema": dict}
        """
        try:
            resp = self._send_request("tools/list", {})
            tools = resp.get("result", {}).get("tools", [])
            return [
                {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "inputSchema": t.get("inputSchema", {}),
                }
                for t in tools
            ]
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] list_tools failed: {e}")
            return []

    def call_tool(self, name: str, arguments: dict) -> str:
        """Call a tool and return the result as a string."""
        try:
            resp = self._send_request("tools/call", {"name": name, "arguments": arguments})
            content = resp.get("result", {}).get("content", [])
            parts = [item.get("text", "") for item in content if item.get("type") == "text"]
            return "\n".join(parts)
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] call_tool({name}) failed: {e}")
            return f"Error: {e}"

    def shutdown(self):
        """Close the connection / terminate the child process."""
        if self._proc is not None:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None
            logger.debug(f"[MCP:{self.name}] stdio process terminated")

        # 尽力而为的 Streamable-http 会话终止
        if self.transport == "streamable-http" and self._http_session_id and self._http_url:
            try:
                req = urllib.request.Request(
                    self._http_url,
                    method="DELETE",
                    headers={"Mcp-Session-Id": self._http_session_id, **self._http_headers},
                )
                with urllib.request.urlopen(req, timeout=5):
                    pass
            except Exception:
                pass
            self._http_session_id = None

        self._initialized = False

    # ------------------------------------------------------------------
    # stdio 传输
    # ------------------------------------------------------------------

    def _init_stdio(self) -> bool:
        command = self.config.get("command")
        if not command:
            logger.warning(f"[MCP:{self.name}] stdio config missing 'command'")
            return False

        if not self._command_allowed(command):
            return False

        args = self.config.get("args", [])
        env = self._build_stdio_env(self.config.get("env", None))

        self._proc = subprocess.Popen(
            [command] + list(args),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )
        logger.debug(f"[MCP:{self.name}] stdio process started (pid={self._proc.pid})")

        threading.Thread(
            target=self._drain_stderr, daemon=True, name=f"mcp-stderr-{self.name}"
        ).start()
        threading.Thread(
            target=self._drain_stdout, daemon=True, name=f"mcp-stdout-{self.name}"
        ).start()

        return self._handshake()

    def _command_allowed(self, command: str) -> bool:
        """Check the executable against an optional command allowlist.

        Disabled by default (empty allowlist = allow everything) to keep
        existing mcp.json configs working. Set config.json's
        ``mcp_stdio_command_allowlist`` (e.g. ["npx", "node", "python", "uvx"])
        to restrict which executables MCP stdio servers may launch.
        """
        try:
            from config import conf
            allowlist = conf().get("mcp_stdio_command_allowlist") or []
        except Exception:
            allowlist = []
        if not allowlist:
            return True
        base = os.path.basename(str(command)).lower()
        if base.endswith(".exe"):
            base = base[:-4]
        if base in {str(c).lower() for c in allowlist}:
            return True
        logger.warning(
            f"[MCP:{self.name}] command '{command}' not in "
            f"mcp_stdio_command_allowlist, refusing to start"
        )
        return False

    def _build_stdio_env(self, extra_env) -> dict:
        """Build the environment for a stdio MCP subprocess.

        By default only safe system vars plus the user's explicit ``env``
        block are passed through, so API keys in the agent's own environment
        are not leaked to the subprocess. Set the per-server config
        ``inherit_full_env: true`` to restore full inheritance (obviously
        sensitive names are still stripped).
        """
        extra_env = extra_env or {}
        if self.config.get("inherit_full_env"):
            env = {
                k: v for k, v in os.environ.items()
                if not any(p in k.upper() for p in _STDIO_ENV_SENSITIVE)
            }
        else:
            env = {k: os.environ[k] for k in _STDIO_ENV_PASSTHROUGH if k in os.environ}
        # 用户声明的 env 是显式授权，总是最后应用。
        env.update({str(k): str(v) for k, v in extra_env.items()})
        return env

    def _url_allowed(self, url: str) -> bool:
        """SSRF guard for remote (SSE / streamable-http) MCP endpoints.

        Delegates to the shared ``validate_url_safe`` helper, which is a no-op
        unless ``web_security_ssrf_protection`` is enabled, so local/LAN MCP
        servers keep working by default.
        """
        try:
            from agent.tools.utils.url_safety import validate_url_safe
            validate_url_safe(url)
            return True
        except ValueError as e:
            logger.warning(f"[MCP:{self.name}] url blocked: {e}")
            return False

    def _drain_stderr(self):
        for line in self._proc.stderr:
            line = line.strip()
            if line:
                logger.warning(f"[MCP:{self.name}] stderr: {line}")

    def _drain_stdout(self):
        """Background thread: read lines from stdout and put them into the queue."""
        try:
            for line in self._proc.stdout:
                self._read_queue.put(line)
        except Exception:
            pass
        finally:
            try:
                self._read_queue.put("")
            except Exception:
                pass

    def _readline_with_timeout(self, timeout: Optional[int] = None) -> str:
        """Read one line from stdio stdout with a hard timeout (cross-platform).

        Uses the per-server timeout from mcp.json config when no explicit
        timeout is provided.
        """
        effective = timeout if timeout is not None else self._timeout
        try:
            line = self._read_queue.get(timeout=effective)
        except queue.Empty:
            raise TimeoutError(f"[MCP:{self.name}] stdio read timed out after {effective}s")
        if not line:
            raise IOError(f"[MCP:{self.name}] stdio process closed unexpectedly")
        return line

    def _stdio_send(self, message: dict) -> dict:
        """Send a JSON-RPC message over stdio and read the response."""
        raw = json.dumps(message) + "\n"
        self._proc.stdin.write(raw)
        self._proc.stdin.flush()

        expected_id = message.get("id")
        while True:
            line = self._readline_with_timeout()
            if not line:
                raise IOError(f"[MCP:{self.name}] stdio process closed unexpectedly")
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" not in data:
                logger.debug(f"[MCP:{self.name}] notification skipped: {data.get('method', '?')}")
                continue
            # 校验响应 ID 是否与请求 ID 一致，以免吞掉陈旧响应——
            # 这些响应是之前失败或超时的请求遗留下来的。
            if data.get("id") != expected_id:
                logger.warning(
                    f"[MCP:{self.name}] Stale response id={data.get('id')} "
                    f"(expected {expected_id}), skipping"
                )
                continue
            return data

    # ------------------------------------------------------------------
    # SSE 传输
    # ------------------------------------------------------------------

    def _init_sse(self) -> bool:
        url = self.config.get("url")
        if not url:
            logger.warning(f"[MCP:{self.name}] SSE config missing 'url'")
            return False

        if not self._url_allowed(url):
            return False

        self._sse_url = url

        # 读取第一个 SSE 事件以发现 POST 端点
        try:
            self._post_url = self._sse_discover_endpoint()
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] SSE endpoint discovery failed: {e}")
            return False

        return self._handshake()

    def _sse_discover_endpoint(self) -> str:
        """Open SSE stream and read the 'endpoint' event to learn the POST URL."""
        req = urllib.request.Request(
            self._sse_url,
            headers={"Accept": "text/event-stream"},
        )
        endpoint = None
        with urllib.request.urlopen(req, timeout=10) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8").rstrip("\n\r")
                if line.startswith("data:"):
                    data = line[len("data:"):].strip()
                    # 某些服务器发送带有“uri”或普通路径的 JSON
                    if data.startswith("{"):
                        parsed = json.loads(data)
                        endpoint = parsed.get("uri") or parsed.get("url") or parsed.get("endpoint")
                    elif data.startswith("http"):
                        # 纯绝对 URL
                        endpoint = data
                    else:
                        # 相对路径：基于 SSE 基础 URL 解析
                        from urllib.parse import urljoin
                        endpoint = urljoin(self._sse_url, data)
                    break
        if not endpoint:
            raise ValueError(f"[MCP:{self.name}] No endpoint event received from SSE stream")
        # 重新验证服务器提供的 POST 端点以阻止重定向
        # 进入内部地址（SSRF 保护；保护关闭时无操作）。
        from agent.tools.utils.url_safety import validate_url_safe
        validate_url_safe(endpoint)
        return endpoint

    def _sse_send(self, message: dict) -> dict:
        """POST a JSON-RPC message to the server and return the response."""
        body = json.dumps(message).encode("utf-8")
        req = urllib.request.Request(
            self._post_url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)

    # ------------------------------------------------------------------
    # Streamable HTTP 传输（MCP 规范 2025-03-26）
    # ------------------------------------------------------------------

    def _init_streamable_http(self) -> bool:
        url = self.config.get("url")
        if not url:
            logger.warning(f"[MCP:{self.name}] streamable-http config missing 'url'")
            return False

        if not self._url_allowed(url):
            return False

        self._http_url = url
        # 允许用户提供的标头（例如 {"Authorization": "Bearer xxx"}）
        extra_headers = self.config.get("headers") or {}
        if isinstance(extra_headers, dict):
            self._http_headers = {str(k): str(v) for k, v in extra_headers.items()}

        # 恢复该服务器此前保存的 OAuth 凭据，
        # 让重启后直接复用令牌，而无需重新走授权流程。
        self._maybe_load_oauth()

        return self._handshake()

    # ------------------------------------------------------------------
    # OAuth 辅助方法（仅限 Streamable-http）
    # ------------------------------------------------------------------

    def _has_static_auth(self) -> bool:
        """True when the user supplied their own Authorization header."""
        return any(k.lower() == "authorization" for k in self._http_headers)

    def _maybe_load_oauth(self) -> None:
        """Attach an OAuthHandler when stored credentials exist for this server."""
        if self._has_static_auth():
            return
        try:
            from agent.tools.mcp.mcp_oauth import OAuthHandler, load_server_record
        except Exception:
            return
        rec = load_server_record(self.name)
        # 只有在存在可复用的凭据时才创建处理程序；
        # 否则等首次遇到 401 时再延迟创建。
        if rec.get("access_token") or rec.get("client_id"):
            self._oauth = OAuthHandler(
                server_name=self.name,
                resource_url=self._http_url,
                redirect_uri=_oauth_redirect_uri(),
                scope=self.config.get("scope", ""),
            )

    def _current_bearer(self) -> Optional[str]:
        """Return a valid access token, refreshing if needed."""
        if self._oauth is None:
            return None
        return self._oauth.get_valid_access_token()

    def _begin_oauth(self, www_authenticate: str = "") -> None:
        """Kick off the OAuth flow after a 401: discover, register, prompt user."""
        if self._has_static_auth():
            return
        try:
            from agent.tools.mcp.mcp_oauth import OAuthHandler
        except Exception as e:
            logger.warning(f"[MCP:{self.name}] OAuth module unavailable: {e}")
            return

        if self._oauth is None:
            self._oauth = OAuthHandler(
                server_name=self.name,
                resource_url=self._http_url,
                redirect_uri=_oauth_redirect_uri(),
                scope=self.config.get("scope", ""),
            )

        if not self._oauth.ensure_registered(www_authenticate):
            logger.warning(
                f"[MCP:{self.name}] OAuth discovery/registration failed; "
                f"cannot authorize automatically"
            )
            return

        auth_url = self._oauth.build_authorization_url()
        if not auth_url:
            logger.warning(f"[MCP:{self.name}] Failed to build authorization URL")
            return

        self.needs_auth = True
        logger.warning(
            f"[MCP:{self.name}] ⚠️  Authorization required. Open this URL in a "
            f"browser to authorize, then this server will come online automatically:\n"
            f"    {auth_url}"
        )
        # 在有本地浏览器（desktop/dev）的机器上，直接打开。
        if os.environ.get("COW_DESKTOP") == "1" or not os.environ.get("COW_HEADLESS"):
            try:
                import webbrowser
                webbrowser.open(auth_url)
            except Exception:
                pass

    def _streamable_http_send(self, message: dict) -> dict:
        """POST a JSON-RPC request and return the response (JSON or SSE-wrapped)."""
        return self._streamable_http_post(message, expect_response=True)

    def _handle_401(
        self,
        err,
        message: dict,
        expect_response: bool,
        retried: bool,
        session_retried: bool = False,
    ) -> dict:
        """Handle a 401: refresh the token and retry once, else begin OAuth."""
        www_auth = ""
        try:
            www_auth = err.headers.get("WWW-Authenticate", "") or ""
        except Exception:
            pass
        try:
            err.read()
        except Exception:
            pass

        # 首先尝试使用存储的刷新令牌进行静默刷新。
        if not retried and self._oauth is not None and self._oauth.refresh():
            logger.info(f"[MCP:{self.name}] Token refreshed after 401, retrying")
            return self._streamable_http_post(
                message,
                expect_response,
                _retried=True,
                _session_retried=session_retried,
            )

        # 没有可用的令牌 — 启动（或重新启动）交互式 OAuth 流程。
        self._begin_oauth(www_auth)
        raise IOError(
            f"[MCP:{self.name}] streamable-http HTTP 401: authorization required "
            f"(complete the OAuth flow to enable this server)"
        )

    def _streamable_http_post(
        self,
        message: dict,
        expect_response: bool,
        _retried: bool = False,
        _session_retried: bool = False,
    ) -> dict:
        """
        POST a JSON-RPC message over Streamable HTTP.

        Per the spec, the response Content-Type can be either:
          - application/json   -> single JSON-RPC response in body
          - text/event-stream  -> SSE stream; we read until we get a matching response
        """
        body = json.dumps(message).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        # 在使过期会话失效并完成替换握手期间，
        # 阻止其他请求并发进入。
        with self._http_reinit_lock:
            with self._http_lock:
                sid = self._http_session_id
        if sid:
            headers["Mcp-Session-Id"] = sid
        headers.update(self._http_headers)
        # 若持有 OAuth Bearer 令牌则注入请求（除非用户已设置静态
        # Authorization 标头，此时以静态标头为准）。
        if not self._has_static_auth():
            token = self._current_bearer()
            if token:
                headers["Authorization"] = f"Bearer {token}"

        req = urllib.request.Request(
            self._http_url,
            data=body,
            method="POST",
            headers=headers,
        )

        try:
            resp = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as e:
            # 401 是符合规范的“需要授权”信号。
            if e.code == 401 and not self._has_static_auth():
                return self._handle_401(
                    e,
                    message,
                    expect_response,
                    _retried,
                    _session_retried,
                )
            if (
                e.code == 404
                and sid
                and not _session_retried
                and message.get("method") != "initialize"
            ):
                try:
                    e.read()
                except Exception:
                    pass
                self._replace_expired_http_session(sid)
                return self._streamable_http_post(
                    message,
                    expect_response,
                    _retried=_retried,
                    _session_retried=True,
                )
            # 展示服务器返回的错误正文，方便调试
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="ignore")
            except Exception:
                pass
            raise IOError(
                f"[MCP:{self.name}] streamable-http HTTP {e.code}: {detail[:200]}"
            )

        with resp:
            # 捕获服务器分配的会话 ID（如果有）
            session_id = resp.headers.get("Mcp-Session-Id")
            # 双重检查加锁：只有第一个响应能写入会话 ID，
            # 避免并发的初始化请求
            # 互相覆盖。
            if (
                session_id
                and (message.get("method") == "initialize" or sid is None)
                and not self._http_session_id
            ):
                with self._http_lock:
                    if not self._http_session_id:
                        self._http_session_id = session_id

            status = resp.status if hasattr(resp, "status") else resp.getcode()

            # 通知：服务器可能会回复 202 Accepted，但没有正文
            if not expect_response or status == 202:
                try:
                    resp.read()
                except Exception:
                    pass
                return {}

            content_type = (resp.headers.get("Content-Type") or "").lower()
            expected_id = message.get("id")

            if "text/event-stream" in content_type:
                return self._read_sse_response(resp, expected_id)

            raw = resp.read().decode("utf-8")
            if not raw:
                return {}
            return json.loads(raw)

    def _replace_expired_http_session(self, expired_session_id: str) -> None:
        """Replace an expired Streamable HTTP session once across callers."""
        with self._http_reinit_lock:
            with self._http_lock:
                if self._http_session_id != expired_session_id:
                    if not self._initialized:
                        raise IOError(
                            f"[MCP:{self.name}] failed to reinitialize expired HTTP session"
                        )
                    return
                self._http_session_id = None

            if not self._handshake():
                raise IOError(
                    f"[MCP:{self.name}] failed to reinitialize expired HTTP session"
                )

    def _read_sse_response(self, resp, expected_id) -> dict:
        """Read an SSE stream and return the first JSON-RPC response with matching id."""
        data_buf: list = []
        for raw_line in resp:
            line = raw_line.decode("utf-8").rstrip("\n\r")
            if line == "":
                # SSE事件结束，尝试解析累积的数据
                if data_buf:
                    payload = "\n".join(data_buf)
                    data_buf = []
                    try:
                        msg = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    # 跳过通知消息以及 ID 不匹配的响应
                    if "id" not in msg:
                        continue
                    if expected_id is None or msg.get("id") == expected_id:
                        return msg
                continue
            if line.startswith(":"):
                continue  # SSE 注释/心跳行
            if line.startswith("data:"):
                data_buf.append(line[len("data:"):].lstrip())
            # 忽略 'event:' / 'id:' 行；我们只关心 JSON-RPC 负载

        raise IOError(f"[MCP:{self.name}] streamable-http SSE stream closed before response")

    # ------------------------------------------------------------------
    # 公共的 JSON-RPC 辅助方法
    # ------------------------------------------------------------------

    def _next_request_id(self) -> int:
        with self._id_lock:
            rid = self._next_id
            self._next_id += 1
        return rid

    def _build_request(self, method: str, params: dict) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": self._next_request_id(),
            "method": method,
            "params": params,
        }

    def _build_notification(self, method: str, params: dict) -> dict:
        return {"jsonrpc": "2.0", "method": method, "params": params}

    def _send_request(self, method: str, params: dict) -> dict:
        """Send a request and return the full response dict."""
        if not self._initialized and method != "initialize":
            raise RuntimeError(f"[MCP:{self.name}] Client not initialized")

        message = self._build_request(method, params)

        # stdio 传输共用一个管道，请求必须串行化。
        # SSE 与 Streamable-http 各自发送独立的 HTTP 请求，
        # 可以安全地跨会话并发运行。
        if self.transport == "stdio":
            with self._call_lock:
                return self._stdio_send(message)
        elif self.transport == "sse":
            return self._sse_send(message)
        elif self.transport == "streamable-http":
            return self._streamable_http_send(message)
        else:
            raise ValueError(f"[MCP:{self.name}] Unsupported transport: {self.transport}")

    def _send_notification(self, method: str, params: dict):
        """Fire-and-forget notification (no response expected)."""
        notification = self._build_notification(method, params)
        raw = json.dumps(notification) + "\n"

        if self.transport == "stdio":
            self._proc.stdin.write(raw)
            self._proc.stdin.flush()
        elif self.transport == "sse":
            body = raw.encode("utf-8")
            req = urllib.request.Request(
                self._post_url,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=10):
                    pass
            except Exception:
                pass  # 通知即发即忘，无需等待响应
        elif self.transport == "streamable-http":
            try:
                self._streamable_http_post(notification, expect_response=False)
            except Exception:
                pass  # 通知即发即忘，无需等待响应

    def _handshake(self) -> bool:
        """Perform the MCP initialize / notifications/initialized handshake."""
        init_params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "CowAgent", "version": "1.0"},
        }
        # 暂时标记为已初始化，以便 _send_request 不会阻塞
        self._initialized = True
        try:
            resp = self._send_request("initialize", init_params)
        except Exception as e:
            self._initialized = False
            logger.warning(f"[MCP:{self.name}] Handshake initialize failed: {e}")
            return False

        if "error" in resp:
            self._initialized = False
            logger.warning(f"[MCP:{self.name}] Handshake error: {resp['error']}")
            return False

        self._send_notification("notifications/initialized", {})
        logger.debug(f"[MCP:{self.name}] Handshake complete")
        return True


class McpClientRegistry:
    """Global singleton managing the lifecycle of all MCP Server clients."""

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                obj = super().__new__(cls)
                obj._clients: dict[str, McpClient] = {}
                obj._registry_lock = threading.Lock()
                # 进程级共享的已启动客户端池，以它们的“来源”配置为键。
                # 多个代理若解析到同一份共享 mcp.json，就会复用同一个子进程，
                # 而不是各自再分叉一份。
                # 键为 (mcp_json_path, server_name, config_signature)：
                # 自带 mcp.json 或使用不同 command/env 的代理会得到
                # 不同的键，从而彼此隔离。
                obj._shared_pool: dict[tuple, McpClient] = {}
                obj._shared_pool_lock = threading.Lock()
                # 按 key 加启动锁：当多个代理的加载线程同时发现
                # 同一台服务器不在池中时，只有其中一个会去创建子进程，
                # 其余线程等待并复用它（避免相互竞争、
                # 每个线程各启动一份）。
                obj._boot_locks: dict[tuple, threading.Lock] = {}
                cls._instance = obj
        return cls._instance

    @staticmethod
    def shared_key(mcp_json_path: str, server_name: str, cfg: dict) -> tuple:
        import json as _json
        try:
            sig = _json.dumps(cfg, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            sig = repr(cfg)
        return (mcp_json_path or "", server_name, sig)

    def get_shared_client(self, key: tuple):
        """Return a live pooled client for this exact config, or None. A client
        whose subprocess has died is dropped so the caller boots a fresh one."""
        with self._shared_pool_lock:
            client = self._shared_pool.get(key)
        if client is None:
            return None
        if not self._shared_client_alive(client):
            with self._shared_pool_lock:
                # 只驱逐我们判定已失效的那个对象；并发的重载逻辑
                # 可能已经在同一 key 下放入了新对象。
                if self._shared_pool.get(key) is client:
                    self._shared_pool.pop(key, None)
            return None
        return client

    def put_shared_client(self, key: tuple, client: "McpClient") -> None:
        with self._shared_pool_lock:
            self._shared_pool[key] = client

    def _boot_lock_for(self, key: tuple) -> "threading.Lock":
        with self._shared_pool_lock:
            lock = self._boot_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._boot_locks[key] = lock
            return lock

    def get_or_boot_shared(self, key: tuple, factory):
        """Return a pooled client for ``key``, booting it via ``factory`` if
        absent. Serialized per key so concurrent loader threads don't each fork
        a duplicate; distinct keys still boot in parallel.

        Returns (client, reused). ``client`` is None when ``factory`` failed to
        produce a usable client (e.g. init failed / needs auth); ``reused`` is
        True when an already-booted subprocess was handed back.
        """
        client = self.get_shared_client(key)
        if client is not None:
            return client, True
        with self._boot_lock_for(key):
            # 重新检查：在我们等待时另一个线程可能已经启动了它。
            client = self.get_shared_client(key)
            if client is not None:
                return client, True
            client = factory()
            if client is None:
                return None, False
            self.put_shared_client(key, client)
            return client, False

    @staticmethod
    def _shared_client_alive(client: "McpClient") -> bool:
        """Best-effort liveness: a stdio client whose child process has exited
        must not be reused. Unknown/remote transports are assumed alive."""
        proc = getattr(client, "_proc", None)
        if proc is not None and hasattr(proc, "poll"):
            try:
                return proc.poll() is None
            except Exception:
                return False
        return True

    def start_all(self, configs: list) -> None:
        """Initialize McpClient for each config entry; skip failures with a warning."""
        if not configs:
            return

        for cfg in configs:
            name = cfg.get("name", "<unnamed>")
            client = McpClient(cfg)
            ok = client.initialize()
            if ok:
                with self._registry_lock:
                    self._clients[name] = client
                logger.info(f"[MCP] Server '{name}' initialized successfully")
            else:
                logger.warning(f"[MCP] Server '{name}' failed to initialize — skipping")

    def get(self, server_name: str) -> Optional[McpClient]:
        """Return the initialized client for server_name, or None."""
        with self._registry_lock:
            return self._clients.get(server_name)

    def all_clients(self) -> dict:
        """Return a copy of the {name: McpClient} mapping."""
        with self._registry_lock:
            return dict(self._clients)

    def shutdown_all(self) -> None:
        """Shut down all managed clients."""
        with self._registry_lock:
            clients = list(self._clients.values())
            self._clients.clear()

        for client in clients:
            try:
                client.shutdown()
            except Exception as e:
                logger.warning(f"[MCP] Error shutting down '{client.name}': {e}")

        logger.info("[MCP] All servers shut down")
