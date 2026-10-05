"""向量存储与语义检索。

MVP 阶段直接把向量以 JSON 存在关系库里 + 进程内暴力检索。
数据量大或上生产时替换成 pgvector / Qdrant / Chroma，接口保持不变。
"""
from __future__ import annotations

import json

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Chunk
from app.services.embedding import embed_query

logger = get_logger(__name__)


def search_chunks(db: Session, user_id: int, query: str, top_k: int | None = None,
                  document_ids: list[int] | None = None) -> list[tuple[Chunk, float]]:
    k = top_k or settings.top_k
    stmt = select(Chunk).where(Chunk.user_id == user_id)
    if document_ids:
        stmt = stmt.where(Chunk.document_id.in_(document_ids))
    chunks = db.execute(stmt).scalars().all()
    if not chunks:
        return []

    q = np.asarray(embed_query(query), dtype=np.float32)
    qn = float(np.linalg.norm(q)) or 1.0
    scored: list[tuple[Chunk, float]] = []
    for ch in chunks:
        try:
            v = np.asarray(json.loads(ch.embedding), dtype=np.float32)
        except (ValueError, TypeError):
            continue
        vn = float(np.linalg.norm(v)) or 1.0
        scored.append((ch, float(np.dot(q, v) / (qn * vn))))
    scored.sort(key=lambda x: x[1], reverse=True)
    results = scored[:k]
    logger.info("vector search user=%s query_len=%d hits=%d top=%.3f",
                user_id, len(query), len(results), results[0][1] if results else -1)
    return results
