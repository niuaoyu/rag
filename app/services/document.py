
from typing import List

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.current_user import get_current_user
from app.db import get_db
from app.models.document import Document
from app.models.user import User

# 根据用户id查对应的文档
def get_document_by_user_id(doc_id:int,db:Session=Depends(get_db),user:User = Depends(get_current_user)):

    # doc = db.get(Document,user.id)
    # 鉴权
    doc = (
            db.query(Document)
            .filter(
                Document.id == doc_id,
                Document.user_id == user.id,
            )
            .first()
        )
    if doc is None:
            raise HTTPException(status_code=404, detail="Document not found")
    # 查询数据库


    # 返回文档对象


    return doc