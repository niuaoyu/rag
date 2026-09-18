
from fastapi import FastAPI
from app.core.config import settings

# APIRouter
from app.api.v1 import api_router

from app.db import engine
from app.models.user import Base
from app.models import __all__ 
Base.metadata.create_all(bind=engine) 
# 目的是建表，建表时会自动创建外键约束。
# SQLite 默认不启用外键约束，需要在连接时设置 PRAGMA foreign_keys=ON。SQLAlchemy 里可以通过 event.listen() 来设置。

app = FastAPI(title=settings.app_name,version=settings.app_version)

app.include_router(api_router)



@app.get("/ping")
def ping():
    return {"pong": True}