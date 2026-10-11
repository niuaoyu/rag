
from datetime import datetime

from pydantic import BaseModel


class DocumentOut(BaseModel):
    model_config = {
        "from_attributes": True,
    }# 不加的话， Pydantic 会尝试把 Document 对象当 dict 处理
    
    id: int
    filename: str
    size: int
    status: str
    created_at: datetime
    # M4 新增：done 时 text 非空；failed 时 error_message 非空
    text: str | None = None
    error_message: str | None = None
    char_count: int | None = None   # text 的字符数（省得客户端自己数）
    token_count: int | None = None  # text 的 token 数，用 app/core/tokenizer.py 计数


class ChunkOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    ordinal: int
    text: str
    char_count: int
    token_count: int
