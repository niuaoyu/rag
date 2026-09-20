
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
