from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Document, User
from app.db.session import get_db
from app.schemas.document import DocumentResponse, UploadResponse
from app.services.ingest import ingest_document, save_upload

logger = get_logger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_SUFFIX = {".pdf", ".txt", ".md", ".markdown"}


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
def upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"仅支持 {', '.join(sorted(ALLOWED_SUFFIX))}")

    content = file.file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"文件超过 {settings.max_upload_mb}MB")

    stored_path = save_upload(content, file.filename or "unnamed")
    doc = Document(
        user_id=user.id,
        filename=Path(file.filename or "unnamed").name,
        stored_path=stored_path,
        status="pending",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    background_tasks.add_task(ingest_document, doc.id)
    logger.info("upload accepted: doc=%s user=%s size=%d", doc.id, user.id, len(content))
    return UploadResponse(
        document_id=doc.id, filename=doc.filename, status=doc.status,
        message="文件已上传，正在处理。",
    )


@router.get("", response_model=list[DocumentResponse])
def list_documents(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(Document)
        .filter(Document.user_id == user.id)
        .order_by(Document.id.desc())
        .all()
    )


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: int, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    return doc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: int, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    db.delete(doc)
    db.commit()
    try:
        Path(doc.stored_path).unlink(missing_ok=True)
    except OSError:
        pass
