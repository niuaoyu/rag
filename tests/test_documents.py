def test_upload_and_ingest(client, auth, uploaded_document):
    r = client.get(f"/documents/{uploaded_document}", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "done"
    assert body["chunk_count"] >= 1
    assert body["filename"] == "Java并发编程.txt"


def test_reject_unsupported_type(client, auth):
    files = {"file": ("evil.exe", b"MZ", "application/octet-stream")}
    r = client.post("/documents/upload", files=files, headers=auth)
    assert r.status_code == 400


def test_document_isolation(client, auth, uploaded_document):
    client.post("/auth/register", json={"username": "mallory", "password": "mallory123"})
    other = client.post("/auth/login", json={"username": "mallory", "password": "mallory123"}).json()["access_token"]
    r = client.get(f"/documents/{uploaded_document}", headers={"Authorization": f"Bearer {other}"})
    assert r.status_code == 404
