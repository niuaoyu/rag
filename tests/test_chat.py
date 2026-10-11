"""M8 问答接口测试：三种 mode、多租户隔离、流式。

为什么 mode 这么重要：没有 key 时**不能**用模板文本冒充"AI 回答"，
否则 demo 看起来完美、面试一追问（"你这段回答是模型生成的吗？"）就崩。
"""

from tests.conftest import auth_header
from tests.test_pipeline import _upload


class FakeLLM:
    name = "fake"

    def complete(self, system: str, user: str) -> str:
        assert "【资料】" in user  # 提示词里必须真的带上检索到的资料
        return "FAKE ANSWER [1]"

    def stream(self, system: str, user: str):
        yield "FAKE "
        yield "STREAM"


def _ask(client, token, question, **extra):
    return client.post(
        "/api/v1/chat/ask",
        headers=auth_header(token),
        json={"question": question, **extra},
    )


def test_no_context_when_user_has_no_documents(client, rag_env, user_b):
    _, _, token = user_b
    response = _ask(client, token, "我什么都没上传，问什么？")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "no_context"
    assert body["answer"] is None
    assert body["citations"] == []


def test_retrieval_only_without_llm_key(client, rag_env, user_a):
    _, _, token = user_a
    _upload(client, token, "kb.txt", ("检索增强生成会先检索再生成。" * 60).encode("utf-8"))

    body = _ask(client, token, "检索增强生成是什么").json()
    assert body["mode"] == "retrieval_only"
    assert body["answer"] is None  # 不伪造答案
    assert body["retrieved_count"] > 0
    assert body["citations"]
    assert "未配置 LLM" in body["note"]
    first = body["citations"][0]
    assert first["filename"] == "kb.txt"
    assert first["snippet"]
    assert first["score"] > 0


def test_llm_mode_with_fake_model(client, rag_env, user_a, monkeypatch):
    import app.services.rag as rag_module

    _, _, token = user_a
    _upload(client, token, "kb.txt", ("检索增强生成会先检索再生成。" * 60).encode("utf-8"))
    monkeypatch.setattr(rag_module, "build_llm", lambda cfg=None: FakeLLM())

    body = _ask(client, token, "检索增强生成是什么").json()
    assert body["mode"] == "llm"
    assert body["answer"] == "FAKE ANSWER [1]"
    assert body["citations"]


def test_retrieval_does_not_leak_across_users(client, rag_env, user_a, user_b):
    _, _, token_a = user_a
    _, _, token_b = user_b
    doc_a = _upload(
        client, token_a, "apple.txt", ("苹果种植技术要点：套袋、疏花疏果。" * 40).encode("utf-8")
    ).json()["id"]
    doc_b = _upload(
        client, token_b, "chain.txt", ("区块链共识算法：PoW 与 PoS 的取舍。" * 40).encode("utf-8")
    ).json()["id"]

    body = _ask(client, token_b, "苹果怎么种").json()
    assert body["citations"], "B 自己的文档应该被检索到"
    assert {c["document_id"] for c in body["citations"]} == {doc_b}
    assert doc_a not in {c["document_id"] for c in body["citations"]}


def test_document_ids_of_other_user_is_404(client, rag_env, user_a, user_b):
    _, _, token_a = user_a
    _, _, token_b = user_b
    doc_a = _upload(client, token_a, "a.txt", b"hello world " * 50).json()["id"]

    response = _ask(client, token_b, "hello", document_ids=[doc_a])
    assert response.status_code == 404


def test_empty_question_is_rejected(client, rag_env, user_a):
    _, _, token = user_a
    response = _ask(client, token, "")
    assert response.status_code == 422


def test_stream_requires_llm_config(client, rag_env, user_a):
    _, _, token = user_a
    _upload(client, token, "kb.txt", ("检索增强生成会先检索再生成。" * 60).encode("utf-8"))
    response = client.post(
        "/api/v1/chat/ask/stream",
        headers=auth_header(token),
        json={"question": "检索增强生成是什么"},
    )
    assert response.status_code == 503


def test_stream_emits_citations_then_deltas(client, rag_env, user_a, monkeypatch):
    import app.api.v1.chat as chat_module

    _, _, token = user_a
    _upload(client, token, "kb.txt", ("检索增强生成会先检索再生成。" * 60).encode("utf-8"))
    monkeypatch.setattr(chat_module, "build_llm", lambda cfg=None: FakeLLM())

    response = client.post(
        "/api/v1/chat/ask/stream",
        headers=auth_header(token),
        json={"question": "检索增强生成是什么"},
    )
    assert response.status_code == 200
    text = response.text
    assert "event: citations" in text
    assert "FAKE " in text and "STREAM" in text
    assert text.rstrip().endswith("[DONE]")


def test_stream_404_when_no_context(client, rag_env, user_b, monkeypatch):
    import app.api.v1.chat as chat_module

    monkeypatch.setattr(chat_module, "build_llm", lambda cfg=None: FakeLLM())
    _, _, token = user_b
    response = client.post(
        "/api/v1/chat/ask/stream",
        headers=auth_header(token),
        json={"question": "没有任何文档"},
    )
    assert response.status_code == 404
