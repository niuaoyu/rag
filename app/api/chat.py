from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.logging import get_logger
from app.db.models import Conversation, Message, User
from app.db.session import get_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.rag import answer_question

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
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    return ChatResponse(**result)


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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    msgs = db.query(Message).filter(Message.conversation_id == conversation_id).order_by(Message.id).all()
    return [
        {"id": m.id, "role": m.role, "content": m.content,
         "citations": m.citations, "created_at": m.created_at}
        for m in msgs
    ]
