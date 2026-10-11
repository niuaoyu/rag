
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from sqlalchemy.orm import Session

from app.api.current_user import get_current_user
from app.core.tokenizer import count_tokens
from app.db import get_db
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.user import User
from app.schemas.document import ChunkOut, DocumentOut
from app.services.document import get_document_by_user_id
from app.services.processing import process_document
from app.services.storage import save_upload

router = APIRouter(prefix="/api/v1/documents",tags=["documents"])


def _to_out(doc: Document) -> DocumentOut:
    """把 ORM 对象转成响应模型，并补上 text 的统计量。

    为什么不在模型里存 char_count/token_count：它们完全由 text 派生，存下来就有"不一致"的可能。
    派生量按需算，代价是每次读都得算一遍（大文档是 O(n)，M11 再考虑缓存）。
    """
    out = DocumentOut.model_validate(doc)
    if doc.text:
        out.char_count = len(doc.text)
        out.token_count = count_tokens(doc.text)
    return out


@router.post("",status_code=201,response_model=DocumentOut)
def upload(
    background_tasks: BackgroundTasks,
    file:UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user:User = Depends(get_current_user),
):
    """上传并**立即返回** 201：解析/切块/入向量库全部丢给后台任务。

    响应里的 status 是 pending；真实进度要轮询 GET /{doc_id}。
    为什么不能等解析完再返回：解析 PDF + 调 embedding 是秒级到几十秒级，
    卡在请求里会占满 worker、超时、且客户端无法重试（M4 会考①）。
    """
    doc = save_upload(current_user.id,file=file,db=db)
    background_tasks.add_task(process_document, doc.id)
    return _to_out(doc)

@router.get("", response_model=list[DocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列表**不返回正文**：一份文档的 text 可能几十万字，列表接口带上它会拖垮响应体。

    正文只在 GET /{doc_id} 单查时返回。
    """
    docs = (
        db.query(Document)
        .filter(Document.user_id == current_user.id)
        .order_by(Document.id.desc())
        .all()
    )
    return [
        DocumentOut.model_validate(doc).model_copy(update={"text": None}) for doc in docs
    ]


@router.get("/{doc_id}",response_model=DocumentOut)
def get_document(doc_id:int,db:Session=Depends(get_db),user:User = Depends(get_current_user)):
    """轮询用接口：status 变 done 时 text 非空，变 failed 时 error_message 非空。"""
    return _to_out(get_document_by_user_id(doc_id=doc_id,db=db,user=user))


@router.get("/{doc_id}/chunks", response_model=list[ChunkOut])
def list_chunks(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """看切块结果（M5 的验收：1 份文档切成 N 块，每块大小符合契约）。

    先用 get_document_by_user_id 做归属校验：文档不属于你就 404，不泄露"这条 id 存在"。
    """
    get_document_by_user_id(doc_id=doc_id, db=db, user=user)
    return (
        db.query(Chunk)
        .filter(Chunk.document_id == doc_id)
        .order_by(Chunk.ordinal)
        .all()
    )


@router.post("/{doc_id}/reprocess", response_model=DocumentOut, status_code=202)
def reprocess(
    doc_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """重新跑处理管道（改了解码规则/切块参数后回填用）。

    幂等性由 process_document 保证：先删旧 chunks 与旧向量，再写新的。
    """
    doc = get_document_by_user_id(doc_id=doc_id, db=db, user=user)
    background_tasks.add_task(process_document, doc.id)
    return _to_out(doc)
