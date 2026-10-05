"""测试环境：使用独立的临时 SQLite + 临时上传目录，避免污染开发数据。"""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="rag_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["UPLOAD_DIR"] = f"{_tmp}/uploads"
os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["WEATHER_API_KEY"] = ""
os.environ["JWT_SECRET"] = "test-secret-key-for-pytest-only-32chars!!"

import pytest
from fastapi.testclient import TestClient

from app.db.session import init_db
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def _db():
    init_db()
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth(client):
    client.post("/auth/register", json={"username": "tester", "password": "tester123"})
    token = client.post("/auth/login", json={"username": "tester", "password": "tester123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


SAMPLE = """
volatile关键字只能保证可见性和有序性，不能保证原子性。i++包含读取、加1、写回三个步骤，
多线程执行i++可能交错，导致丢失更新。要保证原子性应使用synchronized或AtomicInteger。
synchronized可以保证原子性、可见性和有序性，是互斥锁。volatile是轻量级同步，不阻塞线程。
跑步计划：每周一三五早上跑5公里，周末长距离10公里，下雨或空气质量差就不跑。
""".strip()


@pytest.fixture()
def uploaded_document(client, auth):
    files = {"file": ("Java并发编程.txt", SAMPLE.encode("utf-8"), "text/plain")}
    resp = client.post("/documents/upload", files=files, headers=auth)
    assert resp.status_code == 202
    return resp.json()["document_id"]
