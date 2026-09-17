from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from app.api.current_user import get_current_user
from app.core.security import create_token, hash_password, verify_password
from app.db import get_db
from app.models.user import  User
from app.schemas.user import UserCreate, UserOut, Token

router = APIRouter(prefix="/api/v1/users",tags=["users"])




@router.post("/register",status_code=201,response_model=UserOut)
def register_user(payload: UserCreate, db:Session = Depends(get_db)):

    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409,detail="email已存在")

    user = User(
        email = payload.email,
        password_hash=hash_password(payload.password)
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return {"user_id": user.id, "email": user.email}



@router.post("/login",status_code=200,response_model=Token)
def login_user(payload:UserCreate,db:Session=Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()

    if user and verify_password(payload.password,user.password_hash):
        token = create_token(user.id)
        return {"access_token":token,"token_type":"bearer"}
    

    raise HTTPException(status_code=401,detail="密码或邮箱错误")    



@router.get("/me",status_code=200,response_model=UserOut)
def user_me(payload:User = Depends(get_current_user)):
    return {"user_id": payload.id, "email": payload.email}

# get_current_user 里的 db 和路由里的 db 是同一个 session 吗？是的，同一请求内，同一个依赖只执行一次，结果被缓存。


