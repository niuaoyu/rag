def test_index_serves_web_ui(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "个人知识库" in r.text


def test_static_assets(client):
    for path in ("/static/style.css", "/static/app.js"):
        r = client.get(path)
        assert r.status_code == 200
