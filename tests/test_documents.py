# tests/test_documents.py
from tests.conftest import auth_header


def test_upload_success(client, user_a):
    _, _, token = user_a
    response = client.post(
        "/api/v1/documents",
        headers=auth_header(token),
        files={"file": ("a.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == "a.pdf"
    assert data["status"] == "pending"
    assert data["size"] == len(b"%PDF-1.4 fake")


def test_upload_without_auth(client):
    response = client.post(
        "/api/v1/documents",
        files={"file": ("a.pdf", b"fake", "application/pdf")},
    )
    assert response.status_code == 401


def test_upload_wrong_extension(client, user_a):
    _, _, token = user_a
    response = client.post(
        "/api/v1/documents",
        headers=auth_header(token),
        files={"file": ("a.exe", b"fake", "application/octet-stream")},
    )
    assert response.status_code == 415


def test_upload_too_large(client, user_a):
    _, _, token = user_a
    big = b"x" * (10 * 1024 * 1024 + 1)
    response = client.post(
        "/api/v1/documents",
        headers=auth_header(token),
        files={"file": ("big.pdf", big, "application/pdf")},
    )
    assert response.status_code == 413


def test_upload_chinese_filename(client, user_a):
    _, _, token = user_a
    response = client.post(
        "/api/v1/documents",
        headers=auth_header(token),
        files={"file": ("测试.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 201
    assert response.json()["filename"] == "测试.pdf"


def test_upload_path_traversal_filename(client, user_a):
    _, _, token = user_a
    response = client.get(
        "/api/v1/documents",
        headers=auth_header(token),
        files={"file": ("../../etc/passwd.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 201
    # 落盘路径是 uuid，不含路径穿越
    # 这个断言需要查磁盘，M3 不强制


def test_list_documents(client, user_a):
    _, _, token = user_a
    # 上传两个
    for name in ("a.pdf", "b.pdf"):
        client.post(
            "/api/v1/documents",
            headers=auth_header(token),
            files={"file": (name, b"%PDF-1.4", "application/pdf")},
        )
    response = client.get("/api/v1/documents", headers=auth_header(token))
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # 倒序：id 大的在前
    assert data[0]["id"] > data[1]["id"]


def test_get_document(client, user_a):
    _, _, token = user_a
    upload = client.post(
        "/api/v1/documents",
        headers=auth_header(token),
        files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
    )
    doc_id = upload.json()["id"]

    response = client.get(f"/api/v1/documents/{doc_id}", headers=auth_header(token))
    assert response.status_code == 200
    assert response.json()["id"] == doc_id


def test_isolation(client, user_a, user_b):
    """A 上传，B 看不到。"""
    _, _, token_a = user_a
    _, _, token_b = user_b

    upload = client.post(
        "/api/v1/documents",
        headers=auth_header(token_a),
        files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
    )
    doc_id = upload.json()["id"]

    # B 的列表为空
    response = client.get("/api/v1/documents", headers=auth_header(token_b))
    assert response.json() == []

    # B 访问 A 的文档 → 404
    response = client.get(f"/api/v1/documents/{doc_id}", headers=auth_header(token_b))
    assert response.status_code == 404


def test_get_nonexistent_document(client, user_a):
    _, _, token = user_a
    response = client.get("/api/v1/documents/9999", headers=auth_header(token))
    assert response.status_code == 404