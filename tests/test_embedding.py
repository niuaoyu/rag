"""M6 embedding 单测：hash 实现的确定性与"词面相关"排序 + OpenAI 兼容客户端的解析。

注意 hash 向量**不是语义向量**：这里断言的是"词面重叠越多、相似度越高"，
不要把它当成"检索质量"的证据。
"""

import json

import httpx
import pytest

from app.services.embedding import (
    EmbeddingError,
    HashEmbedder,
    OpenAICompatEmbedder,
    build_embedder,
)


def _cosine(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def test_hash_embedder_is_deterministic_and_normalized():
    embedder = HashEmbedder(dim=64)
    first = embedder.embed_query("检索增强生成")
    second = embedder.embed_query("检索增强生成")
    assert first == second
    assert len(first) == 64
    assert _cosine(first, first) == pytest.approx(1.0, abs=1e-6)


def test_hash_embedder_prefers_lexically_similar_text():
    embedder = HashEmbedder(dim=256)
    query = embedder.embed_query("苹果种植技术")
    similar = embedder.embed_query("苹果种植技术要点：套袋")
    different = embedder.embed_query("区块链共识算法")
    assert _cosine(query, similar) > _cosine(query, different)


def test_empty_text_returns_zero_vector():
    embedder = HashEmbedder(dim=8)
    assert embedder.embed_query("") == [0.0] * 8


def test_build_embedder_rejects_unknown_provider(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "embedding_provider", "gpt5-magic")
    with pytest.raises(EmbeddingError, match="未知的 embedding_provider"):
        build_embedder(settings)


def test_openai_compat_embedder_sorts_by_index_and_sets_dim():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        assert request.headers["authorization"] == "Bearer k"
        body = json.loads(request.content)
        assert body["input"] == ["第一段", "第二段"]
        # 故意乱序返回：客户端必须按 index 排序，不能信返回顺序
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0, 0.0]},
                    {"index": 0, "embedding": [1.0, 0.0, 0.0]},
                ]
            },
        )

    embedder = OpenAICompatEmbedder(
        base_url="https://fake.local/v1",
        api_key="k",
        model="emb",
        transport=httpx.MockTransport(handler),
    )
    vectors = embedder.embed_documents(["第一段", "第二段"])
    assert vectors == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert embedder.dim == 3


def test_openai_compat_embedder_raises_on_empty_data():
    embedder = OpenAICompatEmbedder(
        base_url="https://fake.local/v1",
        api_key="k",
        model="emb",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []})),
    )
    with pytest.raises(EmbeddingError):
        embedder.embed_query("x")


def test_openai_compat_embedder_requires_key():
    with pytest.raises(EmbeddingError):
        OpenAICompatEmbedder(base_url="https://fake.local/v1", api_key="", model="emb")
