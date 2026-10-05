"""文档入库流水线：解析 -> 切块 -> embedding -> 落库（在后台线程执行）。"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Chunk, Document
from app.db.session import SessionLocal
from app.services.chunking import chunk_pages
from app.services.embedding import embed_texts
from app.services.parsing import parse_document

logger = get_logger(__name__)


def save_upload(content: bytes, filename: str) -> str:
    """保存上传文件，返回磁盘路径。"""
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    stored = upload_dir / f"{uuid.uuid4().hex}_{safe_name}"
    stored.write_bytes(content)
    return str(stored)


def ingest_document(document_id: int) -> None:
    """后台任务：处理单个文档。全程自管 session，失败写状态。"""
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None:
            logger.warning("ingest: document %s not found", document_id)
            return
        doc.status = "processing"
        doc.error = None
        db.commit()
        logger.info("ingest start: doc=%s file=%s", doc.id, doc.filename)

        pages = parse_document(doc.stored_path, doc.filename)
        chunks = chunk_pages(pages)
        if not chunks:
            raise ValueError("文档未解析出任何文本内容")

        embeddings = embed_texts([c.content for c in chunks])

        # 幂等：重跑前清掉旧 chunk
        for old in db.query(Chunk).filter(Chunk.document_id == doc.id).all():
            db.delete(old)
        db.flush()

        for ch, vec in zip(chunks, embeddings):
            db.add(
                Chunk(
                    document_id=doc.id,
                    user_id=doc.user_id,
                    ordinal=ch.ordinal,
                    page=ch.page,
                    content=ch.content,
                    embedding=json.dumps(vec),
                )
            )
        doc.chunk_count = len(chunks)
        doc.status = "done"
        db.commit()
        logger.info("ingest done: doc=%s chunks=%d", doc.id, len(chunks))
    except Exception as exc:  # noqa: BLE001 后台任务必须兜底
        db.rollback()
        logger.exception("ingest failed: doc=%s err=%s", document_id, exc)
        doc = db.get(Document, document_id)
        if doc is not None:
            doc.status = "failed"
            doc.error = str(exc)[:500]
            db.commit()
    finally:
        db.close()
