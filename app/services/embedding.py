"""Embedding 抽象。

默认 hash provider 基于字符 n-gram 哈希，离线、确定、无需 API key，
足以让“相似文本向量更接近”在 demo 中成立；
生产时把 EMBEDDING_PROVIDER 切成 openai 即可接任意 OpenAI 兼容接口。
"""
from __future__ import annotations

import hashlib
import math
import re

import numpy as np
import requests

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _hash_embed(text: str, dim: int) -> list[float]:
    vec = np.zeros(dim, dtype=np.float32)
    tokens = _tokens(text)
    # unigram + bigram，给短查询更好的区分度
    grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    if not grams:
        return vec.tolist()
    for gram in grams:
        h = hashlib.md5(gram.encode("utf-8")).digest()
        idx = int.from_bytes(h[:4], "little") % dim
        sign = 1.0 if h[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec.tolist()


def _openai_embed(texts: list[str]) -> list[list[float]]:
    resp = requests.post(
        f"{settings.embedding_base_url.rstrip('/')}/embeddings",
        headers={"Authorization": f"Bearer {settings.embedding_api_key}"},
        json={"model": settings.embedding_model, "input": texts},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    data.sort(key=lambda x: x["index"])
    return [item["embedding"] for item in data]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if settings.embedding_provider == "openai":
        if not settings.embedding_api_key:
            raise RuntimeError("EMBEDDING_PROVIDER=openai 但未配置 EMBEDDING_API_KEY")
        return _openai_embed(texts)
    return [_hash_embed(t, settings.embedding_dim) for t in texts]


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def _sanity() -> None:
    # 简单自检：相似句子得分应明显高于无关句子
    base = embed_query("volatile 为什么不能保证 i++ 线程安全")
    near = cosine(base, embed_query("volatile 不能保证 i++ 的原子性"))
    far = cosine(base, embed_query("今天北京天气适合跑步吗"))
    assert near > far, (near, far)


if __name__ == "__main__":
    _sanity()
    print("embedding sanity ok, dim=", settings.embedding_dim, "provider=", settings.embedding_provider)
