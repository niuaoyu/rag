from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    response = client.get("http://localhost:8000/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"