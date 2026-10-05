def test_register_login_me(client):
    r = client.post("/auth/register", json={"username": "alice", "password": "alice123"})
    assert r.status_code == 201
    assert r.json()["username"] == "alice"

    r = client.post("/auth/login", json={"username": "alice", "password": "alice123"})
    assert r.status_code == 200
    token = r.json()["access_token"]

    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["username"] == "alice"


def test_duplicate_username(client):
    client.post("/auth/register", json={"username": "bob", "password": "bob12345"})
    r = client.post("/auth/register", json={"username": "bob", "password": "bob12345"})
    assert r.status_code == 409


def test_wrong_password(client):
    client.post("/auth/register", json={"username": "carol", "password": "carol123"})
    r = client.post("/auth/login", json={"username": "carol", "password": "wrong"})
    assert r.status_code == 401


def test_protected_requires_token(client):
    assert client.get("/auth/me").status_code == 401
    assert client.get("/documents").status_code == 401
