import dataclasses
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.current_user import get_current_user
from app.db import get_db
from app.models.document import Document
from app.models.user import User
from app.schemas.chat import AskRequest, AskResponse, CitationOut
from app.services.llm import LLMNotConfigured, build_llm
from app.services.rag import SYSTEM_PROMPT, answer_question, build_context, build_user_prompt
from app.services.retrieval import search_chunks

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


def _owned_document_ids(db: Session, user_id: int) -> set[int]:
    return {row.id for row in db.query(Document.id).filter(Document.user_id == user_id).all()}


def _check_ownership(db: Session, user_id: int, document_ids: list[int] | None) -> None:
    """指定了 document_ids 时必须校验归属：不过滤就等于允许越权检索别人的文档。"""
    if not document_ids:
        return
    owned = _owned_document_ids(db, user_id)
    missing = [doc_id for doc_id in document_ids if doc_id not in owned]
    if missing:
        raise HTTPException(status_code=404, detail=f"文档不存在或不属于你: {missing}")


def _to_response(result) -> AskResponse:
    return AskResponse(
        question=result.question,
        answer=result.answer,
        mode=result.mode,
        citations=[CitationOut(**dataclasses.asdict(c)) for c in result.citations],
        retrieved_count=result.retrieved_count,
        latency_ms=result.latency_ms,
        note=result.note,
    )


@router.post("/ask", response_model=AskResponse)
def ask(
    payload: AskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """检索 + 生成，返回**带来源引用**的答案。

    mode 的含义：
    - llm            真正调了模型
    - retrieval_only 没配 key 或模型报错 → 只回检索结果，不伪造答案
    - no_context     没检索到相关内容 → 不调模型（幻觉的最大来源就是"硬答"）
    """
    _check_ownership(db, current_user.id, payload.document_ids)
    result = answer_question(
        db=db,
        user_id=current_user.id,
        question=payload.question,
        top_k=payload.top_k,
    )
    return _to_response(result)


@router.post("/ask/stream")
def ask_stream(
    payload: AskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SSE 流式版：先推一份来源清单（citations），再逐段推答案增量。

    为什么先推 citations：流式下用户最怕"答案流到一半你告诉我要点开哪个文档"；
    检索是先于生成的，顺序天然如此，别浪费。

    注意：数据库 session 只在**进入生成器之前**使用，生成器里只碰已取回的内存数据 ——
    否则会出现"响应还在流、session 已被依赖清理关闭"的经典报错。
    """
    _check_ownership(db, current_user.id, payload.document_ids)
    chunks = search_chunks(
        db, current_user.id, payload.question, top_k=payload.top_k
    )
    citations = [
        {
            "index": i,
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "filename": chunk.filename,
            "ordinal": chunk.ordinal,
            "score": round(chunk.score, 4),
        }
        for i, chunk in enumerate(chunks, start=1)
    ]
    if not chunks:
        raise HTTPException(status_code=404, detail="没有检索到相关内容，未调用模型")

    try:
        llm = build_llm()
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=503, detail=f"未配置 LLM，无法流式生成：{exc}") from exc

    context = build_context(chunks)
    user_prompt = build_user_prompt(payload.question, context)

    def event_stream():
        yield f"event: citations\ndata: {json.dumps(citations, ensure_ascii=False)}\n\n"
        try:
            for delta in llm.stream(SYSTEM_PROMPT, user_prompt):
                yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001 - 流中途出错只能以事件形式告知
            yield f"event: error\ndata: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

