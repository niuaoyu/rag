from fastapi.testclient import TestClient
import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db import get_db
from app.models.user import Base
from app.main import app


@pytest.fixture()
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread":False}, # FastAPI 的 def 路由跑在线程池，SQLite 默认禁止跨线程。测试时也要加
        poolclass=StaticPool, #解决内存 SQLite 的「多连接不共享」问题。 
    )
    Base.metadata.create_all(bind=engine)  # 建表
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

# 好像没用到
@pytest.fixture
def db_session(db_engine):
    SessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    yield session
    session.close() 

# @pytest.fixture
# def temp_path(tmp_path):
#     """返回一个临时目录路径，测试结束后自动删除。"""
#     return tmp_path


@pytest.fixture
def session_factory(db_engine):
    """测试用的 sessionmaker：后台任务必须写进同一个内存库，才有得断言。"""
    return sessionmaker(bind=db_engine, autocommit=False, autoflush=False)


@pytest.fixture(autouse=True)
def rag_env(monkeypatch, tmp_path):
    """把整条 RAG 管道切到"离线确定性"档：

    - embedding 用 hash（不是语义向量，只保证管道真跑起来、检索能命中词面相关的块）
    - Qdrant 用每个用例独立的临时目录（避免用例之间共享向量 → 检索到别的用例的数据）
    - chunk 参数调小，方便断言块数
    - llm_api_key 置空 → /chat/ask 走 retrieval_only，不依赖外网
    """
    from app.core.config import settings as live_settings
    from app.services.vector_store import reset_vector_store_cache

    monkeypatch.setattr(live_settings, "embedding_provider", "hash")
    monkeypatch.setattr(live_settings, "embedding_dim", 256)
    monkeypatch.setattr(live_settings, "qdrant_path", str(tmp_path / "qdrant"))
    monkeypatch.setattr(live_settings, "qdrant_collection", "chunks_test")
    monkeypatch.setattr(live_settings, "chunk_size_tokens", 120)
    monkeypatch.setattr(live_settings, "chunk_overlap_tokens", 20)
    monkeypatch.setattr(live_settings, "llm_api_key", "")
    reset_vector_store_cache()
    yield live_settings
    reset_vector_store_cache()


@pytest.fixture
def client(db_engine, tmp_path, monkeypatch, session_factory):
    # 测试用的upload_dir路径，避免污染生产环境
    monkeypatch.setattr(settings,"upload_dir", tmp_path) # 只会在当前的测试里把upload_dir改成tmp_path，测试结束后自动恢复
    # tmp_path返回一个临时目录路径，测试结束后自动删除 不用管目录是什么？默认会随机给一个
    SessionLocal = session_factory
    # ★ 后台任务自己开 session（process_document 里 from app import db 后再取 SessionLocal），
    #   不把这里的工厂换掉的话，后台任务会写进真实的 ./app.db，断言全落空。
    monkeypatch.setattr("app.db.SessionLocal", SessionLocal)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db # 生产 get_db 换成测试 get_db。测试结束后 clear()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def registered_user(client):
    """注册一个用户，返回 (email, password)。"""
    email = "test@example.com"
    password = "password123"
    response = client.post(
        "/api/v1/users/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 201
    return email, password

@pytest.fixture
def user_a(client):
    """注册一个用户A，返回 (email, password)。"""
    email = "user_a@example.com"
    password = "password123"
    response = client.post(
        "/api/v1/users/register",
        json={"email": email, "password": password},
    )
    token = client.post(
        "/api/v1/users/login",
        json={"email": email, "password": password},
    ).json()["access_token"]
    return email, password, token

@pytest.fixture
def user_b(client):
    """注册一个用户B，返回 (email, password)。"""
    email = "user_b@example.com"
    password = "password123"
    response = client.post(
        "/api/v1/users/register",
        json={"email": email, "password": password},
    )
    token = client.post(
        "/api/v1/users/login",
        json={"email": email, "password": password},
    ).json()["access_token"]
    return email, password, token

def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}