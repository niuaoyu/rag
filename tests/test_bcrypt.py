import bcrypt

def hash_password(pw:str) -> str:
    return bcrypt.hashpw(pw.encode(),bcrypt.gensalt()).decode()

def verify_password(pw:str,hashed:str) -> bool:
    return bcrypt.checkpw(pw.encode(),hashed.encode())


def test_hash():
    pw = "aasas"
    h = hash_password(pw)
    d = hash_password(pw)

    assert pw not in h
    assert h.startswith("$2b$")
    assert len(h) == 60
    assert verify_password(pw,h) is True
    assert verify_password(pw+"a",h) is False
    assert h != d
    # 密码一样，但是hash不一样，安全，但

