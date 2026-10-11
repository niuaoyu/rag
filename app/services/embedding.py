"""M6：文本 → 向量。

两个实现，切换靠 settings.embedding_provider：
- openai：打任意 OpenAI 兼容的 /embeddings 接口（智谱、DashScope、自建 vLLM 都行），是**唯一语义可用**的实现。
- hash  ：离线确定性哈希（字符 n-gram 词袋）。**只是词面重叠**，不具备语义相似度能力，
          用途仅限于"CI/离线跑通管道 + 单测断言检索能命中词面相关的块"。
          任何检索质量数字（命中率/召回）在 hash 下都是假的，不许写进简历或文档结论。

为什么把 hash 也做成一个正式实现而不是在测试里 mock：
embedding 是管道里最容易"其实没跑"的一环（mock 掉之后，向量库维度、payload、过滤条件全都测不到）。
有确定性的真实现，M6/M7 的测试才测得到真东西。
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, Sequence

import httpx

from app.core.config import settings as default_settings

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
_WORD = re.compile(r"[a-z0-9_]+")


class EmbeddingError(Exception):
    pass


class BaseEmbedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashEmbedder:
    """确定性、离线的词面哈希向量。dim 必须显式指定。"""

    name = "hash"

    def __init__(self, dim: int = 256) -> None:
        if dim <= 0:
            raise ValueError("dim 必须为正数")
        self.dim = dim

    def _features(self, text: str) -> list[str]:
        """特征 = 中文单字 + 中文二元组 + 英文/数字词。中文二元组是为了让"向量检索"能覆盖词序。"""
        lowered = text.lower()
        cjk_chars = _CJK.findall(lowered)
        features = list(cjk_chars)
        features += [cjk_chars[i] + cjk_chars[i + 1] for i in range(len(cjk_chars) - 1)]
        features += _WORD.findall(lowered)
        return features

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for feature in self._features(text):
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest, "big") % self.dim
            vector[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:  # 空文本/纯符号
            return vector
        return [v / norm for v in vector]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)


class OpenAICompatEmbedder:
    """OpenAI 兼容 /embeddings 客户端。dim 由接口首次返回决定。"""

    name = "openai"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        dim: int | None = None,
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise EmbeddingError("embedding_provider=openai 但 embedding_api_key 为空")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dim = dim or 0
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def _post_embeddings(self, texts: Sequence[str]) -> list[list[float]]:
        try:
            response = self._client.post(
                "/embeddings", json={"model": self.model, "input": list(texts)}
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise EmbeddingError(f"embedding 接口调用失败: {type(exc).__name__}: {exc}") from exc

        try:
            # OpenAI 兼容接口按 index 排序返回，不能假设顺序
            items = sorted(payload["data"], key=lambda item: item["index"])
            vectors = [list(map(float, item["embedding"])) for item in items]
        except (KeyError, TypeError) as exc:
            raise EmbeddingError(f"embedding 接口返回格式不符合预期: {payload}") from exc

        if not vectors:
            raise EmbeddingError("embedding 接口返回空结果")
        self.dim = len(vectors[0])
        return vectors

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._post_embeddings(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._post_embeddings([text])[0]


def build_embedder(cfg=default_settings) -> BaseEmbedder:
    provider = (cfg.embedding_provider or "hash").lower()
    if provider == "hash":
        return HashEmbedder(dim=cfg.embedding_dim)
    if provider == "openai":
        return OpenAICompatEmbedder(
            base_url=cfg.embedding_base_url,
            api_key=cfg.embedding_api_key,
            model=cfg.embedding_model,
            dim=None,
            timeout=cfg.llm_timeout_seconds,
        )
    raise EmbeddingError(f"未知的 embedding_provider: {provider}（可选 hash / openai）")
