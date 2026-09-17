from fastapi import HTTPException
import jwt
import pytest
from app.core.config import settings
from app.core.security import create_token, decode_token

# 新建密钥
# import secrets 
# secret = secrets.token_urlsafe(32)

def test_jwt():
    assert decode_token(create_token(123)) == 123
    
def test_expired_token(monkeypatch):
    monkeypatch.setattr(settings, "jwt_expire_minutes", -1)
    expired = create_token(123)
    with pytest.raises(HTTPException) as exc_info:
        decode_token(expired)
    assert exc_info.value.status_code == 401


# 这种写法不好

# def test_jwt():
#     assert decode_token(create_token(123)) == 123

#     # 在app/core/config.py里设置过期时间settings.jwt_expire_minutes = -1 看报错
#     settings.jwt_expire_minutes = -1
#     expired = create_token(123)
#     try:
#         decode_token(expired)
#         print("❌ 过期没被发现")
#     except jwt.ExpiredSignatureError:
#         print("✅ 过期被拒绝")

