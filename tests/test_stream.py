"""M8/M9 增强：SSE 流式问答——事件序列完整、引用与落库正确。"""
import json


def _parse_sse(lines) -> list[dict]:
    events = []
    for line in lines:
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        line = line.strip()
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def test_stream_basic(client, auth, uploaded_document):
    with client.stream("POST", "/chat/stream",
                       json={"question": "volatile为什么不能保证i++线程安全？"},
                       headers=auth) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(r.iter_lines())

    types = [e["type"] for e in events]
    assert types[0] == "meta"
    assert "citations" in types
    assert "done" in types
    deltas = [e for e in events if e["type"] == "delta"]
    assert deltas, "至少应有一段增量输出"
    answer = "".join(e["content"] for e in deltas)
    assert "知识库" in answer
    done = events[-1]
    assert done["type"] == "done"
    assert done["citations"]


def test_stream_tool_round(client, auth, uploaded_document):
    q = "查询上海今天的天气，并结合我知识库中的跑步计划说说适不适合户外跑。"
    with client.stream("POST", "/chat/stream", json={"question": q}, headers=auth) as r:
        events = _parse_sse(r.iter_lines())
    types = [e["type"] for e in events]
    assert "tool_calls" in types
    tc = next(e for e in events if e["type"] == "tool_calls")
    assert tc["tool_calls"][0]["name"] == "get_weather"
    assert tc["tool_calls"][0]["ok"] is True
    assert types[-1] == "done"


def test_stream_no_tools(client, auth, uploaded_document):
    with client.stream("POST", "/chat/stream",
                       json={"question": "volatile保证原子性吗？", "use_tools": False},
                       headers=auth) as r:
        events = _parse_sse(r.iter_lines())
    assert all(e["type"] != "tool_calls" for e in events)
    assert events[-1]["type"] == "done"


def test_stream_bad_conversation_is_error_event(client, auth, uploaded_document):
    with client.stream("POST", "/chat/stream",
                       json={"question": "hi", "conversation_id": 99999},
                       headers=auth) as r:
        events = _parse_sse(r.iter_lines())
    assert events[-1]["type"] == "error"
