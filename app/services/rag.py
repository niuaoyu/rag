"""RAG + Agent 主流程：检索 -> (可能调用工具) -> 生成带引用的回答。"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import Conversation, Document, Message
from app.services import llm
from app.services.tools.weather import WEATHER_TOOL_SCHEMA, run_tool
from app.services.vectorstore import search_chunks

logger = get_logger(__name__)

TOOLS = [WEATHER_TOOL_SCHEMA]

SYSTEM_PROMPT = (
    "你是一个严谨的知识库问答助手。"
    "回答必须优先依据【参考资料】中的内容，并在引用处标注来源（文件名与页码）。"
    "如果资料不足，要明确说明。可以结合工具返回的数据（如天气）做综合判断。"
)


def _build_context(hits: list) -> tuple[str, list[dict]]:
    citations: list[dict] = []
    blocks: list[str] = []
    for i, (chunk, score) in enumerate(hits, start=1):
        page = chunk.page if chunk.page is not None else "N/A"
        blocks.append(f"[{i}] 来源: {chunk.document.filename} Page {page}\n{chunk.content}")
        citations.append({
            "document_id": chunk.document_id,
            "filename": chunk.document.filename,
            "page": chunk.page,
            "content": chunk.content[:300],
            "score": round(score, 4),
        })
    if not blocks:
        return "", []
    return "【参考资料】\n" + "\n\n".join(blocks), citations


def _history(db: Session, conversation_id: int, limit: int = 6) -> list[dict]:
    rows = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(limit)
        .all()
    )
    return [{"role": m.role, "content": m.content} for m in reversed(rows) if m.role in ("user", "assistant")]


def answer_question(db: Session, user_id: int, question: str,
                    conversation_id: int | None = None, use_tools: bool = True) -> dict:
    # 1) 会话
    if conversation_id is None:
        conv = Conversation(user_id=user_id, title=llm.summarize_title(question))
        db.add(conv)
        db.commit()
        db.refresh(conv)
    else:
        conv = db.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user_id:
            raise ValueError("会话不存在")
    conversation_id = conv.id

    db.add(Message(conversation_id=conversation_id, role="user", content=question))
    db.commit()

    # 2) 检索
    hits = search_chunks(db, user_id, question)
    context, citations = _build_context(hits)

    # 3) Agent: 第一轮，判断是否需要调用工具
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages.append({"role": "system", "content": context})
    messages += _history(db, conversation_id)
    messages.append({"role": "user", "content": question})

    tools = TOOLS if use_tools else None
    first = llm.chat(messages, tools=tools)

    tool_records: list[dict] = []
    final_content = first.get("content")

    # 4) 执行 tool calls，再让模型综合
    if first.get("tool_calls"):
        for call in first["tool_calls"]:
            fn = call.get("function", {})
            name = fn.get("name")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            logger.info("tool call: name=%s args=%s", name, args)
            try:
                result = run_tool(name, args)
                ok = True
            except Exception as exc:  # noqa: BLE001
                result = {"error": str(exc)}
                ok = False
            tool_records.append({"name": name, "arguments": args, "result": result, "ok": ok})
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [call],
            })
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id", name),
                "content": json.dumps(result, ensure_ascii=False),
            })
        second = llm.chat(messages, tools=None)
        final_content = second.get("content") or final_content

    if not final_content:
        final_content = "抱歉，我暂时无法生成回答。"

    # 5) 落库
    db.add(Message(
        conversation_id=conversation_id,
        role="assistant",
        content=final_content,
        citations=json.dumps(citations, ensure_ascii=False),
    ))
    db.commit()

    return {
        "conversation_id": conversation_id,
        "answer": final_content,
        "citations": citations,
        "tool_calls": tool_records,
    }
