


from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db import get_db
from app.models.user import User

def get_current_user(
    auth:HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    db:Session = Depends(get_db)
)->User:
    token = auth.credentials
    user_id = decode_token(token)
    if user_id:
        return db.get(User,user_id)
    raise HTTPException(status_code=401,detail="token 缺失/无效/过期")
