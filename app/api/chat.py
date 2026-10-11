import json

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import Conversation, Message, User
from app.db.session import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.rag import answer_question, answer_question_stream

logger = get_logger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, user: User = Depends(get_current_user),
         db: Session = Depends(get_db)):
    try:
        result = answer_question(
            db, user.id, payload.question,
            conversation_id=payload.conversation_id,
            use_tools=payload.use_tools,
        )
    except ValueError as exc:
        raise AppError(status.HTTP_404_NOT_FOUND, "conversation_not_found", str(exc))
    return ChatResponse(**result)


@router.post("/stream")
def chat_stream(payload: ChatRequest, user: User = Depends(get_current_user)):
    """SSE 流式问答。事件序列：meta -> stage -> citations -> [tool_calls]* -> delta* -> done。
    会话校验失败等业务错误以 {"type": "error"} 事件返回（流已开始，状态码固定 200）。"""

    def gen():
        for event in answer_question_stream(
            user.id, payload.question,
            conversation_id=payload.conversation_id,
            use_tools=payload.use_tools,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/conversations")
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id)
        .order_by(Conversation.id.desc())
        .all()
    )
    return [{"id": c.id, "title": c.title, "created_at": c.created_at} for c in convs]


@router.get("/conversations/{conversation_id}/messages")
def get_messages(conversation_id: int, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise AppError(status.HTTP_404_NOT_FOUND, "conversation_not_found", "会话不存在")
    msgs = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.id).all()
    return [
        {"id": m.id, "role": m.role, "content": m.content,
         "citations": m.citations, "created_at": m.created_at}
        for m in msgs
    ]
