"""M4/M5/M6 集成测试：上传 → 后台处理 → 状态机 → 切块 → 入向量库。

这里依赖两个关键事实（面试考点，见 doc/m4异步处理.md）：
1. TestClient 会**等后台任务跑完**才把响应交回调用者 → 测试里可以直接断言 done；
   而响应体是在任务开始前生成的，所以 body 里的 status 仍是 pending。这个差异本身就是考点。
2. 后台任务自己开 session，所以 conftest 里必须把 app.db.SessionLocal 换成测试库，
   否则它写进真实的 ./app.db，测试断言全部落空（这类 bug 极难发现）。
"""

import pytest

from app.core.config import settings
from app.services.processing import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    update_document_status,
)
from tests.conftest import auth_header
from tests.test_parser import _minimal_pdf

PARA = "检索增强生成把外部知识库接进大模型，先检索再生成，答案里带上来源引用。"
GBK_PAYLOAD = "这是GBK编码的中文文档内容，用来验证解码兜底链能从 utf-8 退回 gbk 并读出正确中文。"


def _long_text(paragraphs: int = 30) -> str:
    return "\n\n".join(f"{PARA}（第 {i} 段）" for i in range(paragraphs))


def _upload(client, token, filename, data, content_type="text/plain"):
    return client.post(
        "/api/v1/documents",
        headers=auth_header(token),
        files={"file": (filename, data, content_type)},
    )


def _get(client, token, doc_id):
    return client.get(f"/api/v1/documents/{doc_id}", headers=auth_header(token))


def test_upload_returns_immediately_then_pipeline_finishes(client, rag_env, user_a):
    _, _, token = user_a
    response = _upload(client, token, "kb.txt", _long_text().encode("utf-8"))
    assert response.status_code == 201
    # 响应体在后台任务开始前就生成好了 → 必须是 pending
    assert response.json()["status"] == STATUS_PENDING

    doc_id = response.json()["id"]
    detail = _get(client, token, doc_id)
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == STATUS_DONE
    assert body["text"]
    assert body["char_count"] == len(body["text"])
    assert body["token_count"] > 0
    assert body["error_message"] is None


def test_chunks_are_persisted_within_contract(client, rag_env, user_a):
    _, _, token = user_a
    doc_id = _upload(client, token, "kb.txt", _long_text().encode("utf-8")).json()["id"]

    response = client.get(f"/api/v1/documents/{doc_id}/chunks", headers=auth_header(token))
    assert response.status_code == 200
    chunks = response.json()
    assert len(chunks) > 1
    assert [c["ordinal"] for c in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert chunk["token_count"] <= settings.chunk_size_tokens + settings.chunk_overlap_tokens
        assert chunk["char_count"] == len(chunk["text"])


def test_vectors_land_in_qdrant_and_are_searchable(client, rag_env, user_a):
    from app.services.embedding import build_embedder
    from app.services.vector_store import get_vector_store

    _, _, token = user_a
    doc_id = _upload(client, token, "kb.txt", _long_text().encode("utf-8")).json()["id"]
    chunks = client.get(
        f"/api/v1/documents/{doc_id}/chunks", headers=auth_header(token)
    ).json()



    embedder = build_embedder(rag_env)
    store = get_vector_store(dim=embedder.dim, cfg=rag_env)
    assert store.count() == len(chunks)

    hits = store.search(user_id=1, vector=embedder.embed_query("检索增强生成"), top_k=5)
    assert hits
    assert {hit.chunk_id for hit in hits} <= {chunk["id"] for chunk in chunks}

def test_gbk_document_is_parsed(client, rag_env, user_a):
    _, _, token = user_a
    doc_id = _upload(
        client, token, "gbk.txt", GBK_PAYLOAD.encode("gbk")
    ).json()["id"]
    body = _get(client, token, doc_id).json()
    assert body["status"] == STATUS_DONE
    assert "GBK编码" in body["text"]


def test_pdf_document_is_parsed(client, rag_env, user_a):
    _, _, token = user_a
    doc_id = _upload(
        client, token, "hello.pdf", _minimal_pdf("Hello PDF Pipeline with enough text for the minimum length check"), "application/pdf"
    ).json()["id"]
    body = _get(client, token, doc_id).json()
    assert body["status"] == STATUS_DONE
    assert "Hello PDF Pipeline" in body["text"]


def test_empty_document_fails_with_reason(client, rag_env, user_a):
    _, _, token = user_a
    doc_id = _upload(client, token, "empty.txt", b"").json()["id"]
    body = _get(client, token, doc_id).json()
    assert body["status"] == STATUS_FAILED
    assert body["error_message"]
    assert body["text"] is None


def test_failed_document_creates_no_chunks(client, rag_env, user_a):
    _, _, token = user_a
    doc_id = _upload(client, token, "empty.txt", b"").json()["id"]
    chunks = client.get(f"/api/v1/documents/{doc_id}/chunks", headers=auth_header(token)).json()
    assert chunks == []


def test_reprocess_is_idempotent(client, rag_env, user_a):
    from app.services.embedding import build_embedder
    from app.services.vector_store import get_vector_store

    _, _, token = user_a
    doc_id = _upload(client, token, "kb.txt", _long_text().encode("utf-8")).json()["id"]
    first = client.get(f"/api/v1/documents/{doc_id}/chunks", headers=auth_header(token)).json()

    response = client.post(f"/api/v1/documents/{doc_id}/reprocess", headers=auth_header(token))
    assert response.status_code == 202

    second = client.get(f"/api/v1/documents/{doc_id}/chunks", headers=auth_header(token)).json()
    assert len(second) == len(first)  # 没有插出第二套块
    assert [c["ordinal"] for c in second] == list(range(len(second)))
    assert _get(client, token, doc_id).json()["status"] == STATUS_DONE

    embedder = build_embedder(rag_env)
    store = get_vector_store(dim=embedder.dim, cfg=rag_env)
    assert store.count() == len(second)  # 向量也没重复


def test_status_machine_rejects_illegal_transition(client, rag_env, user_a, session_factory):
    """done 不能退回 pending：状态只能由后台任务按白名单推进，路由和调用方都不许乱改。"""
    _, _, token = user_a
    doc_id = _upload(client, token, "kb.txt", _long_text().encode("utf-8")).json()["id"]

    db = session_factory()
    try:
        with pytest.raises(ValueError, match="非法状态跃迁"):
            update_document_status(db, doc_id, STATUS_PENDING)
    finally:
        db.close()

