"""RAG + Agent 主流程：检索 -> (工具调用循环) -> 生成带引用的回答（含 SSE 流式）。"""
from __future__ import annotations

import json
from collections.abc import Iterator

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Conversation, Message
from app.db.session import SessionLocal
from app.services import llm
from app.services.tools import ALL_TOOL_SCHEMAS, run_tool
from app.services.vectorstore import search_chunks

logger = get_logger(__name__)

TOOLS = ALL_TOOL_SCHEMAS

SYSTEM_PROMPT = (
    "你是一个严谨的知识库问答助手。"
    "回答必须优先依据【参考资料】中的内容，并在引用处标注来源（文件名与页码）。"
    "如果资料不足，要明确说明。可以结合工具返回的数据（如天气、当前日期）做综合判断。"
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


def _get_or_create_conversation(db: Session, user_id: int, question: str,
                                conversation_id: int | None) -> Conversation:
    if conversation_id is None:
        conv = Conversation(user_id=user_id, title=llm.summarize_title(question))
        db.add(conv)
        db.commit()
        db.refresh(conv)
        return conv
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user_id:
        raise ValueError("会话不存在")
    return conv


def _execute_calls(calls: list[dict], messages: list[dict], tool_records: list[dict]) -> None:
    """执行一轮 tool_calls：逐个调用并追加 assistant/tool 消息。"""
    for call in calls:
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
        except Exception as exc:  # noqa: BLE001 工具失败不能拖垮回答
            result = {"error": str(exc)}
            ok = False
        tool_records.append({"name": name, "arguments": args, "result": result, "ok": ok})
        messages.append({"role": "assistant", "content": None, "tool_calls": [call]})
        messages.append({
            "role": "tool",
            "tool_call_id": call.get("id", name),
            "content": json.dumps(result, ensure_ascii=False),
        })


def answer_question(db: Session, user_id: int, question: str,
                    conversation_id: int | None = None, use_tools: bool = True) -> dict:
    conv = _get_or_create_conversation(db, user_id, question, conversation_id)
    conversation_id = conv.id

    db.add(Message(conversation_id=conversation_id, role="user", content=question))
    db.commit()

    # 1) 检索 + 上下文
    hits = search_chunks(db, user_id, question)
    context, citations = _build_context(hits)

    # 2) Agent 循环：模型可连续请求工具，直到给出答案或超出轮次预算
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if context:
        messages.append({"role": "system", "content": context})
    messages += _history(db, conversation_id)
    messages.append({"role": "user", "content": question})

    tools = TOOLS if use_tools else None
    max_rounds = max(1, settings.tool_max_rounds)
    tool_records: list[dict] = []
    final_content: str | None = None

    for round_idx in range(max_rounds + 1):
        allow_tools = tools if round_idx < max_rounds else None  # 预算耗尽强制收口
        msg = llm.chat(messages, tools=allow_tools)
        calls = msg.get("tool_calls") or []
        if not calls:
            final_content = msg.get("content")
            break
        if round_idx == max_rounds:  # 理论上 tools=None 不会再有 calls；兜底
            final_content = msg.get("content")
            break
        _execute_calls(calls, messages, tool_records)

    if not final_content:
        final_content = "抱歉，我暂时无法生成回答。"

    # 3) 落库
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


def answer_question_stream(user_id: int, question: str,
                           conversation_id: int | None = None,
                           use_tools: bool = True) -> Iterator[dict]:
    """流式版问答。产出统一事件流：
    meta -> stage -> citations -> [stage/tool_calls]* -> delta* -> done
    自管 DB session（流式响应期间请求级 session 早已关闭）。"""
    db = SessionLocal()
    try:
        conv = _get_or_create_conversation(db, user_id, question, conversation_id)
        conversation_id = conv.id
        yield {"type": "meta", "conversation_id": conversation_id}

        db.add(Message(conversation_id=conversation_id, role="user", content=question))
        db.commit()

        yield {"type": "stage", "stage": "retrieving"}
        hits = search_chunks(db, user_id, question)
        context, citations = _build_context(hits)
        yield {"type": "citations", "citations": citations}

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context:
            messages.append({"role": "system", "content": context})
        messages += _history(db, conversation_id)
        messages.append({"role": "user", "content": question})

        tools = TOOLS if use_tools else None
        max_rounds = max(1, settings.tool_max_rounds)
        tool_records: list[dict] = []
        final_content: str | None = None

        for round_idx in range(max_rounds + 1):
            allow_tools = tools if round_idx < max_rounds else None
            buf: list[str] = []
            calls: list[dict] | None = None
            for ev in llm.chat_stream(messages, tools=allow_tools):
                if ev["type"] == "delta":
                    buf.append(ev["content"])
                    yield ev
                elif ev["type"] == "tool_calls":
                    calls = ev["tool_calls"]
            if not calls:
                final_content = "".join(buf) or None
                break
            if round_idx == max_rounds:
                final_content = "".join(buf) or None
                break
            _execute_calls(calls, messages, tool_records)
            yield {"type": "tool_calls", "tool_calls": tool_records[-len(calls):]}

        if not final_content:
            final_content = "抱歉，我暂时无法生成回答。"

        db.add(Message(
            conversation_id=conversation_id,
            role="assistant",
            content=final_content,
            citations=json.dumps(citations, ensure_ascii=False),
        ))
        db.commit()
        yield {"type": "done", "conversation_id": conversation_id,
               "citations": citations, "tool_calls": tool_records}
    except llm.LLMError as exc:
        logger.error("stream llm error: %s", exc)
        yield {"type": "error", "message": str(exc)}
    except ValueError as exc:
        yield {"type": "error", "message": str(exc)}
    finally:
        db.close()
