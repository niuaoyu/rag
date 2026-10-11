"""M8 LLM 客户端单测：用 httpx.MockTransport 假造服务端。

为什么不用真 key 测：真 key 测出来的是"今天这个厂商服务正常"，测不到我们的解析逻辑；
MockTransport 能把请求体、请求头、异常分支全部覆盖，且离线可跑。
"""

import json

import httpx
import pytest

from app.services.llm import LLMError, LLMNotConfigured, OpenAICompatLLM, build_llm


def _make_llm(handler) -> OpenAICompatLLM:
    return OpenAICompatLLM(
        base_url="https://fake.local/v1",
        api_key="test-key",
        model="fake-model",
        transport=httpx.MockTransport(handler),
    )


def test_complete_sends_openai_payload_and_parses_answer():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "fake-model"
        assert body["stream"] is False
        assert [m["role"] for m in body["messages"]] == ["system", "user"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "答案 [1]"}}]})

    assert _make_llm(handler).complete("sys", "user") == "答案 [1]"


def test_complete_http_error_becomes_llm_error():
    llm = _make_llm(lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(LLMError, match="LLM 调用失败"):
        llm.complete("sys", "user")


def test_complete_unexpected_payload_becomes_llm_error():
    llm = _make_llm(lambda request: httpx.Response(200, json={"nope": True}))
    with pytest.raises(LLMError, match="返回格式"):
        llm.complete("sys", "user")


def test_stream_parses_sse_deltas():
    sse = (
        b'data: {"choices":[{"delta":{"content":"\xe4\xbd\xa0"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"\xe5\xa5\xbd"}}]}\n\n'
        b"data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    assert list(_make_llm(handler).stream("sys", "user")) == ["你", "好"]


def test_stream_ignores_keepalive_and_bad_json():
    sse = b": keepalive\n\ndata: not-json\n\ndata: [DONE]\n\n"
    llm = _make_llm(lambda request: httpx.Response(200, content=sse))
    assert list(llm.stream("sys", "user")) == []


def test_missing_api_key_raises_not_configured(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "")
    with pytest.raises(LLMNotConfigured):
        build_llm(settings)


def test_constructor_without_key_raises():
    with pytest.raises(LLMNotConfigured):
        OpenAICompatLLM(base_url="https://fake.local/v1", api_key="", model="m")
