

from fastapi import APIRouter

from app.api.v1 import health, user


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(user.router)
