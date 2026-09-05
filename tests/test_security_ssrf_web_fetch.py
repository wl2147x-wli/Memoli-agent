# 编码：utf-8
"""
Regression tests for web_fetch SSRF protection.

The web_fetch tool fetches model-supplied URLs. Without a guard, a model
(including one under prompt injection) can point it at loopback, RFC1918,
link-local or cloud-metadata (169.254.169.254) endpoints, or use a public
URL that 3xx-redirects into such a target. These tests ensure web_fetch
refuses the request instead of connecting to the internal address.

No real network is used: DNS resolution and ``requests.get`` are stubbed.
"""
import os
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 如果未安装，则存根“请求”，以便可以导入该模块进行测试。
if "requests" not in sys.modules:
    _requests_stub = types.ModuleType("requests")
    _requests_stub.get = lambda *a, **k: None

    class _Exc(Exception):
        pass

    _requests_stub.Timeout = type("Timeout", (_Exc,), {})
    _requests_stub.ConnectionError = type("ConnectionError", (_Exc,), {})
    _requests_stub.HTTPError = type("HTTPError", (_Exc,), {})
    _requests_stub.Response = object
    _compat = types.SimpleNamespace(urljoin=__import__("urllib.parse", fromlist=["urljoin"]).urljoin)
    _requests_stub.compat = _compat
    sys.modules["requests"] = _requests_stub


def _gai(ip_str):
    """Build a socket.getaddrinfo return value for a single IPv4 address."""
    return [(2, 1, 6, "", (ip_str, 0))]


class _FakeRedirect:
    """Minimal stand-in for a requests redirect Response."""

    def __init__(self, location):
        self.is_redirect = True
        self.is_permanent_redirect = False
        self.headers = {"Location": location}
        self.closed = False

    def close(self):
        self.closed = True


def _fake_ok_response(body=b"<html><head><title>internal</title></head><body>secret</body></html>"):
    """A well-formed non-redirect response.

    Returned by the mocked ``requests.get`` so that on UNPATCHED code the
    fetch path runs to completion and the test fails specifically on the
    ``assert_not_called`` guard (proving a request reached the internal
    target), rather than on an incidental error.
    """
    resp = MagicMock()
    resp.is_redirect = False
    resp.is_permanent_redirect = False
    resp.status_code = 200
    resp.headers = {"Content-Type": "text/html; charset=utf-8"}
    resp.content = body
    resp.text = body.decode("utf-8")
    resp.apparent_encoding = "utf-8"
    resp.raise_for_status = lambda: None
    return resp


class TestWebFetchSSRF(unittest.TestCase):
    """web_fetch must refuse internal targets and never connect to them.

    SSRF protection is opt-in (disabled by default), so these tests enable it
    via the WEB_SECURITY_SSRF_PROTECTION env var for the duration of the test.
    """

    def setUp(self):
        self._prev_ssrf_env = os.environ.get("WEB_SECURITY_SSRF_PROTECTION")
        os.environ["WEB_SECURITY_SSRF_PROTECTION"] = "true"
        from agent.tools.web_fetch.web_fetch import WebFetch
        self.tool = WebFetch()

    def tearDown(self):
        if self._prev_ssrf_env is None:
            os.environ.pop("WEB_SECURITY_SSRF_PROTECTION", None)
        else:
            os.environ["WEB_SECURITY_SSRF_PROTECTION"] = self._prev_ssrf_env

    # --- 文字内部 IP：在任何套接字调用之前被拒绝 ---

    def test_loopback_literal_blocked(self):
        """http://127.0.0.1:<port>/x must be refused, no request issued."""
        with patch("requests.get", return_value=_fake_ok_response()) as mock_get:
            result = self.tool.execute({"url": "http://127.0.0.1:8080/canary"})
        self.assertEqual(result.status, "error")
        self.assertIn("non-public", result.result)
        mock_get.assert_not_called()

    def test_cloud_metadata_literal_blocked(self):
        """http://169.254.169.254/latest/meta-data/ must be refused."""
        with patch("requests.get", return_value=_fake_ok_response()) as mock_get:
            result = self.tool.execute(
                {"url": "http://169.254.169.254/latest/meta-data/"}
            )
        self.assertEqual(result.status, "error")
        self.assertIn("non-public", result.result)
        mock_get.assert_not_called()

    def test_ipv6_loopback_literal_blocked(self):
        """http://[::1]/x must be refused."""
        with patch("requests.get", return_value=_fake_ok_response()) as mock_get:
            result = self.tool.execute({"url": "http://[::1]/canary"})
        self.assertEqual(result.status, "error")
        self.assertIn("non-public", result.result)
        mock_get.assert_not_called()

    # --- RFC1918 主机通过 DNS 解析：解析后被拒绝 ---

    def test_rfc1918_hostname_blocked(self):
        """A hostname that resolves to 10.x.x.x must be refused, no request."""
        with patch("socket.getaddrinfo", return_value=_gai("10.1.2.3")), \
                patch("requests.get", return_value=_fake_ok_response()) as mock_get:
            result = self.tool.execute({"url": "http://internal.corp/secret"})
        self.assertEqual(result.status, "error")
        self.assertIn("non-public", result.result)
        mock_get.assert_not_called()

    def test_192_168_hostname_blocked(self):
        """A hostname that resolves to 192.168.x.x must be refused."""
        with patch("socket.getaddrinfo", return_value=_gai("192.168.0.5")), \
                patch("requests.get", return_value=_fake_ok_response()) as mock_get:
            result = self.tool.execute({"url": "http://router.local/admin"})
        self.assertEqual(result.status, "error")
        self.assertIn("non-public", result.result)
        mock_get.assert_not_called()

    # --- 重定向退回：公共条目 URL 302 -> 环回 ---

    def test_public_to_loopback_redirect_blocked(self):
        """A public URL that redirects to a loopback target must be refused.

        The first hop resolves to a public IP and returns a 302 pointing at
        127.0.0.1; the guard must re-validate the redirect target and refuse
        instead of fetching the internal address.
        """
        redirect = _FakeRedirect("http://127.0.0.1:8080/canary")

        def fake_getaddrinfo(host, *a, **k):
            # 公共入口主机解析为公共IP；环回文字
            # 回显（就像真正的 getaddrinfo 对 IP 文字所做的那样）。
            if host == "evil.example.com":
                return _gai("93.184.216.34")
            return _gai(host)

        with patch("socket.getaddrinfo", side_effect=fake_getaddrinfo), \
                patch("requests.get", return_value=redirect) as mock_get:
            result = self.tool.execute({"url": "http://evil.example.com/start"})

        self.assertEqual(result.status, "error")
        self.assertIn("non-public", result.result)
        # 第一个（公共）跃点仅发布一次；环回跳是
        # 在第二次请求之前被警卫拒绝。进入内部
        # 目标已定。
        self.assertEqual(mock_get.call_count, 1)
        first_call_url = mock_get.call_args[0][0]
        self.assertEqual(first_call_url, "http://evil.example.com/start")
        # 从未向内部目标发出后续请求。
        for call in mock_get.call_args_list:
            self.assertNotIn("127.0.0.1", call[0][0])

    # --- 理智：允许公共 URL 继续访问获取路径 ---

    def test_public_url_allowed_through_guard(self):
        """A public URL passes the guard and a (mocked) request is issued."""
        ok = MagicMock()
        ok.is_redirect = False
        ok.is_permanent_redirect = False
        ok.headers = {"Content-Type": "text/html; charset=utf-8"}
        ok.content = b"<html><head><title>Hi</title></head><body>ok</body></html>"
        ok.text = "<html><head><title>Hi</title></head><body>ok</body></html>"
        ok.apparent_encoding = "utf-8"
        ok.raise_for_status = lambda: None

        with patch("socket.getaddrinfo", return_value=_gai("93.184.216.34")), \
                patch("requests.get", return_value=ok) as mock_get:
            result = self.tool.execute({"url": "http://example.com/page"})

        self.assertEqual(result.status, "success")
        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args[0][0], "http://example.com/page")


class TestWebFetchSSRFDisabledByDefault(unittest.TestCase):
    """With protection disabled (default), local/internal targets are reachable."""

    def setUp(self):
        self._prev_ssrf_env = os.environ.get("WEB_SECURITY_SSRF_PROTECTION")
        os.environ.pop("WEB_SECURITY_SSRF_PROTECTION", None)
        from agent.tools.web_fetch.web_fetch import WebFetch
        self.tool = WebFetch()

    def tearDown(self):
        if self._prev_ssrf_env is None:
            os.environ.pop("WEB_SECURITY_SSRF_PROTECTION", None)
        else:
            os.environ["WEB_SECURITY_SSRF_PROTECTION"] = self._prev_ssrf_env

    def test_loopback_allowed_when_disabled(self):
        """http://127.0.0.1/x must be fetched when protection is off (default)."""
        with patch("socket.getaddrinfo", return_value=_gai("127.0.0.1")), \
                patch("requests.get", return_value=_fake_ok_response()) as mock_get:
            result = self.tool.execute({"url": "http://127.0.0.1:8080/local"})
        self.assertEqual(result.status, "success")
        mock_get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
