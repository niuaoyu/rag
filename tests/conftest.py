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
def client(db_engine,tmp_path,monkeypatch):
    # 测试用的upload_dir路径，避免污染生产环境
    monkeypatch.setattr(settings,"upload_dir", tmp_path) # 只会在当前的测试里把upload_dir改成tmp_path，测试结束后自动恢复
    # tmp_path返回一个临时目录路径，测试结束后自动删除 不用管目录是什么？默认会随机给一个
    SessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)

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