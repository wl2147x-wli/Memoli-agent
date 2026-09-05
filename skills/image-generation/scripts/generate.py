#!/usr/bin/env python3
"""
Unified image generation script.

Usage:
    python generate.py '<json_args>'

Supported model families (each provider is tried in priority order:
OpenAI → Gemini → Seedream → Qwen → MiniMax → LinkAI; missing API keys
are skipped, and the provider that natively owns the requested model is
promoted to the front of the queue):

    - gpt-image-2 / gpt-image-1                    → OpenAI
    - nano-banana / gemini-*-image-*               → Gemini
    - doubao-seedream-* / seedream-*               → Seedream (Volcengine Ark)
    - qwen-image-2.0 / qwen-image-2.0-pro / etc.   → Qwen (DashScope)
    - image-01 / minimax-image                     → MiniMax
    - any model                                    → LinkAI (universal proxy)

Dependencies: requests (stdlib: json, sys, os, base64, io, abc, uuid, pathlib, urllib)
"""

import json
import sys
import os
import base64
import io
import time
import uuid
import re
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlparse
from urllib.error import URLError

try:
    import requests

    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


# ---------------------------------------------------------------------------
# 尺寸/纵横比分辨率
# ---------------------------------------------------------------------------

_SIZE_TABLE = {
    # （层，比率）->“宽x高”
    ("1K", "1:1"): "1024x1024",
    ("1K", "3:2"): "1536x1024",
    ("1K", "2:3"): "1024x1536",
    ("2K", "1:1"): "2048x2048",
    ("2K", "16:9"): "2048x1152",
    ("2K", "9:16"): "1152x2048",
    ("4K", "16:9"): "3840x2160",
    ("4K", "9:16"): "2160x3840",
}

_TIER_ORDER = ["1K", "2K", "4K"]
_RATIO_DEFAULT = {"1K": "1:1", "2K": "1:1", "4K": "16:9"}

_PIXEL_RE = re.compile(r"^\d+x\d+$")


def resolve_size(size: str | None, aspect_ratio: str | None) -> str | None:
    """Resolve (size, aspect_ratio) to a concrete 'WxH' string or None."""
    if size and _PIXEL_RE.match(size):
        return size
    if size and size.lower() == "auto":
        size = None
    if not size and not aspect_ratio:
        return None

    tier = size.upper() if size else None
    ratio = aspect_ratio

    if tier and ratio:
        key = (tier, ratio)
        if key in _SIZE_TABLE:
            return _SIZE_TABLE[key]
        # 升级：以相同比例尝试更高级别
        start = _TIER_ORDER.index(tier) + 1 if tier in _TIER_ORDER else 0
        for t in _TIER_ORDER[start:]:
            if (t, ratio) in _SIZE_TABLE:
                return _SIZE_TABLE[(t, ratio)]
        # 跨层：具有此比例的任何层
        for t in _TIER_ORDER:
            if (t, ratio) in _SIZE_TABLE:
                return _SIZE_TABLE[(t, ratio)]
        # 等级默认值
        if tier in _RATIO_DEFAULT:
            return _SIZE_TABLE.get((tier, _RATIO_DEFAULT[tier]))

    if tier and not ratio:
        default_ratio = _RATIO_DEFAULT.get(tier)
        if default_ratio:
            return _SIZE_TABLE.get((tier, default_ratio))

    if ratio and not tier:
        for t in _TIER_ORDER:
            if (t, ratio) in _SIZE_TABLE:
                return _SIZE_TABLE[(t, ratio)]

    return None


# ---------------------------------------------------------------------------
# 图像助手
# ---------------------------------------------------------------------------

def _load_image(source: str) -> bytes:
    """Load image from a local file path or URL."""
    if os.path.isfile(source):
        with open(source, "rb") as f:
            return f.read()
    if _HAS_REQUESTS:
        resp = requests.get(source, timeout=60)
        resp.raise_for_status()
        return resp.content
    req = Request(source)
    with urlopen(req, timeout=60) as resp:
        return resp.read()


def _compress_image(data: bytes, max_bytes: int = 4 * 1024 * 1024, max_edge: int = 4096) -> bytes:
    """Compress image to fit size/dimension limits. Requires Pillow only when needed."""
    if len(data) <= max_bytes:
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(data))
            w, h = img.size
            if max(w, h) <= max_edge:
                return data
        except ImportError:
            return data
        except Exception:
            return data

    try:
        from PIL import Image
    except ImportError:
        return data

    img = Image.open(io.BytesIO(data))
    w, h = img.size

    if max(w, h) > max_edge:
        ratio = max_edge / max(w, h)
        w, h = int(w * ratio), int(h * ratio)
        img = img.resize((w, h), Image.LANCZOS)

    buf = io.BytesIO()
    fmt = img.format or "PNG"
    if fmt.upper() == "JPEG":
        quality = 85
        while True:
            buf.seek(0)
            buf.truncate()
            img.save(buf, format="JPEG", quality=quality)
            if buf.tell() <= max_bytes or quality <= 20:
                break
            quality -= 10
    else:
        img.save(buf, format=fmt)
        if buf.tell() > max_bytes:
            buf.seek(0)
            buf.truncate()
            img.save(buf, format="JPEG", quality=75)
    return buf.getvalue()


def _save_image(data: bytes, output_dir: str) -> str:
    """Save image bytes to output_dir and return the path."""
    os.makedirs(output_dir, exist_ok=True)
    ext = "png"
    if data[:3] == b"\xff\xd8\xff":
        ext = "jpg"
    elif data[:4] == b"RIFF":
        ext = "webp"
    filename = f"{uuid.uuid4().hex[:12]}.{ext}"
    path = os.path.join(output_dir, filename)
    with open(path, "wb") as f:
        f.write(data)
    return path


def _apply_attribution_headers(headers: dict) -> None:
    """Forward run/source attribution passed down by the parent agent via env.

    Kept local to this script so it stays self-contained; only invoked for the
    first-party provider so identifiers never leak to third-party vendors.
    """
    mapping = {
        "COW_AGENT_RUN_ID": "X-Agent-Run-Id",
        "COW_CLIENT_SOURCE": "X-Client-Source",
        "COW_CLIENT_OS": "X-Client-OS",
        "COW_CLIENT_VERSION": "X-Client-Version",
        "COW_DEPLOYMENT_ID": "X-Deployment-Id",
    }
    for env_name, header in mapping.items():
        value = (os.environ.get(env_name) or "").strip()
        if value:
            headers[header] = value


# ---------------------------------------------------------------------------
# 提供者接口
# ---------------------------------------------------------------------------

class ImageProvider(ABC):
    """Abstract base class for image generation providers."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        image_url: str | list | None = None,
        quality: str | None = None,
        size: str | None = None,
        aspect_ratio: str | None = None,
        output_dir: str = ".",
    ) -> list[str]:
        """Generate image(s) and return list of local file paths.

        `size` may be a tier ("1K" / "2K" / "4K" / "512") or pixels ("WxH").
        Providers that need pixel sizes should call `resolve_size(size, aspect_ratio)`.
        """
        ...


# ---------------------------------------------------------------------------
# OpenAI 兼容提供程序（gpt-image-2、gpt-image-1）
# ---------------------------------------------------------------------------

class OpenAIProvider(ImageProvider):
    """Provider for OpenAI Image API (generations + edits)."""

    DEFAULT_MODEL = "gpt-image-2"

    def __init__(self, api_key: str, api_base: str, model: str):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model or self.DEFAULT_MODEL

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
        }

    @staticmethod
    def _raise_for_api_error(resp):
        """Raise with server error details instead of bare HTTP status."""
        if resp.status_code >= 400:
            try:
                body = resp.json()
                msg = body.get("error", {}).get("message") or body.get("message") or resp.text
            except Exception:
                msg = resp.text or resp.reason
            raise RuntimeError(f"API {resp.status_code}: {msg} (url: {resp.url})")

    @staticmethod
    def _raise_for_business_error(result: dict):
        """Raise for OpenAI-compatible backends that report business errors
        with HTTP 200 plus an `error` field (e.g. LinkAI, Volcengine Ark)."""
        if isinstance(result, dict) and result.get("error"):
            err = result["error"]
            if isinstance(err, dict):
                msg = err.get("message") or err.get("code") or str(err)
            else:
                msg = str(err)
            raise RuntimeError(f"API error: {msg}")

    def _post_json(self, url: str, payload: dict) -> dict:
        headers = {**self._headers(), "Content-Type": "application/json"}
        if _HAS_REQUESTS:
            resp = requests.post(url, headers=headers, json=payload, timeout=300)
            self._raise_for_api_error(resp)
            result = resp.json()
        else:
            data = json.dumps(payload).encode()
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=300) as r:
                result = json.loads(r.read())
        self._raise_for_business_error(result)
        return result

    def _post_multipart(self, url: str, fields: dict, files: list[tuple]) -> dict:
        """POST multipart/form-data using requests (or fall back to urllib)."""
        headers = self._headers()
        if _HAS_REQUESTS:
            resp = requests.post(url, headers=headers, data=fields, files=files, timeout=300)
            self._raise_for_api_error(resp)
            result = resp.json()
            self._raise_for_business_error(result)
            return result
        boundary = uuid.uuid4().hex
        body = b""
        for key, val in fields.items():
            body += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{val}\r\n".encode()
        for field_name, (filename, filedata, content_type) in files:
            body += (
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"{field_name}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode() + filedata + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        req = Request(url, data=body, headers=headers, method="POST")
        with urlopen(req, timeout=300) as r:
            result = json.loads(r.read())
        self._raise_for_business_error(result)
        return result

    def generate(
        self,
        prompt: str,
        *,
        image_url=None,
        quality: str | None = None,
        size: str | None = None,
        aspect_ratio: str | None = None,
        output_dir: str = ".",
    ) -> list[str]:
        # OpenAI Images API 期望像素大小为 1024x1024。
        resolved = resolve_size(size, aspect_ratio) if (size or aspect_ratio) else None
        if image_url:
            paths = self._edit(prompt, image_url=image_url, quality=quality, size=resolved, output_dir=output_dir)
        else:
            paths = self._create(prompt, quality=quality, size=resolved, output_dir=output_dir)
        if not paths:
            raise RuntimeError("provider returned no image (empty data)")
        return paths

    def _create(self, prompt: str, *, quality: str | None, size: str | None, output_dir: str) -> list[str]:
        url = f"{self.api_base}/images/generations"
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
        }
        if quality:
            payload["quality"] = quality
        if size:
            payload["size"] = size
        result = self._post_json(url, payload)
        return self._save_results(result, output_dir)

    def _edit(
        self,
        prompt: str,
        *,
        image_url,
        quality: str | None,
        size: str | None,
        output_dir: str,
    ) -> list[str]:
        urls = image_url if isinstance(image_url, list) else [image_url]
        image_data_list = [_compress_image(_load_image(u)) for u in urls]

        url = f"{self.api_base}/images/edits"

        fields = {"model": self.model, "prompt": prompt}
        if quality:
            fields["quality"] = quality
        if size:
            fields["size"] = size

        files = []
        for i, img_bytes in enumerate(image_data_list):
            ext = "png"
            if img_bytes[:3] == b"\xff\xd8\xff":
                ext = "jpg"
            field_name = "image[]" if len(image_data_list) > 1 else "image"
            files.append((field_name, (f"image_{i}.{ext}", img_bytes, f"image/{ext}")))

        result = self._post_multipart(url, fields, files)
        return self._save_results(result, output_dir)

    @staticmethod
    def _save_results(result: dict, output_dir: str) -> list[str]:
        paths = []
        for item in result.get("data", []):
            if "b64_json" in item:
                raw = base64.b64decode(item["b64_json"])
                paths.append(_save_image(raw, output_dir))
            elif "url" in item:
                raw = _load_image(item["url"])
                paths.append(_save_image(raw, output_dir))
        return paths


# ---------------------------------------------------------------------------
# LinkAI 提供程序（使用统一的 /v1/images/ Generations）
# ---------------------------------------------------------------------------

class LinkAIProvider(ImageProvider):
    """Provider for LinkAI unified image generation API."""

    DEFAULT_MODEL = "gpt-image-2"

    def __init__(self, api_key: str, api_base: str, model: str):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model or self.DEFAULT_MODEL

    def generate(
        self,
        prompt: str,
        *,
        image_url=None,
        quality: str | None = None,
        size: str | None = None,
        aspect_ratio: str | None = None,
        output_dir: str = ".",
    ) -> list[str]:
        url = f"{self.api_base}/v1/images/generations"
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
        }
        if quality:
            payload["quality"] = quality
        # LinkAI 接受像素大小 (1024x1024) 和层简写 (1K/2K/4K)。
        # 传递调用者给我们的任何内容；还向前纵横比。
        if size:
            payload["size"] = size
        if aspect_ratio:
            payload["aspect_ratio"] = aspect_ratio
        if image_url:
            urls = image_url if isinstance(image_url, list) else [image_url]
            resolved = []
            for u in urls:
                if os.path.isfile(u):
                    data = _load_image(u)
                    ext = u.rsplit(".", 1)[-1].lower() if "." in u else "png"
                    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")
                    resolved.append(f"data:{mime};base64,{base64.b64encode(data).decode()}")
                else:
                    resolved.append(u)
            payload["image_url"] = resolved if len(resolved) > 1 else resolved[0]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # 归因标头，以便此进程外调用加入与以下相同的运行
        # 它的父代理。仅发送给 LinkAI（此提供商），绝不会发送给其他
        # 供应商。值通过环境变量从代理转发。
        _apply_attribution_headers(headers)

        if _HAS_REQUESTS:
            resp = requests.post(url, headers=headers, json=payload, timeout=300)
            if resp.status_code >= 400:
                try:
                    body = resp.json()
                    msg = body.get("error", {}).get("message") or body.get("message") or resp.text
                except Exception:
                    msg = resp.text or resp.reason
                raise RuntimeError(f"API {resp.status_code}: {msg}")
            result = resp.json()
        else:
            data = json.dumps(payload).encode()
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=300) as r:
                result = json.loads(r.read())

        if "error" in result:
            raise RuntimeError(result["error"].get("message", str(result["error"])))

        paths = []
        for item in result.get("data", []):
            if "url" in item:
                raw = _load_image(item["url"])
                paths.append(_save_image(raw, output_dir))
            elif "b64_json" in item:
                raw = base64.b64decode(item["b64_json"])
                paths.append(_save_image(raw, output_dir))
        return paths


# ---------------------------------------------------------------------------
# Gemini 提供商（纳米香蕉家族 —gemini-*-image-*）
# ---------------------------------------------------------------------------

# 友好的别名 → 真正的 Gemini 型号 id
_GEMINI_MODEL_ALIASES = {
    "nano-banana": "gemini-2.5-flash-image",
    "nano-banana-2": "gemini-3.1-flash-image-preview",
    "nano-banana-pro": "gemini-3-pro-image-preview",
}


class GeminiProvider(ImageProvider):
    """Provider for Google Gemini native image generation (Nano Banana family)."""

    DEFAULT_MODEL = "gemini-3.1-flash-image-preview"  # nano-banana-2

    def __init__(self, api_key: str, api_base: str, model: str):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = _GEMINI_MODEL_ALIASES.get(model, model or self.DEFAULT_MODEL)

    def generate(
        self,
        prompt: str,
        *,
        image_url=None,
        quality: str | None = None,  # 未使用； Gemini 没有 `quality` 参数
        size: str | None = None,
        aspect_ratio: str | None = None,
        output_dir: str = ".",
    ) -> list[str]:
        # 构建请求部分：提示文本+可选的内嵌图像
        parts: list[dict] = [{"text": prompt}]
        if image_url:
            urls = image_url if isinstance(image_url, list) else [image_url]
            for u in urls:
                data = _compress_image(_load_image(u))
                mime = _guess_mime(data)
                parts.append({
                    "inline_data": {
                        "mime_type": mime,
                        "data": base64.b64encode(data).decode(),
                    }
                })

        payload: dict = {
            "contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }

        # Gemini 原生支持宽高比 + imageSize 层 (512/1K/2K/4K)。
        _GEMINI_VALID_TIERS = {"512", "1K", "2K", "4K"}
        _GEMINI_TIER_FALLBACK = {"3K": "2K"}
        image_config: dict = {}
        if size:
            if "x" in size.lower():
                tier = _pixels_to_tier(size)
            else:
                tier = size.upper()
            tier = _GEMINI_TIER_FALLBACK.get(tier, tier)
            if tier in _GEMINI_VALID_TIERS:
                image_config["imageSize"] = tier
        if aspect_ratio:
            image_config["aspectRatio"] = aspect_ratio
        elif size and "x" in size.lower():
            ratio = _pixels_to_ratio(size)
            if ratio:
                image_config["aspectRatio"] = ratio
        if image_config:
            payload["generationConfig"]["imageConfig"] = image_config

        url = f"{self.api_base}/v1beta/models/{self.model}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        if _HAS_REQUESTS:
            resp = requests.post(url, headers=headers, json=payload, timeout=300)
            if resp.status_code >= 400:
                try:
                    body = resp.json()
                    msg = body.get("error", {}).get("message") or resp.text
                except Exception:
                    msg = resp.text or resp.reason
                raise RuntimeError(f"API {resp.status_code}: {msg}")
            result = resp.json()
        else:
            data = json.dumps(payload).encode()
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=300) as r:
                result = json.loads(r.read())

        return self._extract_images(result, output_dir)

    @staticmethod
    def _extract_images(result: dict, output_dir: str) -> list[str]:
        paths: list[str] = []
        for cand in result.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                if part.get("thought"):
                    continue  # 跳过思考阶段临时图像
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    raw = base64.b64decode(inline["data"])
                    paths.append(_save_image(raw, output_dir))
        if not paths:
            # 展示模特的文字回复（通常是拒绝的解释）
            for cand in result.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    if part.get("text"):
                        raise RuntimeError(f"Gemini returned no image: {part['text'][:200]}")
            raise RuntimeError("Gemini returned no image (empty response)")
        return paths


def _guess_mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF":
        return "image/webp"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/png"


def _pixels_to_tier(pixel_str: str) -> str:
    """Map 'WxH' to nearest Gemini tier (512 / 1K / 2K / 4K)."""
    try:
        w, h = (int(x) for x in pixel_str.lower().split("x"))
        long_edge = max(w, h)
    except Exception:
        return "1K"
    if long_edge <= 768:
        return "512"
    if long_edge <= 1536:
        return "1K"
    if long_edge <= 3072:
        return "2K"
    return "4K"


def _pixels_to_ratio(pixel_str: str) -> str | None:
    """Map 'WxH' to a Gemini-supported aspect ratio string when possible."""
    try:
        w, h = (int(x) for x in pixel_str.lower().split("x"))
    except Exception:
        return None
    # 减少到很小的比例
    from math import gcd
    g = gcd(w, h)
    rw, rh = w // g, h // g
    candidate = f"{rw}:{rh}"
    supported = {"1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1", "4:3",
                 "4:5", "5:4", "8:1", "9:16", "16:9", "21:9"}
    return candidate if candidate in supported else None


# ---------------------------------------------------------------------------
# Seedream 提供商（Volcengine Ark、OpenAI 兼容/图像/生成）
# ---------------------------------------------------------------------------

# 友好的别名 → 真实的 Seedream 模型 ID（Ark 模型 ID）。
_SEEDREAM_MODEL_ALIASES = {
    "seedream": "doubao-seedream-5-0-260128",
    "seedream-lite": "doubao-seedream-5-0-260128",
    "seedream-5.0": "doubao-seedream-5-0-260128",
    "seedream-5.0-lite": "doubao-seedream-5-0-260128",
    "seedream-5-0-lite": "doubao-seedream-5-0-260128",
    "doubao-seedream-5-0": "doubao-seedream-5-0-260128",
    "doubao-seedream-5-0-lite": "doubao-seedream-5-0-260128",
    "seedream-4.5": "doubao-seedream-4-5-251128",
    "seedream-4-5": "doubao-seedream-4-5-251128",
    "doubao-seedream-4-5": "doubao-seedream-4-5-251128",
}

# Seedream 支持粗略层（“2K”/“3K”/“4K”）或显式“WxH”。
# 当用户的等级有效时，我们按原样传递；否则翻译比率
# 方舟文档中推荐的像素大小的提示。
# Seedream 的有效尺寸级别（5.0 lite：2K/3K，4.5：2K/4K）。
# 不受支持的层将映射到最近的有效层。
_SEEDREAM_VALID_TIERS = {"2K", "3K", "4K"}
_SEEDREAM_TIER_FALLBACK = {"512": "2K", "1K": "2K"}
_SEEDREAM_SIZE_TABLE = {
    # （层、比例）->“宽x高”推荐像素尺寸（Seedream 5.0 lite + 4.5 共享最多）
    ("2K", "1:1"): "2048x2048",
    ("2K", "3:4"): "1728x2304",
    ("2K", "4:3"): "2304x1728",
    ("2K", "16:9"): "2848x1600",
    ("2K", "9:16"): "1600x2848",
    ("2K", "3:2"): "2496x1664",
    ("2K", "2:3"): "1664x2496",
    ("2K", "21:9"): "3136x1344",
    ("3K", "1:1"): "3072x3072",
    ("3K", "3:4"): "2592x3456",
    ("3K", "4:3"): "3456x2592",
    ("3K", "16:9"): "4096x2304",
    ("3K", "9:16"): "2304x4096",
    ("3K", "2:3"): "2496x3744",
    ("3K", "3:2"): "3744x2496",
    ("3K", "21:9"): "4704x2016",
    ("4K", "1:1"): "4096x4096",
    ("4K", "3:4"): "3520x4704",
    ("4K", "4:3"): "4704x3520",
    ("4K", "16:9"): "5504x3040",
    ("4K", "9:16"): "3040x5504",
    ("4K", "2:3"): "3328x4992",
    ("4K", "3:2"): "4992x3328",
    ("4K", "21:9"): "6240x2656",
}


class SeedreamProvider(ImageProvider):
    """Provider for Volcengine Ark Seedream image generation API.

    The endpoint is OpenAI-compatible (POST {base}/images/generations) but
    accepts an extra `image` field (string or list) for image-to-image and
    multi-image fusion, plus `sequential_image_generation` / `watermark` flags.
    Reference docs accept both `2K` shorthand and explicit `WxH` for `size`.
    """

    DEFAULT_MODEL = "doubao-seedream-5-0-260128"  # 种子梦 5.0 精简版

    def __init__(self, api_key: str, api_base: str, model: str):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = _SEEDREAM_MODEL_ALIASES.get((model or "").lower(), model or self.DEFAULT_MODEL)

    def generate(
        self,
        prompt: str,
        *,
        image_url=None,
        quality: str | None = None,  # 未获得 Seedream 的尊重
        size: str | None = None,
        aspect_ratio: str | None = None,
        output_dir: str = ".",
    ) -> list[str]:
        url = f"{self.api_base}/images/generations"

        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "response_format": "url",
            "watermark": False,
        }

        # 默认为 2K（Seedream 5.0 lite 最低层），除非调用者选择一个。
        seedream_size = self._resolve_seedream_size(size, aspect_ratio)
        if seedream_size:
            payload["size"] = seedream_size

        # 图像到图像/多图像融合（最多 14 个参考图像）。
        if image_url:
            urls = image_url if isinstance(image_url, list) else [image_url]
            prepared: list[str] = []
            for u in urls[:14]:
                if os.path.isfile(u):
                    data = _compress_image(_load_image(u))
                    mime = _guess_mime(data)
                    prepared.append(f"data:{mime};base64,{base64.b64encode(data).decode()}")
                else:
                    prepared.append(u)
            payload["image"] = prepared if len(prepared) > 1 else prepared[0]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if _HAS_REQUESTS:
            resp = requests.post(url, headers=headers, json=payload, timeout=300)
            if resp.status_code >= 400:
                try:
                    body = resp.json()
                    err = body.get("error") or {}
                    msg = err.get("message") or body.get("message") or resp.text
                except Exception:
                    msg = resp.text or resp.reason
                raise RuntimeError(f"API {resp.status_code}: {msg}")
            result = resp.json()
        else:
            data = json.dumps(payload).encode()
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=300) as r:
                result = json.loads(r.read())

        if result.get("error"):
            err = result["error"]
            raise RuntimeError(f"Seedream {err.get('code')}: {err.get('message')}")

        paths: list[str] = []
        for item in result.get("data") or []:
            u = item.get("url")
            b64 = item.get("b64_json")
            if u:
                paths.append(_save_image(_load_image(u), output_dir))
            elif b64:
                paths.append(_save_image(base64.b64decode(b64), output_dir))
        if not paths:
            raise RuntimeError(f"Seedream returned no image: {result}")
        return paths

    @staticmethod
    def _resolve_seedream_size(size: str | None, aspect_ratio: str | None) -> str | None:
        if not size and not aspect_ratio:
            return "2K"
        # 显式像素值：通过（标准化分隔符）
        if size and "x" in size.lower() and "*" not in size:
            return size.lower()
        if size and "*" in size:
            return size.replace("*", "x")
        tier = (size or "2K").upper()
        # 将不受支持的层（512、1K）映射到最接近的有效层
        tier = _SEEDREAM_TIER_FALLBACK.get(tier, tier)
        if tier not in _SEEDREAM_VALID_TIERS:
            tier = "2K"
        ratio = aspect_ratio or "1:1"
        if (tier, ratio) in _SEEDREAM_SIZE_TABLE:
            return _SEEDREAM_SIZE_TABLE[(tier, ratio)]
        return tier


# ---------------------------------------------------------------------------
# Qwen 提供商（DashScope 多模式生成：qwen-image-* 系列）
# ---------------------------------------------------------------------------

# 友好的别名 → 真实的 Qwen 模型 ID
_QWEN_MODEL_ALIASES = {
    "qwen": "qwen-image-2.0-pro",
    "qwen-image": "qwen-image-2.0-pro",
    "qwen-image-pro": "qwen-image-2.0-pro",
}

# Qwen 像素大小表（按层+比率最接近的匹配）。
# qwen-image-2.0(*) 支持 512*512 到 2048*2048 之间的任何宽x高。
_QWEN_SIZE_TABLE = {
    # （层，比率）->“宽*高”
    ("1K", "1:1"): "1024*1024",
    ("1K", "16:9"): "1280*720",
    ("1K", "9:16"): "720*1280",
    ("1K", "4:3"): "1184*888",
    ("1K", "3:4"): "888*1184",
    ("1K", "3:2"): "1248*832",
    ("1K", "2:3"): "832*1248",
    ("2K", "1:1"): "2048*2048",
    ("2K", "16:9"): "2688*1536",  # 超过 2048 上限 → 如果需要，在运行时夹紧
    ("2K", "9:16"): "1536*2688",
    ("2K", "4:3"): "2368*1728",
    ("2K", "3:4"): "1728*2368",
}


class QwenProvider(ImageProvider):
    """Provider for Alibaba DashScope Qwen image API (qwen-image-2.0[-pro])."""

    DEFAULT_MODEL = "qwen-image-2.0"

    def __init__(self, api_key: str, api_base: str, model: str):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = _QWEN_MODEL_ALIASES.get((model or "").lower(), model or self.DEFAULT_MODEL)

    def generate(
        self,
        prompt: str,
        *,
        image_url=None,
        quality: str | None = None,  # Qwen 图像 API 不支持
        size: str | None = None,
        aspect_ratio: str | None = None,
        output_dir: str = ".",
    ) -> list[str]:
        url = f"{self.api_base}/api/v1/services/aigc/multimodal-generation/generation"

        # 构建内容数组：0..3 个图像，然后是一个文本部分。
        content: list[dict] = []
        if image_url:
            urls = image_url if isinstance(image_url, list) else [image_url]
            for u in urls[:3]:  # API 上限为 3 个参考图像
                if os.path.isfile(u):
                    data = _compress_image(_load_image(u))
                    mime = _guess_mime(data)
                    image_field = f"data:{mime};base64,{base64.b64encode(data).decode()}"
                else:
                    image_field = u
                content.append({"image": image_field})
        content.append({"text": prompt})

        payload: dict = {
            "model": self.model,
            "input": {"messages": [{"role": "user", "content": content}]},
        }

        # 地图（尺寸、纵横比）→ Qwen "W*H"
        qwen_size = self._resolve_qwen_size(size, aspect_ratio)
        if qwen_size:
            payload["parameters"] = {"size": qwen_size}

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if _HAS_REQUESTS:
            resp = requests.post(url, headers=headers, json=payload, timeout=300)
            if resp.status_code >= 400:
                try:
                    body = resp.json()
                    msg = body.get("message") or body.get("error", {}).get("message") or resp.text
                except Exception:
                    msg = resp.text or resp.reason
                raise RuntimeError(f"API {resp.status_code}: {msg}")
            result = resp.json()
        else:
            data = json.dumps(payload).encode()
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=300) as r:
                result = json.loads(r.read())

        # 业务级错误通过 `code` 字段到达 HTTP 200。
        if result.get("code"):
            raise RuntimeError(f"Qwen {result.get('code')}: {result.get('message')}")

        paths: list[str] = []
        choices = (result.get("output") or {}).get("choices") or []
        for ch in choices:
            for part in ((ch.get("message") or {}).get("content") or []):
                u = part.get("image")
                if u:
                    paths.append(_save_image(_load_image(u), output_dir))
        if not paths:
            raise RuntimeError(f"Qwen returned no image: {result}")
        return paths

    @staticmethod
    def _resolve_qwen_size(size: str | None, aspect_ratio: str | None) -> str | None:
        if not size and not aspect_ratio:
            return None
        if size and "x" in size.lower() and "*" not in size:
            return size.lower().replace("x", "*")
        if size and "*" in size:
            return size
        tier = (size or "1K").upper()
        # Qwen支持1K和2K；夹住别人
        _QWEN_TIER_MAP = {"512": "1K", "3K": "2K", "4K": "2K"}
        tier = _QWEN_TIER_MAP.get(tier, tier)
        if tier not in ("1K", "2K"):
            tier = "1K"
        ratio = aspect_ratio or "1:1"
        if (tier, ratio) in _QWEN_SIZE_TABLE:
            return _QWEN_SIZE_TABLE[(tier, ratio)]
        return _QWEN_SIZE_TABLE.get((tier, "1:1"))


# ---------------------------------------------------------------------------
# MiniMax 提供商（image-01 系列）
# ---------------------------------------------------------------------------

# 友好的别名 → 真正的 MiniMax 模型 id
_MINIMAX_MODEL_ALIASES = {
    "minimax": "image-01",
    "minimax-image": "image-01",
    "minimax-image-01": "image-01",
}

_MINIMAX_SUPPORTED_RATIOS = {"1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"}


class MinimaxProvider(ImageProvider):
    """Provider for MiniMax image generation API (image-01)."""

    DEFAULT_MODEL = "image-01"

    def __init__(self, api_key: str, api_base: str, model: str):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = _MINIMAX_MODEL_ALIASES.get((model or "").lower(), model or self.DEFAULT_MODEL)

    def generate(
        self,
        prompt: str,
        *,
        image_url=None,
        quality: str | None = None,  # MiniMax 不支持
        size: str | None = None,
        aspect_ratio: str | None = None,
        output_dir: str = ".",
    ) -> list[str]:
        url = f"{self.api_base}/v1/image_generation"
        payload: dict = {
            "model": self.model,
            "prompt": prompt,
            "response_format": "base64",
        }

        # MiniMax直接接受aspect_ratio；如果需要的话，从像素派生。
        ratio = aspect_ratio
        if not ratio and size and "x" in size.lower():
            ratio = _pixels_to_ratio(size)
        if ratio and ratio in _MINIMAX_SUPPORTED_RATIOS:
            payload["aspect_ratio"] = ratio

        # 图像到图像使用subject_reference；接受 URL 或本地文件（→ base64）。
        if image_url:
            urls = image_url if isinstance(image_url, list) else [image_url]
            refs = []
            for u in urls:
                if os.path.isfile(u):
                    data = _compress_image(_load_image(u))
                    mime = _guess_mime(data)
                    image_file = f"data:{mime};base64,{base64.b64encode(data).decode()}"
                else:
                    image_file = u
                refs.append({"type": "character", "image_file": image_file})
            payload["subject_reference"] = refs

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if _HAS_REQUESTS:
            resp = requests.post(url, headers=headers, json=payload, timeout=300)
            if resp.status_code >= 400:
                try:
                    body = resp.json()
                    msg = body.get("base_resp", {}).get("status_msg") or body.get("error", {}).get("message") or resp.text
                except Exception:
                    msg = resp.text or resp.reason
                raise RuntimeError(f"API {resp.status_code}: {msg}")
            result = resp.json()
        else:
            data = json.dumps(payload).encode()
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=300) as r:
                result = json.loads(r.read())

        # 即使在 HTTP 200 上，MiniMax 也会在 base_resp 内返回业务错误。
        base_resp = result.get("base_resp") or {}
        if base_resp.get("status_code") not in (None, 0):
            raise RuntimeError(f"MiniMax {base_resp.get('status_code')}: {base_resp.get('status_msg')}")

        data_obj = result.get("data") or {}
        b64_list = data_obj.get("image_base64") or []
        urls_list = data_obj.get("image_urls") or []

        paths: list[str] = []
        for b64 in b64_list:
            paths.append(_save_image(base64.b64decode(b64), output_dir))
        for u in urls_list:
            paths.append(_save_image(_load_image(u), output_dir))
        if not paths:
            raise RuntimeError(f"MiniMax returned no image: {result}")
        return paths


# ---------------------------------------------------------------------------
# 供应商工厂
# ---------------------------------------------------------------------------

# 型号前缀 → 首选提供商标签。
# 当请求的模型与前缀匹配时，该提供者将被提升为
# 队列前面。所有其他配置的提供程序仍然作为后备运行。
_MODEL_PREFERRED_PROVIDER: list[tuple[tuple[str, ...], str]] = [
    (("gpt-image",), "OpenAI"),
    (("nano-banana", "gemini-"), "Gemini"),
    (("seedream", "doubao-seedream"), "Seedream"),
    (("qwen-image", "qwen"), "Qwen"),
    (("minimax", "image-01"), "MiniMax"),
]

# 当模型没有首选提供者时，默认全局优先级。
_DEFAULT_PROVIDER_ORDER = ["OpenAI", "Gemini", "Seedream", "Qwen", "MiniMax", "LinkAI"]

# UI 提供者 ID（通过模型页面保留）→ 使用的内部标签
# `_build_providers` 中的工厂字典。允许固定供应商
# 前缀推断无法识别的自定义模型名称。
_PROVIDER_ID_TO_LABEL = {
    "openai": "OpenAI",
    "gemini": "Gemini",
    "doubao": "Seedream",
    "dashscope": "Qwen",
    "minimax": "MiniMax",
    "linkai": "LinkAI",
}

_CUSTOM_PROVIDER_ENV = "SKILL_IMAGE_GENERATION_CUSTOM_PROVIDER"


def _preferred_provider(model: str) -> str | None:
    m = (model or "").lower()
    for prefixes, label in _MODEL_PREFERRED_PROVIDER:
        if m.startswith(prefixes):
            return label
    return None


def _build_custom_provider(
    provider_id: str,
    model: str,
) -> tuple[str, ImageProvider] | None:
    """Build the selected OpenAI-compatible custom image provider."""
    try:
        config = json.loads(os.environ.get(_CUSTOM_PROVIDER_ENV, ""))
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(config, dict):
        return None

    custom_id = provider_id[len("custom:"):]
    if config.get("id") != custom_id:
        return None
    api_key = (config.get("api_key") or "").strip()
    api_base = (config.get("api_base") or "").strip()
    selected_model = model or (config.get("model") or "").strip()
    if not api_key or not api_base or not selected_model:
        return None

    label = (config.get("name") or provider_id).strip()
    return (
        label,
        OpenAIProvider(
            api_key=api_key,
            api_base=api_base,
            model=selected_model,
        ),
    )


def _build_providers(model: str, provider_id: str = "") -> list[tuple[str, ImageProvider]]:
    """Build an ordered list of (label, provider) to try.

    Behaviour:
      1. All providers with a configured API key are added in the global
         priority order: OpenAI → Gemini → Seedream → Qwen → MiniMax → LinkAI.
      2. If `model` natively belongs to one of the providers AND that provider
         is configured, it is promoted to the front so it gets the first
         attempt with the right model id.
      3. If the preferred provider is NOT configured (no API key), the model
         id would 100% fail on every other backend, so we drop the explicit
         model and fall back to automatic routing — every provider then uses
         its own DEFAULT_MODEL.
    """
    if provider_id.startswith("custom:"):
        provider = _build_custom_provider(provider_id, model)
        return [provider] if provider else []

    keys = {
        "OpenAI": os.environ.get("OPENAI_API_KEY", ""),
        "Gemini": os.environ.get("GEMINI_API_KEY", ""),
        "Seedream": os.environ.get("ARK_API_KEY", ""),
        "Qwen": os.environ.get("DASHSCOPE_API_KEY", ""),
        "MiniMax": os.environ.get("MINIMAX_API_KEY", ""),
        "LinkAI": os.environ.get("LINKAI_API_KEY", ""),
    }
    bases = {
        "OpenAI": os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1"),
        "Gemini": os.environ.get("GEMINI_API_BASE", "https://generativelanguage.googleapis.com"),
        "Seedream": os.environ.get("ARK_API_BASE", "https://ark.cn-beijing.volces.com/api/v3"),
        "Qwen": os.environ.get("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com"),
        "MiniMax": os.environ.get("MINIMAX_API_BASE", "https://api.minimaxi.com"),
        "LinkAI": os.environ.get("LINKAI_API_BASE", "https://api.link-ai.tech"),
    }

    # 提供商偏好解析优先级：
    #   1.显式`provider_id`（UI持久化，支持自定义模型名称）。
    #   2. 型号名称前缀推断。
    pref = _PROVIDER_ID_TO_LABEL.get(provider_id) if provider_id else None
    if not pref:
        pref = _preferred_provider(model)

    # 如果请求特定模型并且其本地提供者没有密钥，
    # 其他后端无法识别 id → 重置为自动路由。
    if pref and not keys.get(pref):
        model = ""
        pref = None

    factories = {
        "OpenAI": OpenAIProvider,
        "Gemini": GeminiProvider,
        "Seedream": SeedreamProvider,
        "Qwen": QwenProvider,
        "MiniMax": MinimaxProvider,
        "LinkAI": LinkAIProvider,
    }
    available: dict[str, ImageProvider] = {}
    for label, key in keys.items():
        if key:
            available[label] = factories[label](api_key=key, api_base=bases[label], model=model)

    # 当固定特定模型时，仅尝试其本机提供程序 - 其他
    # 后端无法识别模型 ID，因此重试是没有意义的。
    if pref and pref in available:
        return [(pref, available[pref])]

    # 自动路由：按优先级顺序尝试每个配置的提供商。
    ordered: list[str] = []
    for label in _DEFAULT_PROVIDER_ORDER:
        if label in available:
            ordered.append(label)
    return [(label, available[label]) for label in ordered]


# ---------------------------------------------------------------------------
# 主要
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python generate.py '<json_args>'"}))
        sys.exit(1)

    try:
        raw = sys.argv[1]
        raw = raw.replace('\u201c', '"').replace('\u201d', '"').replace('\u2018', "'").replace('\u2019', "'")
        args = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}))
        sys.exit(1)

    prompt = args.get("prompt")
    if not prompt:
        print(json.dumps({"error": "Missing required parameter: prompt"}))
        sys.exit(1)

    # 模型解析优先级：
    #   1. 调用参数中显式 `model`（代理/用户覆盖）
    #   2. SKILL_IMAGE_GENERATION_MODEL 环境变量（从同步
    #      启动时配置[“技能”] [“图像生成”] [“模型”]）
    #   3.无 → 退回到自动提供商路由（尝试每一个
    #      具有按全局优先级顺序配置的 API 密钥的提供商）
    model = args.get("model") or os.environ.get("SKILL_IMAGE_GENERATION_MODEL") or ""
    # 模型 UI 保留提供者提示；让用户固定供应商
    # 前缀推断无法识别的自定义模型名称。
    provider_id = args.get("provider") or os.environ.get("SKILL_IMAGE_GENERATION_PROVIDER") or ""
    quality = args.get("quality")
    size = args.get("size")
    aspect_ratio = args.get("aspect_ratio")
    image_url = args.get("image_url")

    # 独立于实时 cwd 解析输出目录（代理可以 `cd`
    # 其他地方，例如进入该技能的目录，该目录在重新启动时会被擦除）。
    # 优先级：显式 IMAGE_OUTPUT_DIR -> 工作区/项目目录 -> cwd。
    output_base = os.environ.get("IMAGE_OUTPUT_DIR")
    if not output_base:
        workspace = os.environ.get("AGENT_WORKSPACE") or os.getcwd()
        output_base = os.path.join(workspace, "images")
    output_dir = output_base

    providers = _build_providers(model, provider_id=provider_id)
    if not providers:
        if provider_id.startswith("custom:"):
            print(json.dumps({
                "error": (
                    "The selected custom image provider is missing or "
                    "has no API key, API base, or model configured. "
                    "Update it in the Models settings before retrying."
                )
            }, ensure_ascii=False))
            sys.exit(1)
        target = f"model '{model}'" if model else "image generation"
        print(json.dumps({
            "error": (
                f"No API key configured for {target}. "
                "Set at least one of OPENAI_API_KEY / GEMINI_API_KEY / "
                "ARK_API_KEY / DASHSCOPE_API_KEY / MINIMAX_API_KEY / "
                "LINKAI_API_KEY via the env_config tool, then try again."
            )
        }, ensure_ascii=False))
        sys.exit(1)

    errors = []
    for label, provider in providers:
        try:
            attempt_model = getattr(provider, "model", model) or "auto"
            print(f"[image-generation] Trying {label} (model={attempt_model})...", file=sys.stderr)
            t0 = time.time()
            paths = provider.generate(
                prompt,
                image_url=image_url,
                quality=quality,
                size=size,
                aspect_ratio=aspect_ratio,
                output_dir=output_dir,
            )
            elapsed = time.time() - t0
            # 实际发送到 API 的解析模型 ID（别名扩展后）
            actual_model = getattr(provider, "model", model)
            print(
                f"[image-generation] ✅ {label} succeeded in {elapsed:.1f}s "
                f"(model={actual_model})",
                file=sys.stderr,
            )
            result = {
                "model": actual_model,
                "images": [{"url": p} for p in paths],
            }
            print(json.dumps(result, ensure_ascii=False))
            return
        except Exception as e:
            elapsed = time.time() - t0
            print(f"[image-generation] ❌ {label} failed in {elapsed:.1f}s: {e}", file=sys.stderr)
            errors.append(f"{label}: {e}")

    hint = " | ".join(errors)
    print(json.dumps({
        "error": f"All providers failed — {hint}. "
                 "This is likely an API key or base URL configuration issue. "
                 "Do NOT retry with the same parameters. "
                 "Ask the user to verify their API key / base URL "
                 "(OPENAI_API_KEY, GEMINI_API_KEY, ARK_API_KEY, "
                 "DASHSCOPE_API_KEY, MINIMAX_API_KEY, or LINKAI_API_KEY) "
                 "via env_config."
    }, ensure_ascii=False))
    sys.exit(1)


if __name__ == "__main__":
    main()
