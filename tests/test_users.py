# tests/test_users.py


def test_register_success(client):
    response = client.post(
        "/api/v1/users/register",
        json={"email": "new@example.com", "password": "password123"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "new@example.com"
    assert "user_id" in data


def test_register_duplicate_email(client, registered_user):
    email, password = registered_user
    response = client.post(
        "/api/v1/users/register",
        json={"email": email, "password": password},
    )
    assert response.status_code == 409


def test_register_short_password(client):
    response = client.post(
        "/api/v1/users/register",
        json={"email": "x@example.com", "password": "123"},
    )
    # MVP 阶段 Pydantic 返回 422
    assert response.status_code == 422


def test_login_success(client, registered_user):
    email, password = registered_user
    response = client.post(
        "/api/v1/users/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client, registered_user):
    email, _ = registered_user
    response = client.post(
        "/api/v1/users/login",
        json={"email": email, "password": "wrongpassword"},
    )
    assert response.status_code == 401


def test_me_with_valid_token(client, registered_user):
    email, password = registered_user
    login = client.post(
        "/api/v1/users/login",
        json={"email": email, "password": password},
    )
    token = login.json()["access_token"]

    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["email"] == email


def test_me_without_token(client):
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401


def test_me_with_invalid_token(client):
    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer invalid.token.here"},
    )
    assert response.status_code == 401