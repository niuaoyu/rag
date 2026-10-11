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


def test_upload_path_traversal_filename(client, user_a, tmp_path):
    """文件名里带 ../ 时：落盘路径必须仍是 uploads/<user_id>/<uuid>.ext，不能逃出目录。

    上一版这里写成了 client.get(...) 直接 TypeError；修完之后也不能只断言 201 ——
    那样这个用例什么都没测（文件真被写到 /etc 也会通过）。所以这里查磁盘。
    """
    _, _, token = user_a
    response = client.post(
        "/api/v1/documents",
        headers=auth_header(token),
        files={"file": ("../../etc/passwd.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 201
    # 入库的 filename 原样保留（只用于展示），落盘名是 uuid
    assert response.json()["filename"] == "../../etc/passwd.pdf"

    user_dir = tmp_path / "1"
    stored = list(user_dir.iterdir())
    assert len(stored) == 1
    stored_name = stored[0].name
    assert ".." not in stored_name and "/" not in stored_name
    assert stored_name.endswith(".pdf")
    assert stored[0].parent == user_dir  # 真的没跑出 uploads 目录


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
