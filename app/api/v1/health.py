from fastapi import APIRouter
from datetime import datetime , UTC

from app.core.config import settings
from app.core.tokenizer import tokenizer_backend

router = APIRouter()

@router.get("/healthz")
def health_check():
    return {"status": "ok","version": settings.app_version, "time": datetime.now(UTC),
            # 这三个字段是"防止自欺"用的：demo 时一眼能看出当前跑的是真 embedding 还是 hash、
            # token 数是真 BPE 还是估算、LLM 到底配没配。
            "tokenizer": tokenizer_backend(),
            "embedding_provider": settings.embedding_provider,
            "llm_configured": bool(settings.llm_api_key)}