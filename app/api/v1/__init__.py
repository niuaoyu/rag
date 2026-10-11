

from fastapi import APIRouter

from app.api.v1 import chat, documents, health, user


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(user.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
