"""M4/M5/M6 的后台处理管道：解析 → 存全文 → 切块 → 入向量库 → 改状态。

关键设计（面试必问）：
- **状态只由这里改**，路由绝不碰 status（否则并发下会出现"接口把状态改成 done，任务还在写 text"）。
- **自己开 session**：后台任务跑在请求生命周期之外，复用路由的 get_db 会在响应结束后被关闭。
- **异常必须自己兜住**：BackgroundTasks 里未捕获的异常只会打进日志，客户端永远看到 processing。
  所以最外层 try/except 把失败写进 error_message 并置 failed。
- **幂等**：重新处理同一份文档时，先删该文档的旧 chunks 和旧向量，再写新的。
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings as default_settings
from app.core.tokenizer import count_tokens, tokenizer_backend
from app.models.chunk import Chunk
from app.models.document import Document
from app.services.chunker import chunk_text
from app.services.embedding import get_embedder
from app.services.parser import ParseError, parse_document
from app.services.vector_store import VectorRecord, get_vector_store

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"

# 状态机白名单：只允许这两个方向，避免"failed → done"这种绕过重试的跳变
ALLOWED_TRANSITIONS = {
    STATUS_PENDING: {STATUS_PROCESSING, STATUS_FAILED},
    STATUS_PROCESSING: {STATUS_DONE, STATUS_FAILED},
    STATUS_FAILED: {STATUS_PROCESSING},
    # done → processing 只用于显式"重新处理"（POST /documents/{id}/reprocess）；
    # 不放在这里的话，重跑已完成文档会被状态机挡住，而幂等重跑本身是必要能力。
    STATUS_DONE: {STATUS_PROCESSING},
}

ERROR_MESSAGE_MAX = 255


def _new_session() -> Session:
    """每次调用都从 app.db 现取 SessionLocal —— 测试里可以直接 monkeypatch app.db.SessionLocal。"""
    from app import db as db_module

    return db_module.SessionLocal()


def update_document_status(
    db: Session, doc_id: int, status: str, error: str | None = None
) -> Document | None:
    """唯一改状态的地方。非法跃迁直接抛错（宁可炸，也不要静默写出一个不可能的状态）。"""
    doc = db.get(Document, doc_id)
    if doc is None:
        return None
    current = doc.status
    if current != status and status not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"非法状态跃迁: {current} → {status}")
    doc.status = status
    doc.error_message = (error or "")[:ERROR_MESSAGE_MAX] or None
    db.commit()
    db.refresh(doc)
    return doc


def process_document(doc_id: int, cfg=default_settings) -> None:
    """后台任务入口。签名保持 (doc_id)，方便 BackgroundTasks / 后续换 Celery 时只换调用方。"""
    db = _new_session()
    try:
        doc = db.get(Document, doc_id)
        if doc is None:
            logger.warning("process_document: 文档 %s 不存在，跳过", doc_id)
            return

        update_document_status(db, doc_id, STATUS_PROCESSING)

        path = Path(doc.store_path)
        if not path.exists():
            raise ParseError(f"落盘文件不存在: {path}")

        text = parse_document(path)
        if len(text.strip()) < cfg.chunk_min_chars:
            raise ParseError(f"解析结果过短（{len(text.strip())} 字符），视为空文档")

        doc.text = text
        db.commit()

        drafts = chunk_text(
            text, size_tokens=cfg.chunk_size_tokens, overlap_tokens=cfg.chunk_overlap_tokens
        )
        if not drafts:
            raise ParseError("切块结果为空")

        # 幂等：先清掉这份文档的旧块与旧向量
        db.query(Chunk).filter(Chunk.document_id == doc_id).delete()
        db.commit()

        embedder = get_embedder(cfg)
        store = get_vector_store(dim=embedder.dim, cfg=cfg)
        store.delete_document(doc_id)

        chunk_rows = [
            Chunk(
                document_id=doc_id,
                ordinal=draft.ordinal,
                text=draft.text,
                char_count=draft.char_count,
                token_count=draft.token_count,
            )
            for draft in drafts
        ]
        db.add_all(chunk_rows)
        db.commit()
        for row in chunk_rows:
            db.refresh(row)

        vectors = embedder.embed_documents([row.text for row in chunk_rows])
        store.upsert_chunks(
            [
                VectorRecord(
                    chunk_id=row.id,
                    vector=vector,
                    user_id=doc.user_id,
                    document_id=doc_id,
                    ordinal=row.ordinal,
                )
                for row, vector in zip(chunk_rows, vectors)
            ]
        )

        update_document_status(db, doc_id, STATUS_DONE)
        logger.info(
            "process_document: doc=%s 完成，%s 块，tokenizer=%s",
            doc_id,
            len(chunk_rows),
            tokenizer_backend(),
        )
    except Exception as exc:  # noqa: BLE001 - 后台任务必须自己兜住一切
        message = f"{type(exc).__name__}: {exc}"
        logger.exception("process_document: doc=%s 失败", doc_id)
        # 记录 token 计的额外信息便于排查，也确保 error_message 不超过列宽
        try:
            db.rollback()
            update_document_status(db, doc_id, STATUS_FAILED, error=message[:ERROR_MESSAGE_MAX])
        except Exception:  # pragma: no cover - 连失败都写不进去时只能记日志
            logger.exception("process_document: 写入 failed 状态也失败 doc=%s", doc_id)
    finally:
        db.close()


def count_document_tokens(text: str) -> int:
    """给接口层复用的 token 计数（避免接口直接 import tokenizer 细节）。"""
    return count_tokens(text)
