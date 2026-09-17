
from fastapi import FastAPI
from app.core.config import settings

# APIRouter
from app.api.v1.health import router as health_router

app = FastAPI(title=settings.app_name,version=settings.app_version)

# Include the health check endpoint
app.include_router(health_router)

@app.get("/ping")
def ping():
    return {"pong": True}