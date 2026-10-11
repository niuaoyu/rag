"""M7：检索。

管道：query → embedding → 向量库 top-k（带 user_id 过滤）→ **回表取正文** → 组装来源信息。

为什么检索完还要再查一次数据库：
1. 向量库 payload 只留定位信息，正文的唯一真相源是关系库；
2. 二次校验归属（defense in depth）：即使向量库的 payload 被写脏，也不会把别人的文档返回给你。
   → 面试会问"你的多租户隔离做在哪一层？"答案就是"向量库过滤 + 关系库回表校验"两层。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy.orm import Session

from app.core.config import settings as default_settings
from app.models.chunk import Chunk
from app.models.document import Document
from app.services.embedding import build_embedder
from app.services.vector_store import get_vector_store


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    document_id: int
    filename: str
    ordinal: int
    score: float
    text: str


def search_chunks(
    db: Session,
    user_id: int,
    query: str,
    top_k: int | None = None,
    document_ids: Sequence[int] | None = None,
    cfg=default_settings,
) -> list[RetrievedChunk]:
    query = (query or "").strip()
    if not query:
        return []

    limit = top_k or cfg.retrieval_top_k
    embedder = build_embedder(cfg)
    store = get_vector_store(dim=embedder.dim, cfg=cfg)
    hits = store.search(
        user_id=user_id,
        vector=embedder.embed_query(query),
        top_k=limit,
        document_ids=document_ids,
        min_score=cfg.retrieval_min_score,
    )
    if not hits:
        return []

    # 一次 in_ 批量取回，避免 N+1（面试：为什么不用 for 循环逐个 db.get）
    chunk_ids = [hit.chunk_id for hit in hits]
    rows = (
        db.query(Chunk, Document.filename)
        .join(Document, Chunk.document_id == Document.id)
        .filter(
            Chunk.id.in_(chunk_ids),
            Document.user_id == user_id,  # ← 归属二次校验
        )
        .all()
    )
    by_id = {chunk.id: (chunk, filename) for chunk, filename in rows}

    results: list[RetrievedChunk] = []
    for hit in hits:  # 保持向量库的相似度排序，不要用数据库返回顺序
        row = by_id.get(hit.chunk_id)
        if row is None:
            continue
        chunk, filename = row
        results.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                filename=filename,
                ordinal=chunk.ordinal,
                score=hit.score,
                text=chunk.text,
            )
        )
    return results
