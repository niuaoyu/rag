from fastapi import APIRouter
from datetime import datetime , UTC

from app.core.config import settings

router = APIRouter()

@router.get("/healthz")
def health_check():
    return {"status": "healthy","version": settings.app_version, "timestamp": datetime.now(UTC)}