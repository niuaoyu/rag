"""M6 embedding 单测：hash 实现的确定性与"词面相关"排序 + OpenAI 兼容客户端的解析。

注意 hash 向量**不是语义向量**：这里断言的是"词面重叠越多、相似度越高"，
不要把它当成"检索质量"的证据。
"""

import json
from pathlib import Path

import httpx
import pytest

from app.services.embedding import (
    EmbeddingError,
    HashEmbedder,
    LocalOnnxEmbedder,
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


def test_resolve_verify_prefers_env_ca(monkeypatch, tmp_path):
    """沙箱/企业内网的自签 CA 场景：必须尊重环境里的 CA 文件，而不是关掉校验。"""
    from app.core.http import resolve_verify

    ca = tmp_path / "ca.crt"
    ca.write_text("fake ca")
    for name in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE"):
        monkeypatch.delenv(name, raising=False)
    assert resolve_verify() is True

    monkeypatch.setenv("SSL_CERT_FILE", str(ca))
    assert resolve_verify() == str(ca)

    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(tmp_path / "missing.crt"))
    monkeypatch.delenv("SSL_CERT_FILE")
    assert resolve_verify() is True  # 路径不存在时不能假装有 CA


LOCAL_MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "bge-small-zh-v1.5"


@pytest.mark.skipif(
    not (LOCAL_MODEL_DIR / "model_optimized.onnx").exists(),
    reason="本地 ONNX 模型未下载（先跑 scripts/fetch_embedding_model.py）",
)
def test_local_onnx_embedder_is_semantic():
    """本地语义模型：构造后 dim 必须立刻可用（真实 e2e 暴露过 dim=0 的 bug），且能区分语义。"""
    embedder = LocalOnnxEmbedder(model_dir=LOCAL_MODEL_DIR)
    assert embedder.dim > 0, "构造后 dim 必须已确定（需要预热一次前向）"

    docs = [
        "苹果种植需要充足的光照和水分，套袋可以改善果实外观。",
        "区块链共识算法依赖工作量证明与权益证明机制。",
        "检索增强生成先从知识库检索相关片段，再基于片段生成带引用的回答。",
    ]
    vectors = embedder.embed_documents(docs)
    query = embedder.embed_query("怎么让苹果长得更好？")
    scores = [_cosine(query, vector) for vector in vectors]
    assert scores[0] > scores[1], "语义相关的文档应该排在无关文档前面"
    assert embedder.embed_query("怎么让苹果长得更好？") == query, "必须确定性"


@pytest.mark.skipif(
    not (LOCAL_MODEL_DIR / "model_optimized.onnx").exists(),
    reason="本地 ONNX 模型未下载",
)
def test_get_embedder_caches_instance(monkeypatch):
    from app.core.config import settings
    from app.services.embedding import get_embedder, reset_embedder_cache

    monkeypatch.setattr(settings, "embedding_provider", "local")
    monkeypatch.setattr(settings, "embedding_local_dir", str(LOCAL_MODEL_DIR))
    reset_embedder_cache()
    try:
        assert get_embedder(settings) is get_embedder(settings)
    finally:
        reset_embedder_cache()
