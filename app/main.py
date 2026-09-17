
from fastapi import FastAPI
from app.core.config import settings

# APIRouter
from app.api.v1 import api_router

from app.db import engine
from app.models.user import User,Base
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name,version=settings.app_version)

app.include_router(api_router)



@app.get("/ping")
def ping():
    return {"pong": True}