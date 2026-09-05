# 编码：utf-8

"""
Lightweight HTTP client for OpenAI-compatible APIs.

This client is a drop-in replacement for the parts of the `openai` SDK that this
project actually uses (chat completions, completions, image generation), so we
can drop the hard dependency on `openai==0.27.x`.

Design goals:
- Pure `requests` based (no httpx / pydantic / openai SDK dependency).
- Returns plain `dict` responses with the same shape OpenAI's HTTP API returns,
  so existing code that does `response["choices"][0]["message"]["content"]` /
  `response["usage"]["total_tokens"]` keeps working.
- Streaming yields plain `dict` chunks (parsed SSE `data:` JSON), matching the
  shape that `agent/protocol/agent_stream.py` consumes:
    chunk["choices"][0]["delta"]["content" | "tool_calls" | "reasoning_content"]
    chunk["choices"][0]["finish_reason"]
  Plus dict-style error chunks: {"error": True, "message": ..., "status_code": ...}
- Compatible with arbitrary OpenAI-compatible endpoints (LinkAI, Azure-style
  proxies, DeepSeek, Moonshot, etc.) by allowing per-call api_key / api_base
  override and trusting whatever path/payload shape the caller passes.
"""

import json
import os
from typing import Any, Dict, Generator, Optional
from urllib.parse import urlparse

import requests

from common.log import logger


DEFAULT_API_BASE = "https://api.openai.com/v1"
DEFAULT_TIMEOUT = 600  # 秒；匹配旧的 openai SDK 默认值


_APP_TITLE = "CowAgent"
_APP_REFERER = "https://github.com/zhayujie/CowAgent"


# 可选的客户端源标签。只发送到下面带有源标记的主机，所以不会
# 客户端身份泄露给用户自己的代理。
_SOURCE_HEADER = "X-Client-Source"

# 每个网关应用程序归因标头，仅在请求主机时发送
# 与记录的网关匹配。将这些发送到用户配置的自定义
# 代理会泄露应用程序身份，因此我们通过主机后缀进行调度。
_ATTRIBUTION_HEADERS_BY_HOST: Dict[str, Dict[str, str]] = {
    "openrouter.ai": {
        "HTTP-Referer": _APP_REFERER,
        "X-Title": _APP_TITLE,
    },
    "ai-gateway.vercel.sh": {
        "HTTP-Referer": _APP_REFERER,
        "X-Title": _APP_TITLE,
    },
    "link-ai.tech": {
        "X-Title": _APP_TITLE,
    },
}

# 还接收客户端源标记的主机。而是根据请求解决
# 比烘焙到上表中，因此导入后设置的 COW_DESKTOP 是有效的。
_SOURCE_TAGGED_HOSTS = ("link-ai.tech",)


def _resolve_attribution_headers(url: str) -> Dict[str, str]:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return {}
    if not host:
        return {}
    for suffix, headers in _ATTRIBUTION_HEADERS_BY_HOST.items():
        if host == suffix or host.endswith("." + suffix):
            resolved = dict(headers)
            if any(host == h or host.endswith("." + h) for h in _SOURCE_TAGGED_HOSTS):
                try:
                    from common.utils import apply_client_source
                    apply_client_source(resolved)
                except Exception:
                    resolved[_SOURCE_HEADER] = (
                        "desktop" if os.environ.get("COW_DESKTOP") == "1" else "open-source"
                    )
            return resolved
    return {}


class OpenAIHTTPError(Exception):
    """Raised for non-2xx responses. Carries status code + parsed body."""

    def __init__(self, status_code: int, body: Any, message: str = ""):
        self.status_code = status_code
        self.body = body
        # 尝试从 OpenAI 风格的错误信封中提取人类可读的消息
        if not message and isinstance(body, dict):
            err = body.get("error") or {}
            if isinstance(err, dict):
                message = err.get("message") or ""
            elif isinstance(err, str):
                message = err
        if not message:
            message = str(body)[:500]
        self.message = message
        super().__init__(f"HTTP {status_code}: {message}")


class OpenAIHTTPClient:
    """Minimal HTTP client for OpenAI-compatible endpoints.

    Per-instance defaults (api_key / api_base / proxy / timeout) can be
    overridden on every call. Callers can also pass ``extra_headers`` for
    Azure-style ``api-key`` headers or custom routing headers.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        proxy: Optional[str] = None,
        timeout: Optional[float] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        self.api_key = api_key
        self.api_base = (api_base or DEFAULT_API_BASE).rstrip("/")
        self.timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        self.proxies = (
            {"http": proxy, "https": proxy} if proxy else None
        )
        self.extra_headers = dict(extra_headers) if extra_headers else {}

    # ------------------------------------------------------------------ #
    # 公共API接口（镜像旧的openai SDK提供的内容）
    # ------------------------------------------------------------------ #

    def chat_completions(
        self,
        *,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: Optional[float] = None,
        proxy: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        extra_query: Optional[Dict[str, str]] = None,
        path: str = "/chat/completions",
        stream: bool = False,
        **payload,
    ):
        """POST /chat/completions.

        When ``stream=True`` returns a generator yielding parsed SSE chunks
        (plain ``dict``). On error during streaming, yields a single dict with
        ``{"error": True, ...}`` and stops, matching the contract expected by
        ``agent/protocol/agent_stream.py``.
        """
        payload["stream"] = stream
        return self._request(
            path=path,
            payload=payload,
            api_key=api_key,
            api_base=api_base,
            timeout=timeout,
            proxy=proxy,
            extra_headers=extra_headers,
            extra_query=extra_query,
            stream=stream,
        )

    def completions(
        self,
        *,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: Optional[float] = None,
        **payload,
    ) -> Dict[str, Any]:
        """POST /completions (legacy text completion). Non-streaming only."""
        payload.pop("stream", None)
        return self._request(
            path="/completions",
            payload=payload,
            api_key=api_key,
            api_base=api_base,
            timeout=timeout,
            stream=False,
        )

    def images_generate(
        self,
        *,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        timeout: Optional[float] = None,
        **payload,
    ) -> Dict[str, Any]:
        """POST /images/generations."""
        return self._request(
            path="/images/generations",
            payload=payload,
            api_key=api_key,
            api_base=api_base,
            timeout=timeout,
            stream=False,
        )

    # ------------------------------------------------------------------ #
    # 内部辅助函数
    # ------------------------------------------------------------------ #

    def _build_headers(
        self,
        api_key: Optional[str],
        extra_headers: Optional[Dict[str, str]],
        url: Optional[str] = None,
    ) -> Dict[str, str]:
        key = api_key if api_key is not None else self.api_key
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        if url:
            attribution = _resolve_attribution_headers(url)
            if attribution:
                headers.update(attribution)
        if self.extra_headers:
            headers.update(self.extra_headers)
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _request(
        self,
        *,
        path: str,
        payload: Dict[str, Any],
        api_key: Optional[str],
        api_base: Optional[str],
        timeout: Optional[float],
        stream: bool,
        proxy: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        extra_query: Optional[Dict[str, str]] = None,
    ):
        base = (api_base or self.api_base).rstrip("/") if api_base else self.api_base
        url = f"{base}{path}" if path.startswith("/") else f"{base}/{path}"
        headers = self._build_headers(api_key, extra_headers, url=url)
        req_timeout = timeout if timeout is not None else self.timeout
        proxies = (
            {"http": proxy, "https": proxy} if proxy else self.proxies
        )

        # 删除无值键；一些提供商拒绝显式空值。
        clean_payload = {k: v for k, v in payload.items() if v is not None}

        if stream:
            # 返回一个发电机。流期间的错误作为单个错误产生
            # 错误块，以便调用者（agent_stream）可以将它们映射到他们的
            # 现有的错误处理路径，无需 try/ except 循环。
            return self._stream_chat(
                url=url,
                headers=headers,
                payload=clean_payload,
                proxies=proxies,
                timeout=req_timeout,
                params=extra_query,
            )

        try:
            resp = requests.post(
                url,
                headers=headers,
                json=clean_payload,
                timeout=req_timeout,
                proxies=proxies,
                params=extra_query,
            )
        except requests.exceptions.Timeout as e:
            raise OpenAIHTTPError(408, {}, f"Request timed out: {e}")
        except requests.exceptions.ConnectionError as e:
            raise OpenAIHTTPError(0, {}, f"Connection error: {e}")
        except requests.exceptions.RequestException as e:
            raise OpenAIHTTPError(0, {}, f"Request failed: {e}")

        return self._parse_response(resp)

    @staticmethod
    def _parse_response(resp: requests.Response) -> Dict[str, Any]:
        # 尝试 JSON，回到文本
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text}

        if resp.status_code >= 400:
            raise OpenAIHTTPError(resp.status_code, data)

        return data

    def _stream_chat(
        self,
        *,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        proxies: Optional[Dict[str, str]],
        timeout: float,
        params: Optional[Dict[str, str]] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """Stream SSE response and yield parsed JSON chunks.

        Yields:
            - Normal chunks: dict with ``choices[0].delta`` etc.
            - Error chunks: ``{"error": True, "message": str, "status_code": int}``
              followed by termination of the generator.
        """
        try:
            resp = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout,
                proxies=proxies,
                stream=True,
                params=params,
            )
        except requests.exceptions.Timeout as e:
            yield self._make_error_chunk(408, f"Request timed out: {e}")
            return
        except requests.exceptions.ConnectionError as e:
            yield self._make_error_chunk(0, f"Connection error: {e}")
            return
        except requests.exceptions.RequestException as e:
            yield self._make_error_chunk(0, f"Request failed: {e}")
            return

        if resp.status_code >= 400:
            # 阅读全文一次以获取错误报告
            try:
                body = resp.json()
            except ValueError:
                body = {"raw": resp.text[:1000]}
            err_msg = ""
            err_code = ""
            err_type = ""
            if isinstance(body, dict):
                err = body.get("error") or {}
                if isinstance(err, dict):
                    err_msg = err.get("message") or ""
                    err_code = err.get("code") or ""
                    err_type = err.get("type") or ""
                elif isinstance(err, str):
                    err_msg = err
            if not err_msg:
                err_msg = str(body)[:500]
            yield {
                "error": {
                    "message": err_msg,
                    "code": err_code,
                    "type": err_type,
                },
                # 保留顶级字段以向后兼容
                # `_handle_stream_response` 之前发出的错误形状。
                "message": err_msg,
                "status_code": resp.status_code,
            }
            return

        # 重要提示：请勿使用 `iter_lines(decode_unicode=True)`。
        #
        # `requests` 使用响应声明的每个网络块进行解码
        # 编码（通常用于 SSE 的 Latin-1 / ISO-8859-1），它会破坏 UTF-8
        # 跨越块边界的代码点。一些上游（Azure
        # OpenAI 代理、Cloudflare 前端网关...）分割 TCP 块
        # 积极地在多字节字符中间，产生
        # 乱码文本和“跳过格式错误的 SSE 块”错误。
        #
        # 解决方法是读取原始字节，累积它们直到我们有一个
        # 完整的 SSE 事件（根据 SSE 规范以空行终止：
        # https://html.spec.whatwg.org/multipage/server-sent-events.html),
        # 然后才解码为 UTF-8。这反映了官方的说法
        # openai SDK 1.x 在 `openai/_streaming.py::SSEDecoder` 中执行（其中
        # 本身是从 httpx-sse 复制的）。
        try:
            for sse_event in self._iter_sse_events(resp):
                # `sse_event` 是连接的 `data:` 负载作为 str。
                if sse_event == "[DONE]":
                    return
                if not sse_event:
                    continue
                try:
                    chunk = json.loads(sse_event)
                except ValueError:
                    logger.debug(
                        f"[OpenAIHTTP] skip malformed SSE chunk: {sse_event[:200]}"
                    )
                    continue
                yield chunk
        except requests.exceptions.ChunkedEncodingError as e:
            yield self._make_error_chunk(0, f"Stream interrupted: {e}")
        except requests.exceptions.RequestException as e:
            yield self._make_error_chunk(0, f"Stream error: {e}")
        finally:
            try:
                resp.close()
            except Exception:
                pass

    @staticmethod
    def _iter_sse_events(resp: requests.Response) -> Generator[str, None, None]:
        """Decode an SSE byte stream into joined `data:` payloads.

        Implements the subset of the SSE spec that OpenAI / OpenAI-compatible
        endpoints actually use:
          - Events are separated by blank lines (\\r\\r, \\n\\n, or \\r\\n\\r\\n).
          - Within an event, multiple ``data:`` lines are concatenated with
            "\\n" (per spec).
          - ``event:``, ``id:``, ``retry:`` and comment lines (``:``) are
            tolerated but not yielded — for chat-completion we only care
            about the JSON payload in ``data:``.
          - Bytes are buffered until a complete event boundary is seen so
            UTF-8 codepoints split across TCP chunks decode correctly.

        Yields each event's joined ``data`` string. The terminal sentinel
        ``[DONE]`` is yielded as a literal string so the caller can break.
        """
        buf = b""
        for raw in resp.iter_content(chunk_size=None, decode_unicode=False):
            if not raw:
                continue
            buf += raw
            # 查找完整的事件（以空行终止）。
            while True:
                # 寻找最早的事件终止者。上交所允许三
                # 表格；检查所有并选择最早的匹配项。
                idx_nn = buf.find(b"\n\n")
                idx_rr = buf.find(b"\r\r")
                idx_rnrn = buf.find(b"\r\n\r\n")
                candidates = [i for i in (idx_nn, idx_rr, idx_rnrn) if i != -1]
                if not candidates:
                    break
                # 我们需要知道匹配的终止符的长度
                # 正确地前进过去。
                end_pos = min(candidates)
                if end_pos == idx_rnrn:
                    term_len = 4
                else:
                    term_len = 2
                event_bytes = buf[:end_pos]
                buf = buf[end_pos + term_len:]

                # 将完整事件解码为 UTF-8。 ``errors="replace"`` 是
                # 针对真正畸形上游的安全网
                # 字节；对于格式良好的提供者来说，它永远不应该触发。
                try:
                    event_text = event_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    event_text = event_bytes.decode("utf-8", errors="replace")

                data_lines = []
                for line in event_text.splitlines():
                    if not line or line.startswith(":"):
                        continue
                    field, _, value = line.partition(":")
                    # 根据 SSE 规范，冒号后有一个可选空格
                    # 是框架的一部分，而不是价值。
                    if value.startswith(" "):
                        value = value[1:]
                    if field == "data":
                        data_lines.append(value)
                    # 其他字段（事件/ID/重试）被故意忽略
                    # - 聊天完成端点不以我们的方式使用它们
                    # 需要解析。
                if data_lines:
                    yield "\n".join(data_lines)

        # 刷新服务器忘记终止的所有尾随字节。这是
        # 罕见但规范允许（某些提供商省略了最后的 \n\n）。
        if buf.strip():
            try:
                event_text = buf.decode("utf-8")
            except UnicodeDecodeError:
                event_text = buf.decode("utf-8", errors="replace")
            data_lines = []
            for line in event_text.splitlines():
                if not line or line.startswith(":"):
                    continue
                field, _, value = line.partition(":")
                if value.startswith(" "):
                    value = value[1:]
                if field == "data":
                    data_lines.append(value)
            if data_lines:
                yield "\n".join(data_lines)

    @staticmethod
    def _make_error_chunk(status_code: int, message: str) -> Dict[str, Any]:
        return {
            "error": {"message": message, "code": "", "type": ""},
            "message": message,
            "status_code": status_code,
        }


# 一个小帮手，适合只需要一次性客户端而不需要存储的呼叫者
# 状态。与每次实例化类相比，使调用站点更加干净。
def get_default_client(
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    proxy: Optional[str] = None,
    timeout: Optional[float] = None,
) -> OpenAIHTTPClient:
    return OpenAIHTTPClient(
        api_key=api_key, api_base=api_base, proxy=proxy, timeout=timeout
    )
