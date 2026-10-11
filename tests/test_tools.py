"""M9：工具注册表与 Agent 轮次预算。"""
from app.services.tools import ALL_TOOL_SCHEMAS, run_tool


def test_registry_has_expected_tools():
    names = {t["function"]["name"] for t in ALL_TOOL_SCHEMAS}
    assert {"get_weather", "get_current_time"} <= names


def test_clock_tool_works():
    now = run_tool("get_current_time", {})
    assert len(now["date"]) == 10
    assert now["weekday"].startswith("周")


def test_unknown_tool_rejected():
    try:
        run_tool("definitely_not_a_tool", {})
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_tool_round_budget(client, auth, uploaded_document, monkeypatch):
    """模型若反复请求工具，必须在 tool_max_rounds 轮内强制收口。"""
    from app.core.config import settings as app_settings
    from app.services import rag as rag_mod

    monkeypatch.setattr(app_settings, "tool_max_rounds", 2)

    def fake_chat(messages, tools=None):
        if tools:
            return {"content": None, "tool_calls": [{
                "id": "f1", "type": "function",
                "function": {"name": "get_current_time", "arguments": "{}"},
            }]}
        return {"content": "final answer", "tool_calls": []}

    monkeypatch.setattr(rag_mod.llm, "chat", fake_chat)
    body = client.post("/chat", json={"question": "现在几点了？"}, headers=auth).json()
    assert len(body["tool_calls"]) == 2  # 恰好执行了预算内的 2 轮
    assert body["answer"] == "final answer"
