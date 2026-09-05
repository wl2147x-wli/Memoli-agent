"""
Embedding providers for memory

Supports multiple OpenAI-compatible embedding vendors:
  - openai     (text-embedding-3-small / large)
  - linkai     (OpenAI-compatible passthrough)
  - dashscope  (Aliyun Tongyi text-embedding-v4)
  - doubao     (ByteDance Doubao Seed1.5 / large-text on Volcengine Ark)
  - zhipu      (ZhipuAI embedding-3)
  - custom     (any OpenAI-compatible endpoint)

Vendor keys here intentionally match the project's bot_type constants in
common.const (OPENAI, LINKAI, QWEN_DASHSCOPE, DOUBAO, ZHIPU_AI).

Custom providers (bot_type "custom" or "custom:<id>") reuse the same
OpenAI-compatible REST client with user-supplied api_key / api_base.

All providers share a single OpenAI-compatible REST client. Vendor-specific
behaviors (truncation, query instruction prefix) are configured via metadata.
"""

import hashlib
import math
from abc import ABC, abstractmethod
from typing import List, Optional
from urllib.parse import urlparse

# 单个嵌入请求的 HTTP 读取超时（秒）。在境内网络下，
# 一批 64+ 文本块端到端需要 30-50 秒，因此 30 秒通常偏紧；
# 90 秒既能留出充足余量，又不会让故障端点无限期挂起。
EMBEDDING_HTTP_TIMEOUT = 90


class EmbeddingProvider(ABC):
    """Base class for embedding providers"""

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """Generate embedding for a single text (treated as a query by default)"""
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts (treated as documents)"""
        pass

    def embed_query(self, text: str) -> List[float]:
        """Generate embedding for a query string (may apply vendor instruction prefix)"""
        return self.embed(text)

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Effective embedding dimensions"""
        pass


# ---------------------------------------------------------------------------
# 供应商元数据表
# ---------------------------------------------------------------------------
#
# 每个条目都描述了如何访问某家供应商的嵌入端点。多数供应商
# 提供与 OpenAI 兼容的 /embeddings API；少数不兼容的（目前为豆宝）
# 通过设置 `provider_class` 选择专用的适配器实现。
# 各字段含义：
#   provider_class ：可选适配器标识（“doubao”）；缺省走 OpenAI 兼容实现
#   default_base_url ：用户未显式覆盖时使用的默认 API 基础地址
#   default_model ：默认的嵌入模型名称
#   default_dimensions ：推荐的统一维度（仅在需要显式维度时使用）
#   supports_dim_param ：API 是否接受 `dimensions` 请求参数
#   needs_client_truncate ：是否需在客户端做截断 + L2 归一化
#   needs_client_normalize ：是否需在客户端做 L2 归一化（始终安全）
#   query_instruction ：非对称检索时为查询附加的可选前缀
#   max_batch_size ：单次 /embeddings 请求最多可携带的文本条数；
#                    超过此数时嵌入批处理会自动分页。默认值较保守。
#
EMBEDDING_VENDORS = {
    "openai": {
        "default_base_url": "https://api.openai.com/v1",
        "default_model": "text-embedding-3-small",
        # 与旧版默认值保持一致，这样用户把 embedding_provider 配成 openai
        # 时无需重建现有索引。如需 1024 / 1536 / 3072，
        # 可通过 embedding_dimensions 覆盖。
        "default_dimensions": 1536,
        "supports_dim_param": True,
        "needs_client_truncate": False,
        "needs_client_normalize": False,
        "query_instruction": "",
        # OpenAI 虽允许单个请求最多 2048 条，但一次携带数百条长文本的调用，
        # 很容易超过境内网络的 30 秒读取超时。限制为 64 条既能控制单次
        # 请求的 token 预算，也能让耗时保持在合理范围。
        "max_batch_size": 64,
    },
    "linkai": {
        "default_base_url": "https://api.link-ai.tech/v1",
        "default_model": "text-embedding-3-small",
        "default_dimensions": 1536,
        "supports_dim_param": True,
        "needs_client_truncate": False,
        "needs_client_normalize": False,
        "query_instruction": "",
        "max_batch_size": 64,
    },
    "dashscope": {
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "text-embedding-v4",
        "default_dimensions": 1024,
        "supports_dim_param": True,
        "needs_client_truncate": False,
        "needs_client_normalize": False,
        "query_instruction": "",
        "max_batch_size": 10,  # DashScope 的硬性上限（text-embedding-v4）
    },
    "doubao": {
        # 豆宝已不再提供与 OpenAI 兼容的 /v1/embeddings 端点，
        # 现有模型统一走 /api/v3/embeddings/multimodal，并且使用结构化的
        # `input` 载荷——详见 DoubaoEmbeddingProvider。
        "provider_class": "doubao",
        "default_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "default_model": "doubao-embedding-vision-251215",
        # 原生可选维度为 1024 或 2048。这里默认 1024，与国内其他供应商
        #（dashscope/zhipu）保持一致，也让各提供商的存储保持统一；
        # 用户仍可通过配置中的 `embedding_dimensions: 2048` 覆盖。
        "default_dimensions": 1024,
        "supports_dim_param": True,
        "needs_client_truncate": False,
        "needs_client_normalize": False,
        "query_instruction": "",
        # 该多模态端点每次调用只产出一个嵌入（input 列表表示单个文档的
        # 多个组成片段，而不是一批文档），因此 embed_batch 需循环调用。
        "max_batch_size": 1,
    },
    "zhipu": {
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "embedding-3",
        "default_dimensions": 1024,
        "supports_dim_param": True,
        "needs_client_truncate": False,
        "needs_client_normalize": False,
        "query_instruction": "",
        "max_batch_size": 64,
    },
    # 自定义供应商——任何与 OpenAI 兼容的 /embeddings 端点。用户必须在
    # Web 控制台提供 api_key + api_base + 模型（存储在 custom_providers
    # 列表，或旧的 custom_api_key / custom_api_base 中）。维度默认 1024，
    # 可通过配置中的 embedding_dimensions 覆盖。这里不假定端点支持
    # dimensions 参数——对未知端点采取最保守的默认值。
    "custom": {
        "default_base_url": "",
        "default_model": "",
        "default_dimensions": 1024,
        "supports_dim_param": False,
        "needs_client_truncate": False,
        "needs_client_normalize": True,
        "query_instruction": "",
        "max_batch_size": 64,
    },
}


def _l2_normalize(vec: List[float]) -> List[float]:
    """Normalize a vector to unit length (L2 norm). Returns input on zero vector."""
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    OpenAI-compatible embedding provider.

    Used for openai/linkai/dashscope/ark/zhipu by configuring the metadata
    fields. The legacy two-arg constructor (model, api_key, api_base) keeps
    working, so the original OpenAI/LinkAI fallback code path is unchanged.
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        extra_headers: Optional[dict] = None,
        dimensions: Optional[int] = None,
        supports_dim_param: bool = True,
        needs_client_truncate: bool = False,
        needs_client_normalize: bool = False,
        query_instruction: str = "",
        max_batch_size: int = 256,
        source_tagged: Optional[bool] = None,
    ):
        """
        Args:
            model: Model name (e.g. text-embedding-3-small, text-embedding-v4, embedding-3)
            api_key: API key (required)
            api_base: API base URL (defaults to OpenAI)
            extra_headers: Optional extra HTTP headers
            dimensions: Target output dimension. Required when supports_dim_param
                is False and needs_client_truncate is True (used to slice).
            supports_dim_param: Whether the vendor accepts a `dimensions` body param
            needs_client_truncate: Slice the returned vector to `dimensions`
            needs_client_normalize: L2-normalize on the client after slicing
            query_instruction: Optional prefix prepended to query texts only
            max_batch_size: Max items per /embeddings request; embed_batch
                auto-paginates above this.
        """
        self.model = model
        self.api_key = api_key
        self.api_base = api_base or "https://api.openai.com/v1"
        self.extra_headers = extra_headers or {}
        if source_tagged is None:
            _host = (urlparse(self.api_base).hostname or "").lower()
            source_tagged = _host == "link-ai.tech" or _host.endswith(".link-ai.tech")
        self._source_tagged = source_tagged
        self.supports_dim_param = supports_dim_param
        self.needs_client_truncate = needs_client_truncate
        self.needs_client_normalize = needs_client_normalize
        self.query_instruction = query_instruction or ""
        self.max_batch_size = max(1, int(max_batch_size or 1))

        if not self.api_key or self.api_key in ["", "YOUR API KEY", "YOUR_API_KEY"]:
            raise ValueError("Embedding API key is not configured")

        if dimensions is not None and dimensions > 0:
            self._dimensions = dimensions
        else:
            # OpenAI text-embedding-3-* 系列的传统启发式
            self._dimensions = 1536 if "small" in model else 3072

    def _request_headers(self) -> dict:
        headers = dict(self.extra_headers)
        if self._source_tagged:
            try:
                from common.utils import apply_client_source
                apply_client_source(headers)
            except Exception:
                pass
        return headers

    def _call_api(self, input_data):
        """Call OpenAI-compatible /embeddings endpoint"""
        import requests

        url = f"{self.api_base}/embeddings"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            **self._request_headers(),
        }
        data = {
            "input": input_data,
            "model": self.model,
        }
        if self.supports_dim_param and self._dimensions:
            data["dimensions"] = self._dimensions

        try:
            response = requests.post(url, headers=headers, json=data, timeout=EMBEDDING_HTTP_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(
                f"Failed to connect to embedding API at {url}. "
                f"Please check network and api_base. Error: {str(e)}"
            )
        except requests.exceptions.Timeout as e:
            raise TimeoutError(f"Embedding API request timed out. Error: {str(e)}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise ValueError("Invalid embedding API key")
            elif e.response.status_code == 429:
                raise ValueError("Embedding API rate limit exceeded")
            else:
                raise ValueError(
                    f"Embedding API request failed: "
                    f"{e.response.status_code} - {e.response.text}"
                )

    def _post_process(self, raw: List[float]) -> List[float]:
        """Apply optional client-side truncation + normalization"""
        vec = raw
        if self.needs_client_truncate and self._dimensions and len(vec) > self._dimensions:
            vec = vec[: self._dimensions]
        if self.needs_client_normalize:
            vec = _l2_normalize(vec)
        return vec

    def embed(self, text: str) -> List[float]:
        """Generate embedding (treated as document by default)"""
        result = self._call_api(text)
        return self._post_process(result["data"][0]["embedding"])

    def embed_query(self, text: str) -> List[float]:
        """Generate embedding for a query (applies vendor instruction prefix if any)"""
        if self.query_instruction:
            text = f"{self.query_instruction}{text}"
        return self.embed(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple documents.

        Automatically paginates by self.max_batch_size so callers can pass any
        number of texts. Order of returned vectors matches the input order.
        """
        if not texts:
            return []
        out: List[List[float]] = []
        step = self.max_batch_size
        for i in range(0, len(texts), step):
            chunk = texts[i:i + step]
            result = self._call_api(chunk)
            out.extend(self._post_process(item["embedding"]) for item in result["data"])
        return out

    @property
    def dimensions(self) -> int:
        return self._dimensions


class DoubaoEmbeddingProvider(EmbeddingProvider):
    """
    Doubao (Volcengine Ark) multimodal embedding provider.

    Doubao deprecated their OpenAI-compatible /v1/embeddings endpoint and
    unified everything under /api/v3/embeddings/multimodal, which uses a
    structured `input: [{type, text|image_url|video_url}, ...]` payload.

    Notes:
      * The endpoint produces ONE embedding per call (input list is multiple
        modality parts of a single document, not a batch). embed_batch
        therefore loops per-text — no native batch support.
      * Native dimensions: 1024 or 2048 (default 1024 to align with other
        Chinese vendors). No client-side truncation needed.
      * Auth: Bearer ARK API key.
    """

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        extra_headers: Optional[dict] = None,
        dimensions: Optional[int] = None,
    ):
        self.model = model
        self.api_key = api_key
        self.api_base = api_base or "https://ark.cn-beijing.volces.com/api/v3"
        self.extra_headers = extra_headers or {}
        if not self.api_key or self.api_key in ["", "YOUR API KEY", "YOUR_API_KEY"]:
            raise ValueError("Doubao embedding API key (ark_api_key) is not configured")

        if dimensions in (1024, 2048):
            self._dimensions = dimensions
        elif dimensions is None:
            self._dimensions = 1024
        else:
            raise ValueError(
                f"Doubao embedding dimensions must be 1024 or 2048, got {dimensions}"
            )

    def _call_api(self, text: str) -> List[float]:
        """One call → one embedding. multimodal endpoint takes a single
        document represented as a list of typed parts; we send a single
        text part."""
        import requests

        url = f"{self.api_base}/embeddings/multimodal"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            **self.extra_headers,
        }
        payload = {
            "model": self.model,
            "input": [{"type": "text", "text": text}],
            "dimensions": self._dimensions,
            "encoding_format": "float",
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=EMBEDDING_HTTP_TIMEOUT)
            response.raise_for_status()
            body = response.json()
        except requests.exceptions.ConnectionError as e:
            raise ConnectionError(
                f"Failed to connect to Doubao embedding API at {url}. "
                f"Please check network and api_base. Error: {str(e)}"
            )
        except requests.exceptions.Timeout as e:
            raise TimeoutError(f"Doubao embedding API request timed out. Error: {str(e)}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise ValueError("Invalid Doubao (ark) embedding API key")
            elif e.response.status_code == 429:
                raise ValueError("Doubao embedding API rate limit exceeded")
            else:
                raise ValueError(
                    f"Doubao embedding API request failed: "
                    f"{e.response.status_code} - {e.response.text}"
                )

        # 每个文档的响应形状：{"data": {"embedding": [...]}}
        data = body.get("data")
        if isinstance(data, dict) and "embedding" in data:
            return data["embedding"]
        # 部分供应商会把结果包成一层列表——这里做防御性处理
        if isinstance(data, list) and data and "embedding" in data[0]:
            return data[0]["embedding"]
        raise ValueError(f"Unexpected Doubao embedding response shape: {body}")

    def embed(self, text: str) -> List[float]:
        return self._call_api(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        # 该端点每次调用只生成一个嵌入，因此逐个循环调用；顺序保持不变。
        return [self._call_api(t) for t in texts]

    @property
    def dimensions(self) -> int:
        return self._dimensions


class EmbeddingCache:
    """In-memory cache for embeddings to avoid recomputation"""

    def __init__(self):
        self.cache = {}

    def get(self, text: str, provider: str, model: str) -> Optional[List[float]]:
        key = self._compute_key(text, provider, model)
        return self.cache.get(key)

    def put(self, text: str, provider: str, model: str, embedding: List[float]):
        key = self._compute_key(text, provider, model)
        self.cache[key] = embedding

    @staticmethod
    def _compute_key(text: str, provider: str, model: str) -> str:
        content = f"{provider}:{model}:{text}"
        return hashlib.md5(content.encode("utf-8")).hexdigest()

    def clear(self):
        self.cache.clear()


def create_embedding_provider(
    provider: str = "openai",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    extra_headers: Optional[dict] = None,
    dimensions: Optional[int] = None,
    source_tagged: Optional[bool] = None,
) -> EmbeddingProvider:
    """
    Factory function to create an embedding provider.

    Backward compatible: when called with provider in {"openai", "linkai"}
    and no `dimensions` arg, behaves exactly as before (1536-dim OpenAI).

    New providers ("dashscope", "doubao", "zhipu") require explicit configuration
    and use the unified 1024-dim defaults from EMBEDDING_VENDORS.

    Args:
        provider: Vendor key (one of EMBEDDING_VENDORS)
        model: Model name (uses vendor default if None)
        api_key: API key (required)
        api_base: API base URL (uses vendor default if None)
        extra_headers: Optional extra HTTP headers
        dimensions: Target output dimension (uses vendor default if None)

    Returns:
        EmbeddingProvider instance
    """
    meta = EMBEDDING_VENDORS.get(provider)
    if meta is None:
        raise ValueError(
            f"Unsupported embedding provider: {provider}. "
            f"Supported: {sorted(EMBEDDING_VENDORS.keys())}"
        )

    # 豆宝的多模态端点与 OpenAI 不兼容，需走专用实现。
    if meta.get("provider_class") == "doubao":
        final_dim = dimensions if (dimensions and dimensions > 0) else meta["default_dimensions"]
        return DoubaoEmbeddingProvider(
            model=model or meta["default_model"],
            api_key=api_key,
            api_base=api_base or meta["default_base_url"],
            extra_headers=extra_headers,
            dimensions=final_dim,
        )

    # openai/linkai 的旧式双参数调用保留 1536 维的默认行为，
    # 以免已有数据失效。
    is_legacy_call = (
        provider in ("openai", "linkai")
        and dimensions is None
    )
    if is_legacy_call:
        return OpenAIEmbeddingProvider(
            model=model or "text-embedding-3-small",
            api_key=api_key,
            api_base=api_base,
            extra_headers=extra_headers,
            source_tagged=source_tagged,
        )

    final_dim = dimensions if (dimensions and dimensions > 0) else meta["default_dimensions"]
    resolved_model = model or meta["default_model"]
    resolved_base = api_base or meta["default_base_url"]
    # 自定义供应商必须显式提供 api_base 与 model——它们不能
    # 像内置供应商那样回退到 OpenAI 的默认值。
    if provider == "custom":
        if not resolved_base:
            raise ValueError("Custom embedding provider requires an api_base URL")
        if not resolved_model:
            raise ValueError("Custom embedding provider requires a model name")
    return OpenAIEmbeddingProvider(
        model=resolved_model,
        api_key=api_key,
        api_base=resolved_base,
        extra_headers=extra_headers,
        dimensions=final_dim,
        supports_dim_param=meta["supports_dim_param"],
        needs_client_truncate=meta["needs_client_truncate"],
        needs_client_normalize=meta["needs_client_normalize"],
        query_instruction=meta["query_instruction"],
        max_batch_size=meta.get("max_batch_size", 256),
        source_tagged=source_tagged,
    )
