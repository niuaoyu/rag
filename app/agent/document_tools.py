# app/agent/document_tools.py
# 知识库业务工具：这是这个 Agent 真正「有业务」的部分。
# 关键约束：所有查询都必须带上 user_id 过滤——模型能选工具，但不能越权拿到别人的文档。

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.agent.tools import ToolRegistry, ToolSpec
from app.models.document import Document

MAX_LIMIT = 50
SEARCH_BACKEND = "filename_like"
# 扩展点：M6 引入切块与向量库后，把 backend 换成向量检索（chunk -> embedding -> top_k），
# 工具名、参数和返回结构保持不变，模型侧无需改动。


def _brief(doc: Document) -> dict[str, Any]:
    return {
        "id": doc.id,
        "filename": doc.filename,
        "size": doc.size,
        "status": doc.status,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


def _clamp_limit(limit: Any, default: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, MAX_LIMIT))


def list_my_documents(db: Session, user_id: int, limit: Any = 10) -> dict[str, Any]:
    size = _clamp_limit(limit, 10)
    rows = (
        db.query(Document)
        .filter(Document.user_id == user_id)
        .order_by(Document.id.desc())
        .limit(size)
        .all()
    )
    return {"total_returned": len(rows), "items": [_brief(row) for row in rows]}


def search_documents(db: Session, user_id: int, query: str, limit: Any = 5) -> dict[str, Any]:
    keyword = (query or "").strip()
    if not keyword:
        raise ValueError("query 不能为空")
    size = _clamp_limit(limit, 5)
    rows = (
        db.query(Document)
        .filter(Document.user_id == user_id, Document.filename.ilike(f"%{keyword}%"))
        .order_by(Document.id.desc())
        .limit(size)
        .all()
    )
    if not rows:
        return {"matched": 0, "backend": SEARCH_BACKEND, "items": [], "hint": "没有匹配的文档，可改用 list_my_documents 看清单"}
    return {"matched": len(rows), "backend": SEARCH_BACKEND, "items": [_brief(row) for row in rows]}


def get_document(db: Session, user_id: int, doc_id: Any) -> dict[str, Any]:
    try:
        target_id = int(doc_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"doc_id 必须是整数，收到 {doc_id!r}") from exc
    doc = (
        db.query(Document)
        .filter(Document.id == target_id, Document.user_id == user_id)
        .first()
    )
    if doc is None:
        # 越权与不存在统一回同一句话：不向模型暴露「别人的文档存在」这一信息
        raise LookupError(f"文档 {target_id} 不存在或不属于当前用户")
    return _brief(doc)


def build_document_tools(db: Session, user_id: int) -> ToolRegistry:
    """按当前登录用户组装一份工具集：数据边界在注册时就固定，模型无法绕过。"""
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="list_my_documents",
            description="列出当前用户最近上传的文档（id、文件名、大小、状态）。用户问「我有哪些文档」时使用。",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "返回条数，1-50，默认 10"},
                },
                "additionalProperties": False,
            },
            func=lambda limit=10: list_my_documents(db, user_id, limit),
        )
    )
    registry.register(
        ToolSpec(
            name="search_documents",
            description="在当前用户的文档里按关键词检索，返回命中的文档摘要。回答任何文档内容问题前先调用它。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词，例如文件名里的主题词"},
                    "limit": {"type": "integer", "description": "返回条数，1-50，默认 5"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            func=lambda query, limit=5: search_documents(db, user_id, query, limit),
        )
    )
    registry.register(
        ToolSpec(
            name="get_document",
            description="按 id 读取当前用户某篇文档的详细信息。用于确认检索结果里具体是哪一篇。",
            parameters={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "integer", "description": "文档 id，来自 search_documents 或 list_my_documents 的结果"},
                },
                "required": ["doc_id"],
                "additionalProperties": False,
            },
            func=lambda doc_id: get_document(db, user_id, doc_id),
        )
    )
    return registry
