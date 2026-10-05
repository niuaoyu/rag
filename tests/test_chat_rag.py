def test_rag_answer_with_citation(client, auth, uploaded_document):
    r = client.post("/chat", json={"question": "volatile为什么不能保证i++线程安全？"}, headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["answer"]
    assert len(body["citations"]) >= 1
    assert any("Java并发编程" in c["filename"] for c in body["citations"])


def test_conversation_continuity(client, auth, uploaded_document):
    r1 = client.post("/chat", json={"question": "volatile保证原子性吗？"}, headers=auth)
    cid = r1.json()["conversation_id"]
    r2 = client.post("/chat", json={"question": "那应该用什么？", "conversation_id": cid}, headers=auth)
    assert r2.status_code == 200
    assert r2.json()["conversation_id"] == cid

    msgs = client.get(f"/chat/conversations/{cid}/messages", headers=auth).json()
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]


def test_agent_tool_calling(client, auth, uploaded_document):
    q = "查询北京今天的天气，并结合我知识库中的跑步计划告诉我今天适不适合户外训练。"
    body = client.post("/chat", json={"question": q}, headers=auth).json()
    assert len(body["tool_calls"]) == 1
    assert body["tool_calls"][0]["name"] == "get_weather"
    assert body["tool_calls"][0]["ok"] is True
    assert body["tool_calls"][0]["result"]["city"] == "北京"


def test_tools_can_be_disabled(client, auth, uploaded_document):
    q = "北京天气怎么样"
    body = client.post("/chat", json={"question": q, "use_tools": False}, headers=auth).json()
    assert body["tool_calls"] == []
