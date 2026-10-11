from contextlib import asynccontextmanager
from pathlib import Path
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, chat, documents
from app.core.config import settings
from app.core.errors import install_error_handlers
from app.core.logging import get_logger, setup_logging
from app.db.session import init_db

setup_logging()
logger = get_logger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("%s v%s started", settings.app_name, settings.app_version)
    yield
    logger.info("shutdown")


app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)

# 认证走 Authorization 头而非 Cookie，无需 credentials；两者并用本身违反 CORS 规范
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 统一错误出口：所有异常返回 {code, message} JSON
install_error_handlers(app)


@app.middleware("http")
async def _access_log(request: Request, call_next):
    t0 = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        logger.info("access %s %s -> %s %.1fms",
                    request.method, request.url.path, status, (time.perf_counter() - t0) * 1000)


# API 路由
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(chat.router)

# 静态资源（前端）
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health", tags=["system"])
def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "embedding_provider": settings.embedding_provider,
    }


@app.get("/", include_in_schema=False)
def index():
    """浏览器入口：直接打开一个可用的 Web 界面。"""
    return FileResponse(STATIC_DIR / "index.html")
