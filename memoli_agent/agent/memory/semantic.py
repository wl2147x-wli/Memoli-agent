"""可选语义索引：远程 embedding 与事实写入完全解耦。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class EmbeddingError(RuntimeError):
    """embedding 请求或响应不符合合同。"""


class EmbeddingDisabledError(EmbeddingError):
    """部署未启用语义模型。"""


class Embedder(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    @property
    def enabled(self) -> bool: ...

    async def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...


@dataclass(frozen=True, slots=True)
class DisabledEmbedder:
    model: str = "disabled"
    version: str = "disabled"
    dimensions: int = 0
    enabled: bool = False

    async def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        raise EmbeddingDisabledError("语义索引未启用。")


@dataclass(frozen=True, slots=True)
class DeterministicEmbedder:
    """不访问网络的测试/演示实现。"""

    dimensions: int = 16
    model: str = "deterministic"
    version: str = "1"
    enabled: bool = True

    async def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(_deterministic_vector(text, self.dimensions) for text in texts)


@dataclass(frozen=True, slots=True)
class OpenAICompatibleEmbedder:
    model: str
    api_key_env: str
    dimensions: int
    base_url: str = "https://api.openai.com/v1"
    version: str = "1"
    timeout_seconds: float = 30.0
    enabled: bool = True

    async def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        if not texts:
            return ()
        return await asyncio.to_thread(self._embed_sync, tuple(texts))

    def _embed_sync(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        api_key = os.environ.get(self.api_key_env, "").strip()
        if not api_key:
            raise EmbeddingError(f"环境变量 {self.api_key_env} 未配置。")
        payload: dict[str, Any] = {"model": self.model, "input": list(texts)}
        if self.dimensions > 0:
            payload["dimensions"] = self.dimensions
        request = Request(
            f"{self.base_url.rstrip('/')}/embeddings",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            raise EmbeddingError(f"embedding HTTP {exc.code}") from exc
        except (URLError, OSError) as exc:
            raise EmbeddingError("embedding 网络请求失败") from exc
        try:
            raw = json.loads(body)
            rows = sorted(raw["data"], key=lambda row: int(row["index"]))
            vectors = tuple(
                tuple(float(value) for value in row["embedding"]) for row in rows
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise EmbeddingError("embedding 响应格式无效。") from exc
        if len(vectors) != len(texts):
            raise EmbeddingError("embedding 响应数量不匹配。")
        for vector in vectors:
            validate_vector(vector, self.dimensions)
        return vectors


def encode_vector(vector: Sequence[float], dimensions: int) -> bytes:
    """以 little-endian float32 编码，便于 SQLite 紧凑保存。"""

    validate_vector(vector, dimensions)
    return struct.pack(f"<{dimensions}f", *vector)


def decode_vector(blob: bytes, dimensions: int) -> tuple[float, ...]:
    if dimensions <= 0 or len(blob) != dimensions * 4:
        raise EmbeddingError("向量 BLOB 大小与维度不匹配。")
    vector = tuple(float(value) for value in struct.unpack(f"<{dimensions}f", blob))
    validate_vector(vector, dimensions)
    return vector


def validate_vector(vector: Sequence[float], dimensions: int) -> None:
    if dimensions <= 0 or len(vector) != dimensions:
        raise EmbeddingError("向量维度不匹配。")
    if any(not math.isfinite(float(value)) for value in vector):
        raise EmbeddingError("向量包含非有限值。")


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise EmbeddingError("余弦相似度要求相同的非空维度。")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


@dataclass(frozen=True, slots=True)
class IndexTickResult:
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    stale: int = 0


@dataclass(frozen=True, slots=True)
class MemoryIndexWorker:
    store: Any
    embedder: Embedder
    batch_size: int = 8

    async def tick(self) -> IndexTickResult:
        if not self.embedder.enabled:
            return IndexTickResult()
        jobs = self.store.claim_index_jobs(self.batch_size)
        succeeded = failed = stale = 0
        for job in jobs:
            source = self.store.get_index_source(job.memory_type, job.memory_id)
            if source is None or source.content_hash != job.content_hash:
                self.store.discard_index_job(
                    job.memory_type, job.memory_id, job.content_hash
                )
                stale += 1
                continue
            try:
                vectors = await self.embedder.embed((source.content,))
                vector = vectors[0]
                self.store.complete_index_job(
                    job,
                    model=self.embedder.model,
                    version=self.embedder.version,
                    dimensions=self.embedder.dimensions,
                    vector_blob=encode_vector(vector, self.embedder.dimensions),
                )
                succeeded += 1
            except Exception as exc:
                # 只记录错误类型，避免 provider 响应或密钥进入数据库。
                self.store.fail_index_job(job, type(exc).__name__)
                failed += 1
        return IndexTickResult(len(jobs), succeeded, failed, stale)

    def rebuild(self, memory_type: str | None = None) -> int:
        return self.store.rebuild_index_jobs(memory_type)


def _deterministic_vector(text: str, dimensions: int) -> tuple[float, ...]:
    if dimensions <= 0:
        raise EmbeddingError("确定性向量维度必须大于 0。")
    values = [0.0] * dimensions
    normalized = " ".join(text.casefold().split())
    tokens = normalized.split() or [normalized]
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for index, byte in enumerate(digest):
            bucket = index % dimensions
            values[bucket] += (byte / 127.5) - 1.0
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return tuple(value / norm for value in values)
