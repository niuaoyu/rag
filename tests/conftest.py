from fastapi.testclient import TestClient
import pytest
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

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

@pytest.fixture
def db_session(db_engine):
    SessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    yield session
    session.close() 

@pytest.fixture
def client(db_engine):
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

