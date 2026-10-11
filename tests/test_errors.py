"""M10：统一错误出口——任何异常都返回 {code, message} JSON。"""
from fastapi.testclient import TestClient

from app.main import app


def test_auth_error_shape(client):
    r = client.post("/chat", json={"question": "hi"})
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "http_401"
    assert body["message"]


def test_validation_error_shape(client):
    r = client.post("/auth/register", json={})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    assert isinstance(body["errors"], list) and body["errors"]


def test_route_404_shape(client):
    r = client.get("/definitely/not/exist")
    assert r.status_code == 404
    assert r.json()["code"] == "http_404"


def test_business_404_shape(client, auth):
    r = client.post("/chat", json={"question": "hi", "conversation_id": 99999}, headers=auth)
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "conversation_not_found"


def test_unhandled_error_shape(client, auth, monkeypatch):
    from app.api import chat as chat_api

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(chat_api, "answer_question", boom)
    with TestClient(app, raise_server_exceptions=False) as c2:
        r = c2.post("/chat", json={"question": "hi"}, headers=auth)
    assert r.status_code == 500
    assert r.json()["code"] == "internal_error"
    assert "boom" not in r.text  # 不泄漏内部细节
