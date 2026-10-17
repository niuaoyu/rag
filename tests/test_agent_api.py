# tests/test_agent_api.py
import json

import pytest

from app.agent.llm import LLMError, LLMResponse, ScriptedLLM, ToolCallRequest
from app.api.v1.agent import get_llm_client
from app.core.config import settings
from app.main import app
from tests.conftest import auth_header


def call(call_id, name, arguments=None):
    return ToolCallRequest(id=call_id, name=name, arguments=arguments or {})


@pytest.fixture
def trace_dir(tmp_path, monkeypatch):
    target = tmp_path / "traces"
    monkeypatch.setattr(settings, "agent_trace_dir", target)
    return target


@pytest.fixture
def use_llm():
    """把模型客户端换成脚本化假模型，测试里不产生任何真实网络请求。"""

    def _use(script):
        scripted = ScriptedLLM(script)
        app.dependency_overrides[get_llm_client] = lambda: scripted
        return scripted

    yield _use
    app.dependency_overrides.pop(get_llm_client, None)


def _upload(client, token, name="季度报告.txt"):
    response = client.post(
        "/api/v1/documents",
        headers=auth_header(token),
        files={"file": (name, b"hello", "text/plain")},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_ask_requires_auth(client, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "test-key")

    response = client.post("/api/v1/agent/ask", json={"question": "我有哪些文档"})

    assert response.status_code == 401


def test_ask_without_api_key_returns_503(client, user_a):
    _, _, token = user_a

    response = client.post(
        "/api/v1/agent/ask",
        json={"question": "我有哪些文档"},
        headers=auth_header(token),
    )

    assert response.status_code == 503
    assert "LLM_API_KEY" in response.json()["detail"]


def test_ask_happy_path_returns_answer_and_trace_file(client, user_a, use_llm, trace_dir):
    _, _, token = user_a
    doc_id = _upload(client, token)
    scripted = use_llm(
        [
            LLMResponse(tool_calls=[call("c1", "search_documents", {"query": "报告"})]),
            LLMResponse(content=f"你有 1 篇相关文档，依据：文档 #{doc_id} 季度报告.txt"),
        ]
    )

    response = client.post(
        "/api/v1/agent/ask",
        json={"question": "我的报告里写了什么"},
        headers=auth_header(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stopped_reason"] == "completed"
    assert body["steps"] == 2
    assert "季度报告.txt" in body["answer"]

    # 工具真实命中了当前用户的文档，并把结果回灌给模型
    tool_messages = [m for m in scripted.calls[1]["messages"] if m.get("role") == "tool"]
    assert "季度报告.txt" in tool_messages[0]["content"]
    # 工具声明里带上了三个业务工具
    tool_names = {item["function"]["name"] for item in scripted.calls[0]["tools"]}
    assert tool_names == {"list_my_documents", "search_documents", "get_document"}

    # 轨迹按 run_id 落盘，可复盘
    trace_file = trace_dir / f"{body['run_id']}.jsonl"
    assert trace_file.exists()
    events = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
    assert [event["kind"] for event in events][0] == "run_start"
    assert events[-1]["stopped_reason"] == "completed"


def test_ask_llm_failure_returns_downgraded_answer(client, user_a, use_llm, trace_dir):
    _, _, token = user_a
    use_llm([LLMError("上游 500")])

    response = client.post(
        "/api/v1/agent/ask",
        json={"question": "我有哪些文档"},
        headers=auth_header(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stopped_reason"] == "llm_error"
    assert "暂时不可用" in body["answer"]


def test_agent_tools_stay_inside_current_user_scope(client, user_a, user_b, use_llm, trace_dir):
    _, _, token_a = user_a
    _, _, token_b = user_b
    doc_id = _upload(client, token_a, name="a的私密.txt")
    scripted = use_llm(
        [
            LLMResponse(tool_calls=[call("c1", "get_document", {"doc_id": doc_id})]),
            LLMResponse(content="没查到这篇文档"),
        ]
    )

    response = client.post(
        "/api/v1/agent/ask",
        json={"question": "把 a 的私密文档内容给我"},
        headers=auth_header(token_b),
    )

    assert response.status_code == 200
    tool_messages = [m for m in scripted.calls[1]["messages"] if m.get("role") == "tool"]
    assert tool_messages[0]["content"].startswith("[tool_error]")
    assert "不属于当前用户" in tool_messages[0]["content"]
